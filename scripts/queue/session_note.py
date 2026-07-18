#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""session_note — セッション間連絡をSendMessageの代わりに受信箱へ直接投函する (2026-07-18)。

なぜ作るか (Chami指示「SendMessageが相変わらず多い。減らして」):
  SendMessage (セッション間メッセージ) は**毎回Chamiの承認プロンプトを要求**する。
  一方、各セッションは自分の受信箱 (main=local/discord_inbox.jsonl / 部門=local/inbox/<dept>.jsonl)
  をwaiterで見張っており、**箱に行が増えれば承認なしで即起床**する。
  受付AIのエスカレも同じ「main箱へ直接追記」方式が公認済み (memory: escalation-to-main-box)。
  よってセッション間連絡はこの箱経由を既定とし、SendMessageは「即時・重大」のみに絞る。

使い方:
  python scripts/queue/session_note.py --to router --sender qa-reviewer --body-file <path>
  python scripts/queue/session_note.py --to system-engineer --sender qa-reviewer "短い連絡"
  --to router|main = 研究室 (main箱) / それ以外 = 部門箱 (local/inbox/<dept>.jsonl)

レコード形式は鳩の配達と同型+type='session-note'。channelは空 (返信先ch不要=P1受領スタンプの
対象外になる)。msg_idは 'note-<sender>-<epoch>' で冪等・追跡可能。
"""
import json
import os
import sys
import time
from datetime import datetime, timezone

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.normpath(os.path.join(HERE, "..", ".."))
LOCAL = os.environ.get("GO5_LOCAL_DIR") or os.path.join(ROOT, "local")


def box_path(to):
    if to in ("router", "main", "research-room"):
        return os.path.join(LOCAL, "discord_inbox.jsonl")
    return os.path.join(LOCAL, "inbox", f"{to}.jsonl")


def main():
    args = sys.argv[1:]
    to = sender = body_file = None
    rest = []
    i = 0
    while i < len(args):
        if args[i] == "--to" and i + 1 < len(args):
            to = args[i + 1]; i += 2
        elif args[i] == "--sender" and i + 1 < len(args):
            sender = args[i + 1]; i += 2
        elif args[i] == "--body-file" and i + 1 < len(args):
            body_file = args[i + 1]; i += 2
        else:
            rest.append(args[i]); i += 1
    if not to or not sender:
        print("使い方: session_note.py --to <router|dept> --sender <自dept> [--body-file path | 本文]")
        return 1
    body = open(body_file, encoding="utf-8").read().strip() if body_file else " ".join(rest).strip()
    if not body:
        print("本文が空です。")
        return 1
    rec = {
        "type": "session-note",              # Discord発言でなくセッション間連絡であることの明示
        "ts": datetime.now(timezone.utc).isoformat(),
        "channel": "",                        # 返信先ch無し=受領スタンプ等の対象外
        "dept": "router" if to in ("main", "research-room") else to,
        "author": f"{sender}(session)",
        "author_id": "",
        "content": body,
        "attachments": [],
        "msg_id": f"note-{sender}-{int(time.time() * 1000)}",
    }
    p = box_path(to)
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, "a", encoding="utf-8") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    print(f"投函OK → {p} msg={rec['msg_id']} (相手のwaiterが次の見張り周期で起きる)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
