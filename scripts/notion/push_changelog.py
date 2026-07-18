#!/usr/bin/env python3
"""改修履歴ビューをNotionへ一方向push(コンテキスト永続化設計書§4-2)。

前提:
- 正本はgit。`build_changelog.py` が作る `local/history/改修履歴_YYYY-MM.md` は使い捨てビュー。
- Notion側も「窓」であって保管先ではない。**一方向push**(Notion側の編集は次回pushで消える。
  同名の月ページはアーカイブ(ゴミ箱・30日復元可)して作り直す=ビューは使い捨ての思想どおり)。
- キーは local/notion_api_key.txt(gitignore配下)。**キーを出力・ログ・コミットしない。**
- 依存ゼロ(標準ライブラリのみ)。notion-sdk-pyすら入れない(この用途はHTTP4本で足りる)。

使い方:
  python scripts/notion/push_changelog.py                # 今月分
  python scripts/notion/push_changelog.py --month 2026-07
親ページ(「…改修履歴」・コネクト接続済み)はsearchで自動発見。月ごとに子ページを作る。
"""
import argparse
import datetime as dt
import io
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.normpath(os.path.join(HERE, "..", ".."))
KEY_FILE = os.path.join(ROOT, "local", "notion_api_key.txt")
HISTORY_DIR = os.path.join(ROOT, "local", "history")
API = "https://api.notion.com/v1"
NV = "2022-06-28"
PARENT_QUERY = "改修履歴"   # 親ページ名の検索語(コネクト接続済みページ)
MAX_TEXT = 1990             # Notionのrich_text 1要素は2000字上限
BATCH = 100                 # blocks.children.append は1回100ブロック上限


def _key():
    return io.open(KEY_FILE, encoding="utf-8-sig").read().strip()


def call(method, path, body=None):
    req = urllib.request.Request(
        API + path, method=method,
        data=json.dumps(body).encode() if body is not None else None,
        headers={"Authorization": "Bearer " + _key(), "Notion-Version": NV,
                 "Content-Type": "application/json"})
    for attempt in range(4):
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                return json.loads(r.read())
        except urllib.error.HTTPError as e:
            if e.code == 429 and attempt < 3:   # rate limit → Retry-Afterに従う
                time.sleep(float(e.headers.get("Retry-After", "1")) + 0.2)
                continue
            raise RuntimeError(f"Notion API {e.code}: {e.read()[:300]}") from e


def rich(text):
    return [{"type": "text", "text": {"content": text[:MAX_TEXT]}}]


def md_to_blocks(md_text):
    """月次ビューmd→Notionブロック(単純変換。見出し/箇条書き/段落のみ=ビューには十分)。"""
    blocks = []
    for line in md_text.splitlines():
        s = line.rstrip()
        if not s.strip():
            continue
        if s.startswith("# "):
            blocks.append({"type": "heading_1", "heading_1": {"rich_text": rich(s[2:])}})
        elif s.startswith("## "):
            blocks.append({"type": "heading_2", "heading_2": {"rich_text": rich(s[3:])}})
        elif s.startswith("### "):
            blocks.append({"type": "heading_3", "heading_3": {"rich_text": rich(s[4:])}})
        elif s.startswith("    - "):
            blocks.append({"type": "bulleted_list_item",
                           "bulleted_list_item": {"rich_text": rich("└ " + s[6:])}})
        elif s.startswith("- "):
            blocks.append({"type": "bulleted_list_item",
                           "bulleted_list_item": {"rich_text": rich(s[2:])}})
        else:
            blocks.append({"type": "paragraph", "paragraph": {"rich_text": rich(s)}})
    return blocks


def find_parent():
    d = call("POST", "/search", {"query": PARENT_QUERY,
                                 "filter": {"value": "page", "property": "object"}})
    for p in d.get("results", []):
        title = "".join(t.get("plain_text", "")
                        for t in p.get("properties", {}).get("title", {}).get("title", []))
        if PARENT_QUERY in title and p.get("parent", {}).get("type") != "page_id":
            return p["id"], title, p.get("url")
    # workspace直下でなくても、タイトル一致の先頭を親として使う
    for p in d.get("results", []):
        title = "".join(t.get("plain_text", "")
                        for t in p.get("properties", {}).get("title", {}).get("title", []))
        if PARENT_QUERY in title:
            return p["id"], title, p.get("url")
    raise RuntimeError("親ページが見つからない(コネクトがページに接続されているか確認)")


def find_child(parent_id, title):
    """親ページ直下の子ページから同名を探す(再pushでの重複防止)。"""
    cursor = None
    while True:
        path = f"/blocks/{parent_id}/children?page_size=100" + (f"&start_cursor={cursor}" if cursor else "")
        d = call("GET", path)
        for b in d.get("results", []):
            if b.get("type") == "child_page" and b["child_page"].get("title") == title:
                return b["id"]
        if not d.get("has_more"):
            return None
        cursor = d.get("next_cursor")


def main():
    ap = argparse.ArgumentParser(description="改修履歴ビューのNotion一方向push")
    ap.add_argument("--month", default=dt.date.today().strftime("%Y-%m"))
    args = ap.parse_args()

    src = os.path.join(HISTORY_DIR, f"改修履歴_{args.month}.md")
    if not os.path.exists(src):
        print(f"ビューが無い: {src} (先に build_changelog.py --month {args.month})")
        return 1
    md = io.open(src, encoding="utf-8").read()
    blocks = md_to_blocks(md)
    title = f"改修履歴 {args.month}"

    parent_id, parent_title, parent_url = find_parent()
    print(f"親ページ: {parent_title}")

    old = find_child(parent_id, title)
    if old:
        call("PATCH", f"/blocks/{old}", {"archived": True})
        print(f"既存の「{title}」をアーカイブ(ゴミ箱・30日復元可)して作り直す")

    page = call("POST", "/pages", {
        "parent": {"page_id": parent_id},
        "properties": {"title": {"title": rich(title)}},
        "children": blocks[:BATCH]})
    page_id = page["id"]
    sent = min(len(blocks), BATCH)
    while sent < len(blocks):
        call("PATCH", f"/blocks/{page_id}/children", {"children": blocks[sent:sent + BATCH]})
        sent += min(BATCH, len(blocks) - sent)
        print(f"  …{sent}/{len(blocks)}ブロック")
        time.sleep(0.35)  # 3req/s制限に余裕を持つ

    print(f"push完了: 「{title}」 {len(blocks)}ブロック")
    print(f"URL: {page.get('url')}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
