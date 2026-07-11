#!/usr/bin/env python3
"""Discord Webhook通知 (Phase DA・AI組織のOUT口)。

使い方:
  python scripts/kaizen/discord_notify.py "メッセージ本文"
  echo "本文" | python scripts/kaizen/discord_notify.py
  python scripts/kaizen/discord_notify.py --title "デプロイ完了" "本文..."

前提: local/discord_webhook.txt にWebhook URLを1行で保存(手順=local/discord_setup.md)。
      URLは秘密扱い(gitignore済のlocal/のみ・出力にも表示しない)。
"""
import json
import os
import sys
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.normpath(os.path.join(HERE, "..", ".."))
HOOK_FILE = os.path.join(ROOT, "local", "discord_webhook.txt")


def main():
    args = sys.argv[1:]
    title = ""
    if args and args[0] == "--title" and len(args) >= 2:
        title = args[1]
        args = args[2:]
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
