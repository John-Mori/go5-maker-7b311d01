#!/usr/bin/env python3
"""GOLDEN(純関数・LLM不要): 出力ゲート ルールC=呼称違反チェック  2026-07-30.

設計書= 00_AI-HQ/設計_出力ゲート_呼称スラッグ非日本語スクリプト_2026-07-30.md §4。
写像= 00_AI-HQ/departments/hr/personas/呼称ルール.json(この1本をゲートと同じく引く=ORG-11)。

実行: python tests/test_naming_gate.py   (全PASSで終了コード0)
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.normpath(os.path.join(HERE, ".."))
sys.path.insert(0, os.path.join(ROOT, "scripts", "llm"))

from naming_gate import load_naming_rules, naming_verdicts  # noqa: E402

# 呼称ルール.json の場所(AI-HQ 管轄)。無ければ skip せず fail(写像が正本)。
RULES_PATH = os.path.join(
    r"D:\SougouStartFolder\00_AI-HQ",
    "departments", "hr", "personas", "呼称ルール.json")


def _run():
    rules = load_naming_rules(RULES_PATH)
    if not rules:
        print(f"FAIL: 呼称ルール.json を読めない: {RULES_PATH}")
        return 1

    # (話者, 部屋, 本文, 期待=発火するか, 説明)
    cases = [
        ("ケヴィン・デ・ブライネ", "aegis-gl",
         "アロンソさんに確認します。", True,
         "現役選手→アロンソに『アロンソさん』=発火(allowedはコーチ/監督のみ)"),

        ("アメス", "hr-room",
         "アロンソさんへ伝えておきます。", False,
         "一般他者→『アロンソさん』=通過(honorific_required の allowed)"),

        ("ククール", "aegis-gl",
         "デブライネの意見に賛成だ。", False,
         "ククール特例=デブライネ呼び捨てが正=通過"),

        ("ククール", "aegis-gl",
         "デブライネさんの意見に賛成だ。", True,
         "ククール特例=『デブライネさん』はこの話者では違反=発火"),

        ("花海咲季", "system-engineer-a",
         "デブライネに任せます。", True,
         "さん付け必須の一般話者が裸の姓『デブライネ』=発火"),

        ("アメス", "hr-room",
         "その件はシャビさんが詳しい。", True,
         "forbidden『シャビさん』=発火(話者非依存)"),

        ("アメス", "hr-room",
         "こんにちは。今日の進捗を確認しました。問題ありません。", False,
         "呼称に無関係な通常文=通過(0件)"),

        # --- 追加の境界(取りこぼし/許容の確認) ---
        ("ケヴィン・デ・ブライネ", "aegis-gl",
         "アロンソコーチに報告します。", False,
         "現役選手→『アロンソコーチ』=許容形=通過"),

        ("ルカ・モドリッチ", "aegis-gl",
         "デブライネ、この件を頼む。", False,
         "モドリッチ→デブライネ呼び捨てOK(override)=通過"),
    ]

    failed = 0
    for i, (persona, dept, text, expect_fire, desc) in enumerate(cases, 1):
        verdicts = naming_verdicts(persona, dept, text, rules)
        fired = len(verdicts) > 0
        ok = (fired == expect_fire)
        mark = "PASS" if ok else "FAIL"
        if not ok:
            failed += 1
        detail = ""
        if verdicts:
            v = verdicts[0]
            detail = f" [target={v['target']} found={v['found']} reason={v['reason']}]"
        print(f"{mark} T-{i}: 期待={'発火' if expect_fire else '通過'} "
              f"実際={'発火' if fired else '通過'}{detail}  {desc}")

    print("-" * 60)
    if failed:
        print(f"{failed} 件 FAIL / {len(cases)} 件")
        return 1
    print(f"全 {len(cases)} 件 PASS")
    return 0


if __name__ == "__main__":
    sys.exit(_run())
