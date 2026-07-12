#!/usr/bin/env python3
"""投稿履歴の計測コード(r2短縮URL)バックフィル。

対象: シートの短縮URL列にr2計測URLが無い行(da.gd直リンク時代/Bitly時代/空)。
方法: Bluesky投稿URLを特定して r2 /api/shorten(冪等) → GAS sync_historyで短縮URL列を更新。
  特定手段(優先順): ①postUri ②da.gd/bit.ly等のリダイレクト解決 ③作者feedのcidリンク照合(手動投稿時代は
  シート時刻=YT時刻でBluesky実投稿とズレるため、投稿本文のdmm cid=行のcid一致で当てる。時刻は同率時のタイブレークのみ)
安全: 既定はドライラン(何も書かない)。--go で実行。テスト行(test/テスト)は除外。
使い方: python scripts/maintenance/backfill_short_links.py [--go]
"""
import datetime
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.normpath(os.path.join(HERE, "..", ".."))
GAS = json.load(open(os.path.join(ROOT, "scripts", "gas_deploy_config.json"), encoding="utf-8"))["execUrl"]
R2 = "https://r2.trustsignalbot.workers.dev"
ORIGIN = "https://john-mori.github.io"
DIDS = {"acc1": "did:plc:shidd44xs2jyq6pqsreaqmrc", "acc2": "did:plc:ytx35ji7pykeezwtkggxtur7"}


def jsonp(q, tries=3):
    for i in range(tries):
        try:
            with urllib.request.urlopen(f"{GAS}?{q}&callback=x", timeout=90) as r:
                return json.loads(re.sub(r'^x\(|\)$', '', r.read().decode("utf-8", "replace").strip()))
        except Exception:
            time.sleep(3)
    return {}


def gas_post(payload, tries=3):
    for i in range(tries):
        try:
            req = urllib.request.Request(GAS, data=json.dumps(payload).encode("utf-8"),
                                         headers={"Content-Type": "application/json"})
            with urllib.request.urlopen(req, timeout=90) as r:
                return json.loads(r.read())
        except Exception:
            time.sleep(3)
    return {}


def _secrets():
    """X-Shared-Secret候補(順に試す)。値は出力しないこと。"""
    out = []
    try:
        cfg = json.load(open(os.path.join(ROOT, "scripts", "scrape_config.json"), encoding="utf-8"))
        for k in ("sharedSecret", "adminSecret"):
            if cfg.get(k):
                out.append(cfg[k])
    except Exception:
        pass
    # GASのshortSecret_と同じソフト鍵(リポジトリ内既出のフォールバック)
    out.append("daremogamewoubawareteikukimihakanpekidekyukyokunoidol")
    return out


def shorten(url):
    last_err = ""
    for sec in _secrets():
        req = urllib.request.Request(f"{R2}/api/shorten", data=json.dumps({"url": url}).encode("utf-8"),
                                     headers={"Content-Type": "application/json", "Origin": ORIGIN,
                                              "X-Shared-Secret": sec,
                                              "User-Agent": "Mozilla/5.0 (go5-backfill)"})  # 素のPython-urllibはWAFに403で弾かれる
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                d = json.loads(r.read())
            if d.get("shortUrl") or d.get("short"):
                return d.get("shortUrl") or d.get("short")
            last_err = d.get("error", "")
        except urllib.error.HTTPError as e:
            try:
                last_err = json.loads(e.read().decode("utf-8", "replace")).get("error", str(e.code))
            except Exception:
                last_err = str(e.code)
            if last_err != "bad_secret":
                break
    print(f"  shorten拒否: {last_err}")
    return ""


def resolve(u, depth=0):
    """他社短縮のリダイレクト先を追う(GET+UA・最大4段。本文はダウンロードしない)。"""
    if not u or depth > 4:
        return u or ""

    class NR(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, *a, **k):
            return None
    op = urllib.request.build_opener(NR)
    try:
        with op.open(urllib.request.Request(u, headers={"User-Agent": "Mozilla/5.0"}), timeout=20):
            return u
    except urllib.error.HTTPError as e:
        loc = e.headers.get("Location", "")
        return resolve(loc, depth + 1) if loc else u
    except Exception:
        return u


def links_of(rec):
    out = []
    for f in (rec.get("facets") or []):
        for feat in f.get("features", []):
            if feat.get("uri"):
                out.append(feat["uri"])
    ext = (rec.get("embed") or {}).get("external") or {}
    if ext.get("uri"):
        out.append(ext["uri"])
    return out


def author_posts(did, pages=4):
    """作者の投稿一覧(リンク展開込み)。新しい順・最大 pages*100 件。"""
    out, cursor = [], ""
    for _ in range(pages):
        u = f"https://public.api.bsky.app/xrpc/app.bsky.feed.getAuthorFeed?actor={did}&limit=100"
        if cursor:
            u += f"&cursor={urllib.parse.quote(cursor)}"
        try:
            with urllib.request.urlopen(u, timeout=30) as r:
                d = json.loads(r.read())
        except Exception:
            break
        for f in d.get("feed", []):
            if f.get("reason"):
                continue  # リポスト除外
            p = f.get("post", {})
            rec = p.get("record", {})
            out.append({"uri": p.get("uri", ""), "created": rec.get("createdAt", ""),
                        "text": rec.get("text", ""), "links": links_of(rec)})
        cursor = d.get("cursor", "")
        if not cursor:
            break
    return out


def post_cids(p, cache={}):
    """投稿内リンク(da.gd等は解決済みへ展開)からdmmのcidを抽出。"""
    key = p["uri"]
    if key in cache:
        return cache[key]
    cids = set()
    for l in p["links"]:
        fin = resolve(l) if re.search(r'(da\.gd|x\.gd|bit\.ly)/', l) else l
        for m in re.finditer(r'cid=([a-z0-9_]+)', urllib.parse.unquote(fin)):  # al.fanzaのlurl内=URLエンコードcidも拾う
            cids.add(m.group(1))
    cache[key] = cids
    return cids


def uri_to_url(uri):
    m = re.match(r'at://(did:plc:[a-z0-9]+)/app\.bsky\.feed\.post/(\w+)', uri)
    return f"https://bsky.app/profile/{m.group(1)}/post/{m.group(2)}" if m else ""


def main():
    go = "--go" in sys.argv
    print("モード:", "実行(--go)" if go else "ドライラン")
    plans, feeds = {}, {}
    for ch in ("acc1", "acc2"):
        items = jsonp(f"action=history&channel={ch}&limit=120").get("items", [])
        print(f"== {ch}: {len(items)}行 ==")
        plan = []
        for it in items:
            vid = it.get("videoId") or ""
            title = it.get("title") or ""
            su = it.get("shortUrl") or ""
            if "workers.dev" in su:
                continue  # 既にr2
            if "test" in vid.lower() or "テスト" in title:
                continue
            bsky, src, uri = "", "", it.get("postUri") or ""
            if uri:
                bsky, src = uri_to_url(uri), "postUri"
            if not bsky:
                for cand in (su, it.get("shareUrl") or ""):
                    if re.search(r'(da\.gd|x\.gd|bit\.ly)/', cand or ""):
                        loc = resolve(cand)
                        if "bsky.app" in loc:
                            bsky, src = loc.split("?")[0], f"リダイレクト解決({cand})"
                            break
            if not bsky:
                did = DIDS[ch]
                if did not in feeds:
                    feeds[did] = author_posts(did)
                cid = it.get("cid") or ""
                cands = [p for p in feeds[did] if cid and cid in post_cids(p)] if cid else []
                if cands:
                    best = cands[0]
                    if len(cands) > 1 and it.get("postedAt"):
                        t0 = datetime.datetime.fromisoformat(it["postedAt"].replace("Z", "+00:00"))
                        def dist(p):
                            try:
                                return abs((datetime.datetime.fromisoformat(p["created"].replace("Z", "+00:00")) - t0).total_seconds())
                            except Exception:
                                return 1e18
                        best = min(cands, key=dist)
                    bsky, uri = uri_to_url(best["uri"]), best["uri"]
                    src = f"cid照合({cid}) 投稿={best['created']} text={best['text'][:30]!r}"
            if not bsky:
                plan.append({"videoId": vid, "action": "SKIP(投稿特定不可)", "title": title[:24], "cid": it.get("cid") or ""})
                continue
            plan.append({"videoId": vid, "action": "repair", "src": src, "bsky": bsky,
                         "postUri": uri, "postedAt": it.get("postedAt") or "", "title": title[:24]})
        plans[ch] = plan
        for p in plan:
            print(" ", json.dumps(p, ensure_ascii=False))
    if not go:
        print("\nドライラン終了。実行は --go を付ける。")
        return
    for ch, plan in plans.items():
        items = []
        for p in plan:
            if p["action"] != "repair":
                continue
            short = shorten(p["bsky"])
            if not short:
                print(f"  shorten失敗: {p['videoId']}")
                continue
            entry = {"videoId": p["videoId"], "shortUrl": short, "postedAt": p["postedAt"]}
            if p.get("postUri"):
                entry["postUri"] = p["postUri"]
            items.append(entry)
            print(f"  {p['videoId']} → {short}")
            time.sleep(0.4)
        if items:
            res = gas_post({"op": "sync_history", "channel": ch, "items": items})
            print(f"== {ch} シート更新: {res}")
    print("スナップショット即時実行...")
    print(jsonp("action=snapshot_now"))


if __name__ == "__main__":
    main()
