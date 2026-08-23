# -*- coding: utf-8 -*-
"""床(毎便の固定費)の**キャッシュ書込**がどこで作られているかを測る。

★なぜ要るか(2026-08-23・研究室HQ msg 1540949449638019122 の■3=イージス研究室へ正式発注)
  HQの実測= 8/23の朝は キャッシュ書込 42.8% / 読込 35.8% / 出力 21.4%。
  **同じ1トークンでも 書込は重み1.25・読込は0.10=12.5倍高い。**だから書込側から入る。
  ところが「書込がどの便で起きているか」を誰も持っていなかった。
  `quota_burn` は部門別・モデル別までしか割れず、`morning_burn` は朝の窓しか見ない。
  ★**入口が分からないまま床を削ると、削った所と高い所が別になる。**

★何を測るか
  ①便ごとの cache_creation の分布(どのバケツが書込の何%を作っているか)
  ②大書込の便が「セッションの初回」か「継続の途中」か
    → 初回なら床の初回書込=避けられない。継続なら**前置きが毎回動いている**=直せる。
  ③その便の cache_read(直前の便と比べて激減していれば「前の方が変わって以降を全部書き直した」)
  ④前便からの経過秒(5分のキャッシュ寿命切れなのか、そうでないのか)

★何を見ていないか(誤読を防ぐために先に書く)
  ここは**どの部屋の便か**を割らない(記録の1行に部門名が無い=`quota_burn.dept_map` は
  セッションIDの対応表であって、サブエージェントや手動セッションは載らない)。
  「940便が書込の76%」までは言えるが、「その940便が誰か」はここでは言えない。
  ★次の一手はそこ= 大書込の便を部屋と便の種類まで割ること。

使い方:
  python scripts/llm/floor_burn.py                  # 直近24時間
  python scripts/llm/floor_burn.py --hours 168      # 直近1週間
  python scripts/llm/floor_burn.py --big 30000      # 大書込の線を変える
"""
import argparse
import collections
import os
import statistics
import sys
from datetime import datetime, timedelta, timezone

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import quota_burn as q                                   # noqa: E402  重みと収集の正本はあちら

# 便あたり cache_creation の分布を見るバケツ(上限は開区間)
BUCKETS = [(0, 1), (1, 2000), (2000, 10000), (10000, 30000),
           (30000, 60000), (60000, 10 ** 9)]
# 前便からの経過秒のバケツ。★300秒= キャッシュの寿命(既定5分)の目安。
#   ここを跨いだ書込なら「寿命切れ」、跨がない書込なら「前置きが動いた」だ。
GAPS = [(0, 60), (60, 300), (300, 900), (900, 3600), (3600, 10 ** 9)]


def by_session(rows):
    """(sid → 時刻順の便)。quota_burn.collect の行は (sid, model, dt, in, cc, cr, out)。"""
    out = collections.defaultdict(list)
    for r in rows:
        out[r[0]].append(r)
    for rs in out.values():
        rs.sort(key=lambda r: r[2])
    return out


def pct(a, b):
    return 100.0 * a / b if b else 0.0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--hours", type=float, default=24)
    ap.add_argument("--big", type=int, default=30000,
                    help="これ以上の cache_creation を「大書込」として扱う")
    a = ap.parse_args()

    since = datetime.now(timezone.utc) - timedelta(hours=a.hours)
    rows = q.collect(since)
    if not rows:
        print("直近 %g 時間に記録が無い。" % a.hours)
        return 0

    cc = sum(r[4] for r in rows)
    cr = sum(r[5] for r in rows)
    ses = by_session(rows)
    print("直近 %g 時間 / %d便 / %dセッション" % (a.hours, len(rows), len(ses)))
    print("  キャッシュ書込 %d (重み%.2f → %d) / 読込 %d (重み%.2f → %d)"
          % (cc, q.W_CACHE_CREATE, int(cc * q.W_CACHE_CREATE),
             cr, q.W_CACHE_READ, int(cr * q.W_CACHE_READ)))

    print("\n■ 便あたり書込の分布(どのバケツが書込を作っているか)")
    for lo, hi in BUCKETS:
        sel = [r for r in rows if lo <= r[4] < hi]
        s = sum(r[4] for r in sel)
        print("  %7d〜%-10s : %6d便 (%4.1f%%)  書込 %12d (%4.1f%%)"
              % (lo, ("%d" % hi) if hi < 10 ** 9 else "上限なし",
                 len(sel), pct(len(sel), len(rows)), s, pct(s, cc)))

    big, first_cc, cont_cc, nf, nc = [], 0, 0, 0, 0
    gapbuf = []
    for sid, rs in ses.items():
        for i, r in enumerate(rs):
            if i == 0:
                nf += 1
                first_cc += r[4]
            else:
                nc += 1
                cont_cc += r[4]
            if r[4] >= a.big:
                big.append(r)
                gapbuf.append((None if i == 0 else (r[2] - rs[i - 1][2]).total_seconds(), r))

    print("\n■ 初回か、継続か(★ここが判定の芯)")
    print("  セッション初回 %5d便  書込 %12d (%4.1f%%)  ← 床の初回書込=避けられない分"
          % (nf, first_cc, pct(first_cc, cc)))
    print("  継続の途中     %5d便  書込 %12d (%4.1f%%)  ← ここが大きいなら前置きが毎回動いている"
          % (nc, cont_cc, pct(cont_cc, cc)))

    if not big:
        print("\n大書込(>= %d)の便は無い。" % a.big)
        return 0

    bcc = sum(r[4] for r in big)
    print("\n■ 大書込(>= %d)の便 %d本= 全便の %.1f%% で、書込の %.1f%% を作っている"
          % (a.big, len(big), pct(len(big), len(rows)), pct(bcc, cc)))
    oth = [r for r in rows if r[4] < a.big]
    print("  書込  中央値 %8d / 平均 %8d / 最大 %8d"
          % (statistics.median(r[4] for r in big),
             bcc // len(big), max(r[4] for r in big)))
    print("  読込  中央値 %8d   ←★普通の便の読込中央値 %8d と比べる。"
          % (statistics.median(r[5] for r in big),
             statistics.median(r[5] for r in oth) if oth else 0))
    print("        大書込の便でここが**激減**していたら、前置きの「前の方」が変わって")
    print("        以降を丸ごと書き直している=床の総量ではなく**前置きの安定性**が真因だ。")
    print("  丸ごと書き直し(読込<1000)の便: %d本 (%.1f%%)"
          % (len([r for r in big if r[5] < 1000]),
             pct(len([r for r in big if r[5] < 1000]), len(big))))

    print("\n■ 大書込の便は、前便からどれだけ空いていたか(寿命切れかどうか)")
    for lo, hi in GAPS:
        sel = [(g, r) for g, r in gapbuf if g is not None and lo <= g < hi]
        print("  %5d〜%-8s秒 : %5d便 (%4.1f%%)  書込 %12d"
              % (lo, ("%d" % hi) if hi < 10 ** 9 else "上限なし",
                 len(sel), pct(len(sel), len(big)), sum(r[4] for _, r in sel)))
    fs = [(g, r) for g, r in gapbuf if g is None]
    print("  セッション初回   : %5d便 (%4.1f%%)  書込 %12d"
          % (len(fs), pct(len(fs), len(big)), sum(r[4] for _, r in fs)))
    print("  ★300秒より内側に固まっていたら、寿命切れではない=**前置きが動いている**。")

    print("\n■ 大書込の便のモデル内訳(重み5.0のopus系なら値段はさらに5倍)")
    m = collections.Counter()
    mc = collections.Counter()
    for r in big:
        m[r[1]] += 1
        mc[r[1]] += r[4]
    for k, v in m.most_common():
        print("  %-28s %5d便  書込 %12d" % (k, v, mc[k]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
