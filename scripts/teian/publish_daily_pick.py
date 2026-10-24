#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""publish_daily_pick.py — 5S部門の「今日のおすすめ」JSONをアプリの帯へ届ける(改修β・設計 2026-10-24 §1)。

役割:
  5S部門の 06:00 便が出した LocalData/fivesec/daily_pick_YYYYMMDD.json を Cloudflare R2(go5-sync-images)
  へ置く。置き先=daily_pick/<date>.json と daily_pick/latest.json の2キー。
  アプリの動画作成タブは sync-worker の GET /api/daily-pick/latest で当日分を取り込む(トークン必須の読み取り口)。

フック画像:
  doujin-assets.dmm.co.jp の直リンクはブラウザから canvas へ載せる時に CORS で落ちうる。
  hook.url の画像をここで落として sha256 名で同バケットへ置き、JSON の hook.r2_key に入れる
  (sync-worker の GET /img/:key はトークン不要で配信済みの既存口)。落とせなければ r2_key は空のまま=url を使う。

なぜ wrangler か:
  publish_candidates.py と同じ。R2への書き込みは wrangler(=アカウント資格情報)で行い、SYNC_TOKEN をPCへ置かない。

使い方:
  python scripts/teian/publish_daily_pick.py            # 今日(JST)のおすすめを配信
  python scripts/teian/publish_daily_pick.py --date 2026-10-24
  python scripts/teian/publish_daily_pick.py --dry-run  # コマンドを表示するだけ

受け入れ:
  実行後に `npx wrangler r2 object get go5-sync-images/daily_pick/latest.json --remote --pipe` で中身が返れば着地。
"""
import argparse
import datetime
import hashlib
import json
import os
import subprocess
import sys
import tempfile
import urllib.request

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
BUCKET = "go5-sync-images"
SRC_DIR = r"D:\SougouStartFolder\LocalData\fivesec"
MIN_ITEMS = 3


def jst_today() -> str:
    return (datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(hours=9)).strftime("%Y-%m-%d")


def guard_not_empty(doc: dict) -> list:
    """空配信ガード。items が3件未満、または題名案(titles)が空の作品があれば理由を返す。
    返り値が空リスト=配信OK。"""
    items = doc.get("items")
    if not isinstance(items, list):
        return ["items が無い"]
    bad = []
    if len(items) < MIN_ITEMS:
        bad.append(f"items が {len(items)} 件(最低 {MIN_ITEMS} 件)")
    for it in items:
        cid = (it or {}).get("cid") or "?"
        titles = (it or {}).get("titles") or []
        if not any(isinstance(t, dict) and str(t.get("text") or "").strip() for t in titles):
            bad.append(f"{cid}(titles が空)")
        if not (it or {}).get("work_url"):
            bad.append(f"{cid}(work_url が空)")
    return bad


def run(cmd: list, dry: bool) -> bool:
    if dry:
        print("  [dry] " + " ".join(cmd))
        return True
    r = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8",
                       errors="replace", cwd=ROOT, shell=True)
    ok = "Upload complete" in ((r.stdout or "") + (r.stderr or ""))
    if not ok:
        sys.stderr.write((r.stdout or "") + (r.stderr or "") + "\n")
    return ok


def put_r2(key: str, path: str, content_type: str, dry: bool) -> bool:
    return run(["npx", "wrangler", "r2", "object", "put", f"{BUCKET}/{key}",
                "--file", path, "--content-type", content_type, "--remote"], dry)


def mirror_hook(item: dict, tmpdir: str, dry: bool) -> str:
    """hook.url を落として sha256 名で R2 へ置く。返り値=r2_key(失敗は空)。"""
    hook = item.get("hook") or {}
    url = str(hook.get("url") or "")
    if not url.startswith("https://"):
        return ""
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (go5 daily_pick publisher)"})
        with urllib.request.urlopen(req, timeout=30) as res:
            ct = res.headers.get("Content-Type") or "image/jpeg"
            data = res.read()
    except Exception as e:
        sys.stderr.write(f"  フック画像を落とせず({item.get('cid')}): {e}\n")
        return ""
    if not ct.startswith("image/") or len(data) < 1024:
        sys.stderr.write(f"  フック画像が画像でない({item.get('cid')}): {ct} {len(data)}B\n")
        return ""
    key = hashlib.sha256(data).hexdigest()
    p = os.path.join(tmpdir, key)
    with open(p, "wb") as f:
        f.write(data)
    return key if put_r2(key, p, ct, dry) else ""


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", default=None, help="YYYY-MM-DD(既定=今日JST)")
    ap.add_argument("--src", default=None, help="入力JSON(既定=LocalData/fivesec/daily_pick_YYYYMMDD.json)")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--force", action="store_true", help="空配信ガードを無視して上げる")
    args = ap.parse_args()

    date = args.date or jst_today()
    src = args.src or os.path.join(SRC_DIR, f"daily_pick_{date.replace('-', '')}.json")
    if not os.path.exists(src):
        sys.stderr.write(f"おすすめJSONが無い: {src}\n(5S部門の06:00便で md と同じ内容の JSON を出してから)\n")
        return 1
    try:
        with open(src, "r", encoding="utf-8") as f:
            doc = json.load(f)
    except Exception as e:
        sys.stderr.write(f"おすすめJSONが読めない: {e}\n")
        return 1

    bad = guard_not_empty(doc)
    if bad and not args.force:
        sys.stderr.write("配信を止めた(空配信ガード)。このままだと帯に空のカードが出る:\n"
                         + "\n".join(f"  - {b}" for b in bad)
                         + "\nJSON を直すか、どうしても上げるなら --force。\n")
        return 2
    if bad and args.force:
        sys.stderr.write("[force] 欠けたまま配信する: " + ", ".join(bad) + "\n")

    doc["date"] = doc.get("date") or date
    doc["published_at"] = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    with tempfile.TemporaryDirectory() as tmpdir:
        for it in doc.get("items") or []:
            hook = it.setdefault("hook", {})
            if not hook.get("r2_key"):
                hook["r2_key"] = mirror_hook(it, tmpdir, args.dry_run)
        out = os.path.join(tmpdir, "daily_pick.json")
        with open(out, "w", encoding="utf-8") as f:
            json.dump(doc, f, ensure_ascii=False)
        ok1 = put_r2(f"daily_pick/{date}.json", out, "application/json", args.dry_run)
        ok2 = put_r2("daily_pick/latest.json", out, "application/json", args.dry_run)
    if ok1 and ok2:
        keys = [(it.get("cid"), bool((it.get("hook") or {}).get("r2_key"))) for it in doc.get("items") or []]
        print(f"配信OK: {date} → R2 daily_pick/{date}.json + daily_pick/latest.json")
        print("フック画像 R2: " + ", ".join(f"{c}={'有' if k else '無(url直)'}" for c, k in keys))
        return 0
    sys.stderr.write("配信に失敗(上のwrangler出力を確認)\n")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
