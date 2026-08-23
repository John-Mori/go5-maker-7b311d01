#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""publish_candidates.py — 当日の提案候補JSONをスマホから開けるよう配信する(改修α)。

役割:
  軍議(PC)が生成した local/teian/candidates_<date>.json を Cloudflare R2(go5-sync-images)
  へ置く。置き先=teian/<date>.json と teian/latest.json の2キー。
  スマホの提案決定ページ(KouhoTeian.html)は sync-worker の GET /api/teian/latest で
  当日分を取り込む(トークン必須の読み取り口)。

なぜ wrangler か:
  R2への書き込みは wrangler(=アカウント資格情報)で行い、SYNC_TOKEN をPCへ置かない。
  migrate_avatars_to_r2.py と同じ経路。読み取りだけ worker がトークンで守る。

使い方:
  python scripts/teian/publish_candidates.py            # 今日(JST)の候補を配信
  python scripts/teian/publish_candidates.py --date 2026-08-23
  python scripts/teian/publish_candidates.py --dry-run  # コマンドを表示するだけ

受け入れ:
  実行後に `npx wrangler r2 object get go5-sync-images/teian/latest.json --remote` で中身が返れば着地。
"""
import argparse
import datetime
import json
import os
import subprocess
import sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
BUCKET = "go5-sync-images"


def jst_today() -> str:
    return (datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(hours=9)).strftime("%Y-%m-%d")


def guard_not_empty(path: str) -> list:
    """空配信ガード(C-038)。④comments か room_comments が欠けた候補の cid を返す。
    ★候補JSONが再生成されると comments=[]・room_comments無しに戻る=vision/軍議を通す前に
      publish すると空のページが客先へ出る(2026-08-23の寸前事故)。空なら止める。
    返り値が空リスト=全候補OK。中身有り=その cid が未充填。"""
    try:
        with open(path, "r", encoding="utf-8") as f:
            doc = json.load(f)
    except Exception as e:
        return [f"__読めず__:{e}"]
    bad = []
    for c in doc.get("candidates", []):
        cid = c.get("cid") or c.get("id") or "?"
        comments = c.get("comments")
        rc = c.get("room_comments")
        rc_ok = isinstance(rc, dict) and bool(rc.get("mitoma")) and bool(
            (rc.get("main") or {}).get("text") if isinstance(rc.get("main"), dict) else rc.get("main"))
        if not comments or not rc_ok:
            miss = []
            if not comments:
                miss.append("④comments")
            if not rc_ok:
                miss.append("room_comments")
            bad.append(f"{cid}({'/'.join(miss)})")
    return bad


def put_r2(key: str, path: str, dry: bool) -> bool:
    cmd = ["npx", "wrangler", "r2", "object", "put", f"{BUCKET}/{key}",
           "--file", path, "--content-type", "application/json", "--remote"]
    if dry:
        print("  [dry] " + " ".join(cmd))
        return True
    r = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8",
                       errors="replace", cwd=ROOT, shell=True)
    ok = "Upload complete" in ((r.stdout or "") + (r.stderr or ""))
    if not ok:
        sys.stderr.write((r.stdout or "") + (r.stderr or "") + "\n")
    return ok


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", default=None, help="YYYY-MM-DD(既定=今日JST)")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--force", action="store_true",
                    help="空配信ガードを無視して上げる(④comments/room_comments が空でも配信)")
    args = ap.parse_args()

    date = args.date or jst_today()
    src = os.path.join(ROOT, "local", "teian", f"candidates_{date}.json")
    if not os.path.exists(src):
        sys.stderr.write(f"候補JSONが無い: {src}\n(先に candidates_json.py で生成してから)\n")
        return 1

    bad = guard_not_empty(src)
    if bad and not args.force:
        sys.stderr.write(
            "配信を止めた(空配信ガード C-038)。次の候補が未充填のまま=客先に空ページが出る:\n"
            + "\n".join(f"  - {b}" for b in bad)
            + "\n先に vision_comments.py(④comments)と軍議(room_comments)を通すか、"
              "どうしても上げるなら --force。\n")
        return 2
    if bad and args.force:
        sys.stderr.write("[force] 空のまま配信する: " + ", ".join(bad) + "\n")

    ok1 = put_r2(f"teian/{date}.json", src, args.dry_run)
    ok2 = put_r2("teian/latest.json", src, args.dry_run)
    if ok1 and ok2:
        print(f"配信OK: {date} → R2 teian/{date}.json + teian/latest.json")
        print("スマホの提案決定ページ(KouhoTeian.html)を開けば当日分が自動で載ります。")
        return 0
    sys.stderr.write("配信に失敗(上のwrangler出力を確認)\n")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
