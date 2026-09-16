#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""期間を指定して「配った告知＋それへの相槌」を退避してから消す(2026-08-05)。

なぜ作ったか:
  Chami直命(2026-07-22 23:26 JST / msg 1529494745104121938)
    「さっき配った文章Discord上のやつめっちゃ長かったし必要ないから
      あの配ったやつとそれに応答する。了解しましたみたいな各部門のやりとり消しといて」
  既存の purge_broadcast.py は「直近30件・6時間以内」しか見ないため13日前の便に届かない。
  それを取りに行く道具。C-003(こっちが消しといてと言ったら消す)の執行用。

安全策(削除は不可逆):
  - **先に退避**: 対象候補を local/_work/ へJSONLで丸ごと書き出してから消す(--dump だけでも可)。
  - **webhook投稿のみ**を消す(人間=Chamiの発言・bot発言には触らない)。
  - **期間で限る**(--after/--before・snowflakeで厳密に)。
  - 既定は列挙のみ。--delete を明示しない限り1件も消さない。
  - 判断がつかないものは残す側に倒す(相槌の判定は短文＋定型句の両方を満たす時だけ)。

使い方:
  python scripts/discord/purge_window.py --after 2026-07-22T00:00+09:00 --before 2026-07-23T12:00+09:00 --dump
  python scripts/discord/purge_window.py ... --marker "<告知の固有文字列>" --delete
"""
import argparse
import datetime as dt
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)
except Exception:
    pass

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
LOCAL = os.environ.get("GO5_LOCAL_DIR") or os.path.join(ROOT, "local")
WORK = os.path.join(LOCAL, "_work")
API = "https://discord.com/api/v10"
CHANNELS_JSON = os.path.join(LOCAL, "discord_channels.json")
DISCORD_EPOCH = 1420070400000

# 「了解しました」型の相槌(これ**だけ**で構成された短い投稿)を消す対象にする。
ACK_PAT = re.compile(
    r"(了解|承知|把握しました|確認しました|かしこまり|受領|対応します|反映します|周知|ラジャー|OK です|了解です)")
ACK_MAX_LEN = 400   # これより長い投稿は「相槌」とみなさない(中身がある=残す)


def token():
    with open(os.path.join(LOCAL, "discord_bot_token.txt"), encoding="utf-8") as f:
        return f.read().strip()


def api(path, tok, method="GET"):
    req = urllib.request.Request(
        API + path, method=method,
        headers={"Authorization": "Bot " + tok,
                 "User-Agent": "go5-org-purge (personal, v1)"})
    with urllib.request.urlopen(req, timeout=25) as r:
        body = r.read()
        return json.loads(body) if body else None


def to_snowflake(iso):
    d = dt.datetime.fromisoformat(iso)
    if d.tzinfo is None:
        d = d.replace(tzinfo=dt.timezone(dt.timedelta(hours=9)))
    return (int(d.timestamp() * 1000) - DISCORD_EPOCH) << 22


def jst_of(msg_id):
    ms = ((int(msg_id) >> 22) + DISCORD_EPOCH) / 1000.0
    return dt.datetime.fromtimestamp(ms, dt.timezone(dt.timedelta(hours=9))).strftime("%Y-%m-%d %H:%M:%S")


def channels():
    with open(CHANNELS_JSON, encoding="utf-8") as f:
        data = json.load(f)
    rows = data if isinstance(data, list) else data.get("channels", list(data.values()))
    out = []
    for r in rows:
        if isinstance(r, dict) and r.get("id"):
            out.append((str(r.get("name") or r.get("dept") or "?"), str(r["id"])))
    return out


def fetch_window(tok, cid, after_sf, before_sf):
    """[after, before) の全メッセージを古い順に集める(100件ずつ・afterページング)。"""
    got, cursor = [], after_sf
    while True:
        try:
            msgs = api(f"/channels/{cid}/messages?limit=100&after={cursor}", tok)
        except urllib.error.HTTPError as e:
            return got, e.code
        if not msgs:
            break
        msgs = sorted(msgs, key=lambda m: int(m["id"]))
        stop = False
        for m in msgs:
            if int(m["id"]) >= before_sf:
                stop = True
                break
            got.append(m)
        cursor = str(max(int(m["id"]) for m in msgs))
        if stop or len(msgs) < 100:
            break
        time.sleep(0.35)
    return got, 0


def slim(name, cid, m):
    a = m.get("author") or {}
    return {"channel": name, "channel_id": cid, "msg_id": m["id"], "jst": jst_of(m["id"]),
            "author": a.get("username"), "author_id": a.get("id"),
            "webhook_id": m.get("webhook_id"), "is_bot": bool(a.get("bot")),
            "len": len(m.get("content") or ""), "content": m.get("content") or "",
            "attachments": [x.get("filename") for x in (m.get("attachments") or [])]}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--after", required=True)
    ap.add_argument("--before", required=True)
    ap.add_argument("--marker", default=None, help="告知の固有文字列(これを含むwebhook投稿=告知本体)")
    ap.add_argument("--dump", action="store_true", help="期間内の全メッセージを退避JSONLへ書く")
    ap.add_argument("--delete", action="store_true", help="実際に消す(既定は列挙のみ)")
    ap.add_argument("--ids-file", default=None,
                    help="msg_idのJSON配列。**このIDだけ**を対象にする(人が目で選んだ結果を渡す=自動判定より狭い)")
    ap.add_argument("--tag", default="purge_window")
    a = ap.parse_args()

    only_ids = None
    if a.ids_file:
        only_ids = set(str(x) for x in json.load(open(a.ids_file, encoding="utf-8")))
        print(f"ids-file指定: {len(only_ids)}件だけを対象にする")

    after_sf, before_sf = to_snowflake(a.after), to_snowflake(a.before)
    tok = token()
    os.makedirs(WORK, exist_ok=True)
    stamp = time.strftime("%Y%m%d%H%M%S")
    dump_path = os.path.join(WORK, f"{a.tag}_{stamp}.jsonl")

    all_rows, targets = [], []
    for name, cid in channels():
        msgs, err = fetch_window(tok, cid, after_sf, before_sf)
        if err:
            print(f"[読めない] {name} HTTP {err}")
            continue
        if not msgs:
            continue
        print(f"{name}: {len(msgs)}件")
        for m in msgs:
            row = slim(name, cid, m)
            all_rows.append(row)
            if not row["webhook_id"]:
                continue                       # 人間・botの発言は触らない
            body = row["content"]
            if only_ids is not None:
                if row["msg_id"] in only_ids:
                    row["_why"] = "ids-file指定"
                    targets.append(row)
                continue
            if a.marker and a.marker in body:
                row["_why"] = "告知本体(marker一致)"
                targets.append(row)
            elif len(body) <= ACK_MAX_LEN and ACK_PAT.search(body):
                row["_why"] = "相槌(短文＋定型句)"
                targets.append(row)

    if a.dump or not a.delete:
        with open(dump_path, "w", encoding="utf-8") as f:
            for r in all_rows:
                f.write(json.dumps(r, ensure_ascii=False) + "\n")
        print(f"\n退避: {dump_path} ({len(all_rows)}件)")

    print(f"\n削除候補 {len(targets)}件")
    by_ch = {}
    for r in targets:
        by_ch.setdefault(r["channel"], []).append(r)
    for ch, rows in sorted(by_ch.items()):
        print(f"  {ch}: {len(rows)}件")
        for r in rows:
            print(f"    {r['msg_id']} {r['jst']} [{r['_why']}] {r['content'][:60].replace(chr(10),' ')}")

    if not a.delete:
        print("\n(列挙のみ。実際に消すには --delete)")
        return

    hooks = {}
    for fn in ("discord_webhooks_personas.json", "discord_webhooks_auto.json"):
        p = os.path.join(LOCAL, fn)
        if not os.path.exists(p):
            continue
        try:
            data = json.load(open(p, encoding="utf-8"))
        except Exception:
            continue
        for k, v in (data or {}).items():
            c = str(k).split(":")[0]
            url = v if isinstance(v, str) else (v or {}).get("url")
            if url and url.startswith("https://discord.com/api/webhooks/"):
                hooks.setdefault(c, [])
                if url not in hooks[c]:
                    hooks[c].append(url)

    ok, ng = 0, []
    for r in targets:
        done = False
        for base in hooks.get(r["channel_id"], []):
            try:
                req = urllib.request.Request(f"{base}/messages/{r['msg_id']}", method="DELETE",
                                             headers={"User-Agent": "go5-org-purge (personal, v1)"})
                urllib.request.urlopen(req, timeout=20).read()
                done = True
                break
            except urllib.error.HTTPError:
                continue
        if not done:
            try:
                api(f"/channels/{r['channel_id']}/messages/{r['msg_id']}", tok, method="DELETE")
                done = True
            except urllib.error.HTTPError as e:
                ng.append((r["channel"], r["msg_id"], e.code))
                print(f"  [削除NG] {r['channel']} {r['msg_id']} HTTP {e.code}")
        if done:
            ok += 1
            print(f"  [削除OK] {r['channel']} {r['msg_id']}")
        time.sleep(0.9)
    print(f"\n削除 {ok} / 失敗 {len(ng)}")
    for ch, mid, code in ng:
        print(f"  失敗: {ch} {mid} HTTP {code}")


if __name__ == "__main__":
    main()
