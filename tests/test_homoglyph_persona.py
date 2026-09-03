#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""人格名の同形異字(ホモグリフ)正規化の検査(2026-09-04 イージス研究室・依頼=人事部門ククール)。

原症状= Chamiの画面でククールの名義が「(KKール)」に見えた(実物 msg 1545137710820360214 の
本文「オレ(ККール)の持ち場だ」= キリルК U+041A)。名義タグ側の救済は dept_daemon に在ったが
**ラテンK は foreign 扱いされず救済に入らなかった**うえ、**本文中の自称は誰も直していなかった**。

★must-fail(C-053)= 「壊した側」は行を消すのではなく、**もっともらしいが間違った動く実装**へ
  差し替えて赤くする。ここでは (a) 字ごとに機械置換する版 (b) 一意判定を捨てる版 を用意し、
  検査が実際にそれを落とすことを確かめる(常にPASSする検査を足さない)。

走らせ方= `python tests/test_homoglyph_persona.py`
"""
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "scripts", "llm"))
sys.path.insert(0, os.path.join(ROOT, "scripts", "discord"))

import homoglyph as H              # noqa: E402
import dept_daemon as D            # noqa: E402

FAILS = []
ROSTER = ["ククール", "アメス", "ケヴィン・デブライネ", "カスミ"]


def ok(name, cond, detail=""):
    print(("  PASS " if cond else "  FAIL ") + name + (("  " + detail) if detail else ""))
    if not cond:
        FAILS.append(name)


def _resolve(n):
    return n if n in ROSTER else None


# ------------------------------------------------------------------ ① 名義タグ
def t_tag(canon):
    r = []
    r.append(("キリルК版 [ККール] が ククール へ解決される",
              canon("ККール", ROSTER)[0] == "ククール"))
    r.append(("ラテンK版 [KKール] が ククール へ解決される(★今回の穴)",
              canon("KKール", ROSTER)[0] == "ククール"))
    r.append(("片方だけ化けた [Кクール] も解決される",
              canon("Кクール", ROSTER)[0] == "ククール"))
    r.append(("正しい名前は触らない", canon("ククール", ROSTER)[0] == ""))
    r.append(("ただの打ち間違い(ククーる)は寄せない= 誤発火させない",
              canon("ククーる", ROSTER)[0] == ""))
    r.append(("知らない名前は寄せない", canon("モドリッチ", ROSTER)[0] == ""))
    # 2人に当たる字面(ククール と Kクール の両方へ寄せられる)は化けたまま出す=取り違えない
    r.append(("2人に当たる字面は直さない(取り違えない)",
              canon("KKール", ["ククール", "Kクール"])[0] == ""))
    return r


# ------------------------------------------------------------------ ② 本文
def t_body(fix):
    r = []
    src = "オレ(ККール)の持ち場だ。KKールとしては力の限りやる。口約束はしない。"
    got = fix(src, ROSTER)[0]
    r.append(("本文中の自称 (ККール) が (ククール) になる", "(ククール)" in got))
    r.append(("本文中の言及 KKール も直る", got.count("ククール") == 2))
    r.append(("★『力の限り』を壊さない(単字は動かさない)", "力の限り" in got))
    r.append(("★『口約束』を壊さない", "口約束" in got))
    r.append(("化けていない本文は1バイトも変えない",
              fix("ククールが答える。力になる。", ROSTER)[0] == "ククールが答える。力になる。"))
    r.append(("2字以下の名前は触らない(取り違えが怖い)",
              fix("エ口い", ["エロ"])[0] == "エ口い"))
    return r


# ------------------------------------------------------------------ ③ 経路(実物)
def t_route():
    r = []
    for tag in ("[ККール]", "[KKール]"):
        got = D.split_persona_blocks(tag + "\nオレの持ち場だ。", _resolve,
                                     dept="hr-room", names=ROSTER)
        r.append(("部門デーモンが %s を ククール名義で割る" % tag, got[0][0] == "ククール"))
    r.append(("ラテンだけの名乗り [Chami] は foreign 扱いしない",
              D._has_foreign_script("Chami") is False))
    r.append(("日本語と混ざったラテンだけ foreign 扱いする",
              D._has_foreign_script("KKール") is True))
    return r


# ------------------------------------------------------------------ must-fail(C-053)
def _mutant_char_fix(text, names=None):
    """壊した版(a): 字ごとに機械置換する= 一見それらしいが地の文を壊す。"""
    return ("".join(H._FOLD.get(c, c) for c in text), [])


def _mutant_no_unique(name, names=None):
    """壊した版(b): 一意判定を捨てて最初に当たった候補を返す。"""
    for n in (names or []):
        if H._match_name(name, n):
            return n, "mutant"
    return "", "no-match"


def run(title, rows):
    print(title)
    for n, c in rows:
        ok(n, c)


def main():
    run("── ① 名義タグの正規化 ──", t_tag(H.canonical_name))
    run("── ② 本文中の人格名 ──", t_body(H.fix_text))
    run("── ③ 実経路 ──", t_route())

    print("── must-fail(C-053): 壊した実装を検査が落とすか ──")
    for label, rows in (("(a) 字ごと機械置換", t_body(_mutant_char_fix)),
                        ("(b) 一意判定なし", t_tag(_mutant_no_unique))):
        bad = [n for n, c in rows if not c]
        ok("%s は検査に落とされる" % label, bool(bad), "落ちた項目=%d件" % len(bad))

    print()
    if FAILS:
        print("FAIL %d件: %s" % (len(FAILS), " / ".join(FAILS)))
        return 1
    print("ALL PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
