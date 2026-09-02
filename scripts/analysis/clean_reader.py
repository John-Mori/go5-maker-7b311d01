#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""まとめ記事の「広告ゼロ・クリーン閲覧 ＋ 分析ノイズ除去」ツール(分析部門・自室完結)。

Chami直Go(軍議 2026-09-02 / msg 1544693172897194066・1544693443471741018):
  「まとめの広告がadblock貫通でまともに見れない。広告を排除してクリーンに見られるように。
   スクレイピングで分析するのにもノイズが無くていい。設計実装は分析部門内で完結させてほしい」

考え方(コア共有):
  ・取得 = 生HTMLを直取り(urllibのみ)。**広告JS・広告iframe・adsbygoogleは一切実行されない**
    (静的パースなのでJSが発火しない=adblock貫通の元を断つ)。抽出の段で広告DOMも捨てる。
  ・抽出 = 本文抽出コアは1個(extract_article)。ここから
      - 見る    : クリーンHTML/テキストをローカルへ吐く(--view)
      - 分析流し: 同じ抽出結果を素のテキストで出す(--analyze)
    両方が同じコアを通る=二重に書かない。

対応テンプレ:
  ・Livedoor Blog標準テンプレ(vsponews.jp / hololivenews.jp 等・競合まとめの多数派)を土台に、
    本文コンテナ class="article-body*" と 2chまとめレス(dt/dd)を構造化抽出する。
  ・非Livedoorは <article>/大きな本文ブロックの汎用フォールバック(**未確認**=外れたら個別に足す)。

依存ゼロ(vanilla方針・pip不要=どのセッションでも同じに動く):
  標準ライブラリ html.parser / urllib のみ。外部本文抽出ライブラリ(trafilatura等)は使わない
  (このプロジェクトに未導入・依存を増やさない判断)。

出力は local/ 配下限定。成人板(bbspink)は対象外。測っていない数値(取得速度・件数)は語らない。

使い方:
  python scripts/analysis/clean_reader.py --view    URL          # 広告ゼロのHTML+txtを local/clean_reader/ へ
  python scripts/analysis/clean_reader.py --analyze URL          # 分析用の素テキストを標準出力へ
  python scripts/analysis/clean_reader.py --analyze URL --out F  # ファイルへ
  python scripts/analysis/clean_reader.py --view URL --print     # HTMLを書かずテキストを標準出力へ
"""
import argparse
import datetime
import html as _html
import io
import os
import re
import ssl
import sys
import urllib.error
import urllib.request
from html.parser import HTMLParser

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
OUT_DIR = os.path.join(ROOT, "local", "clean_reader")
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
# 本文中の画像を行内マーカーで運ぶ(分析テキストでは捨て、閲覧HTMLでは <img> に戻す)
_IMG_MARK = "\x01IMG:"
# 中身の無い装飾画像(スペーサ/1px/アイコン)は閲覧でも出さない
_IMG_SKIP = ("spacer", "blank", "1x1", "pixel", "grey.gif", "gray.gif", "dot.gif",
             "emoji", "/mono/", "clear.gif")

# 本文キャプチャ中も中身を捨てる要素(広告・スクリプト・フォーム・埋め込み)
SKIP_TAGS = {"script", "style", "noscript", "iframe", "ins", "svg",
             "form", "button", "select", "textarea", "template"}
# 深さを持たない(閉じない)要素
VOID_TAGS = {"br", "hr", "img", "link", "meta", "input", "source",
             "area", "base", "col", "embed", "param", "track", "wbr"}
# 改行を入れる区切り要素
BLOCK_TAGS = {"div", "p", "dt", "dd", "li", "tr", "blockquote", "section",
              "article", "ul", "ol", "table", "h1", "h2", "h3", "h4", "h5", "h6", "br", "hr"}

# 本文の終わり(関連記事ウィジェット/コメント欄/テンプレ残骸)を示す合図
STOP_MARKERS = (
    "カテゴリの最新記事", "この記事へのコメント", "コメントする",
    "コメント一覧", "トラックバックURL", "最新記事", "人気記事",
    "おすすめ記事", "スポンサードリンク", "Recommend",
)


def _is_ad_token(tok):
    """class/id の1トークンが広告枠か(語頭一致中心で "read-more" 等を巻き込まない)。"""
    t = tok.lower()
    if t == "ad" or t.startswith("ad-") or t.startswith("ad_") or t.startswith("g-ad"):
        return True
    for kw in ("adsbygoogle", "google-ad", "google-2ad", "microad",
               "taboola", "outbrain", "popin", "advertisement", "-ad-",
               "sponsor", "ad_rs", "ad-area", "admax", "nend"):
        if kw in t:
            return True
    return False


def _cls_ids(attrs):
    d = dict(attrs)
    toks = []
    for k in ("class", "id"):
        v = d.get(k)
        if v:
            toks.extend(v.split())
    return toks


class _ArticleExtractor(HTMLParser):
    """Livedoor Blog標準テンプレを土台にした本文抽出。

    - class="article-body"(外側)へ入ってから中身を拾う。見つからなければ <article> を代替、
      それも無ければページ全体(汎用フォールバック=未確認)。
    - 広告枠(_is_ad_token)/ SKIP_TAGS の subtree は捨てる。
    - dt/dd/div の区切りで改行を入れ、まとめレスの構造を保つ。
    - <a href="http..."> は本文に URL を残す(元動画リンク等=分析価値)。
    """

    def __init__(self, body_selector="article-body"):
        super().__init__(convert_charrefs=True)
        self.body_selector = body_selector
        self.stack = []            # [{"tag","ad","skip","body"}]
        self.buf = []              # 収集テキスト片
        self.title = ""
        self._in_title = False
        self._href = None
        self._a_text = []
        self.saw_body = False      # article-body を一度でも見たか
        self.stopped = False       # STOP_MARKER 到達

    # --- 状態判定 ---
    def _capturing(self):
        if self.stopped:
            return False
        in_body = any(e["body"] for e in self.stack)
        if not in_body:
            return False
        return not any(e["ad"] or e["skip"] for e in self.stack)

    def handle_starttag(self, tag, attrs):
        if tag == "title":
            self._in_title = True
            return
        toks = _cls_ids(attrs)
        is_ad = any(_is_ad_token(t) for t in toks)
        is_skip = tag in SKIP_TAGS
        is_body = (tag in ("div", "article", "section")
                   and any(t == self.body_selector for t in toks))
        if tag not in VOID_TAGS:
            self.stack.append({"tag": tag, "ad": is_ad, "skip": is_skip, "body": is_body})
        if is_body:
            self.saw_body = True
        # 改行区切り(キャプチャ中のみ)
        if tag in BLOCK_TAGS and self._capturing():
            self.buf.append("\n")
        if tag == "img" and self._capturing():
            d = dict(attrs)
            src = d.get("src") or d.get("data-src") or ""
            if src.startswith("http") and not any(s in src.lower() for s in _IMG_SKIP):
                self.buf.append("\n" + _IMG_MARK + src + "\n")
        if tag == "a" and self._capturing():
            d = dict(attrs)
            h = d.get("href", "")
            self._href = h if h.startswith("http") else None
            self._a_text = []

    def handle_startendtag(self, tag, attrs):
        # <br/> 等の自己終了。深さは持たせない。
        if tag in BLOCK_TAGS and self._capturing():
            self.buf.append("\n")

    def handle_endtag(self, tag):
        if tag == "title":
            self._in_title = False
            return
        if tag == "a" and self._href is not None:
            atext = "".join(self._a_text)
            if self._href not in atext:
                self.buf.append(" " + self._href + " ")
            self._href = None
            self._a_text = []
        if tag in BLOCK_TAGS and self._capturing():
            self.buf.append("\n")
        if tag not in VOID_TAGS:
            # 直近の一致要素まで巻き戻す(未閉じタグに寛容)
            for i in range(len(self.stack) - 1, -1, -1):
                if self.stack[i]["tag"] == tag:
                    del self.stack[i:]
                    break

    def handle_data(self, data):
        if self._in_title:
            self.title += data
            return
        if not self._capturing():
            return
        if not data.strip():
            # 空白でも語間の区切りは残す
            if data and not data.isspace():
                self.buf.append(data)
            return
        # テンプレ残骸(<% %>)の断片を落とす
        if "<%" in data or "%>" in data:
            return
        for m in STOP_MARKERS:
            if m in data:
                self.stopped = True
                # マーカー前までは活かす(ただし「カテゴリ名」だけの残骸は捨てる)
                pre = data.split(m)[0].strip()
                if pre and not re.fullmatch(r"「[^」]*」", pre):
                    self.buf.append(pre)
                return
        if self._href is not None:
            self._a_text.append(data)
        self.buf.append(data)

    def text(self):
        raw = "".join(self.buf)
        lines = [re.sub(r"[ \t　]+", " ", ln).strip() for ln in raw.split("\n")]
        out, blank = [], 0
        for ln in lines:
            if not ln:
                blank += 1
                if blank <= 1 and out:
                    out.append("")
                continue
            blank = 0
            out.append(ln)
        return "\n".join(out).strip()


# 日付の芯(YYYY/MM/DD(曜) HH:MM(:SS(.xx)))
_DATE = r"\d{4}/\d{1,2}/\d{1,2}\([日月火水木金土]\)\s*\d{1,2}:\d{2}(?::\d{2}(?:\.\d{2})?)?"
# レス見出しは2系統をサポート:
#  (A) ホロ/ぶいすぽ系: 「名無しの視聴者 2026/07/24(金) 22:00:19.00」(行末=$)
#  (B) なんJ/VIP系   : 「23 ： 風吹けば名無し ： 2022/06/29(水) 18:49:31.57 ID： ID:xxx」
#      (番号 ：/: 名前 ：/: 日付 …以降のID等は無視)
_RES_HEAD = re.compile(r"^(?P<author>.{0,40}?)\s*(?P<date>" + _DATE + r"(?:\s*ID:[\w/+.-]+)?)\s*$")
_RES_HEAD_VIP = re.compile(
    r"^\d+\s*[：:]\s*(?P<author>.{1,30}?)\s*[：:]\s*(?P<date>" + _DATE + r")")


def _match_res_head(line):
    """行がレス見出しなら (author, date) を返す。2系統を順に試す。"""
    m = _RES_HEAD.match(line)
    if m and (m.group("author") or "").strip():
        return m.group("author").strip(), m.group("date").strip()
    m = _RES_HEAD_VIP.match(line)
    if m and (m.group("author") or "").strip():
        return m.group("author").strip(), m.group("date").strip()
    return None


def _segment_res(body_text):
    """本文テキストを 2ch まとめレスへ分割する。見出しが無ければ空。"""
    lines = body_text.split("\n")
    heads = []
    for i, ln in enumerate(lines):
        hit = _match_res_head(ln.strip())
        if hit:
            heads.append((i, hit[0], hit[1]))
    if len(heads) < 2:
        return []
    res = []
    for k, (i, author, date) in enumerate(heads):
        j = heads[k + 1][0] if k + 1 < len(heads) else len(lines)
        body = "\n".join(x for x in lines[i + 1:j] if x.strip()).strip()
        if body:
            res.append({"author": author, "date": date, "text": body})
    return res


def _decode(raw, header_charset):
    """バイト列を文字列へ。meta/ヘッダ charset を優先、外れたら候補で復号。"""
    m = re.search(rb'charset=["\']?\s*([\w\-]+)', raw[:4096], re.I)
    meta = m.group(1).decode("ascii", "ignore") if m else None
    for enc in [c for c in (meta, header_charset) if c]:
        try:
            return raw.decode(enc)
        except (LookupError, UnicodeDecodeError):
            pass
    for enc in ("utf-8", "cp932", "euc-jp"):
        try:
            return raw.decode(enc)
        except (LookupError, UnicodeDecodeError):
            continue
    return raw.decode("utf-8", "replace")


def fetch(url, insecure=False):
    """生HTMLを直取り(広告JS/iframeは読み込まない=発火させない)。

    insecure=True でTLS証明書の検証を無効化する(**local限定・自己責任**)。
    vippers.jp 等の老舗まとめは証明書切れ/自己署名で素の取得が弾かれる実物ケースがある。
    明示指定していなくても、証明書検証エラーの時だけ緩和して1回だけ再試行し警告を出す
    (閲覧専用のローカルツール=本文しか読まないため。秘密の送信は無い)。
    """
    req = urllib.request.Request(
        url, headers={"User-Agent": UA, "Accept-Language": "ja-JP,ja;q=0.9"})
    ctx = None
    if insecure:
        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
    try:
        with urllib.request.urlopen(req, timeout=30, context=ctx) as r:
            raw = r.read()
            return _decode(raw, r.headers.get_content_charset()), r.geturl()
    except urllib.error.URLError as e:
        # 証明書検証の失敗に限り、検証を切って1回だけ再試行(local限定・自己責任)
        if not insecure and isinstance(getattr(e, "reason", None), ssl.SSLError):
            sys.stderr.write(
                "警告: TLS証明書の検証に失敗(" + type(e.reason).__name__ +
                ")。local限定・自己責任で検証を無効化して再取得する: " + url + "\n")
            return fetch(url, insecure=True)
        raise


def extract_article(html, url=""):
    """本文抽出コア(1個)。戻り値 dict: title / url / body_text / reslist。

    Livedoor(article-body)→ <article> → ページ全体、の順で本文コンテナを探す。
    """
    for sel in ("article-body", None):
        p = _ArticleExtractor(body_selector=sel or "article-body")
        if sel is None:
            # <article> 要素をコンテナにする代替(タグ名で拾う)
            p.body_selector = "\x00none\x00"
        try:
            p.feed(html)
        except Exception:
            pass
        if sel is not None and p.saw_body and p.text():
            body = p.text()
            title = _html.unescape(p.title).strip()
            return {"title": title, "url": url, "body_text": body,
                    "reslist": _segment_res(body)}
    # フォールバック(未確認): <article>…</article>、無ければ本文らしい最大ブロック
    body = _fallback_text(html)
    title = ""
    mt = re.search(r"<title[^>]*>(.*?)</title>", html, re.S | re.I)
    if mt:
        title = _html.unescape(re.sub(r"<[^>]+>", "", mt.group(1))).strip()
    return {"title": title, "url": url, "body_text": body,
            "reslist": _segment_res(body)}


def _fallback_text(html):
    """非Livedoor用の汎用抽出(未確認)。<article> を優先、無ければ本文密度の高い塊。"""
    m = re.search(r"<article[^>]*>(.*?)</article>", html, re.S | re.I)
    src = m.group(1) if m else html
    src = re.sub(r"<(script|style|noscript|iframe|ins|form|nav|header|footer|aside)[^>]*>.*?</\1>",
                 " ", src, flags=re.S | re.I)
    src = re.sub(r"<br\s*/?>", "\n", src, flags=re.I)
    src = re.sub(r"</(p|div|dt|dd|li|h[1-6])>", "\n", src, flags=re.I)
    txt = _html.unescape(re.sub(r"<[^>]+>", " ", src))
    lines = [re.sub(r"[ \t　]+", " ", ln).strip() for ln in txt.split("\n")]
    return "\n".join(ln for ln in lines if ln).strip()


def _strip_img(text):
    """画像マーカー行を落とす(分析用の素テキストには画像を入れない)。"""
    return "\n".join(ln for ln in text.split("\n")
                     if not ln.startswith(_IMG_MARK)).strip()


def as_plain(article):
    """分析パイプライン用の素テキスト。レスがあればレス単位、無ければ本文。"""
    lines = []
    if article["title"]:
        lines.append(article["title"])
        lines.append("")
    if article["reslist"]:
        for r in article["reslist"]:
            head = (r["author"] + " " + r["date"]).strip()
            lines.append(head)
            lines.append(_strip_img(r["text"]))
            lines.append("")
    else:
        lines.append(_strip_img(article["body_text"]))
    return "\n".join(lines).strip() + "\n"


def as_clean_html(article):
    """広告ゼロ・JSゼロのクリーンHTML(ローカル閲覧用)。"""
    t = _html.escape(article["title"] or "(無題)")
    parts = [
        "<!DOCTYPE html>",
        '<html lang="ja"><head><meta charset="utf-8">',
        '<meta name="viewport" content="width=device-width,initial-scale=1">',
        "<title>" + t + "</title>",
        "<style>",
        "body{background:#0e1422;color:#e8e6df;font-family:system-ui,'Hiragino Sans','Noto Sans JP',sans-serif;",
        "line-height:1.8;max-width:720px;margin:0 auto;padding:24px 16px 96px;}",
        "h1{font-size:1.3rem;color:#fffdf6;border-bottom:2px solid #2bb3c0;padding-bottom:8px;}",
        ".src{font-size:.8rem;color:#8aa;word-break:break-all;margin-bottom:24px;}",
        ".res{border-top:1px dashed #2a3550;padding:10px 0;}",
        ".res .h{font-size:.75rem;color:#7f93b5;margin-bottom:4px;}",
        ".res .b{white-space:pre-wrap;}",
        ".body{white-space:pre-wrap;}",
        "a{color:#2bb3c0;}",
        "img{max-width:100%;height:auto;border-radius:6px;margin:8px 0;display:block;}",
        "</style></head><body>",
        "<h1>" + t + "</h1>",
        '<div class="src">' + _html.escape(article["url"]) + "</div>",
    ]
    if article["reslist"]:
        for r in article["reslist"]:
            head = _html.escape((r["author"] + " " + r["date"]).strip())
            body = _render_body_html(r["text"])
            parts.append('<div class="res"><div class="h">' + head +
                         '</div><div class="b">' + body + "</div></div>")
    else:
        parts.append('<div class="body">' + _render_body_html(article["body_text"]) + "</div>")
    parts.append("</body></html>")
    return "\n".join(parts)


def _render_body_html(text):
    """本文テキストをHTML化。画像マーカー行は <img> に、URLはリンクに。"""
    out = []
    for ln in text.split("\n"):
        if ln.startswith(_IMG_MARK):
            src = ln[len(_IMG_MARK):].strip()
            out.append('<img src="%s" loading="lazy" alt="">' % _html.escape(src, quote=True))
        else:
            out.append(_linkify(ln))
    return "\n".join(out)


def _linkify(text):
    esc = _html.escape(text)
    return re.sub(r"(https?://[^\s<]+)",
                  lambda m: '<a href="%s" target="_blank" rel="noopener">%s</a>' % (m.group(1), m.group(1)),
                  esc)


def _slug(url):
    m = re.search(r"://([^/]+).*?/(\d+)\.html", url)
    if m:
        return re.sub(r"[^\w.-]", "_", m.group(1)) + "_" + m.group(2)
    return re.sub(r"[^\w.-]", "_", url)[-60:] or "article"


def _write(path, data):
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    with io.open(path, "w", encoding="utf-8") as f:
        f.write(data)


def main():
    ap = argparse.ArgumentParser(description="まとめ記事の広告除去クリーン閲覧＋分析ノイズ除去")
    ap.add_argument("url", help="記事URL(まとめ記事の /archives/ID.html 等)")
    g = ap.add_mutually_exclusive_group()
    g.add_argument("--view", action="store_true", help="広告ゼロのHTML+txtを local/clean_reader/ へ")
    g.add_argument("--analyze", action="store_true", help="分析用の素テキストを出力")
    ap.add_argument("--out", help="出力ファイルパス(--analyze / --view --print で使用)")
    ap.add_argument("--print", dest="to_stdout", action="store_true", help="ファイルへ書かず標準出力へ")
    ap.add_argument("--insecure", action="store_true",
                    help="TLS証明書の検証を無効化(local限定・自己責任。証明書切れの老舗まとめ用)")
    args = ap.parse_args()

    if not (args.view or args.analyze):
        args.view = True  # 既定は閲覧

    html, final = fetch(args.url, insecure=args.insecure)
    art = extract_article(html, final)

    if args.analyze:
        plain = as_plain(art)
        if args.out:
            _write(args.out, plain)
            print("分析用テキストを書いた:", args.out,
                  "(レス%d件 / 本文%d字)" % (len(art["reslist"]), len(art["body_text"])))
        else:
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")
            sys.stdout.write(plain)
        return

    # --view
    if args.to_stdout:
        plain = as_plain(art)
        if args.out:
            _write(args.out, plain)
            print("テキストを書いた:", args.out)
        else:
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")
            sys.stdout.write(plain)
        return

    slug = _slug(final)
    hpath = args.out or os.path.join(OUT_DIR, slug + ".html")
    tpath = os.path.splitext(hpath)[0] + ".txt"
    _write(hpath, as_clean_html(art))
    _write(tpath, as_plain(art))
    print("クリーン閲覧HTML:", hpath)
    print("素テキスト     :", tpath)
    print("題名:", art["title"] or "(取れず)")
    print("レス%d件 / 本文%d字" % (len(art["reslist"]), len(art["body_text"])))


if __name__ == "__main__":
    main()
