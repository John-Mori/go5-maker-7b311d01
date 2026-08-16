#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
競合チャンネルの YouTube コミュニティ投稿を収集する。

背景: 公式 Data API v3 にはコミュニティ投稿の窓口が無い(gas/競合.gs にも注記)。
      素の HTML GET は "This Community isn't available" で弾かれる(データセンタIP/未認証ゲート・2026-08-16実測)。
      → innertube browse API(youtubei/v1/browse・community タブの params)で取れる(実測で postRenderer を確認)。

出力: local/consult_intel/competitor_community.jsonl(1投稿=1行・post_id で追記デデュープ)
      列 = channel_id / channel_name / post_id / published / type(image|poll|video|text) /
           text / image_urls / vote_count / comment_count / post_url / fetched_at
分析部門(アーモンドアイ)が読む箱。手記録タブ 競合_コミュニティ観察 は潰さない(別物)。

使い方:
  python scripts/comp/community_scrape.py                # seeds を全部回す
  python scripts/comp/community_scrape.py UCxxxx UCyyyy  # 指定チャンネルだけ
  python scripts/comp/community_scrape.py --limit 5      # 1chあたり最大件数
"""
import sys, os, re, json, time, urllib.request, urllib.error, datetime, argparse

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SEEDS = os.path.join(ROOT, "local", "competitor_seeds.jsonl")
OUT = os.path.join(ROOT, "local", "consult_intel", "competitor_community.jsonl")

# 公開の WEB innertube キー(広く知られた固定値。秘密ではない)
INNERTUBE_KEY = "AIzaSyAO_FJ2SlqU8Q4STEHLGCilw_Y9_11qcW8"
# コミュニティ(投稿)タブの固定 params
COMMUNITY_PARAMS = "Egpjb21tdW5pdHnyBgQKAkoA"
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"


def _post(url, body):
    req = urllib.request.Request(
        url, data=json.dumps(body).encode("utf-8"),
        headers={"Content-Type": "application/json", "User-Agent": UA,
                 "Accept-Language": "ja-JP,ja;q=0.9"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read().decode("utf-8", "replace"))


def _ctx():
    return {"client": {"clientName": "WEB", "clientVersion": "2.20240101.00.00",
                       "hl": "ja", "gl": "JP"}}


def resolve_channel_id(url):
    """URL/ハンドルから UCxxxx を得る。UC 形式は直接抽出、@handle は resolve_url を叩く。"""
    m = re.search(r"(UC[0-9A-Za-z_-]{22})", url or "")
    if m:
        return m.group(1)
    m = re.search(r"(@[0-9A-Za-z_.\-]+)", url or "")
    if not m:
        return ""
    try:
        r = _post("https://www.youtube.com/youtubei/v1/navigation/resolve_url?key=" + INNERTUBE_KEY,
                  {"context": _ctx(), "url": "https://www.youtube.com/" + m.group(1)})
        s = json.dumps(r)
        mm = re.search(r"(UC[0-9A-Za-z_-]{22})", s)
        return mm.group(1) if mm else ""
    except Exception:
        return ""


def _runs(t):
    if not isinstance(t, dict):
        return ""
    if "runs" in t:
        return "".join(x.get("text", "") for x in t["runs"])
    return t.get("simpleText", "")


def _images(attachment):
    urls = []

    def dig(o):
        if isinstance(o, dict):
            if "backstageImageRenderer" in o:
                th = o["backstageImageRenderer"].get("image", {}).get("thumbnails", [])
                if th:
                    urls.append(th[-1].get("url", ""))
            for v in o.values():
                dig(v)
        elif isinstance(o, list):
            for x in o:
                dig(x)
    dig(attachment)
    return [u for u in urls if u]


def parse_posts(browse, channel_id, channel_name):
    posts = []

    def walk(o):
        if isinstance(o, dict):
            if "postRenderer" in o:
                posts.append(o["postRenderer"])
            for v in o.values():
                walk(v)
        elif isinstance(o, list):
            for x in o:
                walk(x)
    walk(browse)
    now = datetime.datetime.now().astimezone().isoformat(timespec="seconds")
    out = []
    for p in posts:
        pid = p.get("postId", "")
        att = p.get("backstageAttachment", {}) or {}
        typ = "text"
        if "pollRenderer" in att:
            typ = "poll"
        elif "videoRenderer" in att:
            typ = "video"
        elif "backstageImageRenderer" in att or "postMultiImageRenderer" in att:
            typ = "image"
        cc = ""
        ab = (p.get("actionButtons", {}) or {}).get("commentActionButtonsRenderer", {}) or {}
        rb = (ab.get("replyButton", {}) or {}).get("buttonRenderer", {}) or {}
        cc = _runs(rb.get("text"))
        out.append({
            "channel_id": channel_id,
            "channel_name": channel_name,
            "post_id": pid,
            "published": _runs(p.get("publishedTimeText")),
            "type": typ,
            "text": _runs(p.get("contentText")),
            "image_urls": _images(att),
            "vote_count": _runs(p.get("voteCount")),
            "comment_count": cc,
            "post_url": ("https://www.youtube.com/post/" + pid) if pid else "",
            "fetched_at": now,
        })
    return out


def channel_name_of(browse):
    def dig(o):
        if isinstance(o, dict):
            if "channelMetadataRenderer" in o:
                return o["channelMetadataRenderer"].get("title", "")
            for v in o.values():
                r = dig(v)
                if r:
                    return r
        elif isinstance(o, list):
            for x in o:
                r = dig(x)
                if r:
                    return r
        return ""
    return dig(browse) or ""


def fetch_channel(cid, limit):
    body = {"context": _ctx(), "browseId": cid, "params": COMMUNITY_PARAMS}
    browse = _post("https://www.youtube.com/youtubei/v1/browse?key=" + INNERTUBE_KEY, body)
    name = channel_name_of(browse)
    recs = parse_posts(browse, cid, name)
    if limit:
        recs = recs[:limit]
    return name, recs


def load_seed_channels():
    out = []
    if not os.path.exists(SEEDS):
        return out
    for line in open(SEEDS, encoding="utf-8"):
        line = line.strip()
        if not line:
            continue
        try:
            d = json.loads(line)
        except Exception:
            continue
        out.append(d.get("url", ""))
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("channels", nargs="*", help="UCxxxx / URL / @handle。無指定なら seeds を回す")
    ap.add_argument("--limit", type=int, default=0, help="1chあたり最大件数(0=全部)")
    ap.add_argument("--sleep", type=float, default=1.0, help="ch間の待ち秒")
    args = ap.parse_args()

    raw = args.channels if args.channels else load_seed_channels()
    seen_existing = set()
    if os.path.exists(OUT):
        for line in open(OUT, encoding="utf-8"):
            try:
                seen_existing.add(json.loads(line).get("post_id"))
            except Exception:
                pass

    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    total_new = 0
    with open(OUT, "a", encoding="utf-8") as fo:
        for raw_url in raw:
            cid = resolve_channel_id(raw_url)
            if not cid:
                print("SKIP(解決不可):", raw_url)
                continue
            try:
                name, recs = fetch_channel(cid, args.limit)
            except urllib.error.HTTPError as e:
                print("ERR", cid, e.code)
                continue
            except Exception as e:
                print("ERR", cid, repr(e))
                continue
            new = 0
            for r in recs:
                if r["post_id"] and r["post_id"] in seen_existing:
                    continue
                fo.write(json.dumps(r, ensure_ascii=False) + "\n")
                seen_existing.add(r["post_id"])
                new += 1
            total_new += new
            print(f"{cid} {name!r}: 取得{len(recs)} / 新規{new}")
            time.sleep(args.sleep)
    print(f"=== 新規 {total_new} 件を {OUT} へ追記 ===")


if __name__ == "__main__":
    main()
