#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""scrape_5ch.py — 5ch動画のネタ用スクレイパ v1(改修α / 軍議直依頼)。

なぜ在るか(2026-09-02 軍議 msg 1544620528407420958 / 裁定 1544622936663523418):
  事業転換「5ch動画」(5ch風スレ + VTuber・漫画訴求)のネタ収集。
  肝は「面白い話」ではなく「もう伸びたスレ(=大衆が既に食いついた実証済みネタ)」を機械で拾うこと。
  だから拾う指標は "勢い(短時間でレスが伸びた)"。それを1分に圧縮するのがこのジャンル。

実測で分かった取得経路(2026-09-02・.net→.io へ全面移行済み):
  - 板→サーバ表 : https://menu.5ch.io/bbsmenu.json (UTF-8 JSON。directory_name→host)
  - スレ一覧     : https://<host>/<board>/subject.txt (Shift_JIS。`key.dat<>タイトル (レス数)`)
  - スレ本文     : https://<host>/<board>/dat/<key>.dat (Shift_JIS。`名前<>メール<>日付ID<>本文<>[1行目=スレタイ]`)
  ※認証・APIキー不要。dat/subject.txt とも 200 で取れる(旧 .net は 301/308 で .io へ)。
  ※勢い = レス数 ÷ 経過日数。key はスレ立て時刻の unix epoch。

制約(軍議・CLAUDE.md):
  - 秘密(鍵/トークン)は一切扱わない・出力しない。
  - 成人向け板は対象外(ADULT_DIRS で明示除外 + config は SFW 板のみ)。
  - 出力は local/ 配下のみ。

使い方:
  python scripts/scrape_5ch.py                      # config の全板を処理
  python scripts/scrape_5ch.py --board newsplus     # 1板だけ
  python scripts/scrape_5ch.py --top 5 --max-posts 60 --dry-run
出力:
  local/5ch/threads_<board>_<YYYY-MM-DD>.jsonl (1行=1スレ。勢い降順の上位N件)
"""
import argparse
import html
import json
import os
import re
import sys
import time
import urllib.request
from datetime import datetime, timezone, timedelta

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

UA = "Mozilla/5.0 (compatible; Monazilla/1.00; 5chdouga-neta-scraper)"
BBSMENU = "https://menu.5ch.io/bbsmenu.json"
JST = timezone(timedelta(hours=9))

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
OUT_DIR = os.path.join(ROOT, "local", "5ch")
DEFAULT_CFG = os.path.join(HERE, "scrape_5ch_config.json")
EXAMPLE_CFG = os.path.join(HERE, "scrape_5ch_config.example.json")

# 成人向け板の directory_name(明示除外・軍議制約)。config が誤って挙げても弾く。
ADULT_DIRS = {
    "ascii2d", "ero", "eroaa", "erocg", "erodoujin", "eroparo", "hgame",
    "ascii", "aaslong", "ascii2", "avideo", "avweb", "hage", "gaysalon",
    "hentai", "housou", "pinky", "oimo", "ascii2d2",
}


def fetch(url, timeout=20):
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


def load_config(path):
    if not os.path.exists(path):
        alt = EXAMPLE_CFG
        if os.path.exists(alt):
            print(f"[i] {os.path.basename(path)} が無いので example を使う: {alt}")
            path = alt
        else:
            raise SystemExit(f"config が無い: {path}")
    with open(path, encoding="utf-8") as f:
        cfg = json.load(f)
    return cfg


_server_map = None


def resolve_server(directory_name):
    """bbsmenu.json から directory_name → host を引く(初回だけ取得してキャッシュ)。"""
    global _server_map
    if _server_map is None:
        _server_map = {}
        data = json.loads(fetch(BBSMENU).decode("utf-8", "replace"))
        for cat in data.get("menu_list", []):
            for b in cat.get("category_content", []):
                d = b.get("directory_name")
                u = b.get("url", "")
                m = re.match(r"https?://([^/]+)/", u)
                if d and m:
                    _server_map[d] = m.group(1)
    return _server_map.get(directory_name)


def parse_subject(raw):
    """subject.txt(Shift_JIS) → [{key, title, res}] 。"""
    out = []
    for line in raw.decode("cp932", "replace").splitlines():
        m = re.match(r"^(\d+)\.dat<>(.*)\s\((\d+)\)\s*$", line)
        if not m:
            continue
        out.append({"key": m.group(1), "title": m.group(2).strip(), "res": int(m.group(3))})
    return out


def ikioi(res, key, now_epoch):
    age_days = max((now_epoch - int(key)) / 86400.0, 1.0 / 24)  # 最低1時間で頭打ち
    return round(res / age_days, 1)


_TAG = re.compile(r"<[^>]+>")


def clean_body(raw):
    raw = re.sub(r"<br>", "\n", raw, flags=re.I)
    raw = _TAG.sub("", raw)
    return html.unescape(raw).strip()


def parse_dat(raw, max_posts):
    """dat(Shift_JIS) → (title, [本文,...]) 。max_posts=0 で全件。"""
    lines = raw.decode("cp932", "replace").splitlines()
    title = ""
    posts = []
    for i, line in enumerate(lines):
        f = line.split("<>")
        if len(f) < 4:
            continue
        if i == 0 and len(f) >= 5:
            title = f[4].strip()
        posts.append(clean_body(f[3]))
    if max_posts and max_posts > 0:
        posts = posts[:max_posts]
    return title, posts


def scrape_board(directory_name, top_n, max_posts, sleep, dry_run):
    if directory_name in ADULT_DIRS:
        print(f"[skip] 成人向け板は対象外: {directory_name}")
        return None
    host = resolve_server(directory_name)
    if not host:
        print(f"[skip] bbsmenu にサーバが見つからない: {directory_name}")
        return None
    base = f"https://{host}/{directory_name}"
    now_epoch = int(time.time())

    threads = parse_subject(fetch(f"{base}/subject.txt"))
    for t in threads:
        t["ikioi"] = ikioi(t["res"], t["key"], now_epoch)
    threads.sort(key=lambda t: t["ikioi"], reverse=True)
    top = threads[:top_n]

    print(f"[{directory_name}] host={host} 総スレ={len(threads)} 上位={len(top)}(勢い降順)")
    records = []
    for t in top:
        url = f"{base}/test/read.cgi/{directory_name}/{t['key']}/"
        rec = {
            "board": directory_name,
            "host": host,
            "key": t["key"],
            "title": t["title"],
            "res": t["res"],
            "ikioi": t["ikioi"],
            "url": url,
            "fetched_at": datetime.now(JST).isoformat(timespec="seconds"),
        }
        if not dry_run:
            time.sleep(sleep)
            try:
                dtitle, posts = parse_dat(fetch(f"{base}/dat/{t['key']}.dat"), max_posts)
                if dtitle:
                    rec["title"] = dtitle
                rec["posts_fetched"] = len(posts)
                rec["posts"] = posts
            except Exception as e:
                rec["error"] = f"dat取得失敗: {e}"
        records.append(rec)
        print(f"  勢い{t['ikioi']:>7}/日  レス{t['res']:>4}  {t['title'][:44]}")
    return records


def main():
    ap = argparse.ArgumentParser(description="5ch動画ネタ用スクレイパ v1")
    ap.add_argument("--config", default=DEFAULT_CFG)
    ap.add_argument("--board", help="config を無視して1板だけ(directory_name)")
    ap.add_argument("--top", type=int, help="各板の上位N件(既定=config or 10)")
    ap.add_argument("--max-posts", type=int, help="1スレの取得レス上限(0=全件)")
    ap.add_argument("--sleep", type=float, default=1.2, help="dat取得間の待ち秒(礼儀)")
    ap.add_argument("--dry-run", action="store_true", help="一覧・勢いだけ。本文datは取らない")
    args = ap.parse_args()

    cfg = load_config(args.config)
    top_n = args.top or cfg.get("top_n", 10)
    max_posts = args.max_posts if args.max_posts is not None else cfg.get("max_posts", 80)

    if args.board:
        boards = [{"directory_name": args.board}]
    else:
        boards = cfg.get("boards", [])
    if not boards:
        raise SystemExit("対象板が無い。config の boards を確認。")

    os.makedirs(OUT_DIR, exist_ok=True)
    today = datetime.now(JST).strftime("%Y-%m-%d")
    total = 0
    for b in boards:
        d = b["directory_name"]
        records = scrape_board(d, top_n, max_posts, args.sleep, args.dry_run)
        if not records:
            continue
        out_path = os.path.join(OUT_DIR, f"threads_{d}_{today}.jsonl")
        if not args.dry_run:
            with open(out_path, "w", encoding="utf-8") as f:
                for r in records:
                    f.write(json.dumps(r, ensure_ascii=False) + "\n")
            print(f"  → {out_path} ({len(records)}件)")
        total += len(records)
    print(f"完了: {total}件(dry-run={args.dry_run})")


if __name__ == "__main__":
    main()
