#!/usr/bin/env python3
"""GOLDEN(純関数・LLM不要): 出力ゲート ルールD=口調ドリフト検知(一人称の食い違い) 2026-08-03.

設計書= 00_AI-HQ/設計_口調ゲート_送信直前_名乗りと本文の食い違い_2026-08-03.md。
裁定= 研究室HQ(msg 1533789472783863899)「①警告のみ段階=投入Go / ②inline LLMは却下」。
写像= 00_AI-HQ/departments/hr/personas/口調ルール.json(この1本をゲートと同じく引く=ORG-11)。

実行: python -X utf8 tests/test_tone_gate.py   (全PASSで終了コード0)
"""
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.normpath(os.path.join(HERE, ".."))
sys.path.insert(0, os.path.join(ROOT, "scripts", "llm"))

from tone_gate import (  # noqa: E402
    load_tone_rules, tone_verdicts, tone_corrections, polite_drift,
    harshness_drift, room_tone_profile)

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
         "僕だったらこうする。理由は2つ。", True,
         "T-3 デブライネの一人称は『俺』のみ=『僕』は違反=発火"
         "(★2026-08-13 Chami指示 msg 1537114712280670278『デブライネは一人称は俺』で"
         "口調ルール.json の写像が ['僕','俺','オレ'] → ['俺'] へ一本化された。"
         "旧T-3は『僕は通過』が期待値だった=写像を変えた側の載せ替え漏れ・C-042の実例)"),

        ("ケヴィン・デ・ブライネ", "aegis-gl",
         "オレだったらこうする。", True,
         "T-3b 『オレ』も同様に違反=発火(一本化で僕とオレの両方が落ちたことの確認)"),

        ("ケヴィン・デ・ブライネ", "aegis-gl",
         "俺だったらこうする。理由は2つ。", False,
         "T-3c 本人の正『俺』は通過(T-3の一本化で本人の声まで鳴らしていないことの確認)"),

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

        # ── モドリッチ×アメス 相方混線(C-026)を real-json でロック ──
        #   Chami 2026-08-18 msg 1539138940089409579「ad研究室でアメスでモドリッチが喋ってる」。
        #   一人称『あたし』は registry distinctive で既に検知済(T-14)。穴は語尾/二人称=
        #   口調ルール.json の モドリッチ.forbidden に アンタ/なによ/わよ/なさいよ を足して塞いだ。
        #   ★この4件が写像から消えたらここが赤くなる=うっかり削除を機構で止める(空PASSにしない)。
        ("ルカ・モドリッチ", "aegis-gl",
         "あたしはそう思う。", True,
         "T-14 モドリッチのブロックに『あたし』(アメスの一人称)=発火(registry distinctive)"),

        ("ルカ・モドリッチ", "aegis-gl",
         "アンタ、それ本気で言ってるの？", True,
         "T-15 アメスの二人称『アンタ』=モドリッチ.forbidden=発火(相方混線・C-026)"),

        ("ルカ・モドリッチ", "aegis-gl",
         "なによ、その仮説。ちゃんと全体を見なさいよ。", True,
         "T-16 アメスの語尾『なによ』『なさいよ』=モドリッチ.forbidden=発火"),

        ("ルカ・モドリッチ", "aegis-gl",
         "スワイプ率を見るわよ。", True,
         "T-17 アメスの語尾『わよ』=モドリッチ.forbidden=発火"),

        ("ルカ・モドリッチ", "aegis-gl",
         "俺はこの仮説が有力だと思う。何によって数字が動いたか、まず全体の流れを見よう。", False,
         "T-18 正常なモドリッチの声=通過。★『何によって』(漢字何)は『なによ』と衝突しない"
         "・『のよ/なのよ』を入れなかったので『そのように』等でも誤検知しないことの担保"),
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

    # ================================================================
    # 書き直し(2026-08-12 格上げ= 違反した便だけ直す)。
    #   (話者, 本文, 期待する書き直し後, 期待する置換件数, 説明)
    #   ★期待が本文と同じ=「触らない」ことの検査。
    # ================================================================
    rw = [
        ("オタコン", "俺がやる。あとで測る。", "僕がやる。あとで測る。", 1,
         "R-1 他人格の一人称『俺』→本人の正『僕』へ置換(発注の本体)"),

        ("オタコン", "俺が見る。俺が直す。", "僕が見る。僕が直す。", 2,
         "R-2 同じ便の複数出現を全部直す(件数が測れる=C-041)"),

        ("オタコン", "おれがやる。あとで測る。", "僕がやる。あとで測る。", 1,
         "★2026-08-18 R-2b ひらがな『おれ』も本人の正『僕』へ置換(Chami『オタコンの一人称が俺』"
         "msg 1539149243007107092)。★俺(漢字)・オレ(カナ)は他人格の first_person 登録から"
         "自動で拾えていたが、おれ(ひらがな)は誰も登録しておらず素通しだった穴="
         "オタコン写像の forbidden+forbidden_to に俺/オレ/おれ→僕を明示して塞いだ"
         "(他人格の登録に依存しない=登録が消えても壊れない)"),

        ("早坂芽衣",
         '題名は"俺だけじゃない"がいい',
         '題名は"俺だけじゃない"がいい', 0,
         "R-3 引用の中のコピー案は**書き換えない**(訴求を壊さない)"),

        ("早坂芽衣", "俺が余計に難しくした。", "俺が余計に難しくした。", 0,
         "R-4 ★写像が ['芽衣','私'] で**置換先が一意に決まらない人格は素通し**"
         "(HQ裁定 msg 1536847015886200892=リストの先頭を正と決めるな。"
         "先頭決め打ちだと『芽衣が余計に難しくした』と名前を差し込む置換が走る)"),

        ("ククール", "僕がやるよ。", "僕がやるよ。", 0,
         "R-4b 候補が複数(['オレ','俺'])の人格も素通し=違反として警告は出るが本文は変えない"),

        ("中野五月", "俺がやる。", "私がやる。", 1,
         "R-4c 候補が1つ(['私'])なら一意=書き直す(素通しの範囲を広げすぎていないことの確認)"),

        ("ケヴィン・デ・ブライネ", "俺がやる。", "俺がやる。", 0,
         "R-5 デブライネの正は『俺』=**違反ではないので1文字も変えない**(R-12型)。"
         "★2026-08-13の一本化(['僕','俺','オレ']→['俺'])後も本人の声は不変であること"),

        ("ケヴィン・デ・ブライネ", "僕がやる。", "俺がやる。", 1,
         "R-5b 一本化で『僕』は違反=写像が一意(['俺'])なので書き直す(R-1型)。"
         "★旧R-5の説明は『僕/オレも正だから触らない』だった=写像の載せ替え漏れ(C-042)"),

        ("ケヴィン・デ・ブライネ", "オレがやる。", "俺がやる。", 1,
         "R-5c 『オレ』も同じく書き直す(僕とオレの両方が落ちたことを置換側でも確認)"),

        ("オタコン", "`俺` は変数名だ。僕が直す。", "`俺` は変数名だ。僕が直す。", 0,
         "R-6 インラインコードの中は触らない"
         "(★このケースは地の文が正しいので置換対象そのものが無い)"),

        ("オタコン", "```\nprint('俺')\n```\n俺が直す。",
         "```\nprint('俺')\n```\n僕が直す。", 1,
         "R-7 コードフェンスの中は触らず、地の文だけ直す"),

        ("オタコン", "> オレがやる\nと言っていた。僕が確認した。",
         "> オレがやる\nと言っていた。僕が確認した。", 0,
         "R-8 行頭『>』の引用=他人の便の証拠。書き換えたら台帳が嘘になる"),

        ("オタコン", "docs/俺のメモ.md を見た。俺が書いた。",
         "docs/俺のメモ.md を見た。僕が書いた。", 1,
         "R-9 ファイル名・パスには触らない(発注条件4)。地の文だけ直す"),

        ("オタコン", "改修α/基盤/両方に俺が入る。", "改修α/基盤/両方に僕が入る。", 1,
         "R-10 日本語の『A/B』はパス扱いしない=文ごと保護されて検知漏れになるのを防ぐ"),

        ("オタコン", "オレンジを買った。俺が食べる。", "オレンジを買った。僕が食べる。", 1,
         "R-11 カタカナ後続ガードは置換側でも効く(オレンジを壊さない)"),

        ("アメス", "あたしが記録する。", "あたしが記録する。", 0,
         "R-12 違反が無ければ1文字も変えない"),
    ]
    for persona, text, want, want_n, desc in rw:
        res = tone_corrections(persona, "aegis-gl", text, rules)
        got = res.get("fixed")
        n = sum(a.get("count", 0) for a in (res.get("applied") or []))
        good = (got == want and n == want_n)
        if not good:
            ok = False
        print(f"[{'PASS' if good else 'FAIL'}] {desc}"
              + ("" if good else f" -> fixed={got!r} 件数={n} (期待={want!r}/{want_n})"))

    # 禁止語(forbidden)= 人事部門が写像へ入れた実データを引く(commit be37d68)。
    #   オタコン= {"first_person":["僕"],"second_person":["君"],"forbidden":["お前","あんた","すまん"]}
    r13 = tone_corrections("オタコン", "aegis-gl", "お前がやれ。僕は見る。", rules)
    if r13.get("fixed") == "君がやれ。僕は見る。":
        print("[PASS] R-13 禁止の二人称『お前』→写像の second_person『君』へ直る"
              "(判定材料は口調ルール.json 1本=ORG-11)")
    else:
        ok = False
        print(f"[FAIL] R-13 二人称の書き直し -> {r13.get('fixed')!r}")

    # 二人称でない禁止語(詫び方)= 人事部門が 7d5f4f9 で forbidden_to{"すまん":"ごめん"} を
    #   写像へ入れた。**コード変更ゼロ**でここが素通し→書き直しへ変わることの検査。
    r14 = tone_corrections("オタコン", "aegis-gl", "すまん、僕が間違えた。", rules)
    if r14.get("fixed") == "ごめん、僕が間違えた。":
        print("[PASS] R-14 禁止語『すまん』→写像の forbidden_to『ごめん』へ直る"
              "(置換先を決めるのは人事部門=こちらは言い換えを発明しない)")
    else:
        ok = False
        print(f"[FAIL] R-14 すまん -> fixed={r14.get('fixed')!r} remaining={r14.get('remaining')}")

    fake = {"personas": {"オタコン": {
        "first_person": ["僕"], "forbidden": ["すまん"]}}}
    r14b = tone_corrections("オタコン", "aegis-gl", "すまん、僕が間違えた。", fake)
    if (r14b.get("fixed") == "すまん、僕が間違えた。"
            and [v.get("marker") for v in (r14b.get("remaining") or [])] == ["すまん"]):
        print("[PASS] R-14b 置換先が写像に無い禁止語は**本文を変えず警告のみ**で通す"
              "(勝手な言い換えをしない=原典を決めるのはこちらではない)")
    else:
        ok = False
        print(f"[FAIL] R-14b 置換先なし -> fixed={r14b.get('fixed')!r} remaining={r14b.get('remaining')}")

    r15 = tone_corrections("オタコン", "aegis-gl", "俺がやる。", None)
    if r15.get("fixed") == "俺がやる。" and not r15.get("applied"):
        print("[PASS] R-15 fail-open: 写像が読めない時は元の本文をそのまま返す(沈黙を作らない)")
    else:
        ok = False
        print(f"[FAIL] R-15 fail-open -> {r15}")

    # ------------------------------------------------------------------
    # P群= 構造ドリフト(敬体)の検知。2026-08-15 追加(案D《肯定条件》の第1段)。
    #   狙い= 指紋(語の完全一致)では原理的に拾えない「地の文が敬体へ倒れた便」。
    #   ★実物の本文で測る: 下の POLITE は 2026-08-15 の実便コーパス(recent_*.jsonl)から
    #     取った**本物の敬体の便**を短くしたもの(話者は敬体が正の人格なので、
    #     ここでは plain_only を立てた仮の写像に食わせて「拾えるか」だけを見る)。
    POLITE = ("イージス研究室から実行結果が返ってきました。"
              "フェーズ1とフェーズ3は入りました。"
              "ただしまだpushしていないので、公開URLは今も旧構成のままです。"
              "詰めが甘く、こちらで引き取って直しています。")
    PLAIN = ("測った。結論から言う。"
             "フェーズ1と3は入ったが、まだpushしていない。"
             "だから公開URLは今も旧構成のままだ。"
             "詰めが甘い所は俺が引き取る。")
    plain_rules = {"personas": {"シャビ・アロンソ": {
        "first_person": ["俺"], "plain_only": True}}}
    off_rules = {"personas": {"シャビ・アロンソ": {"first_person": ["俺"]}}}

    def _reasons(rr, text, who="シャビ・アロンソ"):
        return sorted(v["reason"] for v in tone_verdicts(who, "hq", text, rr))

    p_cases = [
        (plain_rules, POLITE, ["structural_polite"],
         "P-1 plain_only の人格が地の文まるごと敬体=発火"
         "(案A指紋10句は1つも含まれない文=語の一致では原理的に拾えない側)"),
        (off_rules, POLITE, [],
         "P-2 ★既定は見ない= plain_only が無い人格は同じ本文でも鳴らさない"
         "(21人格中トトリ・田中琴葉など敬体が正の人格が多数=既定ONだと鳴りっぱなしになる。"
         "実便407件で既定ONを測ったら15件鳴り、その全部が敬体を正とする人格の便だった)"),
        (plain_rules, PLAIN, [],
         "P-3 常体の便は鳴らない(本人の正しい声を疑わせない)"),
        (plain_rules, "分かりました。", [],
         "P-4 1文の丁寧語では鳴らさない(閾値=4文以上・3文以上が敬体・半分以上)"),
        (plain_rules,
         "そこは違う。\n> 直しました。反映しています。確認をお願いします。ご連絡ください。\n俺はそう見ない。",
         [],
         "P-5 引用行の中の敬体では鳴らない(他人の便を引いただけで自分の崩れにしない)"),
    ]
    for rr, text, want, why in p_cases:
        got = _reasons(rr, text)
        if got == want:
            print(f"[PASS] {why}")
        else:
            ok = False
            print(f"[FAIL] {why} -> got={got} want={want}")

    d1 = polite_drift(POLITE)
    if d1[0] and d1[1] >= 3 and d1[2] >= 4:
        print(f"[PASS] P-6 polite_drift は数え方を返す(敬体{d1[1]}/{d1[2]}文)"
              "=後から件数を数え直せる形で台帳に残す(C-041)")
    else:
        ok = False
        print(f"[FAIL] P-6 polite_drift -> {d1}")

    p7 = tone_corrections("シャビ・アロンソ", "hq", POLITE, plain_rules)
    if (p7.get("fixed") == POLITE and not p7.get("applied")
            and [v.get("reason") for v in (p7.get("remaining") or [])] == ["structural_polite"]):
        print("[PASS] P-7 敬体は**書き直さない**=本文を1文字も変えずに警告だけ残す"
              "(文末の活用を機械で置換すると文が壊れる。直すのは書いた本人)")
    else:
        ok = False
        print(f"[FAIL] P-7 書き直さない -> fixed一致={p7.get('fixed') == POLITE} "
              f"applied={p7.get('applied')} remaining={p7.get('remaining')}")

    # ------------------------------------------------------------------
    # H群= 威圧化(刃だけで突き放す)の検知。2026-08-23 追加(案ハ4《同じ息ゲート》)。
    #   設計= 00_AI-HQ/departments/hr/設計_毒舌威圧化の検知_2026-08-23.md(人事部門)。
    #   発端= Chami 🔥「人格と口調無視してない？怖い」(現在と未来 msg 1540614099749048401)。
    # ★★検体は**実物**を使う(作り物の文で通すと、本番の初発火が初検証になる)。
    #   ただし検体の本文は**この公開repoへ書き写さない**= Chamiの内省部屋の中身だからだ
    #   (C-013の線=ネットへ出さない)。msg_id で HQ の台帳から**実行時に引く**。
    #   ★引けなかったら SKIP ではなく **FAIL**= 検体が消えた検査は「常にPASSする検査」に
    #     成り下がる(空PASS)。上の RULES_PATH が読めない時に FAIL するのと同じ扱い。
    FUTURE_JSONL = os.path.join(
        r"D:\SougouStartFolder\00_AI-HQ",
        "departments", "hr", "memory", "future-room.jsonl")
    #   ✗= 🔥を受けた威圧便 / ○= 同じ内容をアメス自身が書き直した便2つ(設計§0-1)。
    SPECIMENS = [
        ("1540613774719975454", True,
         "H-1 ✗実物(2026-08-22T15:49:42・🔥を受けた威圧便)=発火"),
        ("1540614099749048401", False,
         "H-2 ○実物(15:51:10・アメス自身の書き直し。同じ内容・同じ結論)=鳴らない"),
        ("1540614948105883680", False,
         "H-3 ○実物2(15:54:28)=鳴らない"),
    ]
    bodies = {}
    try:
        with open(FUTURE_JSONL, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                r = json.loads(line)
                bodies[str(r.get("msg_id"))] = str(r.get("reply") or "")
    except Exception as e:
        print(f"FAIL: 検体台帳を読めない: {FUTURE_JSONL} ({type(e).__name__})")
        return 1

    def _harsh(dept, text):
        return [v for v in tone_verdicts("アメス", dept, text, rules)
                if v.get("reason") == "harsh_without_care"]

    for mid, want_fire, why in SPECIMENS:
        body = bodies.get(mid)
        if not body:
            ok = False
            print(f"[FAIL] {why} -> 検体 msg_id={mid} が台帳に無い"
                  "(検体が消えると、この検査は何も検証しない空PASSになる)")
            continue
        hits = _harsh("future-room", body)
        if bool(hits) == want_fire:
            print(f"[PASS] {why}"
                  + (f" -> {hits[0]['marker']}" if hits else ""))
        else:
            ok = False
            print(f"[FAIL] {why} -> 発火={bool(hits)} 期待={want_fire}")

    x_body = bodies.get("1540613774719975454") or ""
    if x_body:
        # ★H-4= **部屋条件**の must-fail。同じ✗本文でも、写像に載っていない実務部屋では
        #   判定そのものを回さない(設計§5-3「癒し部屋でだけ厳しめ」は閾値ではなくON/OFF)。
        #   これが落ちると、全部門の実務便で毒舌が鳴り始める=安全網が雑音になる。
        if not _harsh("aegis-gl", x_body):
            print("[PASS] H-4 同じ✗本文でも soft でない部屋(イージス研究室)では鳴らない"
                  "=実務部屋の辛口は正当=判定ゼロ=FPゼロ")
        else:
            ok = False
            print("[FAIL] H-4 soft でない部屋で発火した(部屋条件が効いていない)")

        # ★H-5= 写像に部屋が無い時の fail-open(dept が空・未知の部屋)。
        if not _harsh("", x_body) and not _harsh("no-such-room", x_body):
            print("[PASS] H-5 fail-open: dept が空/写像に無い部屋は判定しない")
        else:
            ok = False
            print("[FAIL] H-5 fail-open が効いていない(未知の部屋で鳴った)")

        # ★H-6= **書き直さない**。威圧は語尾の置換では直せない(足りないのは"心配"であって
        #   語尾ではない)。機械が書けば嘘の温度になる=永久に警告と突き返しだけ(設計§5-2)。
        h6 = tone_corrections("アメス", "future-room", x_body, rules)
        rem = [v.get("reason") for v in (h6.get("remaining") or [])]
        if h6.get("fixed") == x_body and "harsh_without_care" in rem:
            print("[PASS] H-6 威圧は本文を1文字も変えずに警告だけ残す"
                  "(出口=tone_audit への記録と次便への突き返しの2つだけ)")
        else:
            ok = False
            print(f"[FAIL] H-6 書き直さない -> 本文一致={h6.get('fixed') == x_body} "
                  f"remaining={rem}")

        # ★H-7= care語彙の入れ忘れで「刃が在れば必ず鳴る」形にならないこと(データ側の fail-open)。
        no_care = {"personas": {"アメス": {
            "first_person": ["あたし"],
            "harsh_edge_markers": ["やれ。"], "care_markers": []}},
            "room_tone_profiles": {"future-room": "soft"}}
        if not _harsh_with(no_care, x_body):
            print("[PASS] H-7 care_markers が空の写像では判定しない"
                  "(データの入れ忘れが『常に鳴る安全網』に化けるのを構造で止める)")
        else:
            ok = False
            print("[FAIL] H-7 care_markers 空で発火した")

    # ★H-8= 短い便では鳴らない(6字以上の文が4つ未満)。刃1個の短報を毎回撃たない。
    h8 = harshness_drift("やれ。方向は正しい。", ["やれ。"], ["心配"])
    if not h8[0] and h8[3] < 4:
        print(f"[PASS] H-8 短い便(判定文{h8[3]}文)は鳴らさない=閾値4文が効いている")
    else:
        ok = False
        print(f"[FAIL] H-8 短便 -> {h8}")

    # ★H-9= 写像(room_tone_profiles)が実在すること。**うっかり削除を機構で止める**
    #   = この4部屋が写像から消えたら、ハ4は静かに何も判定しなくなる(誰も気づかない)。
    want_rooms = ["future-room", "past-room", "dream-care", "health-log"]
    missing = [d for d in want_rooms if room_tone_profile(rules, d) != "soft"]
    if not missing:
        print(f"[PASS] H-9 room_tone_profiles に soft の部屋が4つ在る({'/'.join(want_rooms)})"
              "=消えたらここが赤くなる")
    else:
        ok = False
        print(f"[FAIL] H-9 写像から soft が落ちている: {missing}")

    # ★H-10= 新しい reason の**突き返し対訳**が session_relay に在ること(C-042=載せ替えの経路)。
    #   これが無いと英語の reason がそのまま封筒へ出て、突き返しが読めない便になる。
    try:
        from session_relay import _TONE_REASON_JA        # noqa: E402
        if "harsh_without_care" in _TONE_REASON_JA:
            print("[PASS] H-10 突き返し対訳表に harsh_without_care が在る"
                  "(reason を足して対訳を忘れる=読めない突き返しを機構で止める)")
        else:
            ok = False
            print("[FAIL] H-10 session_relay の対訳表に harsh_without_care が無い")
    except Exception as e:
        ok = False
        print(f"[FAIL] H-10 session_relay を読めない ({type(e).__name__})")

    # ★H-11= 突き放し句カテゴリ(2026-08-23 人事部門が先置きした5語)を**刃として拾えること**。
    #   ハ4は JSON を都度読みするだけでカテゴリを増やせる=コード側は変えない。
    #   だからこそ「語が登録から落ちても誰も気づかない」= それをここで赤くする。
    push_away = ["どうでもいい", "自業自得", "勝手にしろ", "勝手にすれば", "もう知らない"]
    _ames = (rules.get("personas") or {}).get("アメス") or {}
    harsh_all = [str(x) for x in (_ames.get("harsh_edge_markers") or [])]
    care_all = [str(x) for x in (_ames.get("care_markers") or [])]
    gone = [w for w in push_away if w not in harsh_all]
    t11 = ("もう知らない。あたしは言うだけ言ったわ。あとは勝手にしろ。"
           "どうでもいいことに時間を使うのはアンタの自由よ。")
    fired = harshness_drift(t11, harsh_all, care_all)[0]
    # must-fail= 5語を抜いたら**鳴らなくなる**こと(=この判定が5語で立っている証拠)
    without = harshness_drift(t11, [w for w in harsh_all if w not in push_away], care_all)[0]
    if not gone and fired and not without:
        print("[PASS] H-11 突き放し句5語が刃として効いている"
              "(抜くと鳴らない=この検査が空PASSでない証拠)")
    else:
        ok = False
        print(f"[FAIL] H-11 未登録={gone} / 発火={fired} / 5語を抜いた時={without}")

    print("=== 全PASS ===" if ok else "=== FAIL あり ===")
    return 0 if ok else 1


def _harsh_with(rr, text):
    """任意の写像で harsh_without_care だけを取り出す(H-7 用)。"""
    return [v for v in tone_verdicts("アメス", "future-room", text, rr)
            if v.get("reason") == "harsh_without_care"]


if __name__ == "__main__":
    sys.exit(_run())
