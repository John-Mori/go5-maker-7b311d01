#!/usr/bin/env python3
"""Discord Webhook通知 (Phase DA・AI組織のOUT口)。

使い方:
  python scripts/kaizen/discord_notify.py "メッセージ本文"
  echo "本文" | python scripts/kaizen/discord_notify.py
  python scripts/kaizen/discord_notify.py --title "デプロイ完了" "本文..."
  python scripts/kaizen/discord_notify.py --channel qa --title "QA結果" "全項目合格"
    → local/discord_webhook_qa.txt を使う(部門チャンネル出し分け。無指定=discord_webhook.txt)

前提: local/discord_webhook.txt (または _<channel>.txt) にWebhook URLを1行で保存(手順=local/discord_setup.md)。
      URLは秘密扱い(gitignore済のlocal/のみ・出力にも表示しない)。
"""
import json
import os
import sys
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.normpath(os.path.join(HERE, "..", ".."))


def hook_file(channel):
    name = f"discord_webhook_{channel}.txt" if channel else "discord_webhook.txt"
    return os.path.join(ROOT, "local", name)


def main():
    args = sys.argv[1:]
    title = ""
    channel = ""
    while args and args[0] in ("--title", "--channel") and len(args) >= 2:
        if args[0] == "--title":
            title = args[1]
        else:
            channel = args[1]
        args = args[2:]
    HOOK_FILE = hook_file(channel)
    body = " ".join(args) if args else sys.stdin.read().strip()
    if not body:
        print("本文が空です。引数か標準入力で渡してください。")
        sys.exit(1)
    if not os.path.exists(HOOK_FILE):
        print("Webhook未設定: local/discord_webhook.txt がありません(手順=local/discord_setup.md)。")
        sys.exit(2)
    with open(HOOK_FILE, "r", encoding="utf-8") as f:
        url = f.read().strip()
    content = (f"**{title}**\n{body}" if title else body)[:1900]  # Discord上限2000の安全側
    req = urllib.request.Request(
        url,
        data=json.dumps({"content": content}).encode("utf-8"),
        headers={"Content-Type": "application/json", "User-Agent": "go5-kaizen-notify"},
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            print(f"送信OK (HTTP {r.status})")
    except Exception as e:  # URLを出力しない
        print(f"送信失敗: {type(e).__name__}")
        sys.exit(3)


if __name__ == "__main__":
    main()
