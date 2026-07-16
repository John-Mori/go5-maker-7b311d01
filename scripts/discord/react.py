#!/usr/bin/env python3
"""Discordメッセージにリアクションを押す (AI組織の進捗印・2026-07-16 Chami依頼)。

2段階印の2つ目「着手」を、応対するClaudeセッションが依頼を拾った瞬間に押す。
(1つ目「既読」は inbox_poller.py が配達時に自動で押す)
これで Chami の画面から「未達 / 届いたが無人 / 着手済み」が一目で分かる。

使い方:
  python scripts/discord/react.py --channel 改修-依頼 --msg 1526809157544574976
  python scripts/discord/react.py --channel 1525646154933735425 --msg <id> --emoji 既読
オプション:
  --channel  チャンネル名(local/discord_channels.jsonのname) または チャンネルID
  --msg      対象メッセージID(受信箱レコードの msg_id)
  --emoji    絵文字名(既定: 着手)。サーバー絵文字を名前で解決、無ければUnicode代用
"""
import json
import os
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
LOCAL = os.path.join(ROOT, "local")
API = "https://discord.com/api/v10"
FALLBACK = {"着手": "👀", "既読": "✅"}  # サーバー絵文字が未登録の間の代用
# 呼び名(日本語) → Chami登録の実際の絵文字名。どちらで指定しても解決する
ALIAS = {"着手": ["chakusyu", "着手"], "既読": ["kidoku", "既読"]}


def read_token():
    p = os.path.join(LOCAL, "discord_bot_token.txt")
    with open(p, "r", encoding="utf-8") as f:
        return f.read().strip()


def resolve_channel(spec):
    s = str(spec or "").strip()
    if s.isdigit():
        return s
    with open(os.path.join(LOCAL, "discord_channels.json"), "r", encoding="utf-8") as f:
        for c in json.load(f):
            if c.get("name") == s:
                return str(c.get("id", ""))
    return ""


def api(path, token, method="GET"):
    req = urllib.request.Request(
        API + path, method=method, data=(b"" if method == "PUT" else None),
        headers={"Authorization": "Bot " + token, "User-Agent": "go5-org-react (personal, v1)"},
    )
    for _ in range(3):
        try:
            with urllib.request.urlopen(req, timeout=20) as r:
                body = r.read().decode("utf-8")
                return json.loads(body) if body else True
        except urllib.error.HTTPError as e:
            if e.code == 429:
                try:
                    wait = float(json.loads(e.read().decode("utf-8")).get("retry_after", 1))
                except Exception:
                    wait = 1.0
                time.sleep(min(wait, 10) + 0.3)
                continue
            print(f"HTTP {e.code}: {path}")
            return None
    return None


def resolve_emoji(token, cid, name):
    """サーバー絵文字を名前で解決して name:id へ。無ければUnicode代用(それも無ければそのまま)。"""
    try:
        ch = api(f"/channels/{cid}", token)
        gid = str((ch or {}).get("guild_id", "") or "")
        if gid:
            emojis = api(f"/guilds/{gid}/emojis", token) or []
            for want in ALIAS.get(name, [name]):   # 実名(chakusyu) → 呼び名(着手) の順で探す
                for e in emojis:
                    if e.get("name") == want and e.get("id"):
                        return f"{e['name']}:{e['id']}"
    except Exception:
        pass
    return FALLBACK.get(name, name)


def main():
    args = sys.argv[1:]
    ch = msg = ""
    emoji_name = "着手"
    i = 0
    while i < len(args):
        if args[i] == "--channel" and i + 1 < len(args):
            ch = args[i + 1]; i += 2
        elif args[i] == "--msg" and i + 1 < len(args):
            msg = args[i + 1]; i += 2
        elif args[i] == "--emoji" and i + 1 < len(args):
            emoji_name = args[i + 1]; i += 2
        else:
            i += 1
    if not ch or not msg:
        print("使い方: react.py --channel <名前|ID> --msg <メッセージID> [--emoji 着手]")
        sys.exit(2)
    cid = resolve_channel(ch)
    if not cid:
        print(f"チャンネルを解決できません: {ch}")
        sys.exit(2)
    token = read_token()
    emoji = urllib.parse.quote(resolve_emoji(token, cid, emoji_name))
    ok = api(f"/channels/{cid}/messages/{msg}/reactions/{emoji}/@me", token, method="PUT")
    if ok:
        print(f"リアクションOK → {ch} msg={msg} :{emoji_name}:")
    else:
        print("リアクション失敗(権限/ID/絵文字を確認)")
        sys.exit(1)


if __name__ == "__main__":
    main()
