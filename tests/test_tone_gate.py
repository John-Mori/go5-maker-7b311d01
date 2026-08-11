#!/usr/bin/env python3
"""GOLDEN(純関数・LLM不要): 出力ゲート ルールD=口調ドリフト検知(一人称の食い違い) 2026-08-03.

設計書= 00_AI-HQ/設計_口調ゲート_送信直前_名乗りと本文の食い違い_2026-08-03.md。
裁定= 研究室HQ(msg 1533789472783863899)「①警告のみ段階=投入Go / ②inline LLMは却下」。
写像= 00_AI-HQ/departments/hr/personas/口調ルール.json(この1本をゲートと同じく引く=ORG-11)。

実行: python -X utf8 tests/test_tone_gate.py   (全PASSで終了コード0)
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.normpath(os.path.join(HERE, ".."))
sys.path.insert(0, os.path.join(ROOT, "scripts", "llm"))

from tone_gate import load_tone_rules, tone_verdicts  # noqa: E402

RULES_PATH = os.path.join(
    r"D:\SougouStartFolder\00_AI-HQ",
    "departments", "hr", "personas", "口調ルール.json")


def _run():
    rules = load_tone_rules(RULES_PATH)
    if not rules:
        print(f"FAIL: 口調ルール.json を読めない: {RULES_PATH}")
        return 1

    # (話者, 部屋, 本文, 期待=発火するか, 説明)
    cases = [
        ("アメス", "aegis-gl",
         "オレが記録しておくわね。", True,
         "T-1 アメス(あたし)のブロックに『オレ』=別人格の一人称=発火(HQ例示)"),

        ("アメス", "aegis-gl",
         "あたしが記録しておくわね。", False,
         "T-2 アメス自身の一人称『あたし』=通過"),

        ("ケヴィン・デ・ブライネ", "aegis-gl",
         "僕だったらこうする。理由は2つ。", False,
         "T-3 デブライネは僕/俺の両方が正=『僕』は通過"),

        ("ケヴィン・デ・ブライネ", "aegis-gl",
         "あたしに任せて。", True,
         "T-4 デブライネのブロックに『あたし』(アメスの一人称)=発火"),

        ("ククール", "aegis-gl",
         "オレに任せろ。", False,
         "T-5 ククール自身の一人称『オレ』=通過"),

        ("ククール", "aegis-gl",
         "僕がやるよ。", True,
         "T-6 ククールのブロックに『僕』(オタコンの一人称)=発火"),

        ("アメス", "aegis-gl",
         "デブライネが「オレがやる」と言ってた。", False,
         "T-7 引用「…」内の『オレ』は判定から外す=通過(FP抑制)"),

        ("アメス", "aegis-gl",
         "オレンジを買ってきたわ。", False,
         "T-8 カタカナ後続ガード=『オレ』+ン は別語(オレンジ)=通過"),

        ("早坂芽衣", "copy-director",
         '題名も1にすると"実は女の子も"と"俺だけじゃない"がぴったり手を繋ぐ感じ', False,
         "T-11 二重引用符\"…\"の中の『俺』はコピー案の引用=通過(FP抑制)"
         "。★実物= 2026-08-11 16:59 copy-director で実際に誤検知していた便"),

        ("早坂芽衣", "copy-director",
         "ごめん、俺が余計に難しくした。", True,
         "T-12 引用の外で地の文の『俺』=本物の違反=発火"
         "(T-11で引用を外しても、この本物を取り逃がさないことの確認)"),

        ("早坂芽衣", "copy-director",
         "don't stop、俺がやる、it's fine", True,
         "T-13 シングルクォートは引用spanに数えない=アポストロフィ2個に"
         "挟まれた本物の『俺』を隠さない"),

        ("存在しない人格(未登録・番兵)", "copy-director",
         "オレがやる。", False,
         "T-9 未登録の人格は判定しない(fail-open=鳴らさない)"
         "。★番兵名で固定=実在人格を例に使うと登録された時にこの前提が壊れる"
         "(2026-08-08 三笘薫をゲートへ登録した時に旧・三笘薫例が実際に壊れた)"),

        ("アメス", "aegis-gl",
         "", False,
         "T-10 空文字=通過"),
    ]

    ok = True
    for persona, dept, text, expect_fire, desc in cases:
        v = tone_verdicts(persona, dept, text, rules)
        fired = len(v) > 0
        status = "PASS" if fired == expect_fire else "FAIL"
        if fired != expect_fire:
            ok = False
        print(f"[{status}] {desc} -> fired={fired} expect={expect_fire}"
              + (f" / {v}" if fired else ""))

    # fail-open: rules=None は常に空(=鳴らさない)。
    if tone_verdicts("アメス", "aegis-gl", "オレがやる", None):
        ok = False
        print("[FAIL] fail-open: rules=None で発火してはいけない")
    else:
        print("[PASS] fail-open: rules=None は空(発火しない)")

    print("=== 全PASS ===" if ok else "=== FAIL あり ===")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(_run())
