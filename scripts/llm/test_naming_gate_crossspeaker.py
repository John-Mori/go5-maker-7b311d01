# -*- coding: utf-8 -*-
"""test_naming_gate_crossspeaker — フル名の内側の免除を「対人」へ広げた件を実行で確かめる。

裁定(2026-09-08・人事部門ククール / 呼称ルール.json `self_name_substring_exemption`
の `★2026-09-08_対人拡張`)=
  《ヒットが本人フル名の内側に収まり、かつ そのフル名自体が forbidden 完全一致でないなら、
    自名義・対人を問わず不問》。

★共通規律§3= ソースの文字列一致は検査ではない。ここでは**台帳の実物**(local/llm/
  naming_audit.jsonl に実際に残っている行の near)を検体にして、判定器 naming_verdicts を
  本物のまま通す。合成検体は guardrail の確認にだけ使う。
★この検査は**読むだけ**= naming_verdicts は純関数で台帳へ書かない
  (書く経路は output_gates 側。前例の汚染= test_codex_naming_gate の 2026-09-08 の直し)。

実測(拡張の前後・窓 2026-08-26〜09-08・重複を畳んだ後):
  フル名の内側だけの56件 … 拡張前 56/56 が鳴っていた → 拡張後 0/56(台帳と同じ組で再現しない)
  裸姓『一ノ瀬』19件     … 拡張前 19/19 → 拡張後 14/19。落ちた5件は**覆いの中**
                            (『一ノ瀬』/ `["一ノ瀬"]` = 引用・コード)にしか裸姓が無い行で、
                            読む側の is_full_name_hit が覆いを知らないため「裸姓」へ倒れて
                            いたもの= ゲート側が正しい。G2 はこの対応を独立に計算して見る。
"""
import datetime
import io
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, HERE)

import naming_drift_check as ndc                     # noqa: E402
import naming_gate as ng                             # noqa: E402

RULES = ng.load_naming_rules(os.path.join(ROOT, "..", "00_AI-HQ", "departments", "hr",
                                          "personas", "呼称ルール.json"))

PASS = FAIL = 0


def check(name, cond, extra=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print("  PASS " + name)
    else:
        FAIL += 1
        print("  FAIL " + name + (" | " + str(extra) if extra else ""))


def verdicts(persona, text):
    return ng.naming_verdicts(persona, "hr-room", text, RULES)


def _for_target(r):
    """台帳の行 r の near を再生し、同じ対象に立った判定だけ返す。"""
    return [v for v in verdicts(r.get("persona") or "", str(r.get("near") or ""))
            if v.get("target") == r.get("target")]


def _same_pair(r):
    """★台帳の行と**同じ組(target>found)**が再現するか= 「その56件が数から落ちた」の実物。"""
    return any(v.get("found") == r.get("found") for v in _for_target(r))


# ==== 台帳から検体を取る(窓は naming_drift_check と同じ 14日)========================
_raw = ndc._read()
_end = ndc._end_date(_raw, None)
_start = _end - datetime.timedelta(days=ndc.WINDOW_DAYS - 1)


def _in_window(r):
    d = str(r.get("ts") or "")[:10]
    try:
        d = datetime.date(*[int(x) for x in d.split("-")])
    except Exception:
        return False
    return _start <= d <= _end


_rows = ndc.dedupe([r for r in _raw if _in_window(r)])
FULLNAME = [r for r in _rows if ndc.is_full_name_hit(r) and r.get("near")]
BARE = [r for r in _rows if not ndc.is_full_name_hit(r) and not ndc.is_self_report(r)
        and r.get("reason") == "forbidden" and r.get("target") == "一ノ瀬怜"
        and r.get("found") == "一ノ瀬" and r.get("near")]

print("== G1 台帳の実物「フル名を書いただけ」= 拡張後は同じ組で再現しない ==")
print("   窓 %s〜%s / 検体 %d件" % (_start, _end, len(FULLNAME)))
check("G1z 検体が50件以上ある(空PASSでない)", len(FULLNAME) >= 50, len(FULLNAME))
_g1 = [r for r in FULLNAME if _same_pair(r)]
check("G1a 台帳と同じ組(target>found)が1件も再現しない", not _g1,
      [(r["ts"], r["persona"], r["target"], r["found"]) for r in _g1][:5])
# ★ここは合否ではなく**内訳の実測**を出す(裁定と Chami 指示の境目そのものだから)。
#   黙る = 対象ごと消える(裸姓の誤爆が消えた分)。
#   札替え = 裸姓では鳴らなくなったが、**フル名そのもの**で鳴る= Chami 2026-09-01
#            『またアロンソコーチが一ノ瀬怜呼びしてる。直らないの?』の網に残る分。
_silent = [r for r in FULLNAME if not _for_target(r)]
_relabel = [r for r in FULLNAME if _for_target(r)]
_by = {}
for r in _relabel:
    _by[r["target"]] = _by.get(r["target"], 0) + 1
print("   内訳: 完全に黙る %d件 / フル名そのものへ札替え %d件 %s"
      % (len(_silent), len(_relabel), _by))
check("G1b 黙る側と札替え側の合計が検体と一致する(数え落としが無い)",
      len(_silent) + len(_relabel) == len(FULLNAME))

print("== G2 裸姓は従来どおり=「覆いの外に立っているか」と1対1で対応する ==")


def _bare_outside(near, target, found):
    """★ゲートを使わずに独立に計算する= 引用/コードの覆いを掛けた後、found が
       target(フル名)の範囲の**外**に1つでも残るか。残るなら「裸で呼んだ」だ。"""
    s = ng._mask_quoted_mentions(ng._mask_protected(str(near or "")))
    spans = [(m.start(), m.end()) for m in re.finditer(re.escape(target), s)]
    for m in re.finditer(re.escape(found), s):
        if not any(a <= m.start() and m.end() <= b for a, b in spans):
            return True
    return False


_out = [r for r in BARE if _bare_outside(r["near"], r["target"], r["found"])]
_in = [r for r in BARE if r not in _out]
print("   検体 %d件(覆いの外に裸姓あり %d / 覆いの中だけ %d)" % (len(BARE), len(_out), len(_in)))
check("G2z 両方の束が空でない(=対応が自明でない)", len(_out) >= 5 and len(_in) >= 1,
      (len(_out), len(_in)))
_miss = [r for r in _out if not _same_pair(r)]
check("G2a 覆いの外に裸姓が立つ行は**全件**従来どおり鳴る", not _miss,
      [(r["ts"], r["persona"], str(r["near"])[:60]) for r in _miss][:5])
_extra = [r for r in _in if _same_pair(r)]
check("G2b 覆いの中(引用・コード)だけの行は鳴らない=use/mention のまま", not _extra,
      [(r["ts"], str(r["near"])[:60]) for r in _extra][:5])

print("== G3 guardrail(合成検体) ==")
check("G3a フル名の外に裸姓が立てば鳴る(guardrail①)",
      [v["found"] for v in verdicts("ククール", "この件は一ノ瀬怜へ回す。一ノ瀬にも伝えた。")]
      == ["一ノ瀬"],
      verdicts("ククール", "この件は一ノ瀬怜へ回す。一ノ瀬にも伝えた。"))
check("G3b フル名自体が禁止形なら対人で鳴る(guardrail②・ルカ・モドリッチ)",
      any(v["reason"] == "forbidden" and v["found"] == "ルカ・モドリッチ"
          for v in verdicts("ククール", "ルカ・モドリッチへ回す。")),
      verdicts("ククール", "ルカ・モドリッチへ回す。"))
check("G3c フル名+敬称も鳴る(guardrail③・『ルカ・モドリッチさん』)",
      any(v["found"] == "ルカ・モドリッチ"
          for v in verdicts("ククール", "ルカ・モドリッチさん、頼む。")),
      verdicts("ククール", "ルカ・モドリッチさん、頼む。"))
check("G3d 自名義の免除は無傷(2026-09-02 裁定を壊していない)",
      verdicts("ルカ・モドリッチ", "【AD研究室(ルカ・モドリッチ)→HQ】了解した。") == [],
      verdicts("ルカ・モドリッチ", "【AD研究室(ルカ・モドリッチ)→HQ】了解した。"))
check("G3e 対人フル名の**内側の裸姓**はもう拾わない(拡張の本体・漢字)",
      not [v for v in verdicts("ククール", "この件は一ノ瀬怜へ回す。")
           if v.get("found") == "一ノ瀬"],
      verdicts("ククール", "この件は一ノ瀬怜へ回す。"))
check("G3f 対人でフル名を書いただけは鳴らない(拡張の本体・カナ)",
      verdicts("ククール", "この件はケヴィン・デブライネへ回す。") == [],
      verdicts("ククール", "この件はケヴィン・デブライネへ回す。"))
# ★★ここが裁定と Chami 指示のぶつかる一点。既定 "proper" では**フル名そのもの**は
#   従来どおり判定へ乗る= 2026-09-01 Chami『またアロンソコーチが一ノ瀬怜呼びしてる。
#   直らないの?』(msg 1544235216757858398)で入れた FULL_KEY_SWAP が生きているからだ。
#   人事裁定の文字どおり(=45件も数から落とす)にするには "full" へ回す必要があり、
#   それは上記の Chami 指示を黙らせる= Chami の裁定が要る。切替はこの1語だけ。
check("G3h 一ノ瀬怜のフル名呼び自体は残る(Chami 2026-09-01・FULL_KEY_SWAP)",
      any(v.get("found") == "一ノ瀬怜"
          for v in verdicts("ククール", "この件は一ノ瀬怜へ回す。")),
      verdicts("ククール", "この件は一ノ瀬怜へ回す。"))
try:
    ng.CROSS_SPEAKER_SPAN_EXEMPTION = "full"
    check("G3i must-fail= \"full\" にすると一ノ瀬怜のフル名呼びが黙る(=既定が守っている)",
          verdicts("ククール", "この件は一ノ瀬怜へ回す。") == [],
          verdicts("ククール", "この件は一ノ瀬怜へ回す。"))
    check("G3j \"full\" でも guardrail② は _fullname_is_forbidden が担う(モドリッチは鳴る)",
          any(v["found"] == "ルカ・モドリッチ" for v in verdicts("ククール", "ルカ・モドリッチへ回す。")),
          verdicts("ククール", "ルカ・モドリッチへ回す。"))
finally:
    ng.CROSS_SPEAKER_SPAN_EXEMPTION = "proper"
check("G3g 裸姓だけの本文は鳴る(空PASSでない証明の対)",
      any(v["found"] == "一ノ瀬" for v in verdicts("ククール", "一ノ瀬、頼む。")),
      verdicts("ククール", "一ノ瀬、頼む。"))

print("== G4 must-fail= 旧仕様(対人は免除しない)へ戻すと台帳の56件がそのまま戻る ==")
#   ★数を直書きしない= 検体は14日の窓で毎日ずれる。「旧仕様で鳴った行」を**その場で採り**、
#     同じ行が拡張後に鳴らないことを見る=自己校正(C-041= 一度の観測を状態の代理にするな)。
#   ★実測(2026-09-08)= 旧仕様は56件**全件**その対象で鳴り、うち46件は台帳と同じ組まで一致。
#     残る10件は台帳の found が便の全文で決まった形なのに対し、ここは near(台帳が切った窓)
#     だけを再生するので最初に当たる形が違う(例= 『デブライネ』ではなく『ケヴィン』)。
#     どちらにせよ**同じ対象で鳴っていた**= 拡張後に黙るのはこの56件だ。
try:
    ng.CROSS_SPEAKER_SPAN_EXEMPTION = "off"
    _fires_old = [r for r in FULLNAME if _for_target(r)]
    _pair_old = [r for r in FULLNAME if _same_pair(r)]
    check("G4a 旧仕様では検体が**全件**その対象で鳴る(=この拡張が効いている)",
          len(_fires_old) == len(FULLNAME), (len(_fires_old), len(FULLNAME)))
    check("G4z 旧仕様で同じ組まで戻る行が過半ある(空PASSでない)",
          len(_pair_old) > len(FULLNAME) // 2, (len(_pair_old), len(FULLNAME)))
    check("G4b 旧仕様でも自名義の免除は生きている(2026-09-02 分は別物)",
          verdicts("ルカ・モドリッチ", "【AD研究室(ルカ・モドリッチ)→HQ】了解した。") == [])
finally:
    ng.CROSS_SPEAKER_SPAN_EXEMPTION = "proper"
check("G4c 旧仕様で鳴っていたその行が、拡張後は1件も同じ組で再現しない",
      not [r for r in _pair_old if _same_pair(r)],
      [(r["ts"], r["target"], r["found"]) for r in _pair_old if _same_pair(r)][:5])

print("== G5 must-fail= guardrail②の除外を外すとモドリッチが黙る(\"full\" のとき) ==")
#   ★既定 "proper" では _fullname_is_forbidden は**呼ばれない**= フル名そのものは常に
#     判定へ乗るので guardrail② は構造で成立する。この除外が要るのは "full" だけだ。
#     だから must-fail も "full" の側で見る(C-053= 壊した側は「働く別実装」で作る)。
_saved = ng._fullname_is_forbidden
try:
    ng.CROSS_SPEAKER_SPAN_EXEMPTION = "full"
    ng._fullname_is_forbidden = lambda tk, ent, ov: False
    check("G5a \"full\"で除外を外すと『ルカ・モドリッチへ回す。』が黙る(=guardrail②が効いている)",
          verdicts("ククール", "ルカ・モドリッチへ回す。") == [],
          verdicts("ククール", "ルカ・モドリッチへ回す。"))
    ng.CROSS_SPEAKER_SPAN_EXEMPTION = "proper"
    check("G5c 既定\"proper\"は除外を外しても鳴る(=guardrail②を構造で持っている)",
          any(v["found"] == "ルカ・モドリッチ" for v in verdicts("ククール", "ルカ・モドリッチへ回す。")),
          verdicts("ククール", "ルカ・モドリッチへ回す。"))
finally:
    ng._fullname_is_forbidden = _saved
    ng.CROSS_SPEAKER_SPAN_EXEMPTION = "proper"
check("G5b 戻した後は再び鳴る",
      any(v["found"] == "ルカ・モドリッチ" for v in verdicts("ククール", "ルカ・モドリッチへ回す。")))

print("\n結果: %d PASS / %d FAIL" % (PASS, FAIL))
sys.exit(1 if FAIL else 0)
