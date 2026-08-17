#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Geminiの使用量を集計して印字する(2026-08-18 研究室HQ)。

  python scripts/llm/gemini_usage_report.py            # 全期間
  python scripts/llm/gemini_usage_report.py --days 7   # 直近7日(★1週間の判定はこれ)

出るもの= 束(behop/homin)別・用途(tag)別・モデル別の件数と文字数、失敗の内訳。
★「課金すべきか」の判定は **429(quota)の件数** を見る。0なら無料枠は枯れていない=払う理由がない。
"""
import os
import sys
import time
from collections import defaultdict

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import gemini_usage  # noqa: E402

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass


def main():
    days = None
    if "--days" in sys.argv:
        i = sys.argv.index("--days")
        if i + 1 < len(sys.argv):
            days = float(sys.argv[i + 1])

    rows = gemini_usage.read_all()
    if days:
        cutoff = time.time() - days * 86400
        kept = []
        for r in rows:
            try:
                t = time.mktime(time.strptime(r["ts"][:19], "%Y-%m-%dT%H:%M:%S"))
            except Exception:
                continue
            if t >= cutoff:
                kept.append(r)
        rows = kept

    if not rows:
        print(f"記録なし ({gemini_usage.USAGE_FILE})")
        return 0

    print(f"件数 {len(rows)}件" + (f" (直近{days:g}日)" if days else " (全期間)")
          + f" / 記録 {gemini_usage.USAGE_FILE}")
    print(f"期間 {rows[0]['ts']} 〜 {rows[-1]['ts']}")

    def dump(title, keyfn):
        agg = defaultdict(lambda: [0, 0, 0, 0])   # 件数, 成功, 入力字, 出力字
        for r in rows:
            a = agg[keyfn(r)]
            a[0] += 1
            a[1] += 1 if r.get("ok") else 0
            a[2] += r.get("in_chars", 0)
            a[3] += r.get("out_chars", 0)
        print(f"\n--- {title} ---")
        for k, a in sorted(agg.items(), key=lambda kv: -kv[1][0]):
            print(f"  {k or '(空)'}: {a[0]}件 (成功{a[1]}) 入力{a[2]:,}字 出力{a[3]:,}字")

    dump("束(どちらのキー)", lambda r: r.get("who"))
    dump("用途(tag)", lambda r: r.get("tag"))
    dump("モデル", lambda r: r.get("model"))

    errs = defaultdict(int)
    for r in rows:
        if not r.get("ok"):
            errs[r.get("err") or "(不明)"] += 1
    print("\n--- 失敗の内訳 ---")
    if not errs:
        print("  失敗なし")
    for k, n in sorted(errs.items(), key=lambda kv: -kv[1]):
        print(f"  {k}: {n}件")
    # ★2026-08-18 研究室HQ: 429は「失敗した呼び出し」だけを見ても数えられない。
    #   降格ラダーは上の段が429で落ちても下で成功するので、成功行の err(降格の内訳)にも
    #   429が入っている。実測: proが毎回429で落ちているのに、旧集計は 0件 と表示していた。
    quota = sum((r.get("err") or "").count("429") for r in rows)
    demoted = sum(1 for r in rows if r.get("ok") and (r.get("err") or "").strip())
    print(f"\n★無料枠の枯れ(429)= {quota}回 (降格ラダーで空振りした段の数。失敗した呼び出しだけではない)")
    print(f"  うち降格して結局成功= {demoted}件 / 全滅した呼び出し= {sum(1 for r in rows if not r.get('ok'))}件")
    if quota == 0:
        print("  → 枯れていない。課金する理由がまだ無い。")
    else:
        print("  → 上の段(pro)は無料枠で空振りしている。"
              "★ただし『空振りしても下で用が足りている』なら課金の理由にはならない。"
              "全滅した呼び出しの数を見ろ。")
    imgs = sum(r.get("images", 0) for r in rows)
    print(f"★画像を読ませた回数= {imgs}回 (画像はflashでも重い=課金判断の主因になりやすい)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
