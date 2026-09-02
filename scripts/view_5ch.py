#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""view_5ch.py — scrape_5ch.py の出力(local/5ch/threads_<board>_<date>.jsonl)を
広告ゼロのローカルHTMLに整形するビューア(モドリッチ発注msg1544666644813582357)。

なぜ在るか:
  まとめサイト経由だと広告貫通する。5chの subject/dat は scrape_5ch.py が既に
  取っているので、それを勢い降順のまま静的HTMLへ流すだけでよい。新しい取得経路は作らない
  (取得は scrape_5ch.py 一本・このファイルは表示専用)。

使い方:
  python scripts/scrape_5ch.py --board streaming --top 20   # 先にデータを取る
  python scripts/view_5ch.py --board streaming              # local/5ch/viewer_streaming.html を作る
  python scripts/view_5ch.py --board streaming --date 2026-09-02
出力:
  local/5ch/viewer_<board>.html (ローカルのみ・外部リクエスト無し=広告ゼロ)
"""
import argparse
import glob
import html
import json
import os
import re
from datetime import datetime, timezone, timedelta

JST = timezone(timedelta(hours=9))
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
OUT_DIR = os.path.join(ROOT, "local", "5ch")

# 「VTuber×際どい」triage用のソフトハイライト(タイトルに出やすい語)。
# フィルタではなく表示上の目印だけ。成人板は scrape_5ch.py 側で最初から対象外。
HIGHLIGHT_KW = [
    "水着", "際どい", "透け", "エロ", "パンツ", "下着", "セクシー",
    "枕", "枕営業", "整形", "劣化", "変わりすぎ", "別人",
]


def find_input(board, date):
    if date:
        path = os.path.join(OUT_DIR, f"threads_{board}_{date}.jsonl")
        if os.path.exists(path):
            return path
        raise SystemExit(f"見つからない: {path}")
    cands = sorted(glob.glob(os.path.join(OUT_DIR, f"threads_{board}_*.jsonl")))
    if not cands:
        raise SystemExit(f"{board} のデータが無い。先に scrape_5ch.py --board {board} を実行して。")
    return cands[-1]


def load_records(path):
    records = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                records.append(json.loads(line))
    return records


def highlight_tags(title):
    return [kw for kw in HIGHLIGHT_KW if kw in title]


def render_html(board, path, records):
    rows = []
    for r in records:
        tags = highlight_tags(r.get("title", ""))
        tag_html = "".join(f'<span class="tag">{html.escape(t)}</span>' for t in tags)
        rows.append(
            "<tr>"
            f'<td class="num">{r.get("ikioi", 0)}</td>'
            f'<td class="num">{r.get("res", 0)}</td>'
            f'<td class="title"><a href="{html.escape(r.get("url",""))}" target="_blank" rel="noopener">'
            f'{html.escape(r.get("title",""))}</a>{tag_html}</td>'
            f'<td class="fetched">{html.escape(r.get("fetched_at",""))}</td>'
            "</tr>"
        )
    generated = datetime.now(JST).isoformat(timespec="seconds")
    return f"""<!DOCTYPE html>
<html lang="ja"><head><meta charset="utf-8">
<title>5ch勢い順ビューア - {html.escape(board)}</title>
<style>
body{{font-family:sans-serif;background:#0e1422;color:#eee;margin:0;padding:16px}}
h1{{font-size:18px}}
.meta{{color:#9aa;font-size:12px;margin-bottom:12px}}
table{{width:100%;border-collapse:collapse}}
th,td{{padding:6px 8px;border-bottom:1px solid #2a3350;text-align:left;font-size:13px}}
th{{color:#2bb3c0;position:sticky;top:0;background:#0e1422}}
.num{{text-align:right;white-space:nowrap;color:#c8d0e0}}
a{{color:#7fd8e0;text-decoration:none}}
a:hover{{text-decoration:underline}}
.tag{{display:inline-block;margin-left:6px;padding:1px 6px;font-size:11px;border-radius:8px;background:#2a3350;color:#ffd27f}}
</style></head>
<body>
<h1>5ch 勢い順ビューア — {html.escape(board)}板</h1>
<div class="meta">元データ: {html.escape(os.path.basename(path))} / 生成: {generated} / 広告なし・外部通信なし(ローカル完結)</div>
<table>
<thead><tr><th>勢い/日</th><th>レス</th><th>タイトル</th><th>取得時刻</th></tr></thead>
<tbody>
{"".join(rows)}
</tbody>
</table>
</body></html>
"""


def main():
    ap = argparse.ArgumentParser(description="5ch勢い順ローカルビューア")
    ap.add_argument("--board", required=True, help="directory_name(例: streaming)")
    ap.add_argument("--date", help="YYYY-MM-DD(省略時は最新ファイル)")
    args = ap.parse_args()

    path = find_input(args.board, args.date)
    records = load_records(path)
    records.sort(key=lambda r: r.get("ikioi", 0), reverse=True)
    out_html = render_html(args.board, path, records)

    os.makedirs(OUT_DIR, exist_ok=True)
    out_path = os.path.join(OUT_DIR, f"viewer_{args.board}.html")
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(out_html)
    print(f"→ {out_path} ({len(records)}件)")


if __name__ == "__main__":
    main()
