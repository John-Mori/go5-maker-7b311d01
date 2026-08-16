# -*- coding: utf-8 -*-
"""口調ゲートD: 関西弁マーカーの**データ側拡張**(口調ルール.json `dialect_kansai_extra`)の検査。

なぜ要るか= 関西弁のパターン列は tone_gate.py にハードコードされていて、
1形足すたびに「基盤コードの編集 + 全デーモンの載せ替え」が要った。検知の正本は人事部門
(ORG-11)なのに、実体は人事部門が触れない場所に在った=**穴が埋まらない構造の摩擦**。
2026-08-17 に人事部門(ククール)が提案し、イージス研究室で実装(C-038/C-042)。

★この検査が守る不変条件:
  ①組み込み列は消えない(データ側は**足すだけ**)
  ②データ側の壊れた1件でゲート全体が落ちない(共通規律§3 fail-open)
  ③文字列で書いたらリテラル(正規表現メタで事故らない)
  ④どの形がデータ側から載っているかを**機械で数えられる**(C-041)

走らせ方= python scripts/llm/test_tone_dialect_extra.py
"""
import copy
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import tone_gate as tg  # noqa: E402

RULES_PATH = os.path.join("D:", os.sep, "SougouStartFolder", "00_AI-HQ",
                          "departments", "hr", "personas", "口調ルール.json")

_ok = 0
_ng = 0


def chk(label, cond):
    global _ok, _ng
    if cond:
        _ok += 1
        print("  PASS", label)
    else:
        _ng += 1
        print("  FAIL", label)


def dialect(persona, text, rules):
    return [v for v in tg.tone_verdicts(persona, "system-engineer", text, rules)
            if v.get("reason") == "dialect_kansai"]


def main():
    rules = tg.load_tone_rules(RULES_PATH)
    if rules is None:
        print("SKIP: 口調ルール.json が読めない(%s)" % RULES_PATH)
        return 0

    print("== ①組み込み列は消えない(回帰) ==")
    chk("「元凶や。」は鳴る", dialect("オタコン", "これが元凶や。", rules))
    chk("「やなく」(8/17追加)は鳴る", dialect("オタコン", "外れやなく本命だ。", rules))
    chk("標準語「ではなく/じゃなく」は鳴らない",
        not dialect("オタコン", "外れではなく本命だ。じゃなく、こうだ。", rules))

    print("== ②データ側=文字列はリテラル ==")
    r1 = copy.deepcopy(rules)
    r1["dialect_kansai_extra"] = ["まいど"]
    chk("「まいど」が鳴る", any(v["marker"] == "まいど" for v in dialect("オタコン", "まいど、こうなった。", r1)))
    chk("無関係な文は鳴らない", not dialect("オタコン", "普通の報告です。", r1))
    chk("載っている形を機械で数えられる", tg.dialect_extra_names(r1) == ["まいど"])
    r3 = copy.deepcopy(rules)
    r3["dialect_kansai_extra"] = ["a.c"]
    chk("リテラル: a.c は鳴る", any(v["marker"] == "a.c" for v in dialect("オタコン", "これは a.c だ", r3)))
    chk("リテラル: abc は鳴らない(. が任意文字にならない)",
        not any(v["marker"] == "a.c" for v in dialect("オタコン", "これは abc だ", r3)))

    print("== ③データ側=dict は正規表現で絞れる ==")
    r2 = copy.deepcopy(rules)
    r2["dialect_kansai_extra"] = [{"name": "てへん", "pattern": r"(?<![大])てへん"}]
    chk("「出来てへん」が鳴る", any(v["marker"] == "てへん" for v in dialect("オタコン", "まだ出来てへん。", r2)))
    chk("絞りが効く(「大てへん」は鳴らない)",
        not any(v["marker"] == "てへん" for v in dialect("オタコン", "大てへんだ。", r2)))

    print("== ④壊れた1件でゲート全体を落とさない(fail-open) ==")
    r4 = copy.deepcopy(rules)
    r4["dialect_kansai_extra"] = [{"name": "壊れ", "pattern": "(("}, {"name": "まいど"}]
    chk("壊れた正規表現はその1件だけ捨てる", "壊れ" not in tg.dialect_extra_names(r4))
    chk("壊れがあっても他のデータ側は生きる", "まいど" in tg.dialect_extra_names(r4))
    chk("壊れがあっても組み込み列は生きる", dialect("オタコン", "これが元凶や。", r4))
    for bad in (None, "string", 123, [], [1, 2, None], [{}]):
        rb = copy.deepcopy(rules)
        rb["dialect_kansai_extra"] = bad
        try:
            tg.tone_verdicts("オタコン", "system-engineer", "ふつうの文だ。", rb)
            chk("異常な型でも例外を投げない %r" % (bad,), True)
        except Exception as e:                                    # noqa: BLE001
            chk("異常な型でも例外を投げない %r -> %s" % (bad, e), False)
    chk("rules=None でも落ちない",
        tg.tone_verdicts("オタコン", "system-engineer", "元凶や。", None) is not None)
    chk("データ未設定なら extra は空", tg.dialect_extra_names(rules) == [])

    print("\n== %d/%d PASS ==" % (_ok, _ok + _ng))
    return 1 if _ng else 0


if __name__ == "__main__":
    sys.exit(main())
