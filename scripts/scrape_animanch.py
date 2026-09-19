#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""scrape_animanch.py — あにまん掲示板のカテゴリ一覧を拾う道具。

取得するのは ``/category<N>/`` の1ページだけで、スレ本文は取得しない。
robots.txt の ``Disallow: /*?*`` に従い、クエリ文字列を使うページ送りは
行わない。そのため ``--pages`` は提供しない。

出力は paths_5ch.matome_dir() 配下の
``animanch_category<N>_<YYYY-MM-DD>.jsonl``。1行が1スレで、掲載順を保つ。
外部サービスへの書き込みは行わない。
"""
import argparse
import json
import os
import re
import sys
import time
import urllib.parse
from datetime import datetime, timedelta, timezone
from html.parser import HTMLParser

try:
    import requests
except ImportError:
    print("requests が要る: pip install requests", file=sys.stderr)
    raise SystemExit(2)

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)

from p0_filter import P0Filter  # noqa: E402
import paths_5ch  # noqa: E402
import rsch_metrics  # noqa: E402


UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) scrape_animanch/1.0 (+local research tool)"
BASE_URL = "https://bbs.animanch.com/"
VALID_TABS = ("recents", "news", "populars")
JST = timezone(timedelta(hours=9))
_CATEGORY_PATH = re.compile(r"/category[1-9][0-9]*/")
_BOARD_PATH = re.compile(r"^/board/[1-9][0-9]*/$")
_WS = re.compile(r"\s+")


def _classes(attrs):
    return set(dict(attrs).get("class", "").split())


class CategoryParser(HTMLParser):
    """指定タブ内の ``a.card`` からタイトル・URL・レス数を読む。"""

    def __init__(self, tab):
        super().__init__(convert_charrefs=True)
        self.tab = tab
        self.stack = []
        self.tab_depth = None
        self.card = None
        self.card_depth = None
        self.body_depth = None
        self.count_depth = None
        self.records = []
        self.invalid_cards = 0

    def handle_starttag(self, tag, attrs):
        attrs_dict = dict(attrs)
        depth = len(self.stack) + 1
        self.stack.append(tag)

        if self.tab_depth is None and attrs_dict.get("id") == self.tab:
            self.tab_depth = depth

        if self.tab_depth is None:
            return

        classes = _classes(attrs)
        if self.card is None and tag == "a" and "card" in classes:
            href = attrs_dict.get("href", "")
            parsed = urllib.parse.urlparse(href)
            if parsed.netloc and parsed.netloc != "bbs.animanch.com":
                return
            if parsed.query or parsed.fragment or not _BOARD_PATH.fullmatch(parsed.path):
                return
            self.card = {"url": urllib.parse.urljoin(BASE_URL, href), "title_parts": [], "count_parts": []}
            self.card_depth = depth
            return

        if self.card is not None:
            if tag == "div" and "card-body" in classes:
                self.body_depth = depth
            elif tag == "p" and "threadCount" in classes:
                self.count_depth = depth

    def handle_data(self, data):
        if self.card is None:
            return
        depth = len(self.stack)
        if self.count_depth is not None:
            self.card["count_parts"].append(data)
        elif self.body_depth is not None and depth == self.body_depth:
            self.card["title_parts"].append(data)

    def handle_endtag(self, tag):
        depth = len(self.stack)
        if self.card is not None:
            if self.count_depth == depth and tag == "p":
                self.count_depth = None
            if self.body_depth == depth and tag == "div":
                self.body_depth = None
            if self.card_depth == depth and tag == "a":
                self._finish_card()

        if self.tab_depth == depth and self.stack and self.stack[-1] == tag:
            self.tab_depth = None

        if tag in self.stack:
            while self.stack:
                opened = self.stack.pop()
                if opened == tag:
                    break

    def _finish_card(self):
        # ★threadCount の中身はタブで変わる(実測 2026-09-20):
        #   recents/populars = レス数の数字 / news = 「16分前」のような相対時刻。
        #   数字を必須にすると news タブが丸ごと0件になるので、生の文字列も残す。
        title = _WS.sub(" ", "".join(self.card["title_parts"])).strip()
        raw_count = _WS.sub("", "".join(self.card["count_parts"]))
        if title:
            record = {"title": title, "url": self.card["url"], "count_raw": raw_count}
            if raw_count.isdigit():
                record["response_count"] = int(raw_count)
            elif raw_count:
                record["updated_rel"] = raw_count
            self.records.append(record)
        else:
            self.invalid_cards += 1
        self.card = None
        self.card_depth = None
        self.body_depth = None
        self.count_depth = None


def category_url(category):
    url = urllib.parse.urljoin(BASE_URL, f"category{category}/")
    parsed = urllib.parse.urlparse(url)
    if parsed.netloc != "bbs.animanch.com" or parsed.query or not _CATEGORY_PATH.fullmatch(parsed.path):
        raise ValueError(f"robots.txt の許可範囲外URL: {url}")
    return url


def fetch(url, sleep_seconds, timeout=20):
    # 1実行1リクエスト。連続実行時にも間を置くため、取得前に待つ。
    time.sleep(sleep_seconds)
    return requests.get(
        url,
        headers={"User-Agent": UA, "Accept-Language": "ja"},
        timeout=timeout,
    )


def extract_threads(html_text, tab):
    parser = CategoryParser(tab)
    parser.feed(html_text)
    parser.close()
    seen = set()
    records = []
    for record in parser.records:
        if record["url"] in seen:
            continue
        seen.add(record["url"])
        records.append(record)
    return records, parser.invalid_cards


def _html_head(text):
    return _WS.sub(" ", text[:200]).strip()


def _selector(tab):
    return f'#{tab} a.card[href^="https://bbs.animanch.com/board/"] .card-body > text / p.threadCount'


def _metric_path():
    return os.path.join(ROOT, "local", "_work", "web_research_metrics.jsonl")


def _append_metric(category, tab, fetched=0, p0_dropped=0, errors=0):
    rsch_metrics.append_metric(
        f"matome:bbs.animanch.com/category{category}/{tab}",
        fetched=fetched,
        bar_ok=fetched,
        p0_dropped=p0_dropped,
        errors=errors,
        path=_metric_path(),
    )


def fail(category, tab, status, html_text, message, p0_dropped=0):
    print(f"[error] {message}", file=sys.stderr)
    print(f"HTTPコード: {status}", file=sys.stderr)
    print(f"想定セレクタ: {_selector(tab)}", file=sys.stderr)
    print(f"実HTML冒頭200字: {_html_head(html_text)}", file=sys.stderr)
    print(f"P0除外={p0_dropped}件", file=sys.stderr)
    _append_metric(category, tab, p0_dropped=p0_dropped, errors=1)
    return 1


def parse_args(argv=None):
    ap = argparse.ArgumentParser(description="あにまん掲示板のカテゴリ一覧スクレイパ")
    ap.add_argument("--category", type=int, default=24, help="カテゴリ番号(既定: 24)")
    ap.add_argument("--tab", choices=VALID_TABS, default="news", help="一覧タブ(既定: news)")
    ap.add_argument("--sleep", type=float, default=2.0, help="取得前の待ち秒(2.0以上)")
    ap.add_argument("--limit", type=int, help="保存する最大件数")
    ap.add_argument("--out", help="出力JSONLのパス")
    args = ap.parse_args(argv)
    if args.category < 1:
        ap.error("--category は1以上が要る")
    if args.sleep < 2.0:
        ap.error("--sleep は robots.txt と礼儀のため2.0秒以上が要る")
    if args.limit is not None and args.limit < 1:
        ap.error("--limit は1以上が要る")
    return args


def main(argv=None):
    args = parse_args(argv)
    url = category_url(args.category)
    p0 = P0Filter.load()
    if not p0.host_ok(urllib.parse.urlparse(url).netloc):
        print(f"[stop] 成人ホストは対象外: {url}", file=sys.stderr)
        return 2

    try:
        response = fetch(url, args.sleep)
    except requests.RequestException as exc:
        return fail(args.category, args.tab, "取得不能", "", f"取得失敗: {exc}")

    print(f"[HTTP] {UA} -> {response.status_code}")
    if response.status_code != 200:
        return fail(args.category, args.tab, response.status_code, response.text, "一覧取得に失敗")

    response.encoding = "utf-8"
    threads, invalid_cards = extract_threads(response.text, args.tab)
    if not threads:
        return fail(args.category, args.tab, response.status_code, response.text, "対象スレを取得できなかった")
    if invalid_cards:
        print(f"[warn] 必須項目を読めず除外={invalid_cards}件", file=sys.stderr)

    fetched_at = datetime.now(JST).isoformat(timespec="seconds")
    kept = []
    p0_dropped = 0
    for thread in threads:
        ok, reason = p0.check_text(thread["title"])
        if not ok:
            p0_dropped += 1
            print(f"[P0除外] {reason} {thread['title'][:60]}", file=sys.stderr)
            continue
        thread.update(
            {
                "category": args.category,
                "tab": args.tab,
                "fetched_at": fetched_at,
            }
        )
        kept.append(thread)
        if args.limit is not None and len(kept) >= args.limit:
            break

    print(f"P0除外={p0_dropped}件", file=sys.stderr)
    if not kept:
        return fail(
            args.category,
            args.tab,
            response.status_code,
            response.text,
            "P0選別後に保存できるスレが0件だった",
            p0_dropped=p0_dropped,
        )

    today = datetime.now(JST).strftime("%Y-%m-%d")
    out_path = args.out or os.path.join(
        paths_5ch.matome_dir(), f"animanch_category{args.category}_{today}.jsonl"
    )
    out_path = os.path.abspath(out_path)
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as out_file:
        for thread in kept:
            out_file.write(json.dumps(thread, ensure_ascii=False) + "\n")

    _append_metric(args.category, args.tab, fetched=len(kept), p0_dropped=p0_dropped)
    print(f"[{url}] タブ={args.tab} 取得={len(kept)}件 P0除外={p0_dropped}件")
    print(f"出力: {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
