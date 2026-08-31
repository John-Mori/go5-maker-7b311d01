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
    # ★2026-09-01 §5-2 で「数えるだけ」から「救済」へ進めた= 判定の物差しを変える。
    #   旧: 本文を1文字も変えない(素通し)。新: **化けた便の出力が、同じ便の正名版の出力と
    #   1文字たがわず一致する**= ホモグリフが下流から見えなくなったことの直接の確認。
    #   これは「素通し」よりも強い= 落としすぎ/落とし足りない のどちらも赤くなる。
    def _twin(s):
        """検体の К(キリル) を ク へ戻した『正名版の双子』。"""
        return str(s).replace(K, "ク")

    for nm, src in (("1行目", s0), ("前置きの後(2行目)", s2), ("前置き+区切り線の後(4行目)", s4)):
        out, rec = solo_run(src)
        outcomes = [o for o, _ in rec]
        check(f"ホモグリフ: {nm}の破損タグを数える", "tag_homoglyph_leak" in outcomes)
        check(f"ホモグリフ: {nm}=推定した正名で記録する", rec and rec[0][1] == KUKURU)
        twin_out, _ = solo_run(_twin(src))
        check(f"ホモグリフ: {nm}=救済後の出力が正名版と完全一致", out == twin_out)
        check(f"ホモグリフ: {nm}=救済したことも記録に残る", "tag_solo_fixed" in outcomes)

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
    # ★★2026-09-01 訂正= 上の2ファイルは**同じ便を両方に持っている**。片方は本文を700字、
    #   もう片方は500字で切るので、本文のハッシュでは重複が落ちない(実測= msg_id
    #   1544095173124816896 / DISPATCH-hr-room-1788212395104 の2便が二重に数えられ、
    #   当室は9件を11件と申告した)。**msg_id で重複を落とす**= §1「有利に盛れる数は
    #   重複を落とした小さい真値で出す」。msg_id が無い行だけ本文で代用する。
    # ★★重複を落とす時に「先に読んだ方を採る」をやると**検体を取りこぼす**(実測)=
    #   発注(3)で recent 側だけ浄化したので、同じ便の写しが「片方は破損・片方は正名」に
    #   なっている(msg 1544087406028914759 など3便)。先勝ちだと浄化済みの写しを採って
    #   破損検体が9→6に減った。**写しを全部見て、1つでも破損なら破損の写しを採る。**
    fixed_n = len(results)

    # ★検体の定義= **タグの形**でКが入っている便だけ(resolver と同じ窓の中)。
    #   2026-08-08 の1本は `ККールの声での報告だ` と**地の文**で化けているだけで、
    #   名乗りタグではない= 機構が触る対象ではない(HQの分析と同じ切り方)。
    def _broken_tag(text):
        return any(
            (dd._tag_match(l) or ("",))[0].find(K) >= 0
            for l in [x for x in text.split("\n") if x.strip()][:dd._SOLO_PREAMBLE_MAX_LINES + 1])

    uniq = {}
    order = []
    for path in corpus:
        if not os.path.isfile(path):
            print(f"  SKIP: コーパスが無い({path})")
            continue
        for ln in io.open(path, encoding="utf-8"):
            ln = ln.strip()
            if not ln:
                continue
            try:
                _row = json.loads(ln)
                r = str(_row.get("reply") or "")
            except Exception:
                continue
            if not r:
                continue
            key = str(_row.get("msg_id") or "") or ("body:" + r[:200])
            if key not in uniq:
                uniq[key] = r
                order.append(key)
            elif _broken_tag(r) and not _broken_tag(uniq[key]):
                uniq[key] = r      # 破損している写しを優先(浄化済みの写しで隠さない)

    seen_broken = seen_clean = 0
    for key in order:
        r = uniq[key]
        out, rec = solo_run(r)
        hit = [o for o, _ in rec if o == "tag_homoglyph_leak"]
        if _broken_tag(r):
            seen_broken += 1
            twin_out, _ = solo_run(_twin(r))
            check("実コーパス: 破損便を検知し、出力が正名版と完全一致",
                  bool(hit) and out == twin_out)
        elif hit:
            seen_clean += 1
            check("実コーパス: 正常便で誤発火しない(1件も鳴らない)", False)
    if seen_broken:
        print(f"  (実コーパスの破損検体 {seen_broken}件を全部検知・誤発火 {seen_clean}件)")
    else:
        print("  SKIP: 実コーパスに破損検体が無い(窓が入れ替わった)")

    # ---- 6.5) ★受け入れ条件の固定(研究室HQ DISPATCH-aegis-gl-1788213934335)----
    #   「今日の検体= gen=18 の9便を全部検知」。上の走査は**件数を印字するだけ**で、
    #   数え方を間違えても緑のままだった(実測= 重複の落とし方を先勝ちにすると9→6に
    #   減るが、それでも 6/6 PASS と出た)。そこで**この9本のmsg_idを名指しで固定する**。
    #   コーパスは追記式(hr-room.jsonl)なので、時間が経っても消えない。
    GEN18_SAMPLES = [
        "DISPATCH-hr-room-1788200414414",   # 03:28:42
        "DISPATCH-hr-room-1788200684995",   # 03:31:11
        "1544081974363291729",              # 05:51:06
        "1544081794238783619",              # 05:51:38
        "1544087406028914759",              # 05:53:58
        "1544087977955819570",              # 05:55:38
        "DISPATCH-hr-room-1788210550541",   # 06:14:07
        "1544095173124816896",              # 06:27:00(=recent側 06:22:57 と同一便)
        "DISPATCH-hr-room-1788212395104",   # 06:45:42(=recent側 06:39:55 と同一便)
    ]
    pinned_at = len(results)   # ここから先は「固定」扱い(コーパスの中身で増減しない)
    missing = [m for m in GEN18_SAMPLES if m not in uniq]
    if missing:
        check(f"受け入れ条件: gen=18 の9検体がコーパスに在る(欠け {len(missing)}本)", False)
    else:
        undetected = []
        for mid in GEN18_SAMPLES:
            r = uniq[mid]
            _out, _rec = solo_run(r)
            _twin_out, _ = solo_run(_twin(r))
            if not (_broken_tag(r) and any(o == "tag_homoglyph_leak" for o, _ in _rec)
                    and _out == _twin_out):
                undetected.append(mid)
        check("受け入れ条件: gen=18 の9検体を全部検知し、出力が正名版と完全一致", not undetected)
        if undetected:
            print(f"    取りこぼし= {undetected}")

    ok = all(v for _, v in results)
    fixed_pass = sum(v for _, v in results[:fixed_n])
    live = results[fixed_n:pinned_at]
    pinned = results[pinned_at:]
    # ★再現できる数=固定分と受け入れ分。live 分はコーパス次第で増減するので分けて出す。
    print(f"\n== 固定 {fixed_pass}/{fixed_n} PASS + 受け入れ {sum(v for _, v in pinned)}/{len(pinned)} "
          f"+ 実コーパス {sum(v for _, v in live)}/{len(live)} "
          f"(合計 {sum(v for _, v in results)}/{len(results)}) ==")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
