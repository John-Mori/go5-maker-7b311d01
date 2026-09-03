#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""web_distill.py — Webページを「LLMが読む前」に素の本文へ蒸留してトークンを節約する道具。

なぜ: サブエージェントやLLMが生HTMLをそのまま読むと、nav/script/style/広告/
装飾タグでトークンを大量に焼く。取得直後にPython側で本文だけ抜いて渡せば、
"読む質"は落とさずに投入トークンだけ落とせる(実測で7〜9割落ちる)。

方針:
- 標準ライブラリ + requests だけで動く(bs4/readability 不要)。
- 文字コードは meta charset / apparent_encoding を見て決める(Shift_JIS の 5ch/したらば対策)。
- どうしても取れない/文字化けする時は --via-jina で r.jina.ai プロキシ(整形済みMarkdownを返す・読み取りのみ)。
- 出力は local/5ch_research/ の中だけ。外部サービスへ書き込まない。
- 生バイト数と蒸留後バイト数を必ず出す(数で報告する=空約束にしない)。

使い方:
  python scripts/web_distill.py <URL> [<URL> ...]
  python scripts/web_distill.py --url-file urls.txt --out local/5ch_research/distilled
  python scripts/web_distill.py <URL> --via-jina        # 文字化け/取得困難ページ
  python scripts/web_distill.py <URL> --stdout          # ファイルに書かず標準出力へ
"""
import argparse
import datetime
import html as htmllib
import os
import re
import sys
import time
import urllib.parse

try:
    import requests
except ImportError:
    print("requests が要る: pip install requests", file=sys.stderr)
    sys.exit(2)

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) web_distill/1.0 (+local research tool)"
REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_OUT = os.path.join(REPO_ROOT, "local", "5ch_research", "distilled")

# 丸ごと捨てるブロック(中身ごと除去)
_DROP_BLOCKS = re.compile(
    r"<(script|style|noscript|template|svg|head|nav|header|footer|form|iframe|aside)\b[^>]*>.*?</\1>",
    re.IGNORECASE | re.DOTALL,
)
_BR = re.compile(r"<br\s*/?>", re.IGNORECASE)
_BLOCK_END = re.compile(r"</(p|div|li|tr|h[1-6]|section|article|blockquote)>", re.IGNORECASE)
_TAG = re.compile(r"<[^>]+>")
_MULTINL = re.compile(r"\n{3,}")
_TRAIL_WS = re.compile(r"[ \t]+\n")
_CHARSET = re.compile(rb'charset=["\']?\s*([a-zA-Z0-9_\-]+)', re.IGNORECASE)


def _decode(resp):
    """本文を文字列化する。★単バイトコーデック(cp1251等)はどんなbytesでも
    strictで"成功"してしまうので、多バイトの日本語/utf-8を先に試し、
    charset宣言も日本語系(utf-8/shift_jis/euc)に限って信用する(誤検出防止)。"""
    raw = resp.content
    m = _CHARSET.search(raw[:4096])
    declared = m.group(1).decode("ascii", "ignore").lower() if m else None
    # 宣言があってもshift_jis/euc/utf系だけ採る。cp1251等のゴミ検出は無視。
    jp = {"shift_jis": "cp932", "shift-jis": "cp932", "sjis": "cp932",
          "x-sjis": "cp932", "windows-31j": "cp932", "ms932": "cp932",
          "euc-jp": "euc-jp", "eucjp": "euc-jp", "utf-8": "utf-8", "utf8": "utf-8"}
    order = []
    if declared in jp:
        order.append(jp[declared])
    # 日本語ページの実在コーデックだけを、多バイト検証が効く順で試す
    for c in ["utf-8", "cp932", "euc-jp"]:
        if c not in order:
            order.append(c)
    for cand in order:
        try:
            return raw.decode(cand, "strict"), cand
        except (LookupError, UnicodeDecodeError):
            continue
    return raw.decode("utf-8", "replace"), "utf-8(replace)"


def distill_html(src):
    """生HTML文字列 -> 本文テキスト。"""
    # <title>だけ拾っておく
    mt = re.search(r"<title[^>]*>(.*?)</title>", src, re.IGNORECASE | re.DOTALL)
    title = htmllib.unescape(_TAG.sub("", mt.group(1)).strip()) if mt else ""
    body = _DROP_BLOCKS.sub(" ", src)
    body = _BR.sub("\n", body)
    body = _BLOCK_END.sub("\n", body)
    body = _TAG.sub("", body)
    body = htmllib.unescape(body)
    body = _TRAIL_WS.sub("\n", body)
    body = _MULTINL.sub("\n\n", body)
    lines = [ln.strip() for ln in body.splitlines()]
    body = "\n".join(ln for ln in lines if ln)
    return title, body.strip()


def fetch(url, via_jina=False, timeout=25):
    if via_jina:
        target = "https://r.jina.ai/" + url
        r = requests.get(target, headers={"User-Agent": UA}, timeout=timeout)
        r.raise_for_status()
        # jina は整形済みMarkdown(text)を返す=そのまま本文扱い
        return "", r.text, len(r.content)
    r = requests.get(url, headers={"User-Agent": UA}, timeout=timeout)
    r.raise_for_status()
    raw_len = len(r.content)
    text, _enc = _decode(r)
    title, body = distill_html(text)
    return title, body, raw_len


def slugify(url):
    p = urllib.parse.urlparse(url)
    base = (p.netloc + p.path).strip("/").replace("/", "_")
    base = re.sub(r"[^0-9A-Za-z_.\-]", "_", base) or "page"
    return base[:80]


def main():
    ap = argparse.ArgumentParser(description="Webページを本文へ蒸留してトークン節約")
    ap.add_argument("urls", nargs="*", help="対象URL")
    ap.add_argument("--url-file", help="1行1URLのファイル")
    ap.add_argument("--out", default=DEFAULT_OUT, help="出力フォルダ(既定=local/5ch_research/distilled)")
    ap.add_argument("--via-jina", action="store_true", help="r.jina.ai経由(文字化け/取得困難ページ)")
    ap.add_argument("--stdout", action="store_true", help="ファイルに書かず標準出力へ")
    ap.add_argument("--sleep", type=float, default=1.2, help="連続取得の間隔秒(既定1.2)")
    args = ap.parse_args()

    urls = list(args.urls)
    if args.url_file:
        with open(args.url_file, encoding="utf-8") as f:
            urls += [ln.strip() for ln in f if ln.strip() and not ln.startswith("#")]
    if not urls:
        ap.error("URLを1つ以上渡す(引数 または --url-file)")

    if not args.stdout:
        os.makedirs(args.out, exist_ok=True)
    today = datetime.date.today().isoformat()
    tot_raw = tot_dist = 0
    ok = 0
    for i, url in enumerate(urls):
        if i:
            time.sleep(args.sleep)
        try:
            title, body, raw_len = fetch(url, via_jina=args.via_jina)
        except Exception as e:
            print(f"[NG] {url} -> {type(e).__name__}: {e}", file=sys.stderr)
            continue
        dist = len(body.encode("utf-8"))
        tot_raw += raw_len
        tot_dist += dist
        ok += 1
        red = (1 - dist / raw_len) * 100 if raw_len else 0
        header = f"# {title or url}\nsource: {url}\nfetched: {today} (JST)\nbytes: raw={raw_len:,} -> distilled={dist:,} (-{red:.0f}%)\n\n"
        if args.stdout:
            sys.stdout.write(header + body + "\n")
        else:
            path = os.path.join(args.out, f"{slugify(url)}.txt")
            with open(path, "w", encoding="utf-8") as f:
                f.write(header + body + "\n")
            print(f"[OK] {url}\n     raw={raw_len:,}B -> distilled={dist:,}B (-{red:.0f}%)  {path}")
    if ok:
        red = (1 - tot_dist / tot_raw) * 100 if tot_raw else 0
        print(f"\n=== 合計 {ok}/{len(urls)}件: raw={tot_raw:,}B -> distilled={tot_dist:,}B (-{red:.0f}%) ===")
    else:
        print("取得できたページなし", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
