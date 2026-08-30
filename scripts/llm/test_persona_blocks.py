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

    ok = all(v for _, v in results)
    print(f"\n== {sum(v for _, v in results)}/{len(results)} PASS ==")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
