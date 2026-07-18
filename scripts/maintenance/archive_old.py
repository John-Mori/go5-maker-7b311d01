#!/usr/bin/env python3
"""日次生成物の月次アーカイブ + ログ肥大の可視化(恒久解C2・安全版)。

解く問題(P3-1): ログ・台帳が追記のみで無限成長する。

★安全のため対象を限定する★
  触るのは「data-orgが単独で書く日次生成物」だけ(reflect/ と reports/ の YYYY-MM-DD.md)。
  - 常駐が握るログ(discord_watchdog.log 等)は触らない = 書き込み中の常駐を壊すため。
    複数プロセスが書くログのローテーションは concurrent-log-handler での常駐側改修(=改修の領分)。
  - 共有の処理済み台帳(discord_processed.jsonl 等)も触らない = 他部門が追記中でレースになる。
    これは恒久解A(SQLiteメッセージバス)が入れば台帳自体が消えるので、それ待ちが正しい。

アーカイブ = 削除ではない。Nヶ月より古いファイルを local/archive/YYYY-MM/ へ「移動」する
(データは失わず、置き場所を hot から cold へ移すだけ)。同一ドライブなので os.replace でアトミック。

肥大の可視化は読むだけ(完全に安全)。閾値超えのファイルを列挙して「改修へ渡すべき対象」を示す。

使い方:
  python scripts/maintenance/archive_old.py            # ドライラン(何が起きるか見るだけ)
  python scripts/maintenance/archive_old.py --go       # 実行
  python scripts/maintenance/archive_old.py --months 1 --go
"""
import argparse
import datetime as dt
import os
import re
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.normpath(os.path.join(HERE, "..", ".."))
LOCAL = os.path.join(ROOT, "local")
ARCHIVE = os.path.join(LOCAL, "archive")

# data-org単独管理の日次生成物のみ(YYYY-MM-DD.md)。ここ以外は触らない。
ARCHIVE_DIRS = [
    os.path.join(LOCAL, "llm", "reflect"),
    os.path.join(LOCAL, "llm", "reports"),
]
DATED = re.compile(r"^(\d{4})-(\d{2})-(\d{2})\.")

# 肥大の可視化。触らない(読むだけ)。閾値超えは「改修/恒久解Aへ渡すべき」印。
BLOAT_THRESHOLD = 1_000_000  # 1MB


def months_ago(y, m, d, months):
    now = dt.date.today()
    cutoff_month = now.year * 12 + now.month - months
    file_month = y * 12 + m
    return file_month <= cutoff_month


def do_archive(months, go):
    moved = []
    for d in ARCHIVE_DIRS:
        if not os.path.isdir(d):
            continue
        for fn in sorted(os.listdir(d)):
            m = DATED.match(fn)
            if not m:
                continue
            y, mo, day = int(m.group(1)), int(m.group(2)), int(m.group(3))
            if not months_ago(y, mo, day, months):
                continue
            dest_dir = os.path.join(ARCHIVE, f"{y:04d}-{mo:02d}")
            src = os.path.join(d, fn)
            dest = os.path.join(dest_dir, os.path.basename(d) + "_" + fn)
            moved.append((src, dest))
            if go:
                os.makedirs(dest_dir, exist_ok=True)
                os.replace(src, dest)
    return moved


def scan_bloat():
    big = []
    for root, _dirs, files in os.walk(LOCAL):
        if os.path.join(LOCAL, "archive") in root:
            continue
        for fn in files:
            p = os.path.join(root, fn)
            try:
                sz = os.path.getsize(p)
            except OSError:
                continue
            if sz >= BLOAT_THRESHOLD:
                big.append((sz, os.path.relpath(p, ROOT)))
    big.sort(reverse=True)
    return big


def main():
    ap = argparse.ArgumentParser(description="日次生成物の月次アーカイブ+肥大可視化(安全版)")
    ap.add_argument("--months", type=int, default=3, help="Nヶ月より古い日次生成物を退避(既定3)")
    ap.add_argument("--go", action="store_true", help="実際に移動する(既定はドライラン)")
    args = ap.parse_args()

    moved = do_archive(args.months, args.go)
    verb = "移動した" if args.go else "移動する(ドライラン)"
    print(f"=== アーカイブ: {len(moved)}件を {verb} (>{args.months}ヶ月・reflect/reports のみ)")
    for src, dest in moved[:20]:
        print(f"  {os.path.relpath(src, ROOT)} → {os.path.relpath(dest, ROOT)}")

    print(f"\n=== 肥大の可視化(>{BLOAT_THRESHOLD // 1000}KB・読むだけ・触らない):")
    big = scan_bloat()
    if not big:
        print("  なし")
    for sz, rel in big[:15]:
        note = ""
        if rel.endswith(".log"):
            note = " ← 常駐ログ=改修の領分(concurrent-log-handler)"
        elif "processed" in rel or "inbox" in rel:
            note = " ← 共有台帳=恒久解A(バス)で解消"
        print(f"  {sz/1000:8.0f}KB  {rel}{note}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
