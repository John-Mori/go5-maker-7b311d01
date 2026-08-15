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

from tone_gate import (  # noqa: E402
    load_tone_rules, tone_verdicts, tone_corrections, polite_drift)

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

    print("=== 全PASS ===" if ok else "=== FAIL あり ===")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(_run())
