# -*- coding: utf-8 -*-
"""self-check(恒久策#5)の回帰ガード= 設計§5-7 の**両側**(イージス研究室 / 2026-09-02)。

設計 `docs/departments/kaizen-analyst/設計_4種不具合恒久策_横断_2026-09-02.md` §5-7=
  「灰色便で検品呼び出しログが残らなければ fail、かつ**検品APIを殺した状態で便が届かなければ fail**
   (fail-open側が本丸)」。

★外へ出る手(= `claude -p`)だけを偽物にする。灰色の判定・答えの読み取り・台帳の書式は**本物のまま**回す。
  ソースの文字列一致では見ない= 入力を差し替えて経路を実行で通す。
★C-053 の must-fail は「動く別の実装」へ:
  ① 灰色を**ゲートJだけ**で決める実装(=上限側支配項だけを見る素朴版。J便では今も正しく動く)
  ② 検品を**fail-close**で使う実装(=検品が死んだら保留する版。APIが生きている間は正しく動く)
  ①は「灰色の呼び出しログ」側を、②は「APIを殺しても便が届く」側を赤くする。

    python tests/test_self_check_gray.py
"""
import json
import os
import subprocess
import sys
import tempfile
import time

PJ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(PJ, "scripts", "llm"))
import dept_daemon as d                      # noqa: E402
import self_check as sc                      # noqa: E402

NG = []
RUN = []

REC = {"msg_id": "1544672325444698154"}
DEPT = "aegis-gl"
SPEAKER = "ケヴィン・デブライネ"

NORMAL_JP = "結論から言う。名乗りタグの件は機構側で塞いだ。次の一手は台帳の監査だ。"
# 灰色③= 英字24字(帯20〜34)の散文段落。日本語の便の中に1段落だけ混じる形。
MIDBAND = "台帳を見た。\n\nRunning the audit now please\n\n続きは明日やる。"
KANJI = "一ノ瀬怜さん、さっきの件は片付いた。"

OK_JSON = '{"jp_only":true,"first_person":true,"naming":true,"script":true,"why":""}'
NG_JSON = ('{"jp_only":false,"first_person":true,"naming":true,"script":true,'
           '"why":"英語段落が残っている"}')


def check(name, cond):
    """数え方は1つ= `check()` を呼んだ回数 == PASS行+FAIL行 == 末尾の総数。"""
    RUN.append(name)
    print(("PASS  " if cond else "FAIL  ") + name)
    if not cond:
        NG.append(name)


# --- 偽物にするのは外へ出る手だけ ------------------------------------------------------
def runner_ok(prompt, model, timeout_s):
    CALLS.append(("ok", model, len(prompt)))
    return OK_JSON


def runner_ng(prompt, model, timeout_s):
    CALLS.append(("ng", model, len(prompt)))
    return NG_JSON


def runner_dead(prompt, model, timeout_s):
    """★検品APIを殺した状態= `claude` が居ない/非ゼロ終了(_claude_runner が None を返す形)。"""
    CALLS.append(("dead", model, len(prompt)))
    return None


def runner_boom(prompt, model, timeout_s):
    CALLS.append(("boom", model, len(prompt)))
    raise RuntimeError("検品プロセスが落ちた")


def runner_timeout(prompt, model, timeout_s):
    CALLS.append(("timeout", model, len(prompt)))
    raise subprocess.TimeoutExpired(cmd="claude", timeout=timeout_s)


def runner_garbage(prompt, model, timeout_s):
    CALLS.append(("garbage", model, len(prompt)))
    return "I checked it and it looks fine to me."


def runner_slow(prompt, model, timeout_s):
    """★遅い検品(本番の実測= 1,962字で28.6秒)。送信がこれを待つかどうかを見る。"""
    CALLS.append(("slow", model, len(prompt)))
    time.sleep(SLOW_S)
    return OK_JSON


CALLS = []
LEDGER = []
RETURNED_IN = [0.0]
SLOW_S = 1.5                     # 実測28.6秒の縮尺版(待つ実装なら必ずこれだけ待たされる)


def run(part, runner, struct_drift=False, regen_round=0, checker=None):
    """本番の合流点と同じ呼び方で1便通す。返り= (関数の戻り値, 台帳の行)。"""
    del CALLS[:]
    fd, tmp = tempfile.mkstemp(suffix=".jsonl")
    os.close(fd)
    keep_path, keep_check, keep_log = d.SELF_CHECK_AUDIT, d._self_check.check, d.log
    real_check = sc.check
    d.SELF_CHECK_AUDIT = tmp
    d.log = lambda *a, **k: None
    # ★判定・組み立て・読み取りは本物。差し替えるのは `claude` を呼ぶ1点だけ。
    d._self_check.check = lambda text, **kw: real_check(text, runner=runner, **kw)
    try:
        t0 = time.time()
        out = (checker or d.audit_self_check)(
            DEPT, REC, SPEAKER, part, struct_drift=struct_drift, regen_round=regen_round)
        RETURNED_IN[:] = [time.time() - t0]     # ★送信経路が待たされた時間
        d.self_check_join(30)                   # 検品は別スレッド= 台帳を読む前に待つ
    finally:
        d.SELF_CHECK_AUDIT, d._self_check.check, d.log = keep_path, keep_check, keep_log
    rows = [json.loads(l) for l in open(tmp, encoding="utf-8") if l.strip()]
    os.remove(tmp)
    return out, rows


def deliver(part, runner, checker=None, **kw):
    """**送信側の契約**= 検品を呼び、返りが真なら送らない(保留)という形で書いてある。

    本番の audit_self_check は**常に None** を返すので、この形でも本文は必ず届く。
    fail-close の実装を差し込むと、ここで初めて沈黙が起きる=それを must-fail で見る。
    """
    out, rows = run(part, runner, checker=checker, **kw)
    return (None if out else part), rows


# --- 1) 灰色でない便は検品を呼ばない(全便一律にしない=§3の不採用の数字) ---------------
out, rows = run(NORMAL_JP, runner_ok)
check("灰色でない便では `claude` を1回も呼ばない", CALLS == [])
check("灰色でない便では台帳に1行も書かない(騒がしくしない)", rows == [])
check("灰色でない便でも戻り値は None(送信に触らない)", out is None)

# --- 2) ★§5-7前半: 灰色4条件それぞれで**検品の呼び出しが台帳に残る** -------------------
out, rows = run(NORMAL_JP, runner_ok, struct_drift=True)
check("灰色①ゲートJ: 検品を1回呼ぶ", len(CALLS) == 1 and CALLS[0][0] == "ok")
check("灰色①ゲートJ: 台帳に1行・reasons に struct_drift",
      len(rows) == 1 and rows[0]["reasons"] == ["struct_drift"])
check("灰色①: 台帳の行に判定が載る(合格)",
      rows[0]["verdict"]["ok"] is True and rows[0]["verdict"]["ng"] == [])
check("灰色①: dept/msg_id/speaker/ref が載る(後から数えられる)",
      rows[0]["dept"] == DEPT and rows[0]["msg_id"] == REC["msg_id"]
      and rows[0]["speaker"] == SPEAKER and rows[0]["ref"] == "KAIZEN-2026-09-02-5")
check("灰色①: モデルはHaiku級(設計§3)", CALLS[0][1] == "haiku")

out, rows = run(KANJI, runner_ok)
check("灰色②漢字フル名: 一ノ瀬怜で灰色になる",
      len(rows) == 1 and any(r.startswith("kanji_fullname:") for r in rows[0]["reasons"]))
out, rows = run("怜、片付いた。", runner_ok)
check("灰色②: **単字の裸呼びでは灰色にしない**(C-035の誤爆源を持ち込まない)", rows == [])
# ★実測(4,659便)= 素朴に「フル名が出た便」を数えると17.45%。中身はほぼ**自分の名乗り**で、
#   呼称崩れとは無関係だった。話者自身と名乗りタグを除いて4.38%= 設計§3の予算内に収まる。
check("灰色②: **話者が自分の名を書いた便**は灰色にしない(実測17.45%→4.38%)",
      sc.gray_reasons("三笘薫だ。台帳は片付けた。", kanji_names=("三笘薫",),
                      speaker="三笘薫") == [])
check("灰色②: 名乗りタグの中の名前も灰色にしない(タグは本文ではない)",
      sc.gray_reasons("[花海咲季] 台帳を見た。", kanji_names=("花海咲季",),
                      speaker="ケヴィン・デブライネ") == [])
check("灰色②: **他人**の名がフル形で本文に出たら灰色(呼称崩れの土俵)",
      [r.split(":")[0] for r in sc.gray_reasons("花海咲季に頼んだ。",
                                                kanji_names=("花海咲季",),
                                                speaker="三笘薫")] == ["kanji_fullname"])

out, rows = run(MIDBAND, runner_ok)
check("灰色③中間帯: 英字24字の段落で灰色になる",
      len(rows) == 1 and any(r.startswith("latin_midband:") for r in rows[0]["reasons"]))
check("灰色③: 帯の外(短い英字)では鳴らない",
      run("台帳を見た。\n\nOK done\n\n続きは明日。", runner_ok)[1] == [])

out, rows = run(NORMAL_JP, runner_ok, regen_round=2)
check("灰色④再生成2周目: 灰色になる",
      len(rows) == 1 and rows[0]["reasons"] == ["nonjp_regen2"])
check("灰色④: 1周目(regen_round=1)では鳴らない",
      run(NORMAL_JP, runner_ok, regen_round=1)[1] == [])

# --- 3) ★§5-7後半(本丸): 検品APIを殺しても**便は届く** --------------------------------
for label, runner, why in (("APIが死んでいる", runner_dead, "no_output"),
                           ("APIが例外を投げる", runner_boom, "error:RuntimeError"),
                           ("APIが時間切れ", runner_timeout, "timeout"),
                           ("答えが壊れている", runner_garbage, "unparsable")):
    sent, rows = deliver(NORMAL_JP, runner, struct_drift=True)
    check("fail-open: %s時も便がそのまま届く" % label, sent == NORMAL_JP)
    check("fail-open: %s時も『呼んだが答えが無い』を台帳に残す(検品の死を静かにしない)" % label,
          len(rows) == 1 and rows[0]["verdict"] is None)
    # ★verdict=null だけでは死因が分からない= 実際、上限25秒に対し実測28.6秒で毎回時間切れ
    #   だったのに台帳の見た目は「呼んだが答えが無い」のままだった。理由を分けて残す。
    check("台帳の null_reason が死因を分ける(%s → %s)" % (label, why),
          rows[0].get("null_reason") == [why])

sent, rows = deliver(NORMAL_JP, runner_ng, struct_drift=True)
check("fail-open: **不合格でも送信は止めない**(設計§3の経路②)", sent == NORMAL_JP)
check("不合格は台帳に残る(ng項目と理由つき)",
      rows[0]["verdict"]["ok"] is False and rows[0]["verdict"]["ng"] == ["jp_only"]
      and "英語段落" in rows[0]["verdict"]["why"])

keep = sc.SELF_CHECK_ON
try:
    sc.SELF_CHECK_ON = False
    sent, rows = deliver(NORMAL_JP, runner_ok, struct_drift=True)
    check("逃げ道: SELF_CHECK_ON=False で検品を呼ばない(1行で止まる)", CALLS == [])
    check("逃げ道: 止めても便は届く・台帳は verdict=null で1行", sent == NORMAL_JP and len(rows) == 1)
finally:
    sc.SELF_CHECK_ON = keep

# --- 3.5) ★検品は**送信経路の外**で回す(配送が検品の速さに縛られない) -------------------
#   本番実測= 1,962字の便で 28.6秒。初版はこれを送信の前に挟んでいて、しかも上限25秒だったので
#   「毎回28.6秒待つ」ではなく「毎回25秒待って何も得ない」形になっていた。上限を伸ばすなら
#   待たない形にしないと、灰色4.38%の便がその秒数だけ遅れて届く。
sent, rows = deliver(NORMAL_JP, runner_slow, struct_drift=True)
check("非同期: 送信経路は検品(%.1fs)を待たない" % SLOW_S, RETURNED_IN[0] < SLOW_S / 2)
check("非同期: それでも検品は走り切り、台帳に判定が載る",
      len(rows) == 1 and rows[0]["verdict"]["ok"] is True and CALLS[0][0] == "slow")
check("上限は本番実測(28.6秒)より長い= 毎回時間切れにならない",
      sc.SELF_CHECK_TIMEOUT_S >= 30)


# ★must-fail③: 検品を**送信経路の中**で待つ動く別実装(初版そのもの)。
#   これは正しく判定を出す(台帳は緑のまま)。壊れるのは配送の速さだけ= そこを赤で固定する。
def _audit_self_check_blocking(dept, rec, speaker, part, struct_drift=False, regen_round=0):
    """動く別実装= 灰色なら**その場で**検品を待ってから台帳へ書く(初版の形)。"""
    names = sc.kanji_fullnames(d._naming_rules())
    reasons = sc.gray_reasons(part, struct_drift=struct_drift,
                              regen_round=regen_round, kanji_names=names, speaker=speaker)
    if not reasons:
        return None
    d._self_check_worker(dept, rec, speaker, part, reasons, "")
    return None


sent, rows = deliver(NORMAL_JP, runner_slow, checker=_audit_self_check_blocking,
                     struct_drift=True)
check("must-fail③: 待つ実装だと送信が検品の秒数だけ遅れる(この検査が意味を持つ)",
      RETURNED_IN[0] >= SLOW_S)
check("must-fail③: その別実装でも判定自体は正しく出る(空実装ではない)",
      len(rows) == 1 and rows[0]["verdict"]["ok"] is True)
sent, rows = deliver(NORMAL_JP, runner_slow, struct_drift=True)
check("must-fail後: 本物へ戻すと送信は待たされない", RETURNED_IN[0] < SLOW_S / 2)

# --- 4) 基準文(QAの保守面)= 4項目そろっていない表は採らない -----------------------------
fd, ctmp = tempfile.mkstemp(suffix=".json")
os.close(fd)
with open(ctmp, "w", encoding="utf-8") as f:
    json.dump({"items": [{"key": "jp_only", "text": "日本語だけか"}]}, f, ensure_ascii=False)
check("基準文: 項目が欠けた表は採らず既定へ倒す(黙って検品項目が減らない)",
      [c["key"] for c in sc.load_criteria(ctmp)] == list(sc.CRITERIA_KEYS))
with open(ctmp, "w", encoding="utf-8") as f:
    json.dump({"items": [{"key": k, "text": "QAが書き換えた基準" + k} for k in sc.CRITERIA_KEYS]},
              f, ensure_ascii=False)
check("基準文: 4項目そろった表はQAの物を使う(コードを触らずに直せる)",
      sc.load_criteria(ctmp)[0]["text"].startswith("QAが書き換えた基準"))
os.remove(ctmp)
check("基準文: ファイルが無くても既定で動く", len(sc.load_criteria(ctmp)) == 4)
check("検品文は4項目を1呼び出しに束ねる(項目キーが全部入る)",
      all(("[" + k + "]") in sc.build_prompt("本文", speaker=SPEAKER) for k in sc.CRITERIA_KEYS))
check("答えの読み取り: 4項目そろわない答えは採らない(部分判定で騒がない)",
      sc.parse_verdict('{"jp_only":true}') is None and sc.parse_verdict("") is None)

# --- 5) ★must-fail①: 灰色を**ゲートJだけ**で決める動く別実装 ---------------------------
#   これは素朴だが動く(J便では今も正しく検品が走る)。足りないのは残り3条件だけ=
#   だから「J」は緑のまま「中間帯」「漢字フル名」だけが赤くなるはず。
def _gray_j_only(text, struct_drift=False, regen_round=0, kanji_names=(), speaker=""):
    return ["struct_drift"] if struct_drift else []


keep_gray = sc.gray_reasons
try:
    sc.gray_reasons = _gray_j_only
    _, rows_mid = run(MIDBAND, runner_ok)
    _, rows_j = run(NORMAL_JP, runner_ok, struct_drift=True)
    check("must-fail①: J だけを見る実装だと中間帯の便が検品されない(この検査が意味を持つ)",
          rows_mid == [])
    check("must-fail①: その別実装でも J 便はちゃんと検品される(空実装ではない)",
          len(rows_j) == 1 and rows_j[0]["verdict"]["ok"] is True)
finally:
    sc.gray_reasons = keep_gray

# --- 6) ★must-fail②(本丸): 検品を fail-close で使う動く別実装 -------------------------
#   「検品できなかった便は念のため送らない」= 一見まともで、APIが生きている間は正しく動く。
#   だがAPIが死んだ瞬間に**部屋が黙る**= 設計§3が最悪の事故と呼んだ形。ここを赤で固定する。
def _audit_self_check_strict(dept, rec, speaker, part, struct_drift=False, regen_round=0):
    """動く別実装= 検品の結果が「合格」でなければ保留(真を返す)。"""
    d.audit_self_check(dept, rec, speaker, part,
                       struct_drift=struct_drift, regen_round=regen_round)
    names = sc.kanji_fullnames(d._naming_rules())
    reasons = sc.gray_reasons(part, struct_drift=struct_drift,
                              regen_round=regen_round, kanji_names=names)
    if not reasons:
        return None
    v = d._self_check.check(part, speaker=speaker, reasons=reasons)
    return None if (v or {}).get("ok") else "hold"


sent, _ = deliver(NORMAL_JP, runner_dead, checker=_audit_self_check_strict, struct_drift=True)
check("must-fail②: fail-close の実装だとAPIが死んだ時に**便が届かない**(この検査が意味を持つ)",
      sent is None)
sent, _ = deliver(NORMAL_JP, runner_ok, checker=_audit_self_check_strict, struct_drift=True)
check("must-fail②: その別実装でもAPIが生きていれば便は届く(空実装ではない)",
      sent == NORMAL_JP)
sent, rows = deliver(NORMAL_JP, runner_dead, struct_drift=True)
check("must-fail後: 本物へ戻すとAPIが死んでいても便は届く", sent == NORMAL_JP)

print("-" * 60)
print("%d/%d PASS%s" % (len(RUN) - len(NG), len(RUN),
                        "" if not NG else "  NG: " + " / ".join(NG)))
sys.exit(1 if NG else 0)
