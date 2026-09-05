# -*- coding: utf-8 -*-
"""test_codex_trigger — 純関数 is_codex_mentioned の召喚判定を実行で通す(Discord接続不要)。

イージス研究室(デブライネ)依頼2026-09-05の受け入れ線=
  ・「ソリッド・スネーク」(別人・品質管理部門)への言及で **召喚しない**(False)
  ・確定呼称「ネイキッド・スネーク」/「ネイキッド」で **召喚する**(True)
  ・Chami指定の「ボス」で **召喚する**(True)
must-fail(C-053)= 短縮「スネーク」を素で足すと誤召喚する、を機械が赤で捕まえることも確かめる。
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import codex_trigger as ct  # noqa: E402


CASES = [
    # (本文, 期待, 狙い)
    ("ソリッド・スネークに聞いてくれ", False, "別人=誤召喚しない"),
    ("品質管理部門のソリッド・スネーク、レビュー頼む", False, "別人=誤召喚しない2"),
    ("ネイキッド・スネークに頼む", True, "確定呼称で召喚"),
    ("ネイキッドに任せる", True, "確定呼称の短縮で召喚"),
    ("ボスに任せる", True, "Chami指定の召喚名"),
    ("codexで実装して", True, "素の名指し"),
    ("コーデックスお願い", True, "カナ名指し"),
]


def run(label, tokens_override=None):
    saved = ct.TOKENS
    if tokens_override is not None:
        ct.TOKENS = tokens_override
    try:
        ok = True
        print(f"--- {label} (TOKENS={ct.TOKENS}) ---")
        for body, want, why in CASES:
            got = ct.is_codex_mentioned(body)
            mark = "PASS" if got == want else "FAIL"
            if got != want:
                ok = False
            print(f"  [{mark}] want={want!s:5} got={got!s:5}  {why}  << {body}")
        return ok
    finally:
        ct.TOKENS = saved


if __name__ == "__main__":
    # 本番のTOKENSで検査
    green = run("本番TOKENS")
    # C-053 変異: 短縮「スネーク」を素で足すと、別人ケースが True へ転ぶ(=テストに歯がある)
    mutant = tuple(ct.TOKENS) + ("スネーク",)
    mut_ok = run("変異(素のスネーク追加=誤り)", tokens_override=mutant)
    if mut_ok:
        print("  ※変異が全緑=このテストは誤召喚を捕まえられていない(歯が無い)")
    else:
        print("  ※変異で別人ケースが赤=ガードに歯がある(期待どおり)")
    sys.exit(0 if green else 1)
