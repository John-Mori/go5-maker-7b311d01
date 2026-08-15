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
    check("名乗りの手前の前置きは捨てずに最初のブロックへ付ける",
          split("前置き\n[オタコン] あ") == [("オタコン", "前置き\nあ")])

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

    ok = all(v for _, v in results)
    print(f"\n== {sum(v for _, v in results)}/{len(results)} PASS ==")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
