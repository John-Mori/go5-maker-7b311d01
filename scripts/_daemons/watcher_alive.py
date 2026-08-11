# -*- coding: utf-8 -*-
"""「回数が減った」報告に、**下がったのか黙ったのか**を分ける1行を付けるための実測器。

なぜ在るか(2026-08-12・イージス研究室 / 発注= 研究室HQ シャビ・アロンソ
DISPATCH-aegis-gl-1786467775846):
  ★**「窓が健康」と「見張りが止まっている」は、回数の少なさとして同じ見え方になる。**
  実測の前例= 2026-07-20 に `go5_lab_revive` が無効化されたまま**丸2日死んだ**。
  あの時もログは静かだった。「静か=平和」と読むと、死んでいる見張りを健康と誤診する。
  → 心がけ(毎回書くようにする)ではなく**機構**にする(共通規律§3)。
    回数を語る時はこれを走らせて、出た1行をそのまま報告へ貼る。

使い方:
  python scripts/_daemons/watcher_alive.py                        # 既定= 研究室の復活見張り
  python scripts/_daemons/watcher_alive.py --log <path> --expect-every-min 10 --window-h 2
  python scripts/_daemons/watcher_alive.py --count-pattern revived  # 「何が減ったのか」も併記

出る物(報告へそのまま貼る1行):
  見張り= 生きている(最終書き込み 2026-08-12 02:02:07 / 0.9分前・直近2時間で12行)
  見張り= ★黙っている(最終書き込み 2026-07-20 14:22:01 / 2880.0分前)= 回数の少なさは健康の証拠にならない
"""
import argparse
import os
import re
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DEFAULT_LOG = os.path.join(ROOT, "local", "_lab_revive.log")
# 行頭の 2026-08-12 01:52:07(JSTで書かれている)
_TS_RE = re.compile(r"^(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})")


def _parse_ts(line):
    m = _TS_RE.match(line or "")
    if not m:
        return None
    try:
        return time.mktime(time.strptime(m.group(1), "%Y-%m-%d %H:%M:%S"))
    except ValueError:
        return None


def measure(log_path, expect_every_min=10, window_h=2, count_pattern=""):
    """戻り値= dict。★読めない/無い時は「分からない」と返す(黙って健康と言わない)。"""
    out = {"log": log_path, "exists": os.path.exists(log_path), "last_ts": None,
           "last_line": "", "age_min": None, "window_lines": 0, "alive": None,
           "hits": None, "total_lines": 0}
    if not out["exists"]:
        return out
    now = time.time()
    cut = now - window_h * 3600
    last_ts = None
    last_line = ""
    win = 0
    hits = 0
    total = 0
    try:
        with open(log_path, encoding="utf-8", errors="replace") as f:
            for line in f:
                line = line.rstrip("\n")
                if not line.strip():
                    continue
                total += 1
                if count_pattern and count_pattern in line:
                    hits += 1
                ts = _parse_ts(line)
                if ts is None:
                    continue
                last_ts, last_line = ts, line
                if ts >= cut:
                    win += 1
    except OSError:
        return out
    out["total_lines"] = total
    out["window_lines"] = win
    out["last_line"] = last_line
    if count_pattern:
        out["hits"] = hits
    if last_ts is None:
        return out
    out["last_ts"] = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(last_ts))
    out["age_min"] = round((now - last_ts) / 60.0, 1)
    # ★判定は「書く間隔の3倍」を超えたら黙っていると見る(1回の取りこぼしで騒がない)。
    out["alive"] = out["age_min"] <= expect_every_min * 3
    return out


def one_line(m, expect_every_min=10, window_h=2):
    if not m["exists"]:
        return "見張り= ★**分からない**(ログが無い: %s)= 回数の少なさは健康の証拠にならない" % m["log"]
    if m["last_ts"] is None:
        return "見張り= ★**分からない**(時刻付きの行が1本も無い: %s)" % m["log"]
    if m["alive"]:
        s = ("見張り= 生きている(最終書き込み %s / %s分前・直近%d時間で%d行)"
             % (m["last_ts"], m["age_min"], window_h, m["window_lines"]))
    else:
        s = ("見張り= ★**黙っている**(最終書き込み %s / %s分前= 想定 %d分おきの3倍超)"
             "= **回数の少なさは健康の証拠にならない**"
             % (m["last_ts"], m["age_min"], expect_every_min))
    if m.get("hits") is not None:
        s += " / 該当行 %d本(全%d行)" % (m["hits"], m["total_lines"])
    return s


def main():
    ap = argparse.ArgumentParser(description="見張りが生きているかを測って1行で出す")
    ap.add_argument("--log", default=DEFAULT_LOG)
    ap.add_argument("--expect-every-min", type=int, default=10, help="見張りが書く間隔(分)")
    ap.add_argument("--window-h", type=int, default=2, help="直近何時間の行数を数えるか")
    ap.add_argument("--count-pattern", default="", help="ついでに数える語(例 revived)")
    a = ap.parse_args()
    m = measure(a.log, a.expect_every_min, a.window_h, a.count_pattern)
    sys.stdout.write(one_line(m, a.expect_every_min, a.window_h) + "\n")
    # ★黙っている時だけ 1 を返す= 呼び出し側が機械で気づける。
    return 0 if m["alive"] else 1


if __name__ == "__main__":
    sys.exit(main())
