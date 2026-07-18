#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""discord_gateway — discord.py Gatewayで新着をpush受信し、リースキューへ入れる (恒久解 案A)。

現行の鳩(inbox_poller・15秒RESTポーリング)を将来置き換える受信口。本ファイルは
strangler移行の第一段=**シャドウモード**で動く:
  - Discord Gateway(WebSocket)で on_message を**即時**受信 (ポーリング周期という概念が消える)
  - 受信レコードを LeaseQueue(SQLite) へ enqueue する (msg_id冪等=二重投入無視)
  - ★返信しない・旧inbox(JSONL)に触らない・旧鳩と同時に動いてよい
    (両者は別の宛先へ書くso衝突しない。キューのmsg_id冪等が二重処理も防ぐ)
これにより「新しい受信経路が本番と同じ入力を正しく捌けるか」を、動いている系に一切
リスクを与えずに実測できる。切替(consumerを繋ぐ・旧鳩を止める)は別段階・Chami可視化の上で。

必要な前提 (Chamiのみ可能な設定):
  Discord Developer Portal → 対象Bot → Bot → Privileged Gateway Intents →
  「MESSAGE CONTENT INTENT」をON。これが無いと on_message の content が空になる
  (privileged intent。REST読取り=現行鳩には不要だったが、Gateway受信には必須)。
  未設定のまま起動すると discord.errors.PrivilegedIntentsRequired で即座に落ちる(=検知できる)。

使い方:
  python scripts/queue/discord_gateway.py --selftest   # Discordに繋がず内部配線だけ検証
  python scripts/queue/discord_gateway.py              # シャドウ稼働 (要 MESSAGE CONTENT INTENT)
"""
import json
import os
import sys
import time

sys.stdout.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.normpath(os.path.join(HERE, "..", ".."))
LOCAL = os.environ.get("GO5_LOCAL_DIR") or os.path.join(ROOT, "local")
sys.path.insert(0, HERE)
from leasequeue import LeaseQueue  # noqa: E402

TOKEN_FILE = os.path.join(LOCAL, "discord_bot_token.txt")
CHANNELS_FILE = os.path.join(LOCAL, "discord_channels.json")
QUEUE_DB = os.path.join(LOCAL, "queue", "inbox.db")
LOG_FILE = os.path.join(LOCAL, "discord_gateway.log")


def log(msg):
    line = f"{time.strftime('%Y-%m-%d %H:%M:%S')} {msg}"
    print(line)
    try:
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except OSError:
        pass


def load_channel_map():
    """channel_id -> {name, dept} を作る (受信を台帳のchだけに絞る)。"""
    try:
        chans = json.load(open(CHANNELS_FILE, encoding="utf-8"))
    except OSError:
        return {}
    return {str(c.get("id")): {"name": c.get("name", ""), "dept": c.get("dept", "router")}
            for c in chans if str(c.get("id", "")).isdigit()}


def record_from_message(m, chinfo):
    """discord.Message → 現行鳩と同じ形のレコード (後段が共通に読めるようにキーを揃える)。"""
    return {
        "ts": m.created_at.isoformat() if m.created_at else "",
        "channel": chinfo.get("name", ""),
        "dept": chinfo.get("dept", "router"),
        "author": getattr(m.author, "name", "?"),
        "author_id": str(getattr(m.author, "id", "") or ""),
        "content": m.content or "",
        "attachments": [a.url for a in m.attachments],
        "msg_id": str(m.id),
    }


def run_selftest():
    """Discordに接続せず、レコード生成→enqueue→冪等→statsの内部配線だけ検証する。"""
    import tempfile
    import shutil
    d = tempfile.mkdtemp(prefix="qa_gw_")
    try:
        q = LeaseQueue(os.path.join(d, "inbox.db"))

        class _A:  # 疑似 author
            name = "chami_fusoh"
            id = 490925528367497227

        class _M:  # 疑似 message
            id = 999001
            content = "テスト発言"
            created_at = None
            author = _A()
            attachments = []
        chinfo = {"name": "品質管理部門", "dept": "qa-reviewer"}
        rec = record_from_message(_M(), chinfo)
        ok1 = q.enqueue(json.dumps(rec, ensure_ascii=False), msg_id=rec["msg_id"], dept=rec["dept"])
        ok2 = q.enqueue(json.dumps(rec, ensure_ascii=False), msg_id=rec["msg_id"], dept=rec["dept"])
        c = q.claim(dept="qa-reviewer")
        print(f"  {'PASS' if ok1 else 'FAIL'}: 受信レコードをenqueueできる")
        print(f"  {'PASS' if ok2 is False else 'FAIL'}: 同一msg_idの再受信は無視 (鳩と並走しても二重処理しない)")
        print(f"  {'PASS' if c and c['body']['content']=='テスト発言' else 'FAIL'}: claimで内容が取れる")
        print(f"  {'PASS' if c and c['dept']=='qa-reviewer' else 'FAIL'}: deptが保たれる")
        allok = ok1 and (ok2 is False) and c and c["body"]["content"] == "テスト発言"
        print(f"\n== selftest {'PASS' if allok else 'FAIL'} ==")
        return 0 if allok else 1
    finally:
        shutil.rmtree(d, ignore_errors=True)


def run_gateway():
    import discord

    token = open(TOKEN_FILE, encoding="utf-8").read().strip()
    chan_map = load_channel_map()
    q = LeaseQueue(QUEUE_DB)

    intents = discord.Intents.default()
    intents.message_content = True  # ★要 Developer Portal での有効化 (privileged)
    client = discord.Client(intents=intents)

    @client.event
    async def on_ready():
        log(f"gateway接続 (shadow): {client.user} / 監視ch {len(chan_map)}件 / queue={QUEUE_DB}")

    @client.event
    async def on_message(m):
        if m.author.bot or m.webhook_id:
            return  # Bot/Webhookの発言は無視 (自分の返信でループしない=鳩と同じ方針)
        cid = str(m.channel.id)
        if cid not in chan_map:
            return  # 台帳外のchは拾わない
        rec = record_from_message(m, chan_map[cid])
        added = q.enqueue(json.dumps(rec, ensure_ascii=False), msg_id=rec["msg_id"], dept=rec["dept"])
        st = q.stats()
        log(f"受信[{rec['channel']}] msg={rec['msg_id']} {'enqueue' if added else '重複無視'} "
            f"(ready={st['ready']} leased={st['leased']})")

    try:
        client.run(token, log_handler=None)
    except discord.errors.PrivilegedIntentsRequired:
        log("ABORT: MESSAGE CONTENT INTENT が未設定です。Developer Portalで有効化が必要 "
            "(Bot設定→Privileged Gateway Intents→MESSAGE CONTENT INTENT=ON)。")
        return 2
    except discord.errors.LoginFailure:
        log("ABORT: Botトークンが無効です (local/discord_bot_token.txt を確認)。")
        return 3
    return 0


def main():
    if "--selftest" in sys.argv:
        return run_selftest()
    return run_gateway()


if __name__ == "__main__":
    sys.exit(main())
