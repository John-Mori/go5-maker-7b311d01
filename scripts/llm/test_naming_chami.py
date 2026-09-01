#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""呼称ゲートC: Chami呼称の合流点担保(chami_address バックストップ)の回帰テスト。

実行:            python scripts/llm/test_naming_chami.py
変異(must-fail): python scripts/llm/test_naming_chami.py --mutate

★2026-09-01 新設。引き金= Chami「ちゃみくんってよんで!!おこです!」
  (msg 1544349888945455155 / 回送= 改善提案部門 1544351414455771229)。
  壊れた実物= departments/hr/memory/*.jsonl で「ちゃみくん」が正の話者の便 287件中
  **18件**が裸の「ちゃみ」を含んでいた(中野五月14 / 姫崎莉波3 / トトリ1)。
  写像(呼称ルール.json chami_address)は正しく、送信口が**その表を読んでいなかった**。
★ここで釘付けにするのは2つ:
  ① 「ちゃみくん」が正の話者の裸の「ちゃみ」が合流点で直ること
  ② それ以外の話者(一ノ瀬怜・デブライネ・既定・「Chami」派)は**1文字も触らない**こと
    = blanket にした瞬間に赤になる(変異2)。
★ルールは本番の写像を使わずここで固定する(人事部門が写像を育てても赤にならない)。
"""
import os
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import naming_gate as ng   # noqa: E402

results = []

# 本番と同じ形の最小写像(chami_address は「文字列」と「dict」の両方が実在する)。
RULES = {
    "chami_address": {
        "default": "ちゃみ",
        "overrides": {
            "トトリ": "ちゃみくん",
            "アスナ": "ちゃみくん",
            "中野五月": {"allowed": ["ちゃみくん"], "forbidden": ["Chamiくん"]},
            "カスミ": {"allowed": ["ちゃみくん", "助手くん"], "forbidden": ["あんた"]},
            "一ノ瀬怜": {"allowed": ["ちゃみ", "あなた"], "forbidden": ["あんた"]},
            "ケヴィン・デブライネ": {"allowed": ["Chami", "ちゃみ"],
                                     "forbidden": ["ちゃみくん"]},
            "シャビ・アロンソ": "Chami",
        },
    },
    "target_detect_forms": {"Chami": ["ちゃみくん"]},
    "speaker_target_overrides": [
        # ★デブライネの逆ピン(2026-08-23 Chami指摘)= これと衝突させない。
        {"speaker": "ケヴィン・デブライネ", "target": "Chami",
         "allowed": ["Chami", "ちゃみ"], "forbidden": ["ちゃみくん"]},
    ],
    "honorific_required_targets": {},
}

# 事故の実物(2026-08-24T04:51:15 dept=llm-edu persona=中野五月)の書き出し。
REAL = "ちゃみ、その通りだ。"
REAL_WANT = "ちゃみくん、その通りだ。"


def check(name, cond):
    results.append((name, bool(cond)))
    print(f"  {'PASS' if cond else 'FAIL'}: {name}")


def fix(persona, dept, text):
    return ng.naming_corrections(persona, dept, text, RULES)


def main():
    # ---- 1) 壊れている実物が直ること(0歩目の再現をそのまま検査にした) ----
    v = ng.naming_verdicts("中野五月", "llm-edu", REAL, RULES)
    check("実物: 裸の「ちゃみ」が違反として出る",
          [x for x in v if x.get("reason") == "chami_address"])
    r = fix("中野五月", "llm-edu", REAL)
    check("実物: 中野五月の裸「ちゃみ」が「ちゃみくん」へ直る", r["fixed"] == REAL_WANT)
    check("実物: applied に reason=chami_address が1件",
          len(r["applied"]) == 1 and r["applied"][0]["reason"] == "chami_address"
          and r["applied"][0]["to"] == "ちゃみくん"
          and r["applied"][0]["found"] == "ちゃみ")
    check("実物: 直しきったら警告は残さない", r["remaining"] == [])

    r = fix("トトリ", "kaizen-analyst", "ちゃみ、これはちゃみの読み通りだ。ちゃみに返す。")
    check("複数出現: 3箇所とも直る",
          r["fixed"] == "ちゃみくん、これはちゃみくんの読み通りだ。ちゃみくんに返す。"
          and r["applied"] and r["applied"][0]["count"] == 3)

    # ---- 2) 既に正しい形は触らない ----
    r = fix("トトリ", "kaizen-analyst", "ちゃみくん、これ見て。")
    check("既に正: 「ちゃみくん」は無変化・警告も出ない",
          r["fixed"] == "ちゃみくん、これ見て。" and not r["applied"] and not r["remaining"])

    # ---- 3) ★話者別(blanket 禁止)= ここが本体 ----
    T = "ちゃみ、任せた。"
    check("話者別: 一ノ瀬怜の「ちゃみ」は直さない(allowed に「ちゃみ」)",
          fix("一ノ瀬怜", "hq", T)["fixed"] == T)
    check("話者別: デブライネの「ちゃみ」は直さない(allowed に「ちゃみ」)",
          fix("ケヴィン・デブライネ", "aegis-gl", T)["fixed"] == T)
    check("話者別: 「Chami」派(アロンソ)の「ちゃみ」も触らない(C-035で広げない)",
          fix("シャビ・アロンソ", "hq", T)["fixed"] == T)
    check("話者別: 写像に無い話者は既定「ちゃみ」=触らない",
          fix("ククール", "hr-room", T)["fixed"] == T)
    check("話者別: カスミ(allowed=[ちゃみくん,助手くん])は直る",
          fix("カスミ", "llm-edu", T)["fixed"] == "ちゃみくん、任せた。")

    # ---- 4) デブライネの逆ピン(forbidden=ちゃみくん)と衝突しない ----
    r = fix("ケヴィン・デブライネ", "aegis-gl", "ちゃみくん、任せた。")
    check("逆ピン: デブライネの「ちゃみくん」は本文を触らず警告のみ",
          r["fixed"] == "ちゃみくん、任せた。" and not r["applied"]
          and any(x.get("reason") == "forbidden" for x in r["remaining"]))

    # ---- 5) 敬称付き・マスク・危険境界は素通し(狭く取る) ----
    check("敬称付き: 「ちゃみさん」は触らない",
          fix("トトリ", "kaizen-analyst", "ちゃみさん、これ見て。")["fixed"]
          == "ちゃみさん、これ見て。")
    check("敬称付き: 「ちゃみ君」は触らない",
          fix("トトリ", "kaizen-analyst", "ちゃみ君、これ見て。")["fixed"]
          == "ちゃみ君、これ見て。")
    Q = "「ちゃみ」と書いてしまった。"
    check("マスク: 引用の中は書き換わらない", fix("トトリ", "kaizen-analyst", Q)["fixed"] == Q)
    C = "写像の既定は `ちゃみ` のままだ。"
    check("マスク: コード片(バッククォート)は書き換わらない",
          fix("トトリ", "kaizen-analyst", C)["fixed"] == C)
    TAG = "[中野五月]\nちゃみ、了解した。"
    check("名乗りタグ: 1行目のタグを壊さずに本文だけ直る",
          fix("中野五月", "llm-edu", TAG)["fixed"] == "[中野五月]\nちゃみくん、了解した。")
    D = "ちゃみ用の設定を見た。"
    r = fix("トトリ", "kaizen-analyst", D)
    check("危険境界: 直後が漢字なら直さず警告に残す",
          r["fixed"] == D and len(r["remaining"]) == 1)

    # ---- 6) 人事部門(VOCATIVE_ONLY_DEPTS)は呼びかけ位置だけ ----
    H = "あれはちゃみの指示だ。"
    check("人事部門: 地の文は直さない(呼称ルールを論じる部屋)",
          fix("トトリ", "hr-room", H)["fixed"] == H)
    check("人事部門: 呼びかけ位置(行頭+読点)は直る",
          fix("トトリ", "hr-room", "ちゃみ、確認した。")["fixed"] == "ちゃみくん、確認した。")

    # ---- 7) fail-open(§3 可用性に関わる所は fail-open) ----
    check("fail-open: rules が None なら素通し",
          ng.naming_corrections("中野五月", "llm-edu", REAL, None)["fixed"] == REAL)
    check("fail-open: 空本文",
          ng.naming_corrections("中野五月", "llm-edu", "", RULES)["fixed"] == "")
    check("fail-open: 写像に chami_address が無くても落ちない",
          ng.naming_corrections("中野五月", "llm-edu", REAL,
                                {"honorific_required_targets": {}})["fixed"] == REAL)

    # ---- 8) 配線(共有関数の呼び出し元を数える・§3) ----
    here = os.path.dirname(os.path.abspath(__file__))
    callers = []
    for rel in ("dept_daemon.py", "output_gates.py"):
        with open(os.path.join(here, rel), encoding="utf-8") as f:
            if "naming_corrections(" in f.read():
                callers.append(rel)
    check("配線: naming_corrections の呼び出し元は常駐/relayとミラーの2本",
          sorted(callers) == ["dept_daemon.py", "output_gates.py"])

    ok = sum(1 for _, c in results if c)
    ng_ = len(results) - ok
    print(f"\n{ok} PASS / {ng_} FAIL")
    return 0 if ng_ == 0 else 1


# ---------------------------------------------------------------- 変異(C-053)
#   ★変異は「動く別の実装」へ戻す= 文法を壊した偽の赤にしない。
def _mut_off():
    """変異1= バックストップを入れなかった世界(今の本番)。動くが実物を直せない。"""
    ng.CHAMI_ADDRESS_BACKSTOP = False


def _mut_blanket():
    """変異2= 話者を見ず全員に「ちゃみくん」を当てる実装(blanket)。
    動くが、一ノ瀬怜・デブライネ・既定の「ちゃみ」まで書き換える。"""
    def patched(persona, rules):
        return ([ng.CHAMI_TARGET_FORM], [])
    ng._chami_address_map = patched


def _mut_no_honorific_guard():
    """変異3= 直後の敬称を見ずに裸扱いする実装。
    動くが「ちゃみさん」を「ちゃみくんさん」へ化けさせる。"""
    orig = ng._iter_occurrences

    def patched(s, bare, allowed):
        for i, actual, ok in orig(s, bare, allowed):
            yield i, (bare if bare == ng.CHAMI_BARE else actual), ok
    ng._iter_occurrences = patched


MUTANTS = (
    ("変異1 バックストップ無し(今の本番)", _mut_off,
     "実物: 中野五月の裸「ちゃみ」が「ちゃみくん」へ直る"),
    ("変異2 話者を見ない blanket", _mut_blanket,
     "話者別: 一ノ瀬怜の「ちゃみ」は直さない(allowed に「ちゃみ」)"),
    ("変異3 敬称付きも裸として扱う", _mut_no_honorific_guard,
     "敬称付き: 「ちゃみさん」は触らない"),
)


def mutate():
    bad = 0
    o_flag, o_map, o_iter = (ng.CHAMI_ADDRESS_BACKSTOP, ng._chami_address_map,
                             ng._iter_occurrences)
    for name, fn, want_red in MUTANTS:
        del results[:]
        fn()
        try:
            print(f"\n=== {name} ===")
            try:
                main()
            except Exception as e:
                print("  (検査が例外で止まった: %s)" % e)
        finally:
            (ng.CHAMI_ADDRESS_BACKSTOP, ng._chami_address_map,
             ng._iter_occurrences) = o_flag, o_map, o_iter
        red = [n for n, c in results if not c]
        hit = want_red in red
        print(f"  → 狙った1件が赤か: {'OK' if hit else 'NG'}  (赤={len(red)}件)")
        if not hit:
            bad += 1
    print(f"\n変異 {len(MUTANTS)}件中 {len(MUTANTS) - bad}件が狙いどおり赤")
    return 0 if bad == 0 else 1


if __name__ == "__main__":
    sys.exit(mutate() if "--mutate" in sys.argv else main())
