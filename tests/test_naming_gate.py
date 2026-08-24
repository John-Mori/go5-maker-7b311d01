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

        ("シャビ・アロンソ", "hq",
         "モドリッチさんに任せる。", True,
         "★2026-08-18 Chami(msg 1539147771414843462『アロンソコーチがずっとモドリッチさん"
         "って言ってる、修正を』)=アロンソ→モドリッチは呼び捨てが正=『モドリッチさん』は発火。"
         "★デブライネ行と同型の名指しピン(target:'*'だけでは既定を素通ししていた穴を塞ぐ)"),

        ("シャビ・アロンソ", "hq",
         "モドリッチに任せる。", False,
         "★対照=アロンソ→モドリッチの正の呼び捨て『モドリッチ』は通過(本人の声を潰さない)"),

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

        ("シャビ・アロンソ", "hq",
         "モドリッチさんに任せる。", "モドリッチに任せる。", True,
         "★2026-08-18=アロンソ→『モドリッチさん』を自動で呼び捨て『モドリッチ』へ"
         "(デブライネF案と同型)"),

        ("シャビ・アロンソ", "hq",
         "モドリッチに任せる。", "モドリッチに任せる。", False,
         "★対照=既に正の呼び捨て=書き換えない(applied無し)"),

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
         "★人事部門の呼称ルール解説『三笘くん』を化けさせない(地の文=直さない)"),

        ("ククール", "aegis-gl",
         "三笘くんはオタコンの呼び方だ。", "三笘さんはオタコンの呼び方だ。", True,
         "対照=他部屋では従来どおり自動修正(化けは呼称ルールを論じる人事部門特有)"),

        # ==== 呼びかけ位置だけ直す(2026-08-24・実測46箇所中30箇所が化けたので絞った)====
        #   検体はすべて naming_audit.jsonl の hr-room 実物本文から採った形。
        ("ククール", "hr-room",
         "常体8人格(デブライネ/モドリッチ/ククール/オタコン/三笘/星南)に入れた。",
         "常体8人格(デブライネ/モドリッチ/ククール/オタコン/三笘/星南)に入れた。", False,
         "★★名簿の列挙の中の『三笘』を『三笘さん』に化けさせない(実物・地の文)"),

        ("ククール", "hr-room",
         "口調ルール.jsonの三笘のforbiddenへ「からね」を1語追加した。",
         "口調ルール.jsonの三笘のforbiddenへ「からね」を1語追加した。", False,
         "★★設定オブジェクトの持ち主『三笘のforbidden』を化けさせない(実物・地の文)"),

        ("ククール", "hr-room",
         "アロンソさん、訂正ごと受けた。", "アロンソコーチ、訂正ごと受けた。", True,
         "★呼びかけ位置(行頭+直後が読点)だけは直す=実測7箇所・化け0"),

        ("ククール", "hr-room",
         "了解、アロンソさんへ返した。", "了解、アロンソさんへ返した。", False,
         "★同じ『アロンソさん』でも行頭でなければ地の文=直さない(呼びかけの2条件)"),
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

    # ==== 検出専用forms(target_detect_forms)=敬称必須と切り離した対象検出 =========
    #   2026-08-15。人事部門ククールの実測発注(msg 1537928811746820096)への実装。
    #   それまで 一ノ瀬怜 の検出候補はキー名「一ノ瀬怜」だけで、誰もフル表記では呼ばない=
    #   怜宛ての override(ククール/デブライネ/ヴィルシーナ/芽衣)が**全部空振り**していた。
    #   ★核= 検出formsを足しても、override を持たない話者には**一切**鳴らないこと(D-7)。
    #     これが「honorific_required_targets へ入れてはいけない」理由そのものだ。
    detect_rules = {
        "target_detect_forms": {"一ノ瀬怜": ["怜", "一ノ瀬"]},
        "speaker_target_overrides": [
            {"speaker": "早坂芽衣", "target": "一ノ瀬怜",
             "allowed": ["怜ちゃん"], "forbidden": ["怜くん"]},
            {"speaker": "ヴィルシーナ", "target": "一ノ瀬怜", "allowed": ["怜さん"]},
            {"speaker": "__男性キャラ__", "target": "一ノ瀬怜", "allowed": ["怜"]},
        ],
    }
    detect_cases = [
        ("早坂芽衣",   "怜くん、これ見て",   True,  "★本丸=芽衣の『怜くん』ドリフトが鳴る"),
        ("早坂芽衣",   "怜ちゃん、これ見て", False, "正しい形『怜ちゃん』は鳴らない"),
        ("ヴィルシーナ", "怜に回したわ",     True,  "さん付けが正の話者の裸『怜』=鳴る"),
        ("ヴィルシーナ", "怜さんに回したわ", False, "『怜さん』は鳴らない"),
        ("ククール",   "怜、頼む",           False, "呼び捨てが正の男性話者=鳴らない"),
        ("ククール",   "怜さん、頼む",       True,  "呼び捨てが正なのに『怜さん』=鳴る"),
        ("十王星南",   "怜、ありがと",       False,
         "★overrideを持たない話者には鳴らない=検出formsは敬称必須を意味しない"),
    ]
    for j, (persona, text, exp_fire, desc) in enumerate(detect_cases, 1):
        v = [x for x in naming_verdicts(persona, "hq", text, detect_rules)
             if x.get("target") == "一ノ瀬怜"]
        ok = bool(v) == exp_fire
        if not ok:
            failed += 1
        print(f"{'PASS' if ok else 'FAIL'} D-{j}: fired={bool(v)!s:5} "
              f"exp={exp_fire!s:5}  {desc} | {text}")

    # 本番の写像でも配線が生きていること(hrが行を落としたら赤で気付く)。
    real = [x for x in naming_verdicts("早坂芽衣", "copy-director", "怜くん、これ見て", rules)
            if x.get("target") == "一ノ瀬怜"]
    ok = any(x.get("reason") == "forbidden" for x in real)
    if not ok:
        failed += 1
    print(f"{'PASS' if ok else 'FAIL'} D-8: 本番の呼称ルール.json でも芽衣の『怜くん』が鳴る "
          f"| {real}")

    # 本番の写像で『ルカ』検出が生きていること(2026-08-15 Chami=オタコンがルカと呼ぶ→基本モドリッチ)。
    # target_detect_forms へ『ルカ』を足したので、override を持たない話者(オタコン)の裸『ルカ』が鳴る。
    luka = [x for x in naming_verdicts("オタコン", "hr", "ルカに聞いてみる", rules)
            if x.get("target") == "ルカ・モドリッチ"]
    luka_ok = bool(luka)
    # override を持つ話者(アイ)の『ルカさん』は鳴らない=検出formsが敬称必須を意味しない担保。
    luka_fp = [x for x in naming_verdicts("アーモンドアイ", "hr", "ルカさんに聞く", rules)
               if x.get("target") == "ルカ・モドリッチ"]
    luka_ok = luka_ok and not luka_fp
    if not luka_ok:
        failed += 1
    print(f"{'PASS' if luka_ok else 'FAIL'} D-9: オタコンの裸『ルカ』が鳴る/アイの『ルカさん』は鳴らない "
          f"| fire={luka} fp={luka_fp}")

    # ================================================================
    # E: 名乗りタグ `[人格名]` と自称は判定しない(2026-08-23・イージス研究室)
    # ----------------------------------------------------------------
    # 発端= 改善提案部門トトリの提案(DISPATCH-aegis-gl-1787458670363)を数え直したら、
    #   naming_audit.jsonl の違反候補165件のうち **69件(42%)が「話者==対象」の自称**、
    #   **64件が返信1行目の名乗り `[ケヴィン・デブライネ]`** を本文と見なしたものだった。
    #   日本語で自称に敬称は付かない=**原理的に常に誤りの警告**(共通規律§3)。
    # ★ここは全部「旧仕様なら鳴る/新仕様では黙る」を対で見る(空PASS禁止)。
    #   旧仕様の再現は **直した述語1つだけを元へ戻す**(判定経路は本物のまま通す)。
    import naming_gate as _ng                                   # noqa: E402

    e_failed = 0
    e_total = 0

    def _check(tag, ok, detail):
        nonlocal e_failed, e_total
        e_total += 1
        if not ok:
            e_failed += 1
        print(f"{'PASS' if ok else 'FAIL'} {tag}: {detail}")

    # ★検体は2つの穴を**別々に**踏むものを選ぶ(片方の直しがもう片方を隠すと空PASSになる)。
    #   E-1/E-2 = 名乗りタグだけの穴 → 話者と別人の名札(自称の除外は効かない)。
    #   E-3/E-4 = 自称だけの穴       → 名札の無い地の文(覆いは効かない)。
    _tag_body = "[ルカ・モドリッチ]\n見といたぞ。"
    _self_body = "デブライネの見立てはこうだ。"
    _both_body = "[ケヴィン・デブライネ]\nアロンソコーチ、受けた。"

    _v = naming_verdicts("アメス", "aegis-gl", _tag_body, rules)
    _check("E-1", not _v, f"★他人の名乗りタグも判定しない(鳴らない) | {_v}")

    _orig_mask = _ng._mask_name_tags
    try:
        _ng._mask_name_tags = lambda t, p, r: t          # 旧仕様=覆わない
        _v_old = naming_verdicts("アメス", "aegis-gl", _tag_body, rules)
    finally:
        _ng._mask_name_tags = _orig_mask
    _check("E-2", any(x.get("target") == "ルカ・モドリッチ" for x in _v_old),
           f"★変異: 覆いを外すと同じ検体が鳴る(=穴の再現・空PASSでない) | {_v_old}")

    _v = naming_verdicts("ケヴィン・デブライネ", "aegis-gl", _self_body, rules)
    _check("E-3", not _v, f"★自称に敬称を要求しない(鳴らない) | {_v}")

    _orig_self = _ng._is_self
    try:
        _ng._is_self = lambda p, t: False                # 旧仕様=自称を素通ししない
        _v_old = naming_verdicts("ケヴィン・デブライネ", "aegis-gl", _self_body, rules)
    finally:
        _ng._is_self = _orig_self
    _check("E-4", any(x.get("reason") == "honorific_required" for x in _v_old),
           f"★変異: 自称の除外を外すと同じ検体が鳴る | {_v_old}")

    # ★E-5= 黙らせすぎていないことの担保。同じ裸の姓でも**他人が呼べば**鳴る。
    _v = naming_verdicts("アメス", "aegis-gl", _self_body, rules)
    _check("E-5", any(x.get("reason") == "honorific_required" for x in _v),
           f"他人が呼ぶ裸『デブライネ』は今までどおり鳴る | {_v}")

    # ★E-5b= 手書きの self-override(2026-08-18 に人事部門がモドリッチ/三笘へ個別に足した
    #   『本人がさん無しで名乗るのは正』)と、こちらの一般形が**食い違わない**こと。
    _v = naming_verdicts("ルカ・モドリッチ", "aegis-gl", "モドリッチが見た。", rules)
    _check("E-5b", not _v,
           f"手書きの自称override(モドリッチ)と一般形が同じ結論 | {_v}")

    _v = naming_verdicts("三笘薫", "aegis-gl", "三笘さんが対応する。", rules)
    _check("E-6", any(x.get("reason") == "forbidden" for x in _v),
           f"★わざと書かれた自称の禁止形(三笘→『三笘さん』)は生きている | {_v}")

    _v = naming_verdicts("ククール", "aegis-gl", "[三笘の96h]について話す。", rules)
    _check("E-7", any(x.get("target") == "三笘薫" for x in _v),
           f"人格名でない行頭の括弧は覆わない(取りこぼしを作っていない) | {_v}")

    # ★E-8= 地雷そのもの。`]` が安全境界に入った瞬間、旧仕様は名乗りを書き換える。
    #   今それを止めているのが「境界文字の一覧にたまたま `]` が無い」ことだけなのを、
    #   一覧へ `]` を足した状態で新旧を並べて見せる。
    _orig_chars = _ng._SAFE_AFTER_CHARS
    try:
        _ng._SAFE_AFTER_CHARS = set(_orig_chars) | {"]"}
        _new = naming_corrections("ケヴィン・デブライネ", "aegis-gl", _both_body, rules)
        _ng._mask_name_tags = lambda t, p, r: t
        _ng._is_self = lambda p, t: False
        _old = naming_corrections("ケヴィン・デブライネ", "aegis-gl", _both_body, rules)
    finally:
        _ng._SAFE_AFTER_CHARS = _orig_chars
        _ng._mask_name_tags = _orig_mask
        _ng._is_self = _orig_self
    _check("E-8a", _old["fixed"].startswith("[ケヴィン・デブライネさん]"),
           f"★変異: 旧仕様＋`]`が安全境界 → 名乗りが化ける(名義解決が壊れる) "
           f"| {_old['fixed']!r}")
    _check("E-8b", _new["fixed"] == _both_body and not _new["applied"],
           f"★直った側: `]`が安全境界でも名乗りは1文字も変わらない | {_new['fixed']!r}")

    # ★E-9〜E-12= 引用符の中の名前(2026-08-23・トトリ訂正便 P1③の差し替え)。
    #   検体は**実物から採った形**= 人事部門の解説文『三笘くん』を勝手に化けさせた事故と同型。
    _quo_body = "解説文の「三笘」という表記を直す。"
    _orig_quo = _ng._mask_quoted_mentions

    _v = naming_verdicts("オタコン", "aegis-gl", _quo_body, rules)
    _check("E-9", not _v, f"引用符の中の名前は呼びかけでない(鳴らない) | {_v}")

    try:
        _ng._mask_quoted_mentions = lambda t: t          # 旧仕様=覆わない
        _v_old = naming_verdicts("オタコン", "aegis-gl", _quo_body, rules)
        _c_old = naming_corrections("オタコン", "aegis-gl", _quo_body, rules)
    finally:
        _ng._mask_quoted_mentions = _orig_quo
    _check("E-10", any(x.get("target") == "三笘薫" for x in _v_old),
           f"★変異: 引用の覆いを外すと同じ検体が鳴る(=穴の再現・空PASSでない) | {_v_old}")
    _check("E-11", _c_old["fixed"] == "解説文の「三笘くん」という表記を直す。",
           f"★変異: 旧仕様は**引用の中身を書き換えていた**(解説文が化ける) "
           f"| {_c_old['fixed']!r}")

    _c_new = naming_corrections("オタコン", "aegis-gl", _quo_body, rules)
    _check("E-11b", _c_new["fixed"] == _quo_body and not _c_new["applied"],
           f"★直った側: 引用の中身は1文字も変わらない | {_c_new['fixed']!r}")

    # ★E-12= 黙らせすぎていないことの担保(2件)。
    #   (a) 引用の外の裸の姓は今までどおり鳴る。
    #   (b) **改行を跨ぐ対**は覆わない=実測で 66〜89字を巻き込んでいた誤対応
    #       (これを覆うと地の文の本物の呼び捨てが道連れで黙る)。
    _v = naming_verdicts("オタコン", "aegis-gl", "三笘が対応する。", rules)
    _check("E-12a", any(x.get("target") == "三笘薫" for x in _v),
           f"引用の外の裸の姓は鳴る | {_v}")
    _v = naming_verdicts("オタコン", "aegis-gl", "`コード\nの中の三笘`が対応する。", rules)
    _check("E-12b", any(x.get("target") == "三笘薫" for x in _v),
           f"改行を跨ぐ引用対は覆わない(誤対応で黙らせない) | {_v}")

    failed += e_failed

    total = (len(cases) + len(fix_cases) + len(abbrev_cases)
             + len(detect_cases) + 2 + e_total)
    print("-" * 60)
    if failed:
        print(f"{failed} 件 FAIL / {total} 件")
        return 1
    print(f"全 {total} 件 PASS")
    return 0


if __name__ == "__main__":
    sys.exit(_run())
