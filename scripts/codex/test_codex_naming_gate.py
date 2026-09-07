# -*- coding: utf-8 -*-
"""test_codex_naming_gate — Codex席の出口(dc_send)が呼称ゲートCを通ることを実行で確かめる。

★共通規律§3= ソースの文字列一致は検査ではなく保険だ。だからここでは
  **外へ出る手(HTTP)だけを偽物にし、判定と分岐は本物のまま**通す:
    - 偽物にする = urllib.request.urlopen(Discordへ実際に撃つ点)
    - 本物のまま = dc_send の中身 / output_gates.apply_naming_gate_only /
                   naming_gate.naming_verdicts / 呼称ルール.json / MALE_CHARACTERS

背景(2026-09-05 aegis-gl)= Codexの発話は**どのゲートも通っていなかった**。呼称ルール.json へ
「ネイキッド・スネーク→一ノ瀬怜」の行を作っても(人事部門)、通り道が無ければ休眠する。

★2026-09-08(aegis-gl)= **この検査は本番の naming_audit.jsonl を汚していた**。
  T3/T5 の探り本文 `怜さん、頼む。` が source="codex" で本番台帳へ載り、呼称ドリフトの集計側では
  **ネイキッド・スネークの実出力と見分けが付かない**(実測= found="怜さん" のスネーク行9本は
  全て near/excerpt が丸ごと `怜さん、頼む。`= この探り本文だった)。人事部門はその4行を
  「Codexの敬語バイアスの残渣」と読み、autofix を足すか否かの判断材料にしていた。
  規律=「**本番の部屋でテストしない**」と同じ話が**台帳**でも起きていた、というのが真因だ。
  直し方= `GO5_LOCAL_DIR` を **import より前に**一時フォルダへ向ける(前例=
  `scripts/behop/test_behop_ladder.py`)。output_gates も codex_run も同じ環境変数で
  `local/` を決めるので、判定・分岐は本物のまま、**書き込み先だけ**砂場へ逃げる。
"""
import io
import json
import os
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(ROOT, "scripts", "llm"))

# ★本番台帳を汚さない= import より前に local/ を砂場へ向ける(理由は上のdocstring)
SANDBOX = os.environ["GO5_LOCAL_DIR"] = tempfile.mkdtemp(prefix="codex_naming_gate_test_")

import codex_run                                    # noqa: E402
import naming_gate as ng                            # noqa: E402

AUDIT = os.path.join(SANDBOX, "llm", "naming_audit.jsonl")
# ★本番台帳。**読むだけ**= この検査で1バイトも増えていないことをT7で見る(§4.55の「実物」)
PROD_AUDIT = os.path.join(ROOT, "local", "llm", "naming_audit.jsonl")
PROD_SIZE_BEFORE = os.path.getsize(PROD_AUDIT) if os.path.exists(PROD_AUDIT) else -1

PASS = FAIL = 0


def check(name, cond, extra=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print("  PASS " + name)
    else:
        FAIL += 1
        print("  FAIL " + name + (" | " + str(extra) if extra else ""))


class _FakeResp:
    """urlopen の戻り値の偽物。Discordの 200 応答だけを真似る。"""

    def __init__(self):
        self._b = json.dumps({"id": "9999999999"}).encode("utf-8")

    def read(self):
        return self._b

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def _send(text):
    """dc_send を本物のまま実走し、(実際に撃たれた本文, 標準出力) を返す。"""
    sent = []
    real_urlopen = codex_run.urllib.request.urlopen

    def fake_urlopen(req, timeout=None):
        sent.append(json.loads(req.data.decode("utf-8")).get("content", ""))
        return _FakeResp()

    codex_run.urllib.request.urlopen = fake_urlopen
    buf, real_stdout = io.StringIO(), sys.stdout
    sys.stdout = buf
    try:
        codex_run.dc_send("dummy-token-not-a-secret", "1", text)
    finally:
        codex_run.urllib.request.urlopen = real_urlopen
        sys.stdout = real_stdout
    return "".join(sent), buf.getvalue()


def _audit_tail(since_ts, n=60):
    """naming_audit.jsonl の末尾から、この検査より後に書かれた codex 由来の行だけ拾う。"""
    if not os.path.exists(AUDIT):
        return []
    out = []
    with open(AUDIT, encoding="utf-8") as f:
        for ln in f.readlines()[-n:]:
            try:
                r = json.loads(ln)
            except Exception:
                continue
            if r.get("source") == "codex" and str(r.get("ts", "")) >= since_ts:
                out.append(r)
    return out


print("== T1 名簿(MALE_CHARACTERS)にネイキッド・スネークが載っている ==")
check("T1a 傘の集合に入っている", ng._speaker_matches("__男性キャラ__", "ネイキッド・スネーク"),
      "MALE_CHARACTERS=" + str(sorted(ng.MALE_CHARACTERS))[:200])
check("T1b 別人のソリッド・スネークも残っている(消していない)",
      ng._speaker_matches("__男性キャラ__", "ソリッド・スネーク"))
check("T1c 名簿に無い名前は入っていない(空PASSでない)",
      not ng._speaker_matches("__男性キャラ__", "居ないはずの人格"))

print("== T2 呼称ルール.json をスネークで実走(判定は本物) ==")
RULES = ng.load_naming_rules(os.path.join(ROOT, "..", "00_AI-HQ", "departments", "hr",
                                          "personas", "呼称ルール.json"))
check("T2z 呼称ルールが読めている", bool(RULES))


def _reasons(text):
    return [v.get("reason") for v in ng.naming_verdicts("ネイキッド・スネーク", "hr-room", text, RULES)]


check("T2a 『怜さん』が forbidden で発火", _reasons("怜さん、頼む。") == ["forbidden"],
      _reasons("怜さん、頼む。"))
check("T2b 『一ノ瀬さん』が forbidden で発火", _reasons("一ノ瀬さん、頼む。") == ["forbidden"],
      _reasons("一ノ瀬さん、頼む。"))
check("T2c 呼び捨て『怜』は通る(過矯正なし)", _reasons("怜、頼む。") == [],
      _reasons("怜、頼む。"))
check("T2d 呼称と無関係な文は空(空PASSでない証明の対)",
      _reasons("了解した。作戦は継続する。") == [])

print("== T3 出口 dc_send を実走= ゲートを通り、本文は壊れない ==")
since = time.strftime("%Y-%m-%dT%H:%M:%S")
body, log = _send("怜さん、頼む。")
check("T3a 撃たれた本文が空でない", bool(body), repr(body))
check("T3b 本文は書き換えられていない(呼称ゲートCは警告のみ・誤爆させない)",
      body == "怜さん、頼む。", repr(body))
check("T3c HTTPは実際に撃たれている(投稿OKが出る)", "投稿OK" in log, log)
rows = _audit_tail(since)
check("T3d naming_audit.jsonl へ source='codex' で載った", len(rows) >= 1, rows)
check("T3e 載った行の話者がネイキッド・スネーク",
      any(r.get("persona") == "ネイキッド・スネーク" for r in rows), rows)

print("== T4 傘(MALE_CHARACTERS)だけで効くかを、名指し行を外して測る ==")
#   ★最初これを「名簿を外したら素通りする」で書いて FAIL した。理由は名簿ではなく、人事部門が
#     同じ日に**名指し行**(ネイキッド・スネーク→一ノ瀬怜)を新設したから= 傘を外しても名指しで
#     発火する。つまり素の状態では名簿追加は**冗長**だ。傘そのものの効きを見たいなら、
#     名指し行を抜いた rules で測るしかない(C-041= 一度の観測を状態の代理にするな)。
_NO_PIN = json.loads(json.dumps(RULES))             # 深い写し(正本は触らない)
_NO_PIN["speaker_target_overrides"] = [
    e for e in _NO_PIN.get("speaker_target_overrides", [])
    if not (str(e.get("speaker")) == "ネイキッド・スネーク" and str(e.get("target")) == "一ノ瀬怜")]
check("T4z 写しから名指し行が1行だけ消えている",
      len(_NO_PIN["speaker_target_overrides"]) == len(RULES["speaker_target_overrides"]) - 1)


def _reasons_nopin(text):
    return [v.get("reason") for v in ng.naming_verdicts("ネイキッド・スネーク", "hr-room", text, _NO_PIN)]


check("T4a 名指し行が無くても傘で『怜さん』が発火する(=名簿が効いている)",
      _reasons_nopin("怜さん、頼む。") == ["forbidden"], _reasons_nopin("怜さん、頼む。"))
_saved = ng.MALE_CHARACTERS
try:
    ng.MALE_CHARACTERS = {x for x in _saved if x != ng._norm("ネイキッド・スネーク")}
    check("T4b must-fail= 名簿からも外すと素通りする(この検査は名簿を見ている)",
          _reasons_nopin("怜さん、頼む。") == [], _reasons_nopin("怜さん、頼む。"))
finally:
    ng.MALE_CHARACTERS = _saved
check("T4c 戻した後は再び発火する", _reasons_nopin("怜さん、頼む。") == ["forbidden"])
check("T4d 名指し行が在る現状は、名簿を外しても発火する(=二重に閉じている)",
      _reasons("怜さん、頼む。") == ["forbidden"])

print("== T5 must-fail= ゲートを外した出口では監査に1行も載らない ==")
since2 = time.strftime("%Y-%m-%dT%H:%M:%S")
time.sleep(1.1)                                     # ts の秒解像度ぶんだけ待つ
_saved_og = sys.modules.get("output_gates")
try:
    sys.modules["output_gates"] = None              # import が転ぶ=ゲート無しの出口を再現
    body2, _ = _send("怜さん、頼む。")
finally:
    if _saved_og is not None:
        sys.modules["output_gates"] = _saved_og
    else:
        sys.modules.pop("output_gates", None)
check("T5a ゲートが落ちても投稿は死なない(fail-open)", body2 == "怜さん、頼む。", repr(body2))
check("T5b ゲート無しでは監査に載らない(=T3dは本当にゲート経由)",
      len([r for r in _audit_tail(since2) if str(r.get("ts", "")) > since2]) == 0,
      _audit_tail(since2))

print("== T6 話者名の綴りが responder 側と一致している ==")
sys.path.insert(0, os.path.join(ROOT, "scripts", "llm"))
import codex_responder                              # noqa: E402
check("T6a codex_run.CODEX_PERSONA == codex_responder.PERSONA_TENTATIVE",
      codex_run.CODEX_PERSONA == codex_responder.PERSONA_TENTATIVE,
      (codex_run.CODEX_PERSONA, codex_responder.PERSONA_TENTATIVE))

print("== T7 この検査は本番の naming_audit.jsonl を1バイトも増やしていない ==")
#   ★2026-09-08 まで、ここが破れていた= T3/T5 の探り本文が source="codex" で本番へ載り、
#     呼称ドリフト集計では実出力と見分けが付かなかった。砂場が効いていれば本番は不動だ。
check("T7z 砂場が本番と別物である", os.path.abspath(AUDIT) != os.path.abspath(PROD_AUDIT),
      (AUDIT, PROD_AUDIT))
check("T7y 砂場側には実際に書かれている(空PASSでない)",
      os.path.exists(AUDIT) and os.path.getsize(AUDIT) > 0, AUDIT)
_prod_now = os.path.getsize(PROD_AUDIT) if os.path.exists(PROD_AUDIT) else -1
check("T7a 本番台帳のサイズが前後で同じ",
      _prod_now == PROD_SIZE_BEFORE, (PROD_SIZE_BEFORE, _prod_now))

print("\n結果: %d PASS / %d FAIL" % (PASS, FAIL))
sys.exit(1 if FAIL else 0)
