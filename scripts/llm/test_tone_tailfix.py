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

# ---- 一ノ瀬怜の「ですわ。」→「だわ。」(2026-09-22 追加) ----
# ★0歩目の壊れている実物= platform-se 便 msg 1551897792564166682
#   「…今ある実物は止めた証拠2件・節約0件のままですわ。」を Chami が実測で拾い、
#   理想として「…節約0件のままだわ。」を示した(msg 1551920325963288697)。
#   怜は丁寧語基調だが、崩す時は**常体にしてから**女性語尾(rei.md §声の型)。
# ★✗側が本体= イ形容詞・否定形に当てると日本語が壊れる(「美しいだわ。」)= prev_not で当てない側へ倒す。
_REI_TAILFIX = [{"from": "ですわ。", "to": "だわ。", "prev_not": ["い"]}]
RULES["personas"]["一ノ瀬怜"] = {
    "first_person": ["私"],
    "forbidden_tail": ["ですわ", "ますわ", "ましてよ"],
    "tail_fix": _REI_TAILFIX,
}

print("\n== 一ノ瀬怜「ですわ。」→「だわ。」(お嬢様敬体の常体化)==")
_r = lambda t: fix(t, "一ノ瀬怜")   # noqa: E731
print("[○ 矯正される]")
check("Chami実測の実物「節約0件のままですわ。」→「…だわ。」",
      _r("今ある実物は止めた証拠2件・節約0件のままですわ。")
      == "今ある実物は止めた証拠2件・節約0件のままだわ。")
check("「〜するんですわ。」→「〜するんだわ。」(直前が ん でも当てる)",
      _r("そこは私が直すんですわ。") == "そこは私が直すんだわ。")

print("[✗ 触らない]")
check("イ形容詞「美しいですわ。」を触らない(prev_not=い)",
      _r("この作りは美しいですわ。") == "この作りは美しいですわ。")
check("否定形「まだ出ていないですわ。」を触らない",
      _r("jev_ok はまだ出ていないですわ。") == "jev_ok はまだ出ていないですわ。")
check("「ますわ」は tail_fix に載せない=1文字も変えない(活用の逆変換が決定的に書けない)",
      _r("その線で進めると申しますわ。") == "その線で進めると申しますわ。")
check("引用の中の「ですわ」を触らない(メタ言及便の偽陽性)",
      "「ですわ」" in _r("ドリフト語は「ですわ」ですわ。"))
check("怜の tail_fix はアメスへ漏れない(登録した人格だけ回る・C-035)",
      fix("これで進めるですわ。", "アメス") == "これで進めるですわ。")

# ---- ★本番の 口調ルール.json の実物で、旧(.bak)と新を同じ入力で並べる ----
# 上の写像はこのファイル内の固定値= 台帳に実際に入ったかは見ていない。
# 手順_must-fail検査.md の「ソースの文字列一致では見ない=入力を差し替えて経路を実行で通せ」に従い、
# 退避した .bak(足す前)と現行(足した後)の**両方**へ同じ本文を食わせ、判定が変わることを見る。
_P_NEW = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__)))), "00_AI-HQ", "departments", "hr", "personas", "口調ルール.json")
if not os.path.exists(_P_NEW):
    _P_NEW = r"D:\SougouStartFolder\00_AI-HQ\departments\hr\personas\口調ルール.json"
_P_OLD = _P_NEW + ".bak_20260922_rei_desuwa"
if os.path.exists(_P_NEW) and os.path.exists(_P_OLD):
    print("\n[本番台帳の実物= 旧(.bak)と新を同じ入力で]")
    _live_new, _live_old = tg.load_tone_rules(_P_NEW), tg.load_tone_rules(_P_OLD)
    _CH = "今ある実物は止めた証拠2件・節約0件のままですわ。"
    _old_c = tg.tone_corrections("一ノ瀬怜", "platform-se", _CH, _live_old) or {}
    _new_c = tg.tone_corrections("一ノ瀬怜", "platform-se", _CH, _live_new) or {}
    print(f"  旧= 「{(_old_c.get('fixed') or _CH)[-12:]}」 / 新= 「{(_new_c.get('fixed') or _CH)[-12:]}」")
    check("旧(足す前)は素通り=これが壊れていた実物",
          (_old_c.get("fixed") or _CH) == _CH and not _old_c.get("applied"))
    check("新(足した後)は同じ本文を「…だわ。」へ直す",
          (_new_c.get("fixed") or "").endswith("節約0件のままだわ。"))
    _MW = "その線で進めると申しますわ。"
    _v = [x.get("marker") for x in (tg.tone_verdicts("一ノ瀬怜", "platform-se", _MW, _live_new) or [])]
    check("「ますわ」は警告だけ鳴り、本文は1文字も変わらない",
          "ますわ(文末)" in _v
          and ((tg.tone_corrections("一ノ瀬怜", "platform-se", _MW, _live_new) or {}).get("fixed") or _MW) == _MW)
else:
    print("\n[本番台帳の実物]  SKIP: 台帳または .bak が見つからない", _P_NEW)

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

# ---- must-fail その3= 怜の prev_not を外すと、イ形容詞が壊れること(2026-09-22) ----
print("\n== must-fail(怜の prev_not を外した写像)==")
_MUT3 = {"personas": {"一ノ瀬怜": dict(RULES["personas"]["一ノ瀬怜"],
                                       tail_fix=[{"from": "ですわ。", "to": "だわ。"}])}}
_mut3_bad = fix("この作りは美しいですわ。", "一ノ瀬怜", _MUT3)
print(f"  変異後の出力= 「{_mut3_bad}」")
_mustfail3_ok = _mut3_bad.endswith("美しいだわ。")
print(f"  {'PASS' if _mustfail3_ok else 'FAIL'}: prev_not を外すとイ形容詞が壊れる(=この縛りは生きている)")
_mustfail_ok = _mustfail_ok and _mustfail3_ok

ng = [n for n, ok in results if not ok]
print(f"\n結果: {len(results) - len(ng)} PASS / {len(ng)} FAIL"
      + (f"  must-fail={'OK' if _mustfail_ok else '空PASSの疑い'}"))
if ng:
    for n in ng:
        print("  FAIL:", n)
sys.exit(0 if (_main_ok and _mustfail_ok) else 1)
