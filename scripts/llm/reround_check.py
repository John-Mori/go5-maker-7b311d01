# -*- coding: utf-8 -*-
"""reround_check — 「同じ依頼の往復が増えていないか」を**計器で**言えるようにする。

★発注(2026-08-29 研究室HQ HQ-0218 便3/3 → イージス研究室)
  「kaizen-analyst を採用。★**投入の前に戻す条件を数字で書け**(推奨= 基準+50%を超えたら即戻す)。
   ★ベースラインは待たなくていい= inbox.db に過去の便が全部あるので遡って計算できる。
   同じ日に『計器を立てる→過去14日で基準値→投入』まで行け。7日待つのは判定だけ。
   ★計器の弱点= 『同一差出人が60分以内に投げ直した率』は**別話題の投げ直しも拾う**。
   → 絶対値で判断するな。**ベースラインとの差だけ**を見ろ。」

★測る量= inbox.db の queue から、ある部屋宛ての便を差出人ごとに時系列に並べ、
  **次の便が同じ差出人から WINDOW 秒以内に来た**ものの割合。
  値そのものに意味は無い(定刻便も雑談も混ざる)。**同じ部屋の前後の差**だけが読める量。

使い方:
  python scripts/llm/reround_check.py --dept kaizen-analyst --days 14
  python scripts/llm/reround_check.py --all --days 14
  python scripts/llm/reround_check.py --dept kaizen-analyst --baseline 14   # 基準値を台帳へ保存
"""
import argparse
import json
import os
import sqlite3
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

DB = os.path.join(ROOT, "local", "queue", "inbox.db")
BASELINE = os.path.join(ROOT, "local", "llm", "reround_baseline.json")
WINDOW = 3600.0            # 「投げ直し」と見なす間隔(秒)= HQ指定の60分


def load(t0, t1, dept=None):
    """[t0, t1) の便を (dept, author, ts) で返す。"""
    con = sqlite3.connect(DB)
    try:
        q = "select dept, body, enqueued_at from queue where enqueued_at >= ? and enqueued_at < ?"
        args = [t0, t1]
        if dept:
            q += " and dept = ?"
            args.append(dept)
        out = []
        for d, b, ts in con.execute(q + " order by enqueued_at", args):
            try:
                j = json.loads(b)
            except ValueError:
                j = {}
            out.append((d, str(j.get("author") or "?"), float(ts)))
        return out
    finally:
        con.close()


def rate(rows, window=WINDOW):
    """(部屋宛ての便数, 投げ直し数, 率%) 。差出人ごとに時系列で見る。"""
    by = {}
    for d, a, ts in rows:
        by.setdefault((d, a), []).append(ts)
    n = re = 0
    for _k, v in by.items():
        v.sort()
        n += len(v)
        for i in range(len(v) - 1):
            if v[i + 1] - v[i] <= window:
                re += 1
    return n, re, (100.0 * re / n if n else 0.0)


def measure(dept, t0, t1, window=WINDOW):
    return rate(load(t0, t1, dept), window)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dept")
    ap.add_argument("--all", action="store_true", help="部屋ごとに一覧で出す")
    ap.add_argument("--days", type=float, default=14.0)
    ap.add_argument("--window", type=float, default=WINDOW)
    ap.add_argument("--baseline", type=float, default=None, metavar="DAYS",
                    help="この日数を基準値として台帳へ保存する(--dept 必須)")
    a = ap.parse_args()

    now = time.time()
    if a.baseline is not None:
        if not a.dept:
            print("--baseline には --dept が要る")
            return 2
        t0 = now - a.baseline * 86400
        n, re, r = measure(a.dept, t0, now, a.window)
        doc = {}
        if os.path.exists(BASELINE):
            try:
                with open(BASELINE, encoding="utf-8-sig") as f:
                    doc = json.load(f)
            except ValueError:
                doc = {}
        doc[a.dept] = {"taken_at": now, "days": a.baseline, "window_sec": a.window,
                       "n": n, "reround": re, "rate_pct": round(r, 2)}
        os.makedirs(os.path.dirname(BASELINE), exist_ok=True)
        tmp = BASELINE + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(doc, f, ensure_ascii=False, indent=1)
        os.replace(tmp, BASELINE)
        print("基準値を保存= %s 過去%g日 / 便 %d・投げ直し %d・**%.2f%%**"
              % (a.dept, a.baseline, n, re, r))
        return 0

    t0 = now - a.days * 86400
    rows = load(t0, now, None if a.all else a.dept)
    if a.all:
        agg = {}
        for d, au, ts in rows:
            agg.setdefault(d, []).append((d, au, ts))
        print("■ 60分以内の投げ直し率 / 過去 %g日(窓 %.0f分)" % (a.days, a.window / 60))
        print("  %-20s %6s %8s %8s" % ("部屋", "便数", "投げ直し", "率"))
        for d, v in sorted(agg.items(), key=lambda x: -len(x[1])):
            n, re, r = rate(v, a.window)
            print("  %-20s %6d %8d %7.1f%%" % (d, n, re, r))
        n, re, r = rate(rows, a.window)
        print("  %-20s %6d %8d %7.1f%%" % ("(全体)", n, re, r))
    else:
        n, re, r = rate(rows, a.window)
        print("%s / 過去%g日= 便 %d・投げ直し %d・**%.2f%%**" % (a.dept, a.days, n, re, r))
    return 0


if __name__ == "__main__":
    sys.exit(main())
