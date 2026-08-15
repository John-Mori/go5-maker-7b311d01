#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""meta_strip(送信直前ゲートE= 内部の手続きメタの剥ぎ)の回帰テスト。

なぜ要るか(2026-08-15 イージス研究室):
  「ソースの文字列一致は検査ではなく保険だ。入力を差し替えて経路を実行で通せ」(HQ裁定2026-08-14)。
  このゲートは**本文を削る**方向に働く唯一のゲートなので、
  陽性(実物の漏れ)と同じ数だけ**陰性(剥いではいけない文)**を固定しておく。
  ★陽性の入力は実物のコピー= local/llm/recent_copy-director.jsonl の
    msg_id=DISPATCH-copy-director-1786794044539 の reply(Chami指示③の壊れた実物)。

実行= python scripts/llm/test_meta_strip.py (全PASSで exit 0)
"""
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

import meta_strip                                          # noqa: E402

_PASS = 0
_FAIL = 0

# ★実物(壊れた本文そのもの)。1行=本文の全部だった。
LEAK = ("No response requested — this is a backchannel HQ→部門 answer to my own §3.9 上申, "
        "with no Chami手番 and nothing left on my side (winning-patterns.md 4行目の "
        "`★★C-047` ポインタはアロンソコーチの実測どおりコア条文と一致・変更不要)。"
        "§4.7に従い部屋への「了解」返信はしない。")


def _check(name, cond):
    global _PASS, _FAIL
    if cond:
        _PASS += 1
        print("PASS %s" % name)
    else:
        _FAIL += 1
        print("FAIL %s" % name)


def main():
    # --- 陽性: 剥ぐべきもの ------------------------------------------------
    body, hits = meta_strip.strip_meta_tail(LEAK)
    _check("実物の漏れが剥がれる", body == "" and len(hits) == 1)
    _check("剥いだ理由が記録に残る", hits and hits[0]["marker"] == "no_response_requested")

    real = "怜、②受け取った。実物を見て測った。縛り5つは満たしてる。"
    body, hits = meta_strip.strip_meta_tail(real + "\n\n" + LEAK)
    _check("本文の後ろに付いたメタだけ剥ぐ", body == real and len(hits) == 1)

    body, _ = meta_strip.strip_meta_tail(real + "\n\nNo further action required.")
    _check("no further action も剥ぐ", body == real)

    body, hits = meta_strip.strip_meta_tail(real + "\n\n**No response requested.**\n\n")
    _check("飾り付き・末尾空行つきでも剥ぐ", body == real and len(hits) == 1)

    # --- 陰性: 剥いではいけないもの(誤爆=本文欠け=取り返しがつかない) ------
    same = "了解した。手は空いてる。"
    _check("マーカーが無ければ1文字も変えない", meta_strip.strip_meta_tail(same) == (same, []))

    quoted = ('デブライネ、③を基盤へ回す。漏れた原文=\n'
              '「No response requested — this is a backchannel …」\n'
              'これは§4.8違反が出力へ抜けた形だ。')
    _check("引用符の中のマーカーは剥がない", meta_strip.strip_meta_tail(quoted)[0] == quoted)

    tail_quoted = real + '\n「No response requested」を高確度マーカーにする。'
    _check("末尾でも引用なら剥がない", meta_strip.strip_meta_tail(tail_quoted)[0] == tail_quoted)

    bq = real + "\n> No response requested — this is a backchannel"
    _check("引用ブロック(>)は剥がない", meta_strip.strip_meta_tail(bq)[0] == bq)

    fenced = real + "\n```\nNo response requested\n```"
    _check("コードブロックの中は剥がない", meta_strip.strip_meta_tail(fenced)[0] == fenced)

    mid = "No response requested\n" + real
    _check("末尾でないメタは剥がない(真ん中は触らない)",
           meta_strip.strip_meta_tail(mid)[0] == mid)

    jp = real + "\n§4.7に従い、部屋への返信は人事部門へ回す。"
    _check("日本語の規律語だけでは剥がない", meta_strip.strip_meta_tail(jp)[0] == jp)

    # --- fail-open: どんな入力でも例外を投げない --------------------------
    ok = True
    for bad in (None, 123, {"a": 1}, [], "", "   \n  "):
        try:
            meta_strip.strip_meta_tail(bad)
        except Exception:                                  # noqa: BLE001
            ok = False
    _check("壊れた入力でも例外を投げない", ok)
    _check("Noneは空を返す(送信側で失敗扱いになる)",
           meta_strip.strip_meta_tail(None)[0] in ("", None))

    print("\n%d PASS / %d FAIL" % (_PASS, _FAIL))
    return 1 if _FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
