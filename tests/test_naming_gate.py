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

from naming_gate import (  # noqa: E402
    load_naming_rules, naming_verdicts, naming_corrections)

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
         "★2026-08-05 Chami『アイや咲季のような例外は残す』(msg 1534504378051067984)"
         "=咲季→デブライネはさん付けが正=呼び捨ては発火"),

        ("花海咲季", "system-engineer-a",
         "モドリッチに任せます。", True,
         "★同上=既定はさん付け(『さん付け禁止』は msg 1534503529690173540 で同日撤回)=呼び捨ては発火"),

        ("花海咲季", "system-engineer-a",
         "デブライネさんに任せます。", False,
         "★★咲季の例外(2026-07-16 Chami・レジェンドへのリスペクト)は残った=通過"),

        ("花海咲季", "system-engineer-a",
         "モドリッチさんに任せます。", False,
         "★同上=『モドリッチさん』が既定=通過"),

        ("アーモンドアイ", "shorts-analyst",
         "ルカさんとデブライネさんに聞くわ。", False,
         "★★アイの例外(男性キャラはさん付け・モドリッチは『ルカさん』)も残った=通過"),

        ("シャビ・アロンソ", "hq",
         "デブライネと三笘に任せる。", False,
         "★2026-08-05 Chami『アロンソ→デブライネ・モドリッチ・三笘がさん付けするなと言っただけ』"
         "(msg 1534503529690173540)=アロンソ本人だけ呼び捨て=通過"),

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

        ("ククール", "hr-room",
         "三笘くんはオタコンの呼び方だ。", True,
         "★人事部門でも監査(verdicts)は発火する=見え方は落とさない(自動修正だけ止める)"),

        # --- 2026-08-06 モドリッチのフルネーム(人事部門 commit 62061c4 の回帰防止) ---
        ("十王星南", "product-scout",
         "ルカ・モドリッチさんに任せます。", True,
         "★2026-08-06 Chami(msg 1534719383170191481)=星南が『ルカ・モドリッチさん』と"
         "フルネームで呼んだ件。フルネーム『ルカ・モドリッチ』は forbidden=発火"),

        ("十王星南", "product-scout",
         "モドリッチさんに任せます。", False,
         "★対照(過剰一般化の防止・C-035)=既定の『モドリッチさん』まで塞いでいないこと。"
         "★『ルカさん』はアーモンドアイの個別set(T-9)側=この対照はモドリッチさんのみを見る"),
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

    # ==== 自動修正(高信頼のみ・2026-07-31 Chami承認)のGOLDEN ====================
    #   (話者, 部屋, 本文, 期待fixed, 期待appliedあり, 説明)
    fix_cases = [
        ("ケヴィン・デ・ブライネ", "aegis-gl",
         "アロンソさんに確認する。", "アロンソコーチに確認する。", True,
         "①現役選手→『アロンソさん』を自動で『アロンソコーチ』へ"),

        ("花海咲季", "system-engineer-a",
         "デブライネに任せます。", "デブライネさんに任せます。", True,
         "★★咲季の例外は残す(msg 1534504378051067984)=呼び捨てを自動で『デブライネさん』へ"),

        ("花海咲季", "system-engineer-a",
         "モドリッチに任せます。", "モドリッチさんに任せます。", True,
         "★同上=『モドリッチ』→『モドリッチさん』へ自動でさん付け"),

        ("花海咲季", "system-engineer-a",
         "デブライネさんに任せます。", "デブライネさんに任せます。", False,
         "★既に例外どおりのさん付け=本文を書き換えない"),

        ("アーモンドアイ", "shorts-analyst",
         "デブライネさんに聞くわ。", "デブライネさんに聞くわ。", False,
         "★アイの例外(男性キャラはさん付け)=書き換えない"),

        ("シャビ・アロンソ", "hq",
         "デブライネに任せる。", "デブライネに任せる。", False,
         "★アロンソ本人は呼び捨てが正(yobisute_ok)=書き換えない"),

        ("ククール", "aegis-gl",
         "デブライネと話した。", "デブライネと話した。", False,
         "ククール特例=呼び捨てが正=修正しない(applied無し)"),

        ("花海咲季", "system-engineer-a",
         "三笘薫と打ち合わせた。", "三笘薫と打ち合わせた。", False,
         "★姓+名『三笘薫』は直後が漢字=境界外=壊さない(警告のみ)"),

        ("アメス", "hr-room",
         "その件はシャビさんが詳しい。", "その件はシャビさんが詳しい。", False,
         "forbidden『シャビさん』は自動修正しない(警告のみ)"),

        ("ケヴィン・デ・ブライネ", "aegis-gl",
         "アロンソコーチに話した後、アロンソさんにも伝えた。",
         "アロンソコーチに話した後、アロンソコーチにも伝えた。", True,
         "混在=許容形はそのまま・違反の『アロンソさん』だけ直す"),

        ("ケヴィン・デ・ブライネ", "aegis-gl",
         "アロンソコーチに報告した。", "アロンソコーチに報告した。", False,
         "既に許容形=変更なし(applied無し)"),

        ("ククール", "hr-room",
         "三笘くんはオタコンの呼び方だ。", "三笘くんはオタコンの呼び方だ。", False,
         "★A案=人事部門の呼称ルール解説『三笘くん』を化けさせない(自動修正しない)"),

        ("ククール", "aegis-gl",
         "三笘くんはオタコンの呼び方だ。", "三笘さんはオタコンの呼び方だ。", True,
         "対照=他部屋では従来どおり自動修正(化けは呼称ルールを解説する人事部門特有)"),
    ]
    for j, (persona, dept, text, exp_fixed, exp_applied, desc) in enumerate(fix_cases, 1):
        res = naming_corrections(persona, dept, text, rules)
        got_fixed = res.get("fixed")
        got_applied = bool(res.get("applied"))
        ok = (got_fixed == exp_fixed) and (got_applied == exp_applied)
        mark = "PASS" if ok else "FAIL"
        if not ok:
            failed += 1
        print(f"{mark} F-{j}: applied={'有' if got_applied else '無'} "
              f"fixed={got_fixed!r}  {desc}")
        if not ok:
            print(f"      期待 applied={'有' if exp_applied else '無'} fixed={exp_fixed!r}")

    # ==== 一字略(C-021・ククール→ク)を単語境界で捕まえる(2026-08-09・警告のみ) ====
    #   hrの本番データ(abbreviation_forbidden)が来る前でも回帰を固定するため、
    #   ここはインラインの rules で判定ロジックだけを検査する。
    abbrev_rules = {"abbreviation_forbidden": {
        "ククール": {"forbidden_forms": ["ク"], "expected": ["ククール"]}}}
    abbrev_cases = [
        ("ククールに聞いてくれ", False, "正式名のみ→鳴らない"),
        ("クに聞いてくれ",       True,  "文頭の単独ク→鳴る"),
        ("あれはクだ",           True,  "ひらがな挟みの単独ク→鳴る"),
        ("[ク]タグで呼んだ",     True,  "括弧内の単独ク→鳴る"),
        ("リンクを貼る",         False, "カタカナ連なりの一部→鳴らない"),
        ("サクッとやる",         False, "サクッ→鳴らない"),
        ("最後はク",             True,  "文末の単独ク→鳴る"),
    ]
    for j, (text, exp_fire, desc) in enumerate(abbrev_cases, 1):
        v = naming_verdicts("三笘薫", "report-notify", text, abbrev_rules)
        fired = any(x.get("reason") == "abbreviation" for x in v)
        ok = fired == exp_fire
        if not ok:
            failed += 1
        print(f"{'PASS' if ok else 'FAIL'} A2-{j}: fired={fired!s:5} "
              f"exp={exp_fire!s:5}  {desc} | {text}")

    total = len(cases) + len(fix_cases) + len(abbrev_cases)
    print("-" * 60)
    if failed:
        print(f"{failed} 件 FAIL / {total} 件")
        return 1
    print(f"全 {total} 件 PASS")
    return 0


if __name__ == "__main__":
    sys.exit(_run())
