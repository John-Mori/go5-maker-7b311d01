# -*- coding: utf-8 -*-
"""出力ゲート ルールA へ**簡体字**を合流させた分の検査(イージス研究室 / 2026-09-01)。

場面(実物)= 部門の返信の前置きに「实况」(実況の簡体字)が出た。
  Chami原文(2026-08-31 15:16・改善提案部門 msg 1544003068067192903)=
  「前置き実況って描きたいんだろうけど日本の常用漢字じゃない表現やめてね」。
  研究室HQ実測= 00_AI-HQ/departments/hr/memory/*.jsonl 32部屋/6,033行に真の事故4行
  (改善提案部門3行・イージス研究室1行=aegis-gl.jsonl L510 / 2026-08-31 21:24)。
  全部同じ語・全部21:15〜21:36に集中= **モデル側の癖**=人に言って直る類ではない。

★C-053= 壊した側は**動く別の実装**であること。
  ここでの「別実装」= **2026-09-01より前の本物そのもの**= `detect_hangul` だけを見るゲート。
  それ自体は今も正しく動く(ハングルは検知し、再生成→警告付き送信まで通す)。
  足りないのは「簡体字も同じ流れに載せる」一点だけ= だから old は削除せず**そのまま残してある**。

    python tests/test_simplified_gate.py
"""
import os
import sys

PJ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(PJ, "scripts", "llm"))
import dept_daemon as d                      # noqa: E402
import lang_gate as lg                       # noqa: E402

STRIP = d.split_wip_marker
NG = []


def check(name, cond):
    print(("PASS  " if cond else "FAIL  ") + name)
    if not cond:
        NG.append(name)


def gate_old(text, regen=None, strip_marker=None):
    """動く別実装= 2026-09-01より前の本番のルールA(ハングルだけを見る)。

    引数・返り値の形は今の hangul_gate と同じ。違うのは**検知器が detect_hangul である**一点だけ。
    """
    info = {"hit1": False, "regenerated": False, "hit2": False, "warned": False, "kind": ""}
    base = str(text or "")
    if d.detect_hangul(base) is None:
        return base, info
    info["hit1"] = True
    info["kind"] = "hangul"
    if regen is None:
        info["warned"] = True
        return base + "\n\n" + d.HANGUL_WARN, info
    regen_text = regen()
    if regen_text:
        info["regenerated"] = True
        cleaned = str(regen_text)
        if strip_marker is not None:
            cleaned, _ = strip_marker(cleaned)
        if cleaned and d.detect_hangul(cleaned) is None:
            return cleaned, info
        info["hit2"] = True
    info["warned"] = True
    return base + "\n\n" + d.HANGUL_WARN, info


# 実物の事故文(aegis-gl.jsonl L510 / kaizen-analyst の3行と同じ語)
BROKEN = "五月の呼び方変更=完了。以下、实况。\n名乗りタグの件、機構側で塞いだ。"
CLEAN = "五月の呼び方変更=完了。以下、実況。\n名乗りタグの件、機構側で塞いだ。"

# --- 1) ★must-fail: 旧ルールAはこの事故を1件も検知しない。新ルールAは検知する ----------
out_old, info_old = gate_old(BROKEN, regen=lambda: CLEAN, strip_marker=STRIP)
check("must-fail: 旧ルールA(ハングルのみ)は实况を素通しする",
      info_old["hit1"] is False and out_old == BROKEN)
out, info = d.hangul_gate(BROKEN, regen=lambda: CLEAN, strip_marker=STRIP)
check("新ルールA: 实况を検知し kind=simplified",
      info["hit1"] is True and info["kind"] == "simplified")
check("新ルールA: 再生成できれいな本文へ差し替え・警告は付かない",
      out == CLEAN and info["regenerated"] and info["warned"] is False)

# --- 2) 再生成しても残るなら**元文に警告付きで送る**(沈黙にしない=fail-open) -----------
out, info = d.hangul_gate(BROKEN, regen=lambda: "まだ实况が残る", strip_marker=STRIP)
check("2回目も残れば元文+簡体字の警告(沈黙にしない)",
      out.startswith(BROKEN) and d.SIMPLIFIED_WARN in out and info["hit2"] and info["warned"])
check("警告文そのものは検知に鳴かない(自分の警告に再発火しない)",
      d.detect_nonjp(d.SIMPLIFIED_WARN) is None and d.detect_nonjp(d.HANGUL_WARN) is None)

# --- 3) 再生成できない/失敗/空でも送る(fail-open) ------------------------------------
out, info = d.hangul_gate(BROKEN, regen=None, strip_marker=STRIP)
check("regen=None でも警告付きで送る", d.SIMPLIFIED_WARN in out and info["warned"])


def boom():
    raise RuntimeError("生成が落ちた")


out, info = d.hangul_gate(BROKEN, regen=boom, strip_marker=STRIP)
check("再生成の例外は握り潰して警告付き送信", d.SIMPLIFIED_WARN in out and info["warned"])
out, info = d.hangul_gate(BROKEN, regen=lambda: "", strip_marker=STRIP)
check("再生成が空でも警告付き送信", d.SIMPLIFIED_WARN in out and info["warned"])

# --- 4) ★自動置換は絶対にしない(实→実 に書き換えて送っていないこと) -------------------
out, _ = d.hangul_gate(BROKEN, regen=None, strip_marker=STRIP)
check("自動置換をしていない(元文はそのまま残る)", BROKEN in out)

# --- 5) ★回帰: ハングル(ORG-45)の挙動は1ミリも変えていない --------------------------
out, info = d.hangul_gate("左右각약9%", regen=lambda: "各約9%", strip_marker=STRIP)
check("回帰: ハングルは再生成で解消・kind=hangul",
      out == "各約9%" and info["kind"] == "hangul" and info["warned"] is False)
out, info = d.hangul_gate("左右각약9%", regen=lambda: "まだ각약が残る", strip_marker=STRIP)
check("回帰: ハングル2回目も残れば HANGUL_WARN", d.HANGUL_WARN in out and info["hit2"])
check("回帰: ハングルと簡体字が両方在ればハングルとして扱う",
      d.detect_nonjp("각약と实况")["kind"] == "hangul")

# --- 6) ★誤発火させない= ここが表の生命線(HQ注意3「緩めではなく正確に」) --------------
NORMAL = [
    "結論から言う。名乗りタグの件は機構側で塞いだ。実況の前置きも落ちる。",
    "机の上に書類を据える。斗酒を叶えるのは只今の后。里の云う通り、准教授が冲へ。",
    "常用漢字の外にも正当な字は在る= 諦める・拉致・綺麗・髙橋・﨑・彌。",
    "各約9%を薄く覆う。独立した学習を国の医療体制で会う声。",
    "URL= https://example.com/a/b?c=1 と `code_ident` と ORG-45。",
    "",
]
for s in NORMAL:
    check("誤発火しない: %r" % (s[:26] or "(空文字)",), d.detect_nonjp(s) is None)
check("None も非文字列も例外を出さない",
      d.detect_nonjp(None) is None and d.detect_nonjp(12345) is None)
check("通常の日本語返信はゲートを1文字も通さない",
      d.hangul_gate(NORMAL[0], regen=lambda: "使われない", strip_marker=STRIP)[0] == NORMAL[0])

# --- 7) 表そのものの健全性(書き間違いが誤発火に直結するので機械で見る) -----------------
check("表に简==日 の組が残っていない",
      all(k != v for k, v in lg._SIMPLIFIED_MAP.items()))
check("表に「日本語でも使う漢字」を入れていない",
      not (set("机据斗叶后里云只准冲決丰庄筑独学国体医声当双万与号写台干") & set(lg._SIMPLIFIED_MAP)))
check("実物の事故字が表に載っている(实=実 / 况=況 / 单=単)",
      lg._SIMPLIFIED_MAP.get("实") == "実" and lg._SIMPLIFIED_MAP.get("况") == "況"
      and lg._SIMPLIFIED_MAP.get("单") == "単")
check("検知結果に日本語の対応字が付く(ログの説明用)",
      d.detect_nonjp(BROKEN)["jp"] == "実")

# --- 8) 監査= 直した回数と漏れた回数を**対で**残す(C-041) ----------------------------
import json                                   # noqa: E402
import tempfile                               # noqa: E402

fd, tmp = tempfile.mkstemp(suffix=".jsonl")
os.close(fd)
keep = d.HANGUL_AUDIT
d.HANGUL_AUDIT = tmp
try:
    d.audit_hangul("aegis-gl", {"msg_id": "1543957324992086177"}, BROKEN)
    d.audit_hangul("aegis-gl", {"msg_id": "x"}, "左右각약9%")
    d.audit_hangul("aegis-gl", {"msg_id": "y"}, NORMAL[0])
finally:
    d.HANGUL_AUDIT = keep
rows = [json.loads(l) for l in open(tmp, encoding="utf-8") if l.strip()]
os.remove(tmp)
check("監査は2件だけ(通常の返信は書かない=騒がしくしない)", len(rows) == 2)
check("event で簡体字とハングルを数え分けられる",
      [r["event"] for r in rows] == ["simplified", "hangul"])
check("簡体字の行に char/jp/dept/msg_id が載る",
      rows[0]["char"] == "实" and rows[0]["jp"] == "実"
      and rows[0]["dept"] == "aegis-gl" and rows[0]["msg_id"] == "1543957324992086177")

print("-" * 60)
print("%s (%d NG)" % ("ALL PASS" if not NG else "NG: " + " / ".join(NG), len(NG)))
sys.exit(1 if NG else 0)
