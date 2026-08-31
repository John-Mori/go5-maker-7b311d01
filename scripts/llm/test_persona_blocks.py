#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""多人格の名乗りブロック分割(split_persona_blocks)の回帰テスト。

実行: python scripts/llm/test_persona_blocks.py

★2026-08-16 新設。理由= この関数は**誰の名義とアイコンでChamiの画面に出るか**を決める
  一番手前の分岐なのに、機械の検査が1本も無かった(口調ゲート側には在るのに、こちらは無かった)。
  実物の事故(軍議 msg 1538228236499034143)=
    セッションが `[十王星南][クラウディア] **商品候補選定** → …` と1行に2つ並べたため、
    正規表現が最初の1つだけを食い、**本文の冒頭に `[クラウディア]` がそのまま出た**
    (webhook名=十王星南 / 本文=「[クラウディア] 商品候補選定 →…」)。
★解決関数は本物を使わずここで固定する(本番の名簿が育っても赤にならない)。
"""
import os
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import dept_daemon as dd   # noqa: E402

ROOM = ("三笘薫", "オタコン", "花海咲季", "十王星南", "クラウディア")
results = []


def check(name, cond):
    results.append((name, bool(cond)))
    print(f"  {'PASS' if cond else 'FAIL'}: {name}")


def resolve(name):
    n = str(name or "").strip()
    return n if n in ROOM else None


def split(text):
    return dd.split_persona_blocks(text, resolve)


def main():
    # ---- 1) 既存の挙動(壊していないことの確認) ----
    check("名乗りが無ければ1通のまま", split("ただの本文") == [(None, "ただの本文")])
    check("1行目の名乗りで名義が決まる",
          split("[オタコン] 見たよ。") == [("オタコン", "見たよ。")])
    check("複数ブロックはそれぞれの名義へ割れる",
          split("[オタコン] あ\n[三笘薫] い") == [("オタコン", "あ"), ("三笘薫", "い")])
    check("解決できない[...]は本文として残す(文を壊さない)",
          split("[オタコン] あ\n[検証] い") == [("オタコン", "あ\n[検証] い")])
    # ★2026-08-30 挙動を**反転**させた(イージス研究室)。旧= 前置きを最初のブロックへ付ける。
    #   新= 落として persona_render_audit.jsonl へ記録する。理由= Chami「表示がおかしいことが多いね、
    #   どの部屋も」・実測 reply129中 [名前]付き102本の14本(13.7%・8部屋)で前置きが人格の発言へ
    #   混ざっていた。旧の意図(黙って削らない)は**記録に残す**ことで満たす。
    check("名乗りの手前の前置きは落とす(記録は audit へ)",
          split("前置き\n[オタコン] あ") == [("オタコン", "あ")])
    check("実物: 作業実況の前置きが落ちる",
          split("Committed as `2694831`. Report to the room:\n\n[オタコン] おはよう。")
          == [("オタコン", "おはよう。")])
    check("実物: 区切り線だけの前置きも落ちる",
          split("記録・発注ともに完了。\n\n---\n\n[三笘薫] ……ごめん。")
          == [("三笘薫", "……ごめん。")])
    check("★前置きだけで本文が空なら落とさない(沈黙させない)",
          split("前置きだけ\n[オタコン]") == [(None, "前置きだけ\n[オタコン]")])
    check("★名乗りが解決できない便は1文字も触らない",
          dd.split_persona_blocks("前置き\n[知らない人] あ", lambda n: None)
          == [(None, "前置き\n[知らない人] あ")])

    # ---- 2) ★実物: 同じ行に名乗りが2つ並んだ時、2つ目が本文へ漏れない ----
    real = "[十王星南][クラウディア] **商品候補選定** → 使うのは主に🔗アフィリンクタブ。"
    got = split(real)
    check("実物: 連続タグの2つ目が本文に漏れない",
          got == [("十王星南", "**商品候補選定** → 使うのは主に🔗アフィリンクタブ。")])
    check("実物: 話者は最初のタグのまま(どちらが話者かは機械には決められない)",
          got[0][0] == "十王星南")
    check("3つ以上並んでも全部剥ぐ",
          split("[十王星南][クラウディア][オタコン] 本文") == [("十王星南", "本文")])
    check("2行目以降の連続タグでも剥ぐ",
          split("[オタコン] あ\n[三笘薫][花海咲季] い")
          == [("オタコン", "あ"), ("三笘薫", "い")])
    check("解決できないタグは剥がない(本文を1文字も削らない)",
          split("[十王星南][検証] 本文") == [("十王星南", "[検証] 本文")])
    check("タグの後ろが空でも落ちない", split("[オタコン][三笘薫]") == [(None, "[オタコン][三笘薫]")])

    # ---- 3) fail-safe ----
    check("Noneでも落ちない", split(None) == [(None, "")] or split(None) == [(None, "")])
    check("解決関数が常にNoneなら1通のまま",
          dd.split_persona_blocks("[オタコン] あ", lambda n: None) == [(None, "[オタコン] あ")])

    # ---- 4) ★実rosterの別名漏れを機械で止める(2026-08-23) ----
    # 実物の事故(軍議 msg 1540821783584964618)= `[クラウディア・バレンツ]` が gunji roster の
    #   aliases に無く resolve が None に落ち、彼女の文が十王星南のブロックへ接着・タグが本文へ漏れた。
    # ★ここは**本物の resolve_persona_tag と本物の roster**を使う(固定resolveでは別名漏れを検知できない)。
    #   フルネームで名乗るメンバーは全員フルネームが引けること=同型の再発を丸ごと止める。
    gunji = dd.DEPT_CONF.get("gunji", {})
    roster = gunji.get("personas") or ()
    for p in roster:
        full = str(p.get("persona") or "")
        # 「姓・名」形式(中黒入り)で名乗る人は、そのフルネームが roster から引けねばならない
        if "・" in full:
            got_name = dd.resolve_persona_tag(gunji, full)
            check(f"実roster: フルネーム[{full}]が解決できる(別名漏れ無し)", got_name == full)
    # クラウディアは表示名が短縮形なので個別に固定(フルネーム→短縮の表示名へ解決)
    check("実roster: [クラウディア・バレンツ]→クラウディアへ解決",
          dd.resolve_persona_tag(gunji, "クラウディア・バレンツ") == "クラウディア")
    # 本物のresolveで、接着せず独立ブロックに割れる(実物の事故の直接の再現)
    real2 = "[クラウディア・バレンツ]\nこれは私の意見よ。\n[十王星南]\nこっちは星南の意見。"
    got2 = dd.split_persona_blocks(real2, lambda n: dd.resolve_persona_tag(gunji, n))
    check("実roster: クラウディア文が星南へ接着しない",
          got2 == [("クラウディア", "これは私の意見よ。"), ("十王星南", "こっちは星南の意見。")])

    # ---- 5) ★名乗りタグのホモグリフ破損を「数える」(2026-09-01・研究室HQの発注(1)) ----
    # 実物= hr-room の `[ククール]` が `[ККール]`(キリルК U+041A ×2)に化け、resolve が外れて
    #   下流ゲート一式が丸ごと fail-open で抜けた。**7本出荷して計器ゼロ**(persona_render_audit の
    #   КК=0件)。ここで足したのは記録だけ= 本文も名義も1文字も動かさない。
    KUKURU = "ククール"
    K = "К"                     # CYRILLIC CAPITAL LETTER KA(見た目はカタカナのク/ラテンK)
    BROKEN = K * 2 + "ール"          # 実物の破損形
    solo = dd.solo_tag_resolver({"persona": KUKURU})

    def spy(fn):
        """_audit_tag を捕まえる。★外へ出る手(監査書き込み)だけ偽物・判定と分岐は本物。"""
        rec = []
        orig = dd._audit_tag
        dd._audit_tag = lambda dept, who, outcome, line: rec.append((outcome, who))
        try:
            return fn(), rec
        finally:
            dd._audit_tag = orig

    def solo_run(text):
        return spy(lambda: dd.strip_solo_persona_tag(text, solo, dept="hr-room"))

    # 実物と同じ3つの形(1行目 / 前置き1行の後 / 前置き+区切り線の後)を全部拾えること
    s0 = "[%s] その2枚、もう入ってるぜ。" % BROKEN
    s2 = "Chami(部屋)への返信 —\n\n[%s]\n\nデブライネから返しが来た。" % BROKEN
    s4 = "Done. Report to Chami (output text = the reply):\n\n---\n\n[%s] 2つとも手ぇ入れといたよ。" % BROKEN
    for nm, src in (("1行目", s0), ("前置きの後(2行目)", s2), ("前置き+区切り線の後(4行目)", s4)):
        out, rec = solo_run(src)
        check(f"ホモグリフ: {nm}の破損タグを数える",
              [o for o, _ in rec] == ["tag_homoglyph_leak"])
        check(f"ホモグリフ: {nm}=推定した正名で記録する", rec and rec[0][1] == KUKURU)
        check(f"ホモグリフ: {nm}=本文は1文字も変えない", out == src)

    # ★正常便は1文字も変えない・鳴らない(受け入れ条件の後半)
    clean = "[%s] ああ、ハブは全部ここで作ったやつだよ。\n\n続きの本文。" % KUKURU
    out, rec = solo_run(clean)
    check("ホモグリフ: 正常便は従来どおりタグだけ落ちる",
          out == "ああ、ハブは全部ここで作ったやつだよ。\n\n続きの本文。")
    check("ホモグリフ: 正常便で homoglyph は鳴らない",
          [o for o, _ in rec] == ["tag_solo_fixed"])

    # ★誤発火しない線= foreign-script が無ければ鳴らさない(共通規律§3)
    for nm, tag in (("ただの打ち間違い", "ククーる"), ("無関係な本文", "検証"),
                    ("別人の名前", "オタコン"), ("長すぎる別語", "ククールのアイコン一覧")):
        out, rec = solo_run("[%s] 本文だ。" % tag)
        check(f"ホモグリフ: {nm}では鳴らない",
              not [o for o, _ in rec if o == "tag_homoglyph_leak"])

    # ★窓の外(非空3行を越えた先)は見ない= resolver と同じ幅のまま
    far = "あ\nい\nう\n[%s] 本文" % BROKEN
    out, rec = solo_run(far)
    check("ホモグリフ: 窓の外のタグは見ない(既存の幅を広げない)", rec == [] and out == far)

    # ★多人格部屋(split 側)も同じ穴が在る= names を渡した時だけ数える
    broken_multi = "[%sタコン] 本文だ。" % "О"   # CYRILLIC CAPITAL LETTER O
    got, rec = spy(lambda: dd.split_persona_blocks(
        broken_multi, resolve, dept="gunji", names=list(ROOM)))
    check("ホモグリフ: 多人格部屋でも数える",
          [o for o, _ in rec] == ["tag_homoglyph_leak"] and rec[0][1] == "オタコン")
    check("ホモグリフ: 多人格部屋でも本文は割らない・触らない",
          got == [(None, broken_multi)])
    got, rec = spy(lambda: dd.split_persona_blocks(broken_multi, resolve, dept="gunji"))
    check("ホモグリフ: names 未指定の既存呼び元は従来どおり(落ちない・鳴らない)",
          rec == [] and got == [(None, broken_multi)])

    # ---- 6) ★実コーパスの検体を全部拾えるか(無ければ skip= 黙って緑にしない) ----
    import io  # noqa: E402
    import json  # noqa: E402
    root = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
    corpus = [os.path.join(root, "local", "llm", "recent_hr-room.jsonl"),
              os.path.normpath(os.path.join(root, "..", "00_AI-HQ", "departments", "hr",
                                            "memory", "hr-room.jsonl"))]
    # ★ここから先の check は**生きたコーパス**の件数ぶん増える= 総数は日によって動く。
    #   固定分の数を控えておき、最後に別々に出す(HQ検算 2026-09-01: 同じ HEAD で
    #   51/51 → 48/48 → 50/50 と割れた真因がこれだった。総数だけ見ると齟齬に見える)。
    fixed_n = len(results)
    seen_broken = seen_clean = 0
    for path in corpus:
        if not os.path.isfile(path):
            print(f"  SKIP: コーパスが無い({path})")
            continue
        for ln in io.open(path, encoding="utf-8"):
            ln = ln.strip()
            if not ln:
                continue
            try:
                r = str(json.loads(ln).get("reply") or "")
            except Exception:
                continue
            if not r:
                continue
            out, rec = solo_run(r)
            hit = [o for o, _ in rec if o == "tag_homoglyph_leak"]
            # ★検体の定義= **タグの形**でКが入っている便だけ(resolver と同じ窓の中)。
            #   2026-08-08 の1本は `ККールの声での報告だ` と**地の文**で化けているだけで、
            #   名乗りタグではない= 機構が触る対象ではない(HQの分析と同じ切り方)。
            broken_tag = any(
                (dd._tag_match(l) or ("",))[0].find(K) >= 0
                for l in [x for x in r.split("\n") if x.strip()][:dd._SOLO_PREAMBLE_MAX_LINES + 1])
            if broken_tag:
                seen_broken += 1
                check("実コーパス: 破損便を検知し本文は無傷", bool(hit) and out == r)
            elif hit:
                seen_clean += 1
                check("実コーパス: 正常便で誤発火しない(1件も鳴らない)", False)
    if seen_broken:
        print(f"  (実コーパスの破損検体 {seen_broken}件を全部検知・誤発火 {seen_clean}件)")
    else:
        print("  SKIP: 実コーパスに破損検体が無い(窓が入れ替わった)")

    ok = all(v for _, v in results)
    fixed_pass = sum(v for _, v in results[:fixed_n])
    live_pass = sum(v for _, v in results[fixed_n:])
    live_n = len(results) - fixed_n
    # ★再現できる数=固定分。live 分はコーパス次第で増減するので分けて出す。
    print(f"\n== 固定 {fixed_pass}/{fixed_n} PASS + 実コーパス {live_pass}/{live_n} "
          f"(合計 {sum(v for _, v in results)}/{len(results)}) ==")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
