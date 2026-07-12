#!/usr/bin/env python3
"""Discord受信ポーラー (Phase DB・AI組織のIN口)。

各部門チャンネルの発言をポーリングで拾い、local/discord_inbox.jsonl へ追記する。
常駐起動: scripts/discord/start_discord_inbox.bat (または python inbox_poller.py)
動作テスト: python scripts/discord/inbox_poller.py --once

前提(local/・全てgitignore済):
  discord_bot_token.txt   … BotトークンURL1行(手順=local/discord_bot_setup.md)
  discord_channels.json   … [{"name":"総合-受付","id":"<チャンネルID>","dept":"router"},...]
仕様:
  - 初回はチャンネルの最新メッセージIDだけ記録し、過去ログは取り込まない
  - Bot/Webhook発言(author.bot / webhook_id)は無視(自分の返信で無限ループしないため)
  - トークン等の秘密は出力しない
"""
import json
import os
import sys
import time
import urllib.request
import urllib.error

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.normpath(os.path.join(HERE, "..", ".."))
LOCAL = os.path.join(ROOT, "local")
TOKEN_FILE = os.path.join(LOCAL, "discord_bot_token.txt")
CHANNELS_FILE = os.path.join(LOCAL, "discord_channels.json")
STATE_FILE = os.path.join(LOCAL, "discord_inbox_state.json")
INBOX_FILE = os.path.join(LOCAL, "discord_inbox.jsonl")
POLL_SEC = 45
API = "https://discord.com/api/v10"


def read_token():
    if not os.path.exists(TOKEN_FILE):
        print("Botトークン未設定: local/discord_bot_token.txt がありません(手順=local/discord_bot_setup.md)")
        sys.exit(2)
    with open(TOKEN_FILE, "r", encoding="utf-8") as f:
        return f.read().strip()


def read_channels():
    if not os.path.exists(CHANNELS_FILE):
        print("チャンネル表未設定: local/discord_channels.json がありません(手順=local/discord_bot_setup.md)")
        sys.exit(2)
    with open(CHANNELS_FILE, "r", encoding="utf-8") as f:
        chans = json.load(f)
    return [c for c in chans if str(c.get("id", "")).strip().isdigit()]


def load_state():
    if os.path.exists(STATE_FILE):
        with open(STATE_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}


def save_state(state):
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=1)


def api_get(path, token):
    req = urllib.request.Request(
        API + path,
        headers={"Authorization": "Bot " + token, "User-Agent": "go5-org-inbox (personal, v1)"},
    )
    for attempt in range(3):
        try:
            with urllib.request.urlopen(req, timeout=20) as r:
                return json.loads(r.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            if e.code == 429:
                try:
                    wait = float(json.loads(e.read().decode("utf-8")).get("retry_after", 2))
                except Exception:
                    wait = 2.0
                time.sleep(min(wait, 30) + 0.5)
                continue
            raise
    return None


def poll_channel(ch, token, state, out):
    cid = str(ch["id"])
    last = state.get(cid)
    if not last:
        msgs = api_get(f"/channels/{cid}/messages?limit=1", token)
        state[cid] = msgs[0]["id"] if msgs else "0"
        return 0
    msgs = api_get(f"/channels/{cid}/messages?limit=50&after={last}", token)
    if not msgs:
        return 0
    msgs.sort(key=lambda m: int(m["id"]))  # 古い順に処理
    new = 0
    for m in msgs:
        state[cid] = m["id"]
        if m.get("webhook_id") or m.get("author", {}).get("bot"):
            continue
        rec = {
            "ts": m.get("timestamp", ""),
            "channel": ch.get("name", cid),
            "dept": ch.get("dept", "router"),
            "author": m.get("author", {}).get("username", "?"),
            "content": m.get("content", ""),
            "attachments": [a.get("url") for a in m.get("attachments", [])],
            "msg_id": m["id"],
        }
        out.append(rec)
        new += 1
    return new


def main():
    once = "--once" in sys.argv
    token = read_token()
    channels = read_channels()
    if not channels:
        print("有効なチャンネルIDが0件です。local/discord_channels.json のidを埋めてください。")
        sys.exit(2)
    print(f"受信ポーラー開始: {len(channels)}チャンネルを{POLL_SEC}秒間隔で監視" + (" (--once)" if once else ""))
    while True:
        state = load_state()
        out = []
        for ch in channels:
            try:
                poll_channel(ch, token, state, out)
            except urllib.error.HTTPError as e:
                if e.code == 401:
                    print("トークンが無効です(401)。local/discord_bot_token.txt を確認してください。")
                    sys.exit(3)
                print(f"チャンネル取得失敗 [{ch.get('name')}] HTTP {e.code} (権限/IDを確認)")
            except Exception as e:
                print(f"チャンネル取得失敗 [{ch.get('name')}] {type(e).__name__}")
        if out:
            with open(INBOX_FILE, "a", encoding="utf-8") as f:
                for rec in out:
                    f.write(json.dumps(rec, ensure_ascii=False) + "\n")
            print(f"{time.strftime('%H:%M:%S')} 新着{len(out)}件 → local/discord_inbox.jsonl")
        save_state(state)
        if once:
            print(f"1回分の巡回完了(新着{len(out)}件)")
            break
        time.sleep(POLL_SEC)


if __name__ == "__main__":
    main()
