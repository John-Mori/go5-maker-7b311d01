#!/usr/bin/env python3
"""Discord返信送信 (Phase DB・Bot経由のOUT口。webhook版discord_notify.pyの上位互換)。

使い方:
  python scripts/discord/bot_send.py "総合-受付" "本文..."
  python scripts/discord/bot_send.py --dept system-engineer "改修完了: ..."   (dept名でチャンネル解決)
  echo 本文 | python scripts/discord/bot_send.py "品質-QA"

前提: local/discord_bot_token.txt と local/discord_channels.json (手順=local/discord_bot_setup.md)。
秘密(トークン)は出力しない。本文は2000字制限の安全側1900字で切る。
"""
import json
import os
import sys
import urllib.request

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    # stdinもUTF-8に(パイプ経路 `echo 日本語 | bot_send` の文字化け根治・2026-07-15)。
    sys.stdin.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.normpath(os.path.join(HERE, "..", ".."))
LOCAL = os.path.join(ROOT, "local")

# ★炎上表記ゲート(素の🔥→<:enjoh:…> / 絵文字に隣接したラベル「炎上」→「恒久」・正本= enjoh.py)。
#   ここはBot APIのOUT口= webhook(persona_send)と並ぶ**もう1つの合流点**。2026-09-01 に
#   persona_send だけへ入れた結果、bot_send 経由の便(例 absence_watchdog の配送失敗警報)は
#   素の🔥がChamiの目の前へ出続けた= 部分適用。同じ実装を両方から呼んで割れを止める
#   (REQ-kaizen-analyst-90ebe8bfc8)。
if HERE not in sys.path:
    sys.path.insert(0, HERE)
try:
    from enjoh import enjoh_backstop
except Exception as _e:                        # 正本が読めない時も送信は殺さない(fail-open)
    print(f"[bot_send] 炎上表記ゲートの正本 enjoh.py を読めない({type(_e).__name__})=素通し。",
          file=sys.stderr)

    def enjoh_backstop(body, tag="bot_send"):
        return body


def main():
    args = sys.argv[1:]
    by_dept = False
    if args and args[0] == "--dept":
        by_dept = True
        args = args[1:]
    if not args:
        print("使い方: bot_send.py [--dept] <チャンネル名|dept> [本文]")
        sys.exit(1)
    key = args[0]
    body = " ".join(args[1:]) if len(args) > 1 else sys.stdin.read().strip()
    if not body:
        print("本文が空です。")
        sys.exit(1)
    with open(os.path.join(LOCAL, "discord_bot_token.txt"), "r", encoding="utf-8") as f:
        token = f.read().strip()
    with open(os.path.join(LOCAL, "discord_channels.json"), "r", encoding="utf-8") as f:
        channels = json.load(f)
    field = "dept" if by_dept else "name"
    ch = next((c for c in channels if c.get(field) == key and str(c.get("id", "")).strip().isdigit()), None)
    if not ch:
        print(f"チャンネル未登録: {key} (local/discord_channels.json を確認)")
        sys.exit(2)
    # ★POSTの直前=この口の最後の一点で正規化する(呼び出し元が何本あっても必ず通る)。
    body = enjoh_backstop(body, tag="bot_send")
    req = urllib.request.Request(
        f"https://discord.com/api/v10/channels/{ch['id']}/messages",
        data=json.dumps({"content": body[:1900]}).encode("utf-8"),
        headers={
            "Authorization": "Bot " + token,
            "Content-Type": "application/json",
            "User-Agent": "go5-org-send (personal, v1)",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            print(f"送信OK → {ch.get('name')} (HTTP {r.status})")
    except Exception as e:
        print(f"送信失敗: {type(e).__name__}")
        sys.exit(3)


if __name__ == "__main__":
    main()
