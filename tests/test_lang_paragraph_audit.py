# -*- coding: utf-8 -*-
"""恒久策#2(lang_gate拡張)の検査= 文中の英語段落 / 日本語以外のスクリプトを**台帳へ載せる**
(イージス研究室 / 2026-09-02)。

場面(実物)= 00_AI-HQ の各部屋 memory の返信4,659便を通したところ、
  ・英語段落 32件(0.69%)= 「File saved and memory recorded. Emitting the reply.」
    「Now the room reply as De Bruyne (GL, orchestration-facing).」等の**本物の英文漏れ**。
    どれも本文の大半は日本語なので `detect_english_dump`(本文まるごと英語)では鳴らない。
  ・他スクリプト 42件(0.90%)= キリル29/ハングル10/文字化けU+FFFD 2/ギリシャ1。
    決め打ちの3種を持つ表は「起きた事故を1つずつ足した表」で、次の1種はまた素通しになる。

★この策は**検知のみ**= 送信可否・再生成・⚠️付き送信の分岐を1ミリも動かさない。
  よって検査の主眼は2つ: ①新しい事故が台帳に載ること ②既存の便の扱いが変わらないこと。
★§5= must-fail を2本。壊す側は C-053 に従い「動く別の実装」へ戻す(空実装で赤くしない)。
★判定と分岐は本物を実行する。偽物にするのは**書き先(temp)とログ(黙らせる)だけ**
  = 本番の local を汚さないため。

    python tests/test_lang_paragraph_audit.py
"""
import json
import os
import sys
import tempfile

PJ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(PJ, "scripts", "llm"))
import dept_daemon as d                      # noqa: E402
import lang_gate as lg                       # noqa: E402

NG = []
RUN = []


def check(name, cond):
    RUN.append(name)
    print(("PASS  " if cond else "FAIL  ") + name)
    if not cond:
        NG.append(name)


# --- 実物に近い便 ---------------------------------------------------------------------
# ①日本語の返信の**途中**に英語段落(実測32件と同じ型)。
MIXED_EN = (
    "[ケヴィン・デブライネ] 恒久策#2を入れた。検知だけで送信は止めない。\n"
    "\n"
    "Verified: all seven departments have the paragraph detector wired into the audit path.\n"
    "\n"
    "以上だ。次は#4の名乗りタグ修復へ行く。"
)
# ②**先頭**が英語の便(「動く別の実装」が拾える型= 変異体が空実装でないことの証拠)。
HEAD_EN = (
    "File saved and memory recorded. Emitting the room reply now for the department.\n"
    "\n"
    "[ケヴィン・デブライネ] 保存は済んだ。中身はこれからだ。"
)
# ③英文ダンプ(本文まるごと英語)= 既存の判定が拾う型。扱いを変えていないことを見る。
DUMP_EN = (
    "I have completed the requested changes to the department daemon and verified "
    "the audit path. The gate behaviour is unchanged and the reply is delivered."
)
# ④日本語として正当な文字だけの通常返信(騒がしくしてはいけない)。
NORMAL_JP = (
    "[ケヴィン・デブライネ] 結論から言う。封筒に応答言語の固定文を常設した。\n"
    "根拠= 検査33件PASS。次の一手= lang_gate の拡張を配線する。\n"
    "URL= https://example.com/a?b=1 と `code_ident` と ORG-45・改修部門α。"
)
# ⑤キリル混入(既存の決め打ちが拾う=event は今まで通り "cyrillic")。
CYRILLIC_JP = "[ケヴィン・デブライネ] 測定は済んだ。GО判定は保留だ。"        # О=U+041E
# ⑥ギリシャ+文字化け(決め打ちの3種の外=これまで誰も気づかなかった型)。
#   ★σ・α・β・Σ 等は「改修部門α」「係数σ」で**正当に**使うので許可表に入れてある。
#     許可表の外(χ)だけが鳴る= 誤発火を抑える設計がそのまま検査になっている。
GREEK_JP = "[ケヴィン・デブライネ] 係数はχで置いた。数値は後で出す。"        # χ=U+03C7
MOJIBAKE_JP = "[ケヴィン・デブライネ] 文字が欠けた= 実�況。ここは直す。"      # U+FFFD


def run_audits(calls, which="english"):
    """本物の audit_* を実行し、書かれた台帳の行を返す(書き先とログだけ偽物)。

    ★偽物にするのは「外へ出る手」だけ= 書き先(temp)と log(黙らせる)。
      判定・分岐・戻り値は本物のまま通す(ソースの文字列一致では検査にならない)。
    """
    fd, tmp = tempfile.mkstemp(suffix=".jsonl")
    os.close(fd)
    keep_h, keep_e, keep_log = d.HANGUL_AUDIT, d.ENGLISH_AUDIT, d.log
    d.HANGUL_AUDIT = tmp
    d.ENGLISH_AUDIT = tmp
    d.log = lambda *a, **k: None
    rets = []
    try:
        for i, reply in enumerate(calls):
            fn = d.audit_english if which == "english" else d.audit_hangul
            rets.append(fn("aegis-gl", {"msg_id": str(i)}, reply))
    finally:
        d.HANGUL_AUDIT, d.ENGLISH_AUDIT, d.log = keep_h, keep_e, keep_log
    rows = [json.loads(l) for l in open(tmp, encoding="utf-8") if l.strip()]
    os.remove(tmp)
    return rows, rets


# --- 1) 英語段落= 実物の型が台帳に載る(設計§5-2) --------------------------------------
rows, rets = run_audits([MIXED_EN], "english")
check("文中の英語段落が検知される(既存のダンプ判定では鳴らない便)", len(rows) == 1)
check("event で英文ダンプと数え分けられる",
      bool(rows) and rows[0]["event"] == "english_paragraph")
check("台帳の行に latin/words/by/index/excerpt が載る",
      bool(rows) and rows[0]["latin"] >= 35 and rows[0]["words"] >= 5
      and rows[0]["by"] in ("heuristic", "py3langid")
      and rows[0]["index"] > 0 and "Verified" in rows[0]["excerpt"])
check("dept と msg_id が載る(後から出所を追える)",
      bool(rows) and rows[0]["dept"] == "aegis-gl" and rows[0]["msg_id"] == "0")
check("★戻り値は None= english_gate の分岐に一切影響しない", rets == [None])
check("この便は既存のダンプ判定では鳴らない(=新しく拾えた分だ)",
      lg.detect_english_dump(MIXED_EN) is None)

# --- 2) 既存の扱いを1ミリも変えていない ------------------------------------------------
rows, rets = run_audits([DUMP_EN, NORMAL_JP], "english")
check("英文ダンプは今まで通り event=\"english_dump\" で載る",
      len(rows) == 1 and rows[0]["event"] == "english_dump")
check("英文ダンプの戻り値は hit のまま(=再生成→言い換え→保留が動く)",
      rets[0] is not None and rets[1] is None)
check("通常の日本語返信は1行も書かない(騒がしくしない)",
      not [r for r in rows if r["msg_id"] == "1"])
out, info = d.english_gate(MIXED_EN, regen=lambda: "使われない",
                           translate=lambda t: "使われない")
check("★実物の分岐: 英語段落が混じった便も**そのまま送られる**(保留にしない)",
      out == MIXED_EN and not info.get("suppressed"))

# --- 3) 他スクリプト= 決め打ちの3種の外を拾う ------------------------------------------
rows, rets = run_audits([GREEK_JP, MOJIBAKE_JP, CYRILLIC_JP, NORMAL_JP], "hangul")
kinds = [r["event"] for r in rows]
check("ギリシャ・文字化けが新しく拾える(3種の表には無い)",
      kinds[:2] == ["other_script", "other_script"])
check("キリルは今まで通り event=\"cyrillic\"(既存の集計を壊さない)",
      "cyrillic" in kinds and kinds.index("cyrillic") == 2)
check("通常の日本語返信は1行も書かない", len(rows) == 3)
check("台帳の行に script/char/codepoint/index/context が載る",
      bool(rows) and rows[0]["script"] == "GREEK" and rows[0]["char"] == "χ"
      and rows[0]["codepoint"] == "U+03C7" and rows[0]["index"] > 0
      and "χ" in rows[0]["context"])
check("文字化け(U+FFFD)も同じ口で拾える",
      len(rows) > 1 and rows[1]["codepoint"] == "U+FFFD")
check("★他スクリプトの戻り値は None= hangul_gate の再生成・⚠️を動かさない",
      rets[0] is None and rets[1] is None)
check("キリルの戻り値は hit のまま(既存ゲートは今まで通り動く)", rets[2] is not None)
check("★実物の分岐: ギリシャ字の便はゲートを1文字も通さず素通しで送られる",
      d.hangul_gate(GREEK_JP, regen=lambda: "使われない",
                    strip_marker=d.split_wip_marker)[0] == GREEK_JP)

# --- 4) 誤発火しない(実測0.7〜0.9%の裏取り) -------------------------------------------
QUIET = [
    "[アメス] 進捗は3件。KPIのA1は0件、A2は算出中、A3は0件です。",
    "設定キーは `dept_daemon` / `session_relay` / GO5_LOCAL_DIR を使う。",
    "コマンド= python scripts/llm/dispatch.py --dept hr-room --audience ai",
    "```\nfor x in range(10):\n    print(x)  # this loop prints numbers to stdout\n```\n"
    "上のコードは検知しない(コード柵は判定から外す)。",
    "改修部門αとβ、係数はΣで足す(ギリシャ字は正当な用途がある)。",
    "",
]
check("誤発火しない: 英語段落",
      all(lg.detect_english_paragraph(s) is None for s in QUIET))
check("誤発火しない: 他スクリプト",
      all(lg.detect_other_script(s) is None for s in QUIET))
check("短い英語(閾値未満)では鳴らない",
      lg.detect_english_paragraph("Done.\n\nやった。") is None)

# --- 5) fail-open= 監査が配送を殺さない -------------------------------------------------
rows, rets = run_audits([None, 12345, ""], "english")
check("None/非文字列/空文字でも例外を出さず None を返す(英語側)",
      rets == [None, None, None] and not rows)
rows, rets = run_audits([None, 12345, ""], "hangul")
check("None/非文字列/空文字でも例外を出さず None を返す(スクリプト側)",
      rets == [None, None, None] and not rows)

keep_e, keep_log = d.ENGLISH_AUDIT, d.log
d.ENGLISH_AUDIT = os.path.join(tempfile.gettempdir(), "no_such_dir_xyz", "\0bad", "a.jsonl")
d.log = lambda *a, **k: None
try:
    r = d.audit_english("aegis-gl", {"msg_id": "z"}, MIXED_EN)
finally:
    d.ENGLISH_AUDIT, d.log = keep_e, keep_log
check("★書き先が壊れていても便は死なない(戻り値 None・例外を外へ出さない)", r is None)

# --- 6) 本番の local を汚していない -----------------------------------------------------
check("検査は本番の台帳を触らない(書き先は temp のみ)",
      d.ENGLISH_AUDIT.endswith("english_audit.jsonl")
      and d.HANGUL_AUDIT.endswith("hangul_audit.jsonl"))

# --- 7) must-fail ①英語段落= 「先頭段落だけ見る」動く別実装へ戻すと赤くなる -------------
#   C-053= 空実装では赤くしない。これは本番に居た `strip_english_preamble` と同じ着眼
#   (英語は前置きに出る)で、**先頭が英語の便は今も正しく拾える**動く実装だ。
#   足りないのは「真ん中の段落も見る」一点=そこが検査の主張。
def _paragraph_head_only(text, min_latin=35, min_words=5):
    s = str(text or "")
    head = lg._PARA_SPLIT_RE.split(lg._mask_code_spans(s))[0].strip()
    if not head or lg._JP_RE.search(head):
        return None
    latin = len(lg._LATIN_RE.findall(head))
    words = lg._EN_WORD_RE.findall(head)
    if latin < min_latin or len(words) < min_words:
        return None
    return {"latin": latin, "words": len(words), "index": 0, "by": "head_only",
            "excerpt": head[:160]}


check("(変異体の健全性)先頭が英語の便は別実装でも拾える=空実装ではない",
      _paragraph_head_only(HEAD_EN) is not None)
keep_fn = d.detect_english_paragraph
d.detect_english_paragraph = _paragraph_head_only
try:
    rows_mut, _ = run_audits([MIXED_EN], "english")
finally:
    d.detect_english_paragraph = keep_fn
check("★must-fail①: 先頭段落だけ見る実装に戻すと、文中の英語段落が台帳に載らない",
      len(rows_mut) == 0)

# --- 8) must-fail ②他スクリプト= 「決め打ちの3種だけ」へ戻すと赤くなる -------------------
#   これは 2026-09-01 まで本番だった判定そのもの(ハングル/簡体字/キリル)。今も正しく動く。
def _known3_only(text, span=20):
    hit = d.detect_nonjp(text)
    if not hit:
        return None
    return {"char": hit["char"], "script": hit["kind"].upper(),
            "codepoint": hit["codepoint"], "index": hit["index"],
            "context": hit["context"]}


check("(変異体の健全性)キリル便は別実装でも拾える=空実装ではない",
      _known3_only(CYRILLIC_JP) is not None)
keep_fn = d.detect_other_script
d.detect_other_script = _known3_only
try:
    rows_mut, _ = run_audits([GREEK_JP, MOJIBAKE_JP], "hangul")
finally:
    d.detect_other_script = keep_fn
check("★must-fail②: 決め打ちの3種だけへ戻すと、ギリシャ・文字化けが台帳に載らない",
      len(rows_mut) == 0)

print("-" * 60)
print("%d/%d PASS%s" % (len(RUN) - len(NG), len(RUN),
                        "" if not NG else "  NG: " + " / ".join(NG)))
sys.exit(1 if NG else 0)
