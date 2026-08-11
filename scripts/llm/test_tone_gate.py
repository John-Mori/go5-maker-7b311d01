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

    # ---- 3) 誤検知を作らないこと(標準語を関西弁と言わない) ----
    for ok in ["いや。", "赤や青やを並べる。", "やんわり断った。", "やんちゃな子。",
               "やろうと思う。", "見ちゃう。", "めっちゃ良い。", "取るのをやめた。",
               "ええと、そうだね。", "対応や。".replace("や。", "だ。")]:
        check(f"標準語を方言と誤検知しない: {ok}",
              markers("花海咲季", ok, "dialect_kansai") == [])
    check("方言も引用/コードの中なら検知しない",
          markers("花海咲季", "ちゃみが「ほんまごめんな」と言った", "dialect_kansai") == [])

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
