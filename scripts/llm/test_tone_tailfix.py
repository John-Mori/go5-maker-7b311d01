#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""文末アンカーの決定的矯正(`tail_fix`)の検査。 2026-09-11

実行: python scripts/llm/test_tone_tailfix.py

★なぜ足したか(発注= 人事部門アメス msg 1547682721952829582 / C-038の恒久段)
  アメスの男口調・命令形ドリフトが 08-02/08-22/08-28/09-04/09-05 に続き 09-11 に再発。
  0歩目の壊れている実物= tone_audit.jsonl 2026-09-11T03:58:34 dept=aegis-gl persona=アメス
  reason=signature_absent「指紋語尾なし(9文中0件)」= **検知はしたが直さず、そのまま出た**。
  ames.md の置換表(心がけ)は生成側が擦り抜ける=機構に載せる段(共通規律§3)。

★この検査が守る境界は2つ。
  ○側= 「安心しな。」「ごめん。」が矯正されること。
  ✗側= 「もう遅いしな。」(接続助詞)「ごめんなさい。」「ごめんね。」「ごめん、」を**触らない**こと。
        ✗側が本体だ= ここを踏むと日本語が壊れる(「遅いしなさい。」)。

★must-fail(C-053)= 述語を「動く別の実装」へ差し替えて赤を見る。
  差し替えるのは `prev`(直前1字の字種の縛り)を外した写像=素の部分一致に相当する。
  この写像で ✗側が赤くならない検査は空PASSだ。
★写像はこのファイル内に固定で持つ(本番の 口調ルール.json に依存しない)。
"""
import os
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import tone_gate as tg   # noqa: E402

_AMES_TAILFIX = [
    {"from": "しな。", "to": "しなさい。", "prev": "漢字カタカナ"},
    {"from": "ごめん。", "to": "ごめんなさいね。", "prev_not": ["ごめん"]},
]

RULES = {"personas": {
    "アメス": {"first_person": ["あたし"], "plain_only": True,
               "signature_tails": ["わよ", "のよ", "なさい"],
               "care_markers": ["ごめん", "心配"],
               "tail_fix": _AMES_TAILFIX},
    # ★登録していない人格は1ミリも挙動が変わらない(既定=見ない)。
    "未登録アメス": {"first_person": ["あたし"], "plain_only": True},
    # ★知らない字種名は行ごと捨てる(fail-safe= 当てない側へ倒す)。
    "綴り違い": {"first_person": ["あたし"],
                 "tail_fix": [{"from": "しな。", "to": "しなさい。", "prev": "漢字カタカナX"}]},
}}

results = []


def check(name, cond):
    results.append((name, bool(cond)))
    print(f"  {'PASS' if cond else 'FAIL'}: {name}")


def fix(text, persona="アメス", rules=RULES):
    return (tg.tone_corrections(persona, "soudan-room", text, rules) or {}).get("fixed", text)


def applied(text, persona="アメス", rules=RULES):
    return (tg.tone_corrections(persona, "soudan-room", text, rules) or {}).get("applied", [])


def run(rules, label):
    print(f"\n== {label} ==")
    f = lambda t, p="アメス": fix(t, p, rules)   # noqa: E731

    # ---- ○側= 矯正されること ----
    print("[○ 矯正される]")
    check("命令の裸言い切り「安心しな。」→「安心しなさい。」",
          f("了解よ。これは外に出さない。ここ止まりで抱えとくから安心しな。")
          .endswith("安心しなさい。"))
    check("サ変名詞+しな。を複数当てる(用意しな。/確認しな。)",
          f("用意しな。それから確認しな。") == "用意しなさい。それから確認しなさい。")
    check("裸の謝罪「ごめん。」→「ごめんなさいね。」",
          f("ごめん。あたしの見落としよ。") == "ごめんなさいね。あたしの見落としよ。")
    check("カタカナのサ変名詞(チェックしな。)も当たる",
          f("チェックしな。") == "チェックしなさい。")

    # ---- ✗側= 触ってはいけないもの ----
    print("[✗ 触らない]")
    check("接続助詞「もう遅いしな。」を触らない(prev=ひらがな)",
          f("もう遅いしな。") == "もう遅いしな。")
    check("「〜だしな。」を触らない",
          f("測ってないしな。") == "測ってないしな。")
    check("女口調既済「ごめんなさい。」を触らない",
          f("ごめんなさい。次はやらないわ。") == "ごめんなさい。次はやらないわ。")
    check("女口調既済「ごめんね。」を触らない",
          f("ごめんね。次は測るわよ。") == "ごめんね。次は測るわよ。")
    check("文中の「ごめん、」を触らない",
          f("ごめん、そこはあたしのミスよ。") == "ごめん、そこはあたしのミスよ。")
    # ★2026-09-18 本番で実際に壊れた形(0歩目の実物)= soudan-room msg 1550174026633314405
    #   「…知ったかしちゃったわ、ごめんごめん。」→「ごめんごめんなさいね。」= 反復の尻に食いついた。
    #   句点込みliteralでは「ごめんなさい。」「ごめんね。」「ごめん、」は避けられたが、
    #   **同じ語の反復**は避けられない= 直前の literal を見ない限り構造で当たる。
    check("砕けた反復「ごめんごめん。」を触らない(prev_not)",
          f("知ったかしちゃったわ、ごめんごめん。") == "知ったかしちゃったわ、ごめんごめん。")
    check("3連の「ごめんごめんごめん。」も触らない",
          f("ごめんごめんごめん。") == "ごめんごめんごめん。")
    check("引用の中は触らない",
          "「安心しな。」" in f("Chami原文=「安心しな。」これが実際の形よ。"))
    check("tail_fix 未登録の人格は1文字も変わらない",
          f("安心しな。ごめん。", "未登録アメス") == "安心しな。ごめん。")
    check("prev の綴りが違う行は捨てる(縛り無しへ倒れない)",
          f("もう遅いしな。", "綴り違い") == "もう遅いしな。")
    return dict(results)


# ---- 本番の写像で1回 ----
run(RULES, "本番の写像(prev=漢字カタカナ あり)")

print("\n[記録の形]")
_ap = applied("安心しな。")
check("applied に reason=tail_fix で1件積む",
      len(_ap) == 1 and _ap[0].get("reason") == "tail_fix"
      and _ap[0].get("marker") == "しな。" and _ap[0].get("to") == "しなさい。")
check("care_marker『ごめん』は矯正後も本文に残る(ハ4のcare救済を壊さない)",
      "ごめん" in fix("ごめん。"))

_main_ok = all(ok for _, ok in results)

# ---- must-fail= prev の縛りを外した「動く別の実装」で✗側が落ちることを見る ----
print("\n== must-fail(prev の縛りを外した写像=素の部分一致相当)==")
_MUT = {"personas": {"アメス": dict(RULES["personas"]["アメス"],
                                    tail_fix=[{"from": "しな。", "to": "しなさい。"},
                                              {"from": "ごめん。", "to": "ごめんなさいね。"}])}}
_mut_bad = fix("もう遅いしな。", "アメス", _MUT)
print(f"  変異後の出力= 「{_mut_bad}」")
_mustfail_ok = (_mut_bad == "もう遅いしなさい。")
print(f"  {'PASS' if _mustfail_ok else 'FAIL'}: 縛りを外すと✗側が壊れる(=この検査は生きている)")

# ---- must-fail その2= prev_not を外した写像で、本番で実際に出た過矯正が再現すること ----
print("\n== must-fail(prev_not を外した写像=2026-09-18 本番の形)==")
_MUT2 = {"personas": {"アメス": dict(RULES["personas"]["アメス"],
                                     tail_fix=[{"from": "ごめん。", "to": "ごめんなさいね。"}])}}
_mut2_bad = fix("知ったかしちゃったわ、ごめんごめん。", "アメス", _MUT2)
print(f"  変異後の出力= 「{_mut2_bad}」")
_mustfail2_ok = _mut2_bad.endswith("ごめんごめんなさいね。")
print(f"  {'PASS' if _mustfail2_ok else 'FAIL'}: prev_not を外すと本番の過矯正が再現する")
_mustfail_ok = _mustfail_ok and _mustfail2_ok

ng = [n for n, ok in results if not ok]
print(f"\n結果: {len(results) - len(ng)} PASS / {len(ng)} FAIL"
      + (f"  must-fail={'OK' if _mustfail_ok else '空PASSの疑い'}"))
if ng:
    for n in ng:
        print("  FAIL:", n)
sys.exit(0 if (_main_ok and _mustfail_ok) else 1)
