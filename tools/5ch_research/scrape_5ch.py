#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""5ch ネタリサーチ・スクレイパ v1 (platform-se / 軍議直依頼)

用途: 5ch動画(5ch風スレ形式ショート)のタネになる「伸びてるスレ」を機械で拾う。
  1つの板について subject.txt からスレ一覧(スレタイ/レス数/勢い/URL)を取り、
  勢い上位N件のスレ本文まで dat で落として jsonl に出す。

設計メモ:
- 外へ出る手(HTTP取得)は fetch() 1本に閉じ込め、テストで差し替え可能にしている。
  parse/rank(判定・並べ替え)は本物のまま回す(test-must-fail の線・C-053)。
- 板→サーバは bbsmenu で現在値を解決する(5chはサーバ移設が起きる=固定URLは腐る)。
- 成人向け(bbspink 等)は対象外。出力は local/ 配下のみ。
- 「勢い」= レス数 * 86400 / (now - スレ立て時刻)。スレIDが立て時刻(unix秒)。

依存: 標準ライブラリのみ(urllib)。
"""
from __future__ import annotations
import argparse
import html as _html
import json
import os
import re
import sys
import time
import urllib.request
from datetime import datetime, timezone, timedelta
from pathlib import Path

JST = timezone(timedelta(hours=9))
BROWSER_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0 Safari/537.36"
)
BBSMENU_URL = "https://menu.5ch.net/bbsmenu.html"
# 成人向けミラー等・対象外ドメイン(念のための保険)
BLOCKED_HOST_SUBSTR = ("bbspink", "5ch.pink")

DEFAULT_OUT_DIR = Path(__file__).resolve().parents[2] / "local" / "5ch_research"


# --- 外へ出る唯一の手 -------------------------------------------------------
def fetch(url: str, ua: str = BROWSER_UA, timeout: int = 20) -> bytes:
    """URLを取ってbytesで返す。テストではこの関数だけ差し替える。"""
    for host_bad in BLOCKED_HOST_SUBSTR:
        if host_bad in url:
            raise ValueError("対象外ドメイン(成人向け): %s" % url)
    req = urllib.request.Request(url, headers={"User-Agent": ua})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


def _decode_sjis(raw: bytes) -> str:
    return raw.decode("shift_jis", "replace")


# --- 板→サーバ解決 ----------------------------------------------------------
def resolve_base(board: str, fetcher=fetch) -> str:
    """板slugから現在のスレ取得ベースURL(scheme://host/board)を返す。

    bbsmenu で現在サーバを引き、.net / .io の両候補のうち subject.txt が
    多くのスレを返す方を採る(ミラーが部分的なことがあるため=実測で選ぶ)。
    """
    menu = _decode_sjis(fetcher(BBSMENU_URL))
    m = re.search(r"href=(https?://[^/]+/" + re.escape(board) + r"/)", menu, re.I)
    if not m:
        raise LookupError("bbsmenuに板が見つからない: %s" % board)
    resolved = m.group(1).rstrip("/")  # 例: https://asahi.5ch.io/newsplus
    host = resolved.split("//", 1)[1].split("/", 1)[0]
    candidates = []
    for h in (host, host.replace(".5ch.io", ".5ch.net"), host.replace(".5ch.net", ".5ch.io")):
        base = "https://%s/%s" % (h, board)
        if base not in candidates:
            candidates.append(base)
    best, best_n = None, -1
    for base in candidates:
        try:
            n = len(_parse_subject(_decode_sjis(fetcher(base + "/subject.txt"))))
        except Exception:
            n = -1
        if n > best_n:
            best, best_n = base, n
    if best is None or best_n <= 0:
        raise LookupError("subject.txt が取れない: %s" % board)
    return best


# --- パース -----------------------------------------------------------------
_SUBJECT_RE = re.compile(r"^(\d+)\.dat<>(.*?)\s*\((\d+)\)\s*$")


def _parse_subject(text: str) -> list[dict]:
    """subject.txt をパース。各行 `<thread_id>.dat<>タイトル (レス数)`。"""
    out = []
    for line in text.split("\n"):
        line = line.strip()
        if not line:
            continue
        m = _SUBJECT_RE.match(line)
        if not m:
            continue
        out.append({
            "thread_id": m.group(1),
            "title": m.group(2).strip(),
            "res_count": int(m.group(3)),
        })
    return out


def rank_threads(threads: list[dict], now: float | None = None) -> list[dict]:
    """各スレに勢い(momentum=レス/日)を付けて降順ソート。"""
    if now is None:
        now = time.time()
    for t in threads:
        try:
            created = int(t["thread_id"])
        except (ValueError, KeyError):
            created = 0
        age = max(now - created, 60.0)  # 0除算・立て直後の暴走を防ぐ下限
        t["momentum"] = round(t["res_count"] * 86400.0 / age, 1)
        t["created_jst"] = datetime.fromtimestamp(created, JST).strftime("%Y-%m-%d %H:%M") if created else ""
    return sorted(threads, key=lambda x: x["momentum"], reverse=True)


_TAG_RE = re.compile(r"<.*?>")
_ANCHOR_RE = re.compile(r'<a[^>]*>(.*?)</a>', re.I | re.S)


def clean_body(raw: str) -> str:
    """dat本文のHTMLを平文へ。<br>を改行に、アンカーはテキストへ、タグ除去。"""
    s = raw.replace("<br>", "\n").replace("<br/>", "\n").replace("<br />", "\n")
    s = _ANCHOR_RE.sub(lambda m: m.group(1), s)
    s = _TAG_RE.sub("", s)
    s = _html.unescape(s)
    return s.strip()


def parse_dat(text: str) -> dict:
    """dat をパース。各行 `名前<>メール<>日付ID<>本文<>スレタイ(1行目のみ)`。"""
    posts = []
    title = ""
    for i, line in enumerate(text.split("\n")):
        if not line.strip():
            continue
        f = line.split("<>")
        if len(f) < 4:
            continue
        if i == 0 and len(f) >= 5:
            title = f[4].strip()
        posts.append({
            "no": len(posts) + 1,
            "name": clean_body(f[0]),
            "date_id": f[2].strip(),
            "body": clean_body(f[3]),
        })
    return {"title": title, "posts": posts}


# --- 収集 -------------------------------------------------------------------
def scrape_board(board: str, top_n: int = 5, max_posts: int = 50,
                 fetcher=fetch, sleep: float = 1.0, base: str | None = None) -> dict:
    """1板を収集して結果dictを返す(スレ本文込み)。"""
    if base is None:
        base = resolve_base(board, fetcher=fetcher)
    subj = _parse_subject(_decode_sjis(fetcher(base + "/subject.txt")))
    ranked = rank_threads(subj)
    picked = ranked[:top_n]
    threads = []
    for t in picked:
        url = "%s/dat/%s.dat" % (base, t["thread_id"])
        read_url = "%s/test/read.cgi/%s/%s/" % (
            base.rsplit("/", 1)[0], board, t["thread_id"])
        try:
            dat = parse_dat(_decode_sjis(fetcher(url)))
            posts = dat["posts"][:max_posts]
            title = dat["title"] or t["title"]
            err = None
        except Exception as e:  # 取得失敗はスレ単位で握って記録(全体は止めない)
            posts, title, err = [], t["title"], "%s: %s" % (type(e).__name__, e)
        threads.append({
            "board": board,
            "thread_id": t["thread_id"],
            "title": title,
            "res_count": t["res_count"],
            "momentum": t["momentum"],
            "created_jst": t.get("created_jst", ""),
            "url": read_url,
            "posts": posts,
            "fetch_error": err,
        })
        if sleep:
            time.sleep(sleep)
    return {
        "board": board,
        "base": base,
        "fetched_at": datetime.now(JST).strftime("%Y-%m-%d %H:%M:%S %Z"),
        "thread_count_total": len(subj),
        "threads": threads,
    }


def write_jsonl(result: dict, out_dir: Path = DEFAULT_OUT_DIR) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(JST).strftime("%Y%m%d_%H%M%S")
    path = out_dir / ("%s_%s.jsonl" % (result["board"], stamp))
    with path.open("w", encoding="utf-8") as f:
        for t in result["threads"]:
            f.write(json.dumps(t, ensure_ascii=False) + "\n")
    return path


def load_boards(config_path: Path) -> list[str]:
    data = json.loads(config_path.read_text(encoding="utf-8"))
    return [b["slug"] for b in data.get("boards", []) if b.get("enabled", True)]


# --- CLI --------------------------------------------------------------------
def main(argv=None):
    ap = argparse.ArgumentParser(description="5ch 伸びてるスレ リサーチ・スクレイパ v1")
    ap.add_argument("--board", help="板slug(例: newsplus)。未指定なら --config を読む")
    ap.add_argument("--config", default=str(Path(__file__).with_name("boards.json")),
                    help="板一覧の設定json")
    ap.add_argument("--top", type=int, default=5, help="本文を落とす上位スレ数")
    ap.add_argument("--max-posts", type=int, default=50, help="1スレあたり最大レス数")
    ap.add_argument("--sleep", type=float, default=1.0, help="取得間隔(秒・相手に優しく)")
    ap.add_argument("--out-dir", default=str(DEFAULT_OUT_DIR))
    args = ap.parse_args(argv)

    boards = [args.board] if args.board else load_boards(Path(args.config))
    if not boards:
        print("板が指定されていない(--board か boards.json)", file=sys.stderr)
        return 2

    out_dir = Path(args.out_dir)
    for board in boards:
        try:
            res = scrape_board(board, top_n=args.top, max_posts=args.max_posts,
                               sleep=args.sleep)
        except Exception as e:
            print("[%s] 取得失敗: %s: %s" % (board, type(e).__name__, e), file=sys.stderr)
            continue
        path = write_jsonl(res, out_dir)
        top = res["threads"][0] if res["threads"] else None
        print("[%s] スレ%d件中 上位%d件を保存 -> %s" % (
            board, res["thread_count_total"], len(res["threads"]), path))
        if top:
            print("  1位(勢い%.0f/日): %s (%dレス)" % (
                top["momentum"], top["title"][:50], top["res_count"]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
