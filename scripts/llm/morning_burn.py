# -*- coding: utf-8 -*-
"""朝の定時便が週の消費のどこを占めているかを、日別に測る。

★なぜ要るか(2026-08-23・Chami原文 msg 1540945770922905691)
  「ただ毎朝の定時便がトークン食いまくるならそのやり方を改善して欲しい」
  ——**「食いまくる」が本当かどうかを、誰も測れる形で持っていなかった。**
  週枯渇の対策を「間引く/格下げる」で議論していたが、間引く対象の値段が分かっていない。
  ここが黙って値を出せない限り、どの改善も「効いた」と言えない(共通規律 §4.55)。

★何を測るか
  ①朝の窓(既定 05:00〜09:59 JST)に **何部門が起こされたか**(inbox.db への投函)
  ②その窓で実際に飛んだ **API便の数**と重み付き消費(`quota_burn` と同じ重み)
  ③消費の内訳= 入力 / キャッシュ書込 / キャッシュ読込 / 出力
     ★ここが効く= 床(毎便の固定費)は**キャッシュ読込**なら重み0.1で済むが、
       **キャッシュ書込**は1.25だ。同じ床でも12.5倍値段が違う。
  ④モデル内訳(opus/fable=重み5.0 と sonnet=1.0 では便の値段が5倍違う)

★何を見ていないか(誤読を防ぐために先に書く)
  「起こされた部門数」は投函の数であって、**その部門が何ターン回したか**は分からない。
  連鎖(起きた部門どうしが投げ合う分)は②に入るが、①には出ない。
  つまり①が少ない日に②が高ければ、**それは定時便ではなく連鎖の値段**だ。

使い方:
  python scripts/llm/morning_burn.py                 # 直近7日
  python scripts/llm/morning_burn.py --days 14
  python scripts/llm/morning_burn.py --day 08/23     # その日の内訳を細かく
"""
import argparse
import collections
import json
import os
import sqlite3
import sys
from datetime import datetime, timedelta, timezone

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, HERE)
import quota_burn as q                                   # noqa: E402  重みの正本はあちら

JST = timezone(timedelta(hours=9))
QUEUE_DB = os.path.join(ROOT, "local", "queue", "inbox.db")
MORNING = (5, 9)                                          # 05時〜09時台


def woken(days, lo=MORNING[0], hi=MORNING[1]):
    """朝の窓に投函された便を 日 → {部門: [差出人…]} で返す。"""
    out = collections.defaultdict(lambda: collections.defaultdict(list))
    if not os.path.exists(QUEUE_DB):
        return out
    con = sqlite3.connect(QUEUE_DB)
    try:
        rows = con.execute("SELECT dept, body, enqueued_at FROM queue").fetchall()
    finally:
        con.close()
    floor = datetime.now(JST) - timedelta(days=days)
    for dept, body, ts in rows:
        try:
            dt = datetime.fromtimestamp(float(ts), JST)
        except (TypeError, ValueError):
            continue
        if dt < floor or not (lo <= dt.hour <= hi):
            continue
        try:
            who = (json.loads(body) or {}).get("author") or "?"
        except (ValueError, TypeError):
            who = "?"
        out[dt.strftime("%m/%d")][dept].append(who)
    return out


def burn(days, lo=MORNING[0], hi=MORNING[1]):
    """朝の窓の API便を 日 → 集計 で返す。全日合計も同じ形で持つ。"""
    rows = q.collect(datetime.now(timezone.utc) - timedelta(days=days))
    per = collections.defaultdict(lambda: {"n": 0, "w": 0.0, "in": 0, "cc": 0,
                                           "cr": 0, "out": 0,
                                           "model": collections.Counter()})
    allday = collections.defaultdict(float)               # 日 → その日24hの重み付き
    for r in rows:
        t = r[2].astimezone(JST)
        day = t.strftime("%m/%d")
        w = q.weighted(r)
        allday[day] += w
        if not (lo <= t.hour <= hi):
            continue
        a = per[day]
        a["n"] += 1
        a["w"] += w
        a["in"] += r[3]
        a["cc"] += r[4]
        a["cr"] += r[5]
        a["out"] += r[6]
        a["model"][r[1]] += 1
    return per, allday


def fmt(v):
    return "{:,}".format(int(v))


def main():
    ap = argparse.ArgumentParser(description="朝の定時便の値段を測る")
    ap.add_argument("--days", type=int, default=7)
    ap.add_argument("--day", default=None, help="MM/DD。その日の内訳を細かく出す")
    ap.add_argument("--from-hour", type=int, default=MORNING[0])
    ap.add_argument("--to-hour", type=int, default=MORNING[1])
    a = ap.parse_args()

    wk = woken(a.days, a.from_hour, a.to_hour)
    per, allday = burn(a.days, a.from_hour, a.to_hour)

    total_all = sum(allday.values())
    total_morning = sum(v["w"] for v in per.values())
    print("朝の窓 %02d:00〜%02d:59 JST / 直近%d日" % (a.from_hour, a.to_hour, a.days))
    print("期間の総消費(重み付き) %s / うち朝の窓 %s = **%.1f%%**\n"
          % (fmt(total_all), fmt(total_morning),
             100.0 * total_morning / total_all if total_all else 0.0))

    print("日付   起こされた部門  API便   重み付き        その日全体に占める朝の割合")
    for day in sorted(set(list(per) + list(wk))):
        v = per.get(day) or {"n": 0, "w": 0.0}
        share = 100.0 * v["w"] / allday[day] if allday.get(day) else 0.0
        print("%s      %2d部門     %5d  %14s   %5.1f%%"
              % (day, len(wk.get(day, {})), v["n"], fmt(v["w"]), share))

    if a.day:
        d = a.day
        v = per.get(d)
        print("\n=== %s の内訳 ===" % d)
        if not v:
            print("  (この日のAPI便が無い)")
            return 0
        raw = v["in"] * q.W_IN + v["cc"] * q.W_CACHE_CREATE + \
            v["cr"] * q.W_CACHE_READ + v["out"] * q.W_OUT
        for lab, key, w in (("入力(新規)", "in", q.W_IN),
                            ("キャッシュ書込", "cc", q.W_CACHE_CREATE),
                            ("キャッシュ読込", "cr", q.W_CACHE_READ),
                            ("出力", "out", q.W_OUT)):
            share = 100.0 * v[key] * w / raw if raw else 0.0
            print("  %-8s 素 %13s × 重み%.2f = %13s  (%.1f%%)"
                  % (lab, fmt(v[key]), w, fmt(v[key] * w), share))
        print("  1便あたり: 書込 %s / 読込 %s / 出力 %s"
              % (fmt(v["cc"] / v["n"]), fmt(v["cr"] / v["n"]), fmt(v["out"] / v["n"])))
        print("  モデル内訳: %s" % ", ".join(
            "%s %d便" % (m, c) for m, c in v["model"].most_common()))
        print("\n  起こされた部門と差出人:")
        for dept, whos in sorted(wk.get(d, {}).items()):
            print("    %-16s %s" % (dept, ", ".join(sorted(set(whos)))[:90]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
