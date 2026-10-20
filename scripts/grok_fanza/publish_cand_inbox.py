#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""publish_cand_inbox.py — Grok候補(candidates.jsonl)をアプリの候補一覧の受け箱へ置く(改修β)。

役割:
  grok_fanza_pipe.py が貯めた LocalData/grok_fanza/candidates.jsonl を1本のJSONにまとめ、
  Cloudflare R2(go5-sync-images) の cand_inbox/latest.json へ置く。
  アプリ(candidates.js)は sync-worker の GET /api/cand-inbox で読み、
  一覧・削除済み(墓標)・取り込み済みに無い cid だけを本命タブへ足す。

なぜ wrangler か:
  teian(publish_candidates.py) と同じ。R2への書き込みはアカウント資格で行い、SYNC_TOKEN をPCへ置かない。

使い方:
  python scripts/grok_fanza/publish_cand_inbox.py            # 変換して中身の要約を出すだけ(既定=書かない)
  python scripts/grok_fanza/publish_cand_inbox.py --out x.json  # 変換結果をファイルへ書く(テスト用)
  python scripts/grok_fanza/publish_cand_inbox.py --apply    # R2へ置く(★Chamiの承認後だけ)
"""
import argparse
import datetime
import json
import os
import re
import subprocess
import sys
import tempfile

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
BUCKET = "go5-sync-images"
KEY = "cand_inbox/latest.json"
DEFAULT_SRC = r"D:\SougouStartFolder\LocalData\grok_fanza\candidates.jsonl"
# 元ポスト(根)の画像URLの控え={status_id: [pbs.twimg.com/...]}。一度引いた根は二度引かない。
MEDIA_CACHE = os.path.join(os.path.dirname(DEFAULT_SRC), "root_media.json")

# アプリの cand_items に載せる列。出所の列(acct等)は source/postVerified/sourcePost/sourceImgs だけ持ち込む。
ITEM_FIELDS = ("url", "cid", "title", "author", "thumb", "listPrice", "price", "discountPct", "addedAt")


def jst_now() -> str:
    return (datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(hours=9)).strftime("%Y-%m-%dT%H:%M:%S+09:00")


def load_rows(path: str) -> list:
    rows = []
    with open(path, "r", encoding="utf-8-sig") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                rows.append(json.loads(line))
            except Exception:
                continue  # 壊れ行は飛ばす(追記専用の置き場)
    return rows


def root_media(root_post: str, cache: dict) -> list:
    """元ポストの写真URL(公開埋め込みで取り直す)。アプリはこれを投稿編集の画像として取り込む。
    取れない(墓石・通信失敗)時は空を返し、控えには残さない=次の配信で引き直す。"""
    m = re.search(r"/status/(\d+)", root_post or "")
    if not m:
        return []
    rid = m.group(1)
    if rid in cache:
        return cache[rid]
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from grok_fanza_pipe import fetch_tweet  # 根の確認と同じ取り口(cdn.syndication)
    try:
        tw = fetch_tweet(rid)
    except Exception:
        tw = None
    if not tw:
        return []
    urls = [d.get("media_url_https") for d in tw.get("mediaDetails") or []
            if d.get("type") == "photo" and d.get("media_url_https")]
    cache[rid] = urls
    return urls


def build_doc(rows: list, media_cache: dict = None) -> dict:
    items, seen = [], set()
    for r in rows:
        cid = str(r.get("cid") or "").strip()
        if not cid or cid in seen:
            continue  # 置き場の中でも cid で1件に寄せる(先着)
        seen.add(cid)
        it = {k: r.get(k) for k in ITEM_FIELDS if k in r}
        it["cid"] = cid
        it["source"] = r.get("source") or "grok_fanza"
        it["postVerified"] = r.get("post_verified") is not False
        if r.get("root_post"):
            it["sourcePost"] = r.get("root_post")
            if media_cache is not None:
                imgs = root_media(r.get("root_post"), media_cache)
                if imgs:
                    it["sourceImgs"] = imgs
        if r.get("acct"):
            it["sourceAcct"] = r.get("acct")
        items.append(it)
    return {"ok": True, "generatedAt": jst_now(), "source": "grok_fanza", "items": items}


def put_r2(path: str) -> bool:
    cmd = ["npx", "wrangler", "r2", "object", "put", f"{BUCKET}/{KEY}",
           "--file", path, "--content-type", "application/json", "--remote"]
    r = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8",
                       errors="replace", cwd=ROOT, shell=True)
    ok = "Upload complete" in ((r.stdout or "") + (r.stderr or ""))
    if not ok:
        sys.stderr.write((r.stdout or "") + (r.stderr or "") + "\n")
    return ok


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--src", default=DEFAULT_SRC)
    ap.add_argument("--out", default=None, help="変換結果をこのパスへ書く")
    ap.add_argument("--apply", action="store_true", help="R2 cand_inbox/latest.json へ置く(承認後のみ)")
    args = ap.parse_args()

    if not os.path.exists(args.src):
        sys.stderr.write(f"候補が無い: {args.src}\n")
        return 1
    try:
        with open(MEDIA_CACHE, encoding="utf-8") as f:
            media_cache = json.load(f)
    except (OSError, ValueError):
        media_cache = {}
    doc = build_doc(load_rows(args.src), media_cache)
    try:
        with open(MEDIA_CACHE + ".tmp", "w", encoding="utf-8") as f:
            json.dump(media_cache, f, ensure_ascii=False, indent=1)
        os.replace(MEDIA_CACHE + ".tmp", MEDIA_CACHE)
    except OSError:
        pass
    n = len(doc["items"])
    n_img = sum(1 for it in doc["items"] if it.get("sourceImgs"))
    unv = [it["cid"] for it in doc["items"] if not it["postVerified"]]
    print(f"候補 {n} 件(出所未確認 {len(unv)} 件: {', '.join(unv) or 'なし'}・元ポスト画像あり {n_img} 件)")

    if args.out:
        with open(args.out, "w", encoding="utf-8") as f:
            json.dump(doc, f, ensure_ascii=False)
        print(f"書いた: {args.out}")
    if not args.apply:
        print(f"[dry] R2 {BUCKET}/{KEY} へは置いていない(--apply で置く)")
        return 0

    fd, tmp = tempfile.mkstemp(suffix=".json")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(doc, f, ensure_ascii=False)
        if put_r2(tmp):
            print(f"配信OK: R2 {KEY}({n}件)。アプリの候補タブを開けば取り込まれる。")
            return 0
    finally:
        try:
            os.remove(tmp)
        except OSError:
            pass
    sys.stderr.write("配信に失敗(上のwrangler出力を確認)\n")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
