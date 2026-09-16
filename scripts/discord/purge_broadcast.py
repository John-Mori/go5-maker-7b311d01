#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""誤配信した一斉告知を撤収する(2026-07-20)。

    python scripts/discord/purge_broadcast.py            # 対象を列挙するだけ(既定=安全側)
    python scripts/discord/purge_broadcast.py --delete   # 実際に削除

安全策(削除は取り消せないため):
  - **webhook投稿のみ**を対象にする(人間/botの発言は絶対に触らない)
  - **MARKER を含む本文のみ**(部分一致ではなく、告知固有の文字列)
  - **MAX_AGE_SEC 以内**のものだけ(古い投稿を巻き込まない)
  - 既定は列挙のみ。--delete を明示しない限り何も消さない
"""
import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
LOCAL = os.environ.get("GO5_LOCAL_DIR") or os.path.join(ROOT, "local")
API = "https://discord.com/api/v10"
CHANNELS_JSON = os.path.join(LOCAL, "discord_channels.json")

MARKER = "【全部門連絡】2026-07-20 研究室HQセッションの決定事項"
MAX_AGE_SEC = 6 * 3600
DISCORD_EPOCH = 1420070400000


def token():
    with open(os.path.join(LOCAL, "discord_bot_token.txt"), encoding="utf-8") as f:
        return f.read().strip()


def api(path, tok, method="GET"):
    req = urllib.request.Request(
        API + path, method=method,
        headers={"Authorization": "Bot " + tok, "User-Agent": "go5-org-purge (personal, v1)"})
    with urllib.request.urlopen(req, timeout=20) as r:
        body = r.read()
        return json.loads(body) if body else None


def age_of(msg_id):
    ts = ((int(msg_id) >> 22) + DISCORD_EPOCH) / 1000.0
    return time.time() - ts


def load_webhooks():
    """persona_sendがキャッシュしたwebhook URL(トークン込み)を channel_id -> [url] で返す。"""
    out = {}
    for fn in ("discord_webhooks_personas.json", "discord_webhooks_auto.json"):
        p = os.path.join(LOCAL, fn)
        if not os.path.exists(p):
            continue
        try:
            data = json.load(open(p, encoding="utf-8"))
        except Exception:
            continue
        for k, v in (data or {}).items():
            # キーは "<channel_id>" か "<channel_id>:<persona>" のどちらか
            cid = str(k).split(":")[0]
            url = v if isinstance(v, str) else (v or {}).get("url")
            if url and url.startswith("https://discord.com/api/webhooks/"):
                out.setdefault(cid, [])
                if url not in out[cid]:
                    out[cid].append(url)
    return out


def channel_ids():
    with open(CHANNELS_JSON, encoding="utf-8") as f:
        data = json.load(f)
    if isinstance(data, dict):
        rows = data.get("channels", data.values())
    else:
        rows = data
    out = []
    for r in rows:
        if isinstance(r, dict) and r.get("id"):
            out.append((r.get("name", "?"), str(r["id"])))
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--delete", action="store_true", help="実際に削除する(既定は列挙のみ)")
    # ★2026-07-22 引数化(既定値は従来のまま=既存の挙動を変えない)。
    #   理由= MARKER が2026-07-20の告知に固定されていて、別の誤配信に使えなかった。
    #   道具は残す・既定は変えない・必要な時だけ上書きする(C-010=追加のみ)。
    ap.add_argument("--marker", default=MARKER,
                    help="この文字列を含むwebhook投稿だけを対象にする(既定=2026-07-20の告知)")
    ap.add_argument("--max-age-sec", type=int, default=MAX_AGE_SEC,
                    help="この秒数より古い投稿は巻き込まない(既定=6時間)")
    a = ap.parse_args()
    marker, max_age = a.marker, a.max_age_sec
    tok = token()
    hits = []
    for name, cid in channel_ids():
        try:
            msgs = api(f"/channels/{cid}/messages?limit=30", tok)
        except urllib.error.HTTPError:
            continue
        for m in msgs or []:
            if not m.get("webhook_id"):
                continue                      # webhook投稿以外は触らない
            if marker not in (m.get("content") or ""):
                continue                      # 告知固有の文字列を含むものだけ
            if age_of(m["id"]) > max_age:
                continue                      # 古いものは巻き込まない
            hits.append((name, cid, m["id"]))
    print(f"対象 {len(hits)} 件")
    for name, _cid, mid in hits:
        print(f"  {name}  msg={mid}")
    if not a.delete:
        print("\n(列挙のみ。実際に消すには --delete)")
        return
    # webhook投稿は「botの発言」ではないため、bot tokenでのDELETEには Manage Messages が要る
    # (2026-07-20に20件全部403)。**webhookトークン経由なら権限不要で消せる**ので、
    # persona_sendがキャッシュしたwebhook URLを優先して使い、無い時だけbot tokenへ落とす。
    hooks = load_webhooks()
    ok, ng = 0, []
    for name, cid, mid in hits:
        done = False
        for base in hooks.get(cid, []):
            try:
                req = urllib.request.Request(f"{base}/messages/{mid}", method="DELETE",
                                             headers={"User-Agent": "go5-org-purge (personal, v1)"})
                urllib.request.urlopen(req, timeout=20).read()
                done = True
                break
            except urllib.error.HTTPError:
                continue
        if not done:
            try:
                api(f"/channels/{cid}/messages/{mid}", tok, method="DELETE")
                done = True
            except urllib.error.HTTPError as e:
                ng.append((name, e.code))
                print(f"  [削除NG] {name} HTTP {e.code}")
        if done:
            ok += 1
            print(f"  [削除OK] {name}")
        time.sleep(0.9)
    print(f"\n削除 {ok} / 失敗 {len(ng)}")
    if ng:
        print("失敗:", "、".join(f"{n}({c})" for n, c in ng))
        sys.exit(1)


if __name__ == "__main__":
    main()
