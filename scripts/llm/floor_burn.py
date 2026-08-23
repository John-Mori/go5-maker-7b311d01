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

★★2026-08-23(2回目)ここで**真因の向きが変わった**ので、経緯ごと残す。
  最初は「大書込の便が偏っている=どこか特定の部屋・特定の仕掛けが犯人」と見て探した。
  **外れだった。**実測で潰した仮説は4つ=
    ・キャッシュの寿命切れ  → 大書込のうち300秒超えは 10.0%(普通の便は1.0%)= 主因ではない
    ・圧縮の直後           → 大書込のうち圧縮境界の直後は **0.6%**
    ・サブエージェント      → **2.0%**
    ・特定の部屋           → 改修α12.6 / イージス11.6 / HQ11.1 …と**部屋の忙しさ順に素直に散る**
  ★つまり**どこか1か所が悪いのではなく、全部屋で同じ形で起きている構造の話**だった。

★★そして本命は「量」ではなく**キャッシュの寿命の種別**だった(下の --by ttl)。
  記録の `usage.cache_creation` は書込を2種類に分けて持っている=
    `ephemeral_5m_input_tokens`(5分TTL)  `ephemeral_1h_input_tokens`(1時間TTL)
  実測(08/23・直近24h)= **1時間TTLが 91,461,784 / 5分TTLが 2,053,795 = 書込の97.8%が1時間TTL。**
  ★**1時間TTLの書込は5分TTLより高い**(Anthropicの公表値では 5分=基本の1.25倍 / 1時間=2.0倍)。
  ところが `quota_burn.W_CACHE_CREATE` は**書込を一律1.25で数えている**。
  → 書込側の値段を**過小に見ている**(1.25と2.0の公表値をそのまま当てるなら約58.7%の過小)。
  ★★**この倍率だけは公表価格が正**= 週消費の式を書き換える前に必ず当日の価格表で確かめること
    (ここに書いた 2.0 は"確かめるべき値"であって、俺が測った値ではない。measured と混ぜるな)。
  ★俺が測った値は「97.8%が1時間TTL」の方だ。**そこは実測**。

★何を見ていないか(誤読を防ぐために先に書く)
  `--by dept` は `quota_burn.dept_map`(= `context_watch.jsonl` の全履歴)で引く。
  **載らない便は「?」に落ちる**(サブエージェント・手動セッション)= 実測で3.3%。
  「?」が増えたら割り当ての方を疑え。

使い方:
  python scripts/llm/floor_burn.py                  # 直近24時間
  python scripts/llm/floor_burn.py --hours 168      # 直近1週間
  python scripts/llm/floor_burn.py --big 30000      # 大書込の線を変える
  python scripts/llm/floor_burn.py --by dept        # 大書込を部屋別に割る
  python scripts/llm/floor_burn.py --by ttl         # ★書込を寿命の種別(5分/1時間)で割る
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


def scan_detail(since_utc):
    """`quota_burn.collect` より1段細かく読む= **書込の寿命の種別**と**部屋**まで持って返す。

    なぜ別に読むか= `collect` は `cache_creation_input_tokens`(合計)しか返さないので、
    5分TTLと1時間TTLの内訳が落ちる。**そこが値段の差**なので、ここでは生の記録を読む。
    返す形= [{"sid","dept","dt","cc","cc1h","cc5m","cr","model","sub"}]
    """
    import glob
    import json
    from datetime import datetime as _dt

    dm = q.dept_map()
    out = []
    for p in glob.glob(os.path.join(q.PROJECTS, "**", "*.jsonl"), recursive=True):
        try:
            if os.path.getmtime(p) < since_utc.timestamp():
                continue
        except OSError:
            continue
        sid = os.path.basename(p)[:8]
        dept = dm.get(sid) or "?"
        try:
            fh = open(p, encoding="utf-8", errors="replace")
        except OSError:
            continue
        with fh as f:
            for line in f:
                if len(line) < 3 or '"usage"' not in line:
                    continue
                try:
                    d = json.loads(line)
                except ValueError:
                    continue
                if d.get("type") != "assistant":
                    continue
                msg = d.get("message") or {}
                if str(msg.get("model") or "") == "<synthetic>":
                    continue
                try:
                    dt = _dt.fromisoformat(str(d.get("timestamp")).replace("Z", "+00:00"))
                except (ValueError, AttributeError):
                    continue
                if dt < since_utc:
                    continue
                u = msg.get("usage") or {}
                cd = u.get("cache_creation") or {}
                out.append({
                    "sid": sid, "dept": dept, "dt": dt,
                    "cc": u.get("cache_creation_input_tokens", 0) or 0,
                    "cc1h": cd.get("ephemeral_1h_input_tokens", 0) or 0,
                    "cc5m": cd.get("ephemeral_5m_input_tokens", 0) or 0,
                    "cr": u.get("cache_read_input_tokens", 0) or 0,
                    "model": msg.get("model") or "?",
                    "sub": bool(d.get("isSidechain")),
                })
    return out


def report_ttl(rows):
    """★書込を寿命の種別で割る。ここが値段の芯(1時間TTLは5分TTLより高い)。"""
    h1 = sum(r["cc1h"] for r in rows)
    h5 = sum(r["cc5m"] for r in rows)
    n1 = len([r for r in rows if r["cc1h"]])
    n5 = len([r for r in rows if r["cc5m"]])
    tot = h1 + h5
    print("\n■ キャッシュ書込の寿命の種別(★ここが値段の差)")
    print("  1時間TTL %14d (%4.1f%%)  %6d便" % (h1, pct(h1, tot), n1))
    print("  5分TTL   %14d (%4.1f%%)  %6d便" % (h5, pct(h5, tot), n5))
    print("  ★`quota_burn` は書込を一律 %.2f で数えている。" % q.W_CACHE_CREATE)
    print("    公表価格が『5分=1.25倍 / 1時間=2.0倍』のままなら、書込側を過小に見ていることになる=")
    print("      今の式  (%d+%d)*%.2f = %d" % (h1, h5, q.W_CACHE_CREATE,
                                             int(tot * q.W_CACHE_CREATE)))
    print("      2.0を当てた場合 %d*2.00 + %d*1.25 = %d" % (h1, h5, int(h1 * 2.0 + h5 * 1.25)))
    print("  ★★倍率は**公表価格が正**。この行の 2.0 は確かめるべき値であって、測った値ではない。")


def report_dept(rows, big):
    """★大書込の便を部屋別に割る。『どこか1部屋が犯人』かどうかを見る。"""
    tot = sum(r["cc"] for r in rows)
    sel = [r for r in rows if r["cc"] >= big]
    n = collections.Counter()
    c = collections.Counter()
    for r in sel:
        n[r["dept"]] += 1
        c[r["dept"]] += r["cc"]
    print("\n■ 大書込(>= %d)の部屋別内訳 %d本" % (big, len(sel)))
    for d, v in c.most_common(20):
        print("  %-22s %5d本  書込 %12d (%4.1f%%)" % (d, n[d], v, pct(v, tot)))
    print("  ★部屋の忙しさ順に素直に散っていたら、犯人は特定の部屋ではなく**構造**だ。")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--hours", type=float, default=24)
    ap.add_argument("--big", type=int, default=30000,
                    help="これ以上の cache_creation を「大書込」として扱う")
    ap.add_argument("--by", choices=["dept", "ttl"],
                    help="dept= 大書込を部屋別に割る / ttl= 書込を寿命の種別で割る")
    a = ap.parse_args()

    since = datetime.now(timezone.utc) - timedelta(hours=a.hours)
    if a.by:
        det = scan_detail(since)
        if not det:
            print("直近 %g 時間に記録が無い。" % a.hours)
            return 0
        print("直近 %g 時間 / %d便" % (a.hours, len(det)))
        if a.by == "ttl":
            report_ttl(det)
        else:
            report_dept(det, a.big)
        return 0

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
