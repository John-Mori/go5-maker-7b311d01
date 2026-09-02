#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""strip_envelope_echo の検査(2026-09-03 / 研究室HQ・止血)。

検体= local/_work/envelope_echo_specimens.json(軍議 2026-09-03 01:55 の実物2通をAPIで取得)。
陽性2件・陰性(誤爆してはいけない)5件。must-fail= 実装を外した時に陽性が落ちること。

  python scripts/llm/test_envelope_echo.py
"""
import io
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.normpath(os.path.join(HERE, "..", ".."))
if HERE not in sys.path:
    sys.path.insert(0, HERE)
import meta_strip                                # noqa: E402

SPEC = os.path.join(ROOT, "local", "_work", "envelope_echo_specimens.json")

# --- 陰性(切ってはいけない) -------------------------------------------------
NEG = [
    ("普通の返信",
     "うん、届いてるとこは既読・着手も付いてる。\n\nどうする:\n1. このままでいい\n2. 全部屋へ流す"),
    ("事故を論じる便(引用符つき)",
     "アロンソ、封筒の「=== この部屋のセッション状態 ===」がそのまま出てた。\n"
     "受信時刻: 2026-09-03T01:55:03 の便だ。原因を追う。"),
    ("コードブロックで貼った再現手順",
     "再現はこれ。\n\n```\n=== この部屋のセッション状態 ===\n世代: 第8世代\n投稿者: chami_fusoh\n```\n\n以上だ。"),
    ("引用ブロック(>)で写した封筒",
     "> === この部屋のセッション状態 ===\n> 世代: 第8世代\n\nこれが出てた。俺の見立てはこうだ。"),
    ("主マーカー1本だけ(裏づけ無し)",
     "封筒の ■規律: 前便から変更なし の行が気になる。それだけ言っておく。"),
]


def main():
    ok, ng = 0, 0

    def check(label, got, want):
        nonlocal ok, ng
        if got == want:
            ok += 1
            print(f"  OK   {label}")
        else:
            ng += 1
            print(f"  NG   {label}: got={got} want={want}")

    print("[陽性] 実物の検体")
    if not os.path.exists(SPEC):
        print(f"  検体が無い: {SPEC}")
        return 2
    for rec in json.load(io.open(SPEC, encoding="utf-8")):
        body, hits = meta_strip.strip_envelope_echo(rec["content"])
        cut = len(rec["content"]) - len(body)
        print(f"  msg={rec['msg_id']} 元{len(rec['content'])}字 → 残{len(body)}字 "
              f"(落とした{cut}字) 署名={[h['marker'] for h in hits]}")
        check(f"msg={rec['msg_id']} 切れている", bool(hits), True)
        check(f"msg={rec['msg_id']} 封筒が残っていない",
              ("この部屋のセッション状態" in body or "■この部門の目的とKPI" in body
               or "total_tokens" in body), False)
    # ①は正常な返信が頭に在る= 空にしてはいけない / ②は全文が封筒= 空でよい
    recs = json.load(io.open(SPEC, encoding="utf-8"))
    b1, _ = meta_strip.strip_envelope_echo(recs[0]["content"])
    check("① 正常部分は残る(先頭が人格の台詞)", b1.startswith("ははっ"), True)
    b2, _ = meta_strip.strip_envelope_echo(recs[1]["content"])
    check("② 全文が封筒→空になる", b2.strip() == "", True)

    print("[陰性] 切ってはいけない本文")
    for label, text in NEG:
        body, hits = meta_strip.strip_envelope_echo(text)
        check(label, (body == text and not hits), True)

    print(f"\n合計: OK={ok} NG={ng}")
    return 0 if ng == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
