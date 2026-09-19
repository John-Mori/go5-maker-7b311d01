# -*- coding: utf-8 -*-
"""回帰ガード= 「送信の人格欄 ≠ 本文の名乗り」と「本文に裏方の英語足場文が混じる」を落とす
(イージス研究室 / 2026-09-20 / ESC-hr-room-1550916219786240062)。

場面(実物1本)= manga-shorts msg 1550851084782800968(2026-09-19 21:48:31)。
  生成側の原文1行目=
    `Dept-memory recorded and verified. Here is my single return to 軍議
     (the daemon relays this reply本文 and marks the 実依頼 `completed` from my transcript):`
  ① `strip_english_preamble` は「最初の日本語文字」で切るので、**行の途中の「軍」**で切れ、
     `軍議 (the daemon relays this reply本文 and marks ...):` が本文の頭として部屋へ出た
     (send_audit.jsonl:3697 の head がその実物)。
  ② 頭が足場文になったせいで `[名前]` タグが成立せず、名義が解けないまま部屋の既定人格
     (fail-safe先の三笘薫)の名前とアイコンで送られた。本文は「軍議へ。ヴィルシーナだ。」=
     ヴィルシーナとして筋が通っていた=**欄と名乗りの食い違い**。
  ③ さらに `_speaker` も三笘薫で解決されるので、口調ゲートDがヴィルシーナの
     「でございます」を三笘の「だ」へ書き直した(tone_audit.jsonl 21:48:26 / 21:48:30)。

★この検査が見るのは3つ= (a)足場文が残らないこと (b)タグ無しでも本文の名乗りで名義が
  決まること (c)その配線が dept_daemon の送信前ループに**在る**こと。
★§must-fail は2本。壊す側は C-053 に従い「動く旧実装」へ戻す(空実装で赤くしない)。
  ・②の旧実装= 「最初の日本語文字で切る」= 英語だけの前置きは**今も正しく剥がせる**。
  ・①の旧実装= 出力ゲートF(misattributed_speaker)= `[名前]` で名乗った便は**今も直せる**。

    python tests/test_persona_label_vs_selfname.py
"""
import os
import sys

PJ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(PJ, "scripts", "llm"))
import lang_gate as lg                       # noqa: E402
import tone_gate as tg                       # noqa: E402

NG = []


def check(name, cond):
    print(("PASS  " if cond else "FAIL  ") + name)
    if not cond:
        NG.append(name)


# --- 実物(送信台帳・部屋memoryから起こした原文) ------------------------------------
INCIDENT = (
    "Dept-memory recorded and verified. Here is my single return to 軍議 "
    "(the daemon relays this reply本文 and marks the 実依頼 `completed` from my transcript):"
    "\n\n---\n\n"
    "軍議へ。ヴィルシーナでございます。\n\n"
    "**skill化②変換型「実コメント法」台本生成、実物で完遂いたしました。** "
    "置き場は `5chShortMovie\\骨格\\henkan_pipeline\\` 配下でございます。\n\n"
    "- **型v2** — `台本パイプライン設計_v2.md`。§1を旧法から差し替えました。\n"
    "ちゃみのご確認を待っております。"
)
# manga-shorts の名簿(dept_daemon conf["personas"] の正式名)
ROSTER = ["三笘薫", "ヴィルシーナ", "十王星南", "早坂芽衣", "アメス", "カスミ"]
DEFAULT_PERSONA = "三笘薫"          # 名義が引けない時の fail-safe 先(=事故で表に出た方)

# 英語だけの前置き(旧実装でも正しく剥がれる形=変異体の健全性を測る物差し)
PURE_EN_PREAMBLE = (
    "I have recorded the dept memory and verified the files. Emitting the reply now.\n\n"
    "[ヴィルシーナ]\n調べたわ、ちゃみ。台本は3本とも受入チェッカを通ったわよ。"
)


# --- 1) ②足場文= 剥がした残りの1行目に英語の散文が残らない -------------------------
_out, _info = lg.strip_english_preamble(INCIDENT)
check("①足場文が本文の頭に残らない(the daemon relays this reply が消える)",
      "daemon relays" not in _out)
check("②切り落とした足場文は黙って消さず info へ残る(監査できる)",
      "daemon relays" in (_info.get("scaffold_line") or ""))
check("③本文は1文字も欠けない(名乗りの行から始まる)",
      _out.startswith("軍議へ。ヴィルシーナでございます。"))
check("④本文の中身は残る(足場の次の段落以降を食わない)",
      "台本パイプライン設計_v2.md" in _out and "ちゃみのご確認" in _out)

# 通常便を1ミリも変えない(安全弁)
for _name, _t in (
        ("頭から日本語", "ちゃみ、台本を3本書いたわ。置き場は henkan_pipeline よ。"),
        ("英語は固有名詞だけ", "dept_daemon.py の strip_english_preamble を直した。実物で確認済みだ。"),
        ("コード柵が先頭", "```\npython scripts/llm/quota_burn.py --hours 6\n```\n上を叩けば出る。"),
):
    _o, _i = lg.strip_english_preamble(_t)
    check("⑤通常便は触らない(%s)" % _name, _o == _t and not _i.get("stripped"))

# 英語だけの前置きは従来どおり剥がれ、タグは壊れない
_o2, _i2 = lg.strip_english_preamble(PURE_EN_PREAMBLE)
check("⑥英語だけの前置きは従来どおり剥がれ、`[名前]` を食わない",
      _i2.get("stripped") and _o2.startswith("[ヴィルシーナ]"))


# --- 2) ①名義= タグが無くても本文の名乗りで話者が決まる ----------------------------
check("⑦タグ無しの実物から本文の名乗り(ヴィルシーナ)を引ける",
      tg.self_named_speaker(_out, ROSTER) == "ヴィルシーナ")
_sp = tg.self_named_speaker(_out, ROSTER)
check("⑧その名乗りは既定人格と食い違う=名義を動かす根拠になる",
      _sp in ROSTER and _sp != DEFAULT_PERSONA)
check("⑨名簿の外へは出さない(部屋に居ない人格は返らない)",
      tg.self_named_speaker("軍議へ。ククールだ。話がある。", ROSTER) is None)
for _name, _t, _exp in (
        ("他人の紹介は拾わない", "この件の担当はヴィルシーナだ。任せた。", None),
        ("ただの言及は拾わない", "ヴィルシーナの案を見た。悪くない。", None),
        ("引用の中は拾わない", "『ヴィルシーナだ』と彼女は言った。だが違う。", None),
        ("2人ぶんは決めない", "三笘薫だ。ヴィルシーナだ。", None),
        ("名乗りが無い通常便", "Chami、了解した。台本を書く。", None),
        ("一人称+は の名乗りは拾う", "私はアメスよ。今日は代打で入ってるわ。", "アメス"),
):
    check("⑩%s" % _name, tg.self_named_speaker(_t, ROSTER) == _exp)


# --- 3) 配線= dept_daemon の送信前ループが F-2 を実際に呼んでいる --------------------
_src = open(os.path.join(PJ, "scripts", "llm", "dept_daemon.py"), encoding="utf-8").read()
check("⑪ゲートF-2が送信前ループに配線されている(呼び出しが消えたらここが赤くなる)",
      "audit_self_named(self.dept, _speaker, _part, _roster, rec)" in _src)
check("⑫F-2は口調ゲートC/Dより手前に在る(名義を直してから口調を見る)",
      _src.index("audit_self_named(self.dept") < _src.index("audit_naming(self.dept, _speaker, _part, rec)"))
check("⑬機械名義の便は対象外(機械の告知を人格名義へ動かさない)",
      "elif not self.machine_named():" in _src)


# --- 4) must-fail ①: 「最初の日本語文字で切る」旧実装へ戻すと足場文が残る -----------
#   C-053= 空実装で赤くしない。旧実装は本番に居た動く実装で、英語だけの前置きは今も剥がせる。
_keep_cut = lg._cut_scaffold_head_line
lg._cut_scaffold_head_line = lambda body, info=None: body      # ←これが旧実装そのもの
try:
    _o3, _i3 = lg.strip_english_preamble(PURE_EN_PREAMBLE)
    check("(変異体の健全性)旧実装でも英語だけの前置きは剥がせる=空実装ではない",
          _i3.get("stripped") and _o3.startswith("[ヴィルシーナ]"))
    _o4, _ = lg.strip_english_preamble(INCIDENT)
    check("★must-fail①: 旧実装へ戻すと足場文が本文の頭に残る(=事故が再現する)",
          "daemon relays" in _o4)
finally:
    lg._cut_scaffold_head_line = _keep_cut

# --- 5) must-fail ②: ゲートF(一人称で見る旧実装)だけでは、この便を拾えない ---------
#   旧実装= misattributed_speaker。`[名前]` で名乗った便の取り違えは**今も直せる**(健全性)。
#   足りないのは「タグが無い便を本文の名乗りで決める」一点=そこがこの検査の主張。
_rules = tg.load_tone_rules(os.path.join(
    PJ, "..", "00_AI-HQ", "departments", "hr", "personas", "口調ルール.json"))
if _rules:
    _tagged = "[三笘薫]\nあたしが台本を3本書いたわ。受入チェッカも通したのよ。"
    check("(変異体の健全性)旧実装はタグ付きの取り違えを今も直せる=空実装ではない",
          tg.misattributed_speaker("三笘薫", _tagged, _rules, ROSTER) == "アメス")
    check("★must-fail②: 旧実装(一人称で見るゲートF)ではこの便を拾えない",
          tg.misattributed_speaker(DEFAULT_PERSONA, _out, _rules, ROSTER) is None)
else:
    check("口調ルール.json を読めた(must-fail②の前提)", False)

print("-" * 60)
print("全PASS" if not NG else "FAIL %d件: %s" % (len(NG), NG))
sys.exit(1 if NG else 0)
