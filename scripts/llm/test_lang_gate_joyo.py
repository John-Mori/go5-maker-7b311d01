#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""簡体字ゲートが**常用漢字を叩かない**ことの検査(2026-09-05・イージス研究室)。

壊れていた実物= 2026-09-05 03:07 manga-shorts / 03:24 ad研究室 の2便。どちらも本文は
**危惧**という普通の日本語で、ゲートは `惧` を簡体字だと言い、置換先に**非常用漢字の `懼`**
を案内していた。Chami原文「常用漢字じゃない表現やめてね」と逆を向いていた。

★C-053= 壊れた側は**動く別実装**で作る(ここでは「除外表を持たない版」の対応表を組み直し、
  同じ入力で赤になることを先に見せる)。ソースの文字列一致では固めない。

走らせ方:
  python scripts/llm/test_lang_gate_joyo.py
"""
import os
import sys

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)
except Exception:
    pass

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import lang_gate as lg     # noqa: E402

RESULTS = []

# 実物の本文(hangul_audit.jsonl の context から採った)
REAL_1 = ".ymmpに入っていません**＝まさに危惧されていた未反映。`local/5ch/"
REAL_2 = "ymmp`に入っていません**＝まさに危惧されていた未反映**」"
# 効いている検知が死んでいないことの確認用(実測で6便鳴っている取り違え)
REAL_SIMPLIFIED = "宛名=ククール・**前置き实况もタグも**消滅"


def chk(name, cond, detail=""):
    RESULTS.append((name, bool(cond)))
    print(f"  {'PASS' if cond else '★FAIL'}  {name}{('  ' + detail) if detail else ''}")


def broken_map():
    """★壊れた側= 除外表を持たない対応表(2026-09-05 以前の実装と同じ組み立て)。"""
    m = {}
    for pair in lg._SIMPLIFIED_PAIRS.split():
        if len(pair) == 2 and pair[0] != pair[1]:
            m.setdefault(pair[0], pair[1])
    return m


def main():
    print("簡体字ゲート/常用漢字の検査")

    # --- 赤: 除外表が無い実装は、同じ本文(危惧)で鳴ってしまう
    old = broken_map()
    chk("J-0 ★赤= 除外表が無いと『危惧』が簡体字として引っかかる(壊れていた実物)",
        any(c in old for c in REAL_1), f"惧→{old.get('惧')}")
    chk("J-0b ★赤= しかも置換先の『懼』は常用漢字ではない(逆向きの案内)",
        old.get("惧") == "懼", "")

    # --- 緑: 本実装は同じ本文で鳴らない
    chk("J-1 ★緑= 実物1(manga-shorts 03:07)で鳴らない",
        lg.detect_simplified(REAL_1) is None, "")
    chk("J-2 ★緑= 実物2(ad研究室 03:24)で鳴らない",
        lg.detect_simplified(REAL_2) is None, "")
    chk("J-3 『惧』は対応表そのものから消えている",
        "惧" not in lg._SIMPLIFIED_MAP and not lg._SIMPLIFIED_RE.search("危惧"), "")

    # --- 効いている検知を殺していない(一括で落とさなかった理由の裏取り)
    hit = lg.detect_simplified(REAL_SIMPLIFIED)
    chk("J-4 本物の取り違え(实況)は今までどおり鳴る",
        hit is not None and hit["char"] == "实", f"→ {hit}")
    hit2 = lg.detect_simplified("进捗は追ってる")
    chk("J-4b 実測で出た事故(进捗)も今までどおり鳴る",
        hit2 is not None and hit2["char"] == "进", "")

    # --- 増えたら人が気づく(人手の点検を要件にせず、機構で止める)
    review = lg.simplified_review_keys()
    unknown = review - lg._CP932_KEYS_KNOWN
    chk("J-5 日本語でも書ける字が黙って増えていない(増えたらここが赤・見直しの合図)",
        not unknown, f"未点検= {''.join(sorted(unknown)) or '(無し)'}")
    chk("J-5b 除外した字は対応表に残っていない",
        all(k not in lg._SIMPLIFIED_MAP for k in lg._JOYO_EXCLUDE), "")

    # --- fail-safe(落ちない)
    chk("J-6 空・None・非文字列でも例外を出さない",
        all(lg.detect_simplified(x) is None for x in ("", None, 0)), "")

    ng = [n for n, ok in RESULTS if not ok]
    print(f"\n{len(RESULTS) - len(ng)}/{len(RESULTS)} PASS")
    if ng:
        print("★FAIL: " + " / ".join(ng))
    return 1 if ng else 0


if __name__ == "__main__":
    sys.exit(main())
