#!/usr/bin/env python3
"""user_events の集計 (操作頻度 + 操作列バイグラム)。

LLMに生ログを読ませないための前処理 (orchestration.md「Python積極利用方針」第1弾)。
生ログN百件 → このスクリプトで要点(Top N)だけに圧縮 → LLMは解釈と提案に集中する。

使い方:
  python scripts/kaizen/summarize_user_events.py [日数]   # 既定=14日
前提: fanza-worker/ で wrangler が動くこと (D1 go5_kaizen)。
出力: 操作頻度Top15 / 画面別件数 / セッション内の操作列バイグラムTop15 / 端末別件数
"""
import collections
import json
import os
import subprocess
import sys

DAYS = int(sys.argv[1]) if len(sys.argv) > 1 else 14
HERE = os.path.dirname(os.path.abspath(__file__))
WORKER_DIR = os.path.normpath(os.path.join(HERE, "..", "..", "fanza-worker"))
SQL = (
    "SELECT created_at, session_id, device_type, screen, action FROM user_events "
    f"WHERE created_at > datetime('now','-{DAYS} days') ORDER BY session_id, created_at;"
)


def fetch_rows():
    cmd = f'npx wrangler d1 execute go5_kaizen --remote --json --command "{SQL}"'
    r = subprocess.run(cmd, capture_output=True, text=True, cwd=WORKER_DIR, shell=True)
    if r.returncode != 0:
        print("wrangler失敗:", (r.stderr or r.stdout)[-500:])
        sys.exit(1)
    # wrangler --json はJSON配列を出力する(先頭にログ行が混ざる場合があるので '[' から切る)
    out = r.stdout
    start = out.find("[")
    data = json.loads(out[start:])
    return data[0].get("results", [])


def main():
    rows = fetch_rows()
    if not rows:
        print(f"直近{DAYS}日のuser_eventsは0件。ログ蓄積を待つ。")
        return
    actions = collections.Counter(r["action"] for r in rows)
    screens = collections.Counter(r["screen"] for r in rows if r.get("screen"))
    devices = collections.Counter(r.get("device_type") or "?" for r in rows)
    sessions = collections.defaultdict(list)
    for r in rows:
        sessions[r["session_id"]].append(r["action"])
    bigrams = collections.Counter()
    for seq in sessions.values():
        for a, b in zip(seq, seq[1:]):
            if a != b:
                bigrams[f"{a} -> {b}"] += 1

    print(f"== user_events 要約 (直近{DAYS}日 / {len(rows)}件 / {len(sessions)}セッション) ==")
    print("\n[操作頻度 Top15]")
    for k, v in actions.most_common(15):
        print(f"  {v:4d}  {k}")
    print("\n[画面別]")
    for k, v in screens.most_common(10):
        print(f"  {v:4d}  {k}")
    print("\n[操作列バイグラム Top15 (この操作の後にこれをする)]")
    for k, v in bigrams.most_common(15):
        print(f"  {v:4d}  {k}")
    print("\n[端末別]")
    for k, v in devices.most_common():
        print(f"  {v:4d}  {k}")


if __name__ == "__main__":
    main()
