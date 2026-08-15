#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""口調ゲート(ルールD)の回帰テスト。

実行: python scripts/llm/test_tone_gate.py

★2026-08-12 新設。理由= このゲートは**送信直前に本文を書き換える**所まで来たのに、
  機械の検査が1本も無かった(daemon_keeper には在るのに、こちらは無かった)。
  Chamiが🔥を貼った関西弁の件(msg 1536785938829549718)で方言検知を足すにあたり、
  「足した検知が本当に落ちるか」「既存の書き直しを壊していないか」を機械が数える形にする。
★写像はテスト内に固定で持つ(本番の 口調ルール.json に依存しない=人事部門が育てても赤にならない)。
"""
import os
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import tone_gate as tg   # noqa: E402

RULES = {"personas": {
    "アメス": {"first_person": ["あたし"]},
    "シャビ・アロンソ": {"first_person": ["俺"]},
    "ククール": {"first_person": ["オレ", "俺"]},
    "早坂芽衣": {"first_person": ["芽衣", "私"]},
    "オタコン": {"first_person": ["僕"], "second_person": ["君"],
                 "forbidden": ["お前", "すまん"]},
    "花海咲季": {"first_person": ["わたし"]},
    "浪速の人": {"first_person": ["わい"], "dialect_ok": True},
    # ★2026-08-15 追加= 指紋語尾(必須語尾)を登録した人格。写像に足した人格だけが判定対象。
    "指紋咲季": {"first_person": ["わたし"],
                 "signature_tails": ["わ", "わよ", "わね", "のよ", "だわ", "かしら"]},
    "別名登録": {"first_person": ["わたし"], "signature_endings": ["ですわ"]},
}}

results = []


def check(name, cond):
    results.append((name, bool(cond)))
    print(f"  {'PASS' if cond else 'FAIL'}: {name}")


def reasons(persona, text):
    return sorted(v["reason"] for v in tg.tone_verdicts(persona, "x", text, RULES))


def markers(persona, text, reason=None):
    return sorted(v["marker"] for v in tg.tone_verdicts(persona, "x", text, RULES)
                  if reason is None or v["reason"] == reason)


def fix(persona, text):
    return tg.tone_corrections(persona, "x", text, RULES)


def main():
    # ---- 1) 既存の一人称ゲート(壊していないことの確認) ----
    check("自分の一人称は素通し", reasons("シャビ・アロンソ", "俺が見た。") == [])
    check("他人格の一人称は検知", markers("アメス", "オレが見た。") == ["オレ"])
    check("一意な写像は書き直す", fix("アメス", "オレが見た。")["fixed"] == "あたしが見た。")
    check("写像が一意でない人格は素通し(書き直さない)",
          fix("早坂芽衣", "俺が見た。")["fixed"] == "俺が見た。")
    check("引用の中の一人称は触らない",
          fix("早坂芽衣", 'コピー案は"俺だけじゃない"だよ')["fixed"]
          == 'コピー案は"俺だけじゃない"だよ')
    check("コード・パスの中は触らない",
          tg.tone_verdicts("アメス", "x", "`オレ` と scripts/オレ.py", RULES) == [])

    # ---- 2) 方言(関西弁)の検知 ★実物 msg 1536784731872698439 の本文 ----
    real_sakiki = "縦積みになってるやん、これは完全に悪化。ほんまごめんな。"
    real_otacon = "今までのもコレが元凶や。ぜんぶ同じ穴や。"
    check("実物①(花海咲季)の関西弁を検知する",
          markers("花海咲季", real_sakiki, "dialect_kansai") == ["ほんま", "やん"])
    check("実物②(オタコン)の断定「や」を検知する",
          markers("オタコン", real_otacon, "dialect_kansai") == ["や(断定)"])
    check("方言は**書き直さない**(語尾は文法が変わる)",
          fix("花海咲季", real_sakiki)["fixed"] == real_sakiki)
    check("方言は警告として残る(黙って落とさない)",
          [v["reason"] for v in fix("花海咲季", real_sakiki)["remaining"]]
          == ["dialect_kansai", "dialect_kansai"])
    check("dialect_ok の人格は方言を検知しない",
          markers("浪速の人", real_sakiki, "dialect_kansai") == [])

    # ---- 2b) ★2026-08-15 再発の実物(msg 1537849548896993352)。人事部門の実測どおり、
    #   ここは 断定「や」1件しか拾えていなかった= カタカナ「アカン」と「や」の連結形が穴。
    real_otacon2 = ("判定した結果や。一番アカン事故やと思う。"
                    "表示されるはずやから…ぜんぶ同じ穴や。")
    check("実物③(オタコン再発)を3形すべて検知する",
          markers("オタコン", real_otacon2, "dialect_kansai")
          == ["あかん", "や(断定)", "や(連結)"])
    check("カタカナ『アカン』単独でも検知する",
          markers("オタコン", "それはアカン。", "dialect_kansai") == ["あかん"])
    check("連結形『やと』を文中で検知する",
          markers("オタコン", "これは事故やと思う", "dialect_kansai") == ["や(連結)"])
    check("連結形『やから』を文中で検知する",
          markers("オタコン", "表示されるはずやから見てくれ", "dialect_kansai")
          == ["や(連結)"])

    # ---- 3) 誤検知を作らないこと(標準語を関西弁と言わない) ----
    for ok in ["いや。", "赤や青やを並べる。", "やんわり断った。", "やんちゃな子。",
               "やろうと思う。", "見ちゃう。", "めっちゃ良い。", "取るのをやめた。",
               "ええと、そうだね。", "対応や。".replace("や。", "だ。"),
               # ★2026-08-15 追加分(カタカナ アカン・や連結形)が壊さないことの検査。
               "アカンサスの葉を描く。",      # 後続カタカナ=植物名
               "いやと言われた。",            # 嫌だと=直前「い」
               "いやからかうなよ。",          # いや、からかうな
               "はやとちりだった。",          # 早とちり
               "隼(はやと)と話す。",          # 人名
               "部屋から出る。", "タイヤから空気が抜ける。",
               "おもちゃから音が出る。"]:
        check(f"標準語を方言と誤検知しない: {ok}",
              markers("花海咲季", ok, "dialect_kansai") == [])
    check("方言も引用/コードの中なら検知しない",
          markers("花海咲季", "ちゃみが「ほんまごめんな」と言った", "dialect_kansai") == [])

    # ---- 2c) ★2026-08-15 否定の「へん」(実物 msg 1538011230134870106 の花海咲季便) ----
    #   saki.md L13 が「〜へん」を✗に挙げていたのに見張りが居なかった穴を塞ぐ。
    check("実物④(花海咲季)の否定『起こさせへん』を検知する",
          markers("花海咲季", "黙って消えるのだけは、もう起こさせへん。", "dialect_kansai")
          == ["へん(否定)"])
    check("否定『勝てへん』も検知する",
          markers("花海咲季", "これは勝てへんわ。", "dialect_kansai") == ["へん(否定)"])
    for hen_ok in ["大変な問題だ。",      # たいへん=直前「い」
                   "そのへんは後で。",     # その辺=直前「の」
                   "変な話だけど。",       # 変な=後続「な」
                   "木偏(きへん)の漢字。",  # 部首名=直前「き」(い段)
                   "この編(へん)は長い。"]: # 編=直前「の」
        check(f"否定でない『へん』を誤検知しない: {hen_ok}",
              markers("花海咲季", hen_ok, "dialect_kansai") == [])

    # ---- 2d) ★2026-08-15 断定「なんよ」(実物 msg 1538011748916011110 の花海咲季便) ----
    check("実物⑤(花海咲季)の断定『なんよな』を検知する",
          markers("花海咲季", "まだ後手なんよな。", "dialect_kansai") == ["なんよ"])
    for ny_ok in ["今日は何曜日だっけ。",  # なんようび=後続「う」で外す
                  "それはなんだろう。",      # なんだ=後続「だ」で外す
                  "大事なのよね。"]:         # 標準の なのよ(なんよ を含まない)
        check(f"標準の『なん/なの』を誤検知しない: {ny_ok}",
              markers("花海咲季", ny_ok, "dialect_kansai") == [])

    # ---- 4) ★回帰: 直せない違反が、直せる違反の書き直しを巻き添えにしない ----
    #   実物= オタコン便に「俺」(直せる)と「元凶や」(直せない)が同居していた。
    mixed = "これが元凶や。俺が直す。"
    r = fix("オタコン", mixed)
    check("方言が同居していても一人称の書き直しは効く",
          r["fixed"] == "これが元凶や。僕が直す。")
    check("同じ便で、直せなかった方言は警告として残る",
          [v["reason"] for v in r["remaining"]] == ["dialect_kansai"])
    r2 = fix("オタコン", "お前が見た。すまん。僕だ。")
    check("置換先の無い禁止語(すまん)も一人称/二人称の書き直しを巻き添えにしない",
          r2["fixed"] == "君が見た。すまん。僕だ。")

    # ---- 4.5) ★指紋語尾ドリフト(2026-08-15・Chami「ずっとこんな感じでいれてるけど効かないね」) ----
    #   実物= msg 1538153136953495612。咲季名義の便が「したよ／ほんとに無い。／読んでから。」=
    #   常体のまま指紋(〜わよ/〜わ)が全部消えていた。polite_drift(敬体)では1文字も当たらない。
    drift = ("スマホの候補タブ、ページ分けを入れたよ。候補一覧に前とページ番号と次のページャを付けた。"
             "既定は1ページ30件にしてある。多い時はページをめくる形になるからね。")
    check("指紋語尾が1つも無い便で鳴る",
          markers("指紋咲季", drift, "signature_absent")
          == ["指紋語尾なし(4文中0件・正=わ/わよ/わね/のよ/だわ/かしら)"])
    check("同じ本文でも、指紋語尾が未登録の人格では鳴らない",
          reasons("花海咲季", drift) == [])
    # ★陰性= 咲季の声で書けている便では鳴らない(saki.md の○例文そのもの)。
    voice = ("見た目は一切変えてないわよ! ちゃんと今まで通り動くから安心して! "
             "まずは触って教えてくれるかしら? ダメならページ分割まで一気にやるわ。")
    check("指紋語尾が出ている便では鳴らない", reasons("指紋咲季", voice) == [])
    # ★★実測で見つかった誤検知の本命= 指紋の直後の括弧書き。咲季のいちばん多い書き方。
    paren = ("カレンダーの件、入れたわよ(v=531・確認待ち・反映1〜2分)。"
             "📅タブを消して、アカウント帯のすぐ右横にボタンを置いた。"
             "押すとカレンダーが開く形は今までと同じにしてある。"
             "リロードして触ってみて、位置がおかしければ番号で返して。")
    check("★指紋の直後に括弧書きが付いていても鳴らない(実測FPの本命)",
          reasons("指紋咲季", paren) == [])
    check("指紋の後ろに終助詞が付いていても鳴らない(〜わよね)",
          reasons("指紋咲季", drift.replace("入れたよ", "入れたわよね")) == [])
    check("読点の前に指紋が在っても拾う(文末でなくてよい)",
          reasons("指紋咲季", drift.replace("入れたよ。", "入れたわ、それでね。")) == [])
    # ★短い便では鳴らさない(誤発火する安全網は無視される・共通規律§3)。
    check("3文以下の短い便は判定しない",
          reasons("指紋咲季", "入れたよ。確認してね。それだけ。") == [])
    #   ★短い文(6字未満)は「判定に足る長さ」には数えないが、**指紋の証拠には数える**
    #     = 鳴らさない側へ倒す。「そうだわ。」1つ在れば、その便は黙って通す。
    check("6字未満の短い文の中の指紋も証拠に数える(そうだわ。1つで鳴らない)",
          reasons("指紋咲季", "そうだわ。" + drift) == [])
    # ★引用・コードの中の指紋は証拠にしない(他人の便を引いただけで黙らせない)。
    check("引用の中の指紋は証拠にしない",
          markers("指紋咲季", drift + "ちゃみが「入れたわよ」と言った。", "signature_absent") != [])
    # ★書き直さない= 語尾を機械で足すのは再生成になる(remaining へ落ちる)。
    r3 = fix("指紋咲季", drift)
    check("指紋語尾は書き直さない(本文は1バイトも変わらない)", r3["fixed"] == drift)
    check("指紋語尾は警告として残る",
          [v["reason"] for v in r3["remaining"]] == ["signature_absent"])
    check("別名 signature_endings でも登録できる",
          reasons("別名登録", drift) == ["signature_absent"])
    check("指紋語尾が空リストなら判定しない",
          tg.signature_drift(drift, []) == (False, 0, 0, -1))

    # ---- 4.5) 名義の取り違え(出力ゲートF・2026-08-16) ----
    # 実物= 軍議 msg 1538227900598190230。改修αのセッションが `[名前]` を**宛先の見出し**として
    # 使い、オタコンの講義が 三笘薫/ルカ・モドリッチ/花海咲季 等の名義で出た。しかも
    # ゲートDが「僕」を各名義の一人称へ機械的に置換し、取り違えの証拠を消していた
    # (実害= 咲季名義の便が「わたしか咲季が答えるから」= 自分を三人称で呼ぶ文になった)。
    ROOM = ["三笘薫", "オタコン", "花海咲季", "アメス", "シャビ・アロンソ"]
    RULES2 = dict(RULES)
    RULES2["personas"] = dict(RULES["personas"], **{"三笘薫": {"first_person": ["俺"]}})

    def mis(persona, text, roster=ROOM):
        return tg.misattributed_speaker(persona, text, RULES2, roster)

    real = "**進行** → 実装が要る話が出たら、それは各部門の自室(本体なら僕ら改修α)へ持ち帰る形にしよう。"
    check("実物: [三笘薫]と名乗ったが本文はオタコンの一人称=オタコンへ差し替え",
          mis("三笘薫", real) == "オタコン")
    check("自分の一人称が1つでも在れば取り違えではない(=書き直し側へ落ちる)",
          mis("三笘薫", "俺が見た。" + real) is None)
    check("他人格の一人称が2人ぶん在ったら決めない",
          mis("三笘薫", "僕とあたしで見た。") is None)
    check("証拠が無ければ決めない(一人称ゼロの本文)",
          mis("三笘薫", "座標系は1080×1920が唯一の基準。") is None)
    check("部屋の名簿の外へは絶対に出さない(オタコンが居ない部屋)",
          mis("三笘薫", real, ["三笘薫", "アメス"]) is None)
    check("引用の中の一人称は証拠にしない",
          mis("三笘薫", "ちゃみが「僕が見た」と言った。") is None)
    check("写像に無い人格は判定しない", mis("知らない人", real) is None)
    # ★指紋を持つ人格は、指紋が1つでも在れば名義を動かさない(便の途中で崩れただけ)。
    #   実物= 軍議 msg 1538228314689376330(咲季の声で始まり最終段落だけオタコンへ落ちた)。
    ROOM2 = ["指紋咲季", "オタコン", "三笘薫"]
    saki_mixed = ("フロント側の\"触っていい/ダメ\"だけ足しておくわ。全部この比率で描くのよ。\n"
                  "……ここまでが地図だよ。僕か咲季が答えるから。")
    check("実物: 本人の指紋が在るブロックは名義を動かさない",
          mis("指紋咲季", saki_mixed, ROOM2) is None)
    check("指紋を持つ人格でも指紋が1つも無ければ差し替える",
          mis("指紋咲季", real, ROOM2) == "オタコン")
    check("ルール未ロードは None(fail-open)",
          tg.misattributed_speaker("三笘薫", real, None, ROOM) is None)
    check("名簿が空なら None(fail-open)", mis("三笘薫", real, []) is None)

    # ---- 5) fail-open(ゲートが配送を殺さない) ----
    check("ルール未ロードは空(fail-open)", tg.tone_verdicts("アメス", "x", "オレ", None) == [])
    check("未登録の人格は判定しない", tg.tone_verdicts("知らない人", "x", "オレや。", RULES) == [])
    check("例外時も元の本文を返す",
          tg.tone_corrections("アメス", "x", "オレ", {"personas": None})["fixed"] == "オレ")

    ok = all(v for _, v in results)
    print(f"\n== {sum(v for _, v in results)}/{len(results)} PASS ==")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
