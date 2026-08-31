# -*- coding: utf-8 -*-
"""名乗りタグの**開き括弧抜け**を吸収する(イージス研究室 / 2026-08-31)。

場面(実物)= 改修部門αの返信の1行目が `オタコン]`(バイト列= 「オタコン」+0x5d+CRLF)で来た。
  `local/_daemon_reply_system-engineer.txt`。開き括弧が無いので名乗りと認識されず、
  ①本文の頭に `オタコン]` が残り ②宛名が既定の花海咲季へ落ちた。
  型= docs/departments/kaizen-analyst/名乗り漏れ_開き括弧なしタグ_型.md(改善提案部門トトリ)

★C-053= 壊した側は**動く別の実装**であること。
  ここでの「別実装」= **2026-08-31より前の本物そのもの**(開き括弧が必須の正規表現+同じ分割手順)。
  それ自体は正しく動く= 半角も全角も解決するし、解決できない `[...]` は本文のまま残す。
  足りないのは「開き括弧が抜けた形も名乗りとして読む」という一点だけだ。
  旧版が落とす場面で新版が当たり、**それ以外の場面では旧版と一字も違わない**ことを見る。

    python tests/test_persona_tag_split.py
"""
import io
import json
import os
import re
import sys
import tempfile

PJ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(PJ, "scripts", "llm"))
import dept_daemon as dd                    # noqa: E402
import persona_render                       # noqa: E402

ROOM = {"オタコン", "花海咲季"}


def resolve(name):
    """この部屋(改修部門α)で通用する名前だけを返す。resolve_persona_tag と同じ約束。"""
    return name if name in ROOM else None


# ── 動く別実装= 2026-08-31より前の本物(開き括弧が必須) ────────────────────
_OLD_RE = re.compile(r"^[\[［]([^\[\]［］\n]{1,24})[\]］][ 　]*(.*)$")


def split_old(text, resolve):
    """旧版。壊れてはいない= 半角/全角の名乗りは今と同じに割る。"""
    lines = str(text or "").split("\n")
    head, m, who = 0, None, None
    for idx, ln in enumerate(lines):
        mm = _OLD_RE.match(ln.strip())
        if mm and resolve(mm.group(1)):
            head, m, who = idx, mm, resolve(mm.group(1))
            break
    if not m:
        return [(None, str(text or ""))]
    blocks = [[who, [m.group(2)]]]
    for ln in lines[head + 1:]:
        m2 = _OLD_RE.match(ln.strip())
        who2 = resolve(m2.group(1)) if m2 else None
        if who2:
            blocks.append([who2, [m2.group(2)]])
        else:
            blocks[-1][1].append(ln)
    out = [(n, "\n".join(b).strip()) for n, b in blocks if "\n".join(b).strip()]
    return out or [(None, str(text or ""))]


def audit_of(fn):
    """監査の**本物の書き手**(persona_render._audit)を通し、書かれた行を読み返す。

    ★偽物にするのは**外へ出る手=書き込み先のパスだけ**。判定も分岐も本物のまま回す(§3)。
    """
    fd, path = tempfile.mkstemp(suffix=".jsonl")
    os.close(fd)
    keep = persona_render.RENDER_AUDIT
    persona_render.RENDER_AUDIT = path
    try:
        got = fn()
    finally:
        persona_render.RENDER_AUDIT = keep
    rows = []
    for ln in io.open(path, encoding="utf-8"):
        if ln.strip():
            rows.append(json.loads(ln))
    os.remove(path)
    return got, rows


def main():
    ok = []
    BROKEN = "オタコン]\n\n三笘さん・芽衣の解説、直したわ。"

    # 1) ★must-fail: 旧版は `オタコン]` を名乗りと読めない=
    #    宛名が None(=既定の人格へ落ちる)・本文の頭にタグが残る。新版は両方直る。
    old = split_old(BROKEN, resolve)
    assert old == [(None, BROKEN)], "前提が崩れた(旧版が割れている): %r" % (old,)
    got, rows = audit_of(lambda: dd.split_persona_blocks(BROKEN, resolve, dept="system-engineer"))
    assert len(got) == 1 and got[0][0] == "オタコン", "宛名がオタコンになっていない: %r" % (got,)
    assert "オタコン]" not in got[0][1], "本文の頭にタグが残っている: %r" % (got[0][1],)
    assert got[0][1].startswith("三笘さん"), "本文を削りすぎ/残しすぎ: %r" % (got[0][1],)
    ok.append("開き括弧抜け `オタコン]` を宛名オタコンで割り、本文の頭から消す")

    # 2) その1件が**監査に残る**(片方だけでは読めないので fixed 側も数える)
    assert [r["outcome"] for r in rows] == ["tag_unbracketed_fixed"], \
        "吸収した回数が監査に残っていない: %r" % (rows,)
    assert rows[0]["dept"] == "system-engineer" and rows[0]["persona"] == "オタコン", \
        "監査の部門/人格が違う: %r" % (rows[0],)
    ok.append("吸収した1件が tag_unbracketed_fixed で残る")

    # 3) ★回帰: 半角 `[オタコン]` の既存挙動が**一字も変わらない**
    for t in ("[オタコン] 直したわ。\n次の絵、持ってきて。",
              "［オタコン］ 直したわ。\n次の絵、持ってきて。"):
        got, rows = audit_of(lambda t=t: dd.split_persona_blocks(t, resolve, dept="system-engineer"))
        assert got == split_old(t, resolve), "旧版と結果が変わった: %r / %r" % (got, split_old(t, resolve))
        assert rows == [], "括弧が揃っているのに監査へ書いている: %r" % (rows,)
    ok.append("半角[]・全角［］の既存挙動は一字も変わらない(監査にも出さない)")

    # 4) ★解決できない形は**本文のまま**(誤爆させない=沈黙させない)。ただし数える。
    NOISE = "検証] まずは前提を並べる。\n次に測る。"
    got, rows = audit_of(lambda: dd.split_persona_blocks(NOISE, resolve, dept="system-engineer"))
    assert got == [(None, NOISE)], "解決できない `検証]` を勝手にタグ扱いした: %r" % (got,)
    assert got == split_old(NOISE, resolve), "旧版と結果が変わった: %r" % (got,)
    assert [r["outcome"] for r in rows] == ["tag_unbracketed_leak"], \
        "残った漏れが監査に残っていない: %r" % (rows,)
    ok.append("解決できない形は本文のまま返し、tag_unbracketed_leak で数える")

    # 5) 名乗りの形ですらない普通の本文は、監査にも1行も出さない(騒がしくしない)
    PLAIN = "直したわ。次の絵、持ってきて。"
    got, rows = audit_of(lambda: dd.split_persona_blocks(PLAIN, resolve, dept="system-engineer"))
    assert got == [(None, PLAIN)] and rows == [], "素の本文に反応している: %r / %r" % (got, rows)
    ok.append("素の本文には反応しない")

    # 6) 2人が喋る便= 途中の行が開き括弧抜けでも、そこで人格が切り替わる
    TWO = "[花海咲季] こっちは終わったわよ。\nオタコン] 俺の方も入れた。"
    got, _ = audit_of(lambda: dd.split_persona_blocks(TWO, resolve, dept="system-engineer"))
    assert [n for n, _b in got] == ["花海咲季", "オタコン"], "2人目で切り替わっていない: %r" % (got,)
    assert "オタコン]" not in got[1][1], "2人目の本文にタグが残っている: %r" % (got[1][1],)
    assert len(split_old(TWO, resolve)) == 1, "前提が崩れた(旧版が2つに割れている)"
    ok.append("途中の行が開き括弧抜けでも、そこで人格が切り替わる")

    print("\n".join("PASS  " + s for s in ok))
    print("%d/%d PASS" % (len(ok), len(ok)))
    return 0


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    sys.exit(main())
