#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""codex_gateway — Codex専用botの**独立した受信口**(2026-09-05 platform-se・Chami指示書)。

なぜ在るか(Chami指示 msg 1545613962807083040 / 添付「DiscordからCodexを完全独立で呼び出す構成」):
  既存の受信は discord_gateway.py が**Claude(主)botのトークン**でDiscordに繋いで全部屋を捌く。
  その一本足だと「Claude用Discord Botを止めた瞬間」に Codex への @メンション も一緒に届かなくなる
  = 指示書§0/§7/§8/§24 が要求する「Claudeを止めてもCodexは動く」を満たせない。
  そこで **Codex bot自身のトークンで別プロセスとしてWebSocket受信**し、Codexへの名指しだけを
  リースキュー(dept='codex')へ入れる。実処理は既存の codex_responder → codex_run(ChatGPTログイン)
  がそのまま担う=下流は完全にClaude非依存(別プロセス・別CLI・別認証・別キュー・別ログ)。

二重応答にならない理由(実測=leasequeue.py L149 msg_id UNIQUE・L188 enqueue冪等):
  主botが生きている間は discord_gateway の @ボス召喚 も同じ msg_id を dept='codex' で入れるが、
  msg_id が UNIQUE なのでキュー行は**1つに収束**する(二重投入は無視)。よって:
    - 主bot稼働中 … どちらの経路が先でも1件だけ処理(冪等)。
    - 主bot停止中 … この受信口だけが生き、Codexは@メンションに応答し続ける(独立性の核)。

休眠の自己ゲート(指示書§2「新しいBotを勝手に作らない」/ 3ファイルは全部Chamiの手):
  discord_codex_token.txt(=口=Codex botのトークン)が置かれるまで**完全に眠る**(接続もしない)。
  bot自身のUser IDは discord_codex_bot_id.txt(メンション判定の正・codex_trigger と共用)。

Chami側の必須設定(ここでは触れない=合鍵・Portal設定):
  - Codex bot を対象チャンネルへ入室させる(§29:少なくとも初期はオーナー限定運用)。
  - Developer Portal → Codex bot → MESSAGE CONTENT INTENT を ON(無いと content が空=拾えない)。

使い方:
  python scripts/queue/codex_gateway.py --selftest   # Discordに繋がず内部配線だけ検証
  python scripts/queue/codex_gateway.py              # 受信稼働(要 token・MESSAGE CONTENT INTENT)
"""
import json
import os
import sys
import time

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)
except Exception:
    pass

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.normpath(os.path.join(HERE, "..", ".."))
LOCAL = os.environ.get("GO5_LOCAL_DIR") or os.path.join(ROOT, "local")

# 既存の受信口(discord_gateway)から**再利用**する部品=レコード整形と台帳読込(二重管理しない)。
sys.path.insert(0, HERE)
from leasequeue import LeaseQueue                      # noqa: E402
from discord_gateway import record_from_message, load_channel_map  # noqa: E402
# Codexへの名指し判定(codex_trigger は discord_codex_bot_id.txt の実メンションも見る)。
sys.path.insert(0, os.path.join(ROOT, "scripts", "llm"))
try:
    from codex_trigger import is_codex_mentioned       # noqa: E402
except Exception:
    def is_codex_mentioned(_content):                  # 依存が欠けても受信口は動く(fail-open)
        return False

TOKEN_FILE = os.path.join(LOCAL, "discord_codex_token.txt")     # Chami設置待ち(未設置=休眠)
BOT_ID_FILE = os.path.join(LOCAL, "discord_codex_bot_id.txt")   # Codex bot自身のUser ID
OWNER_IDS_FILE = os.path.join(LOCAL, "discord_owner_ids.txt")   # 任意=オーナー限定運用(§29)
QUEUE_DB = os.path.join(LOCAL, "queue", "inbox.db")
LOG_FILE = os.path.join(LOCAL, "llm", "codex_gateway_console.log")  # Codex専用ログ(§30・Claude分離)
PULSE = os.path.join(LOCAL, "queue", "_codex_gateway_pulse.txt")


def log(msg):
    line = f"{time.strftime('%Y-%m-%d %H:%M:%S')} [codex-gw] {msg}"
    print(line)
    try:
        os.makedirs(os.path.dirname(LOG_FILE), exist_ok=True)
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except OSError:
        pass


def _touch_pulse():
    try:
        os.makedirs(os.path.dirname(PULSE), exist_ok=True)
        with open(PULSE, "a", encoding="utf-8"):
            pass
        os.utime(PULSE, None)
    except OSError:
        pass


def token_present():
    """起床判定= Codex botのトークンが置かれているか(口が無ければ受信しても意味がない)。"""
    return os.path.exists(TOKEN_FILE) and os.path.getsize(TOKEN_FILE) > 0


def _bot_user_id():
    try:
        return open(BOT_ID_FILE, encoding="utf-8").read().strip()
    except OSError:
        return ""


def _owner_ids():
    """オーナー限定allowlist(任意)。ファイルが無ければ空集合=部屋ベースの制限のみ(現行と同等)。
    ★Chamiの手で置く(user IDは合鍵ではないが、勝手に推測して埋めない=空なら空のまま)。"""
    try:
        raw = open(OWNER_IDS_FILE, encoding="utf-8").read()
    except OSError:
        return set()
    ids = set()
    for tok in raw.replace(",", "\n").split("\n"):
        tok = tok.strip()
        if tok.isdigit():
            ids.add(tok)
    return ids


def strip_self_mention(content, bot_id):
    """本文からCodex bot自身への @メンション だけを取り除く(§5)。他者mention/コード/URLは壊さない。"""
    if not content:
        return ""
    out = content
    if bot_id:
        for form in (f"<@{bot_id}>", f"<@!{bot_id}>"):
            out = out.replace(form, " ")
    return out.strip()


def enqueue_codex(q, rec):
    """Codex宛て1件をキューへ(dept='codex'固定)。msg_id UNIQUEで冪等=主gatewayと二重にならない。"""
    rec = dict(rec)
    rec["dept"] = "codex"
    ok = q.enqueue(rec, msg_id=str(rec.get("msg_id", "")) or None, dept="codex")
    return ok


# ---------------------------------------------------------------------------
# 内部配線の自己検査(Discordに繋がない)
# ---------------------------------------------------------------------------
def selftest():
    log("selftest 開始(Discord非接続)")
    bot_id = _bot_user_id() or "999"
    # 1) 名指し無し=拾わない
    assert not is_codex_mentioned("普通の雑談です"), "名指し無しを拾ってしまった"
    # 2) 実メンション=拾う(bot_id が置かれている前提)
    if _bot_user_id():
        assert is_codex_mentioned(f"<@{bot_id}> これ見て"), "実メンションを拾えない"
    # 3) 自mention除去
    assert strip_self_mention(f"<@{bot_id}> src/x.py のバグ", bot_id) == "src/x.py のバグ", \
        "自mention除去が壊れている"
    assert strip_self_mention(f"<@{bot_id}>", bot_id) == "", "空指示の判定が壊れている"
    # 4) enqueue が dept=codex で通り、同じ msg_id の二度目は冪等で False
    #    ★本番キュー(inbox.db)は汚さない= 使い捨ての一時DBで確かめる。
    import tempfile
    tmp = os.path.join(tempfile.gettempdir(), f"codexgw_selftest_{os.getpid()}.db")
    q = LeaseQueue(tmp)
    try:
        mid = f"selftest-codexgw-{os.getpid()}"
        rec = {"msg_id": mid, "channel": "selftest", "dept": "router", "content": "x"}
        first = enqueue_codex(q, rec)
        second = enqueue_codex(q, rec)
        assert first is True and second is False, f"冪等でない(first={first} second={second})"
        log(f"enqueue冪等OK(first=True, second=False) mid={mid}")
    finally:
        q.close()
        try:
            os.remove(tmp)
        except OSError:
            pass
    log("selftest OK: 名指し判定/自mention除去/dept=codex冪等 いずれも配線正常")
    return 0


# ---------------------------------------------------------------------------
# 受信稼働(Codex botのトークンで独立接続)
# ---------------------------------------------------------------------------
def run_gateway():
    import discord

    token = open(TOKEN_FILE, encoding="utf-8").read().strip()
    bot_id = _bot_user_id()
    owner_ids = _owner_ids()
    chan_map = load_channel_map()
    q = LeaseQueue(QUEUE_DB)
    if not owner_ids:
        log("注意: discord_owner_ids.txt 未設置=オーナー限定allowlistは無効(部屋登録のみで受ける)。"
            "§29のオーナー限定運用にするなら Chami の手で user ID を置く。")

    intents = discord.Intents.default()
    intents.message_content = True   # ★要 Developer Portal(Codex bot側)での MESSAGE CONTENT INTENT
    client = discord.Client(intents=intents)

    @client.event
    async def on_ready():
        log(f"接続OK: {client.user} / 監視ch {len(chan_map)}件 / bot_id(file)={bot_id or '未設置'} "
            f"/ owner限定={'ON' if owner_ids else 'OFF'} / queue={QUEUE_DB}")
        _touch_pulse()

    @client.event
    async def on_message(m):
        _touch_pulse()
        try:
            if m.author.bot or m.webhook_id:
                return                                   # bot/webhookは無視(自己ループ防止)
            cid = str(m.channel.id)
            if cid not in chan_map:
                return                                   # 台帳外chは受けない(主gatewayと同方針)
            content = m.content or ""
            # 名指しの形(@トークン or 実メンション<@id>)でだけ召喚する(誤召喚対策=codex_trigger)。
            if not is_codex_mentioned(content):
                return
            if owner_ids and str(getattr(m.author, "id", "")) not in owner_ids:
                log(f"許可外ユーザーの@Codex(無視) from={getattr(m.author,'name','?')} "
                    f"id={getattr(m.author,'id','')}")
                return
            rec = record_from_message(m, chan_map[cid])
            # 自mentionを外して指示本文にする。空なら起動しない(§5:短い案内を返す)。
            body = strip_self_mention(content, bot_id or _mention_id_from_client(client))
            rec["content"] = body
            if not body:
                try:
                    await m.reply("Codexへの指示を @Codex の後ろに入力してください。", mention_author=False)
                except Exception:
                    pass
                return
            ok = enqueue_codex(q, rec)
            log(f"@Codex受信→enqueue[{rec.get('channel')}] msg={rec.get('msg_id')} "
                f"{'新規' if ok else '冪等(既存=主gatewayと収束)'}")
        except Exception as e:                           # 受信口は落とさない(沈黙が最悪)
            log(f"on_message処理に失敗(継続): {type(e).__name__}: {e}")

    def _mention_id_from_client(cl):
        try:
            return str(cl.user.id)
        except Exception:
            return ""

    log("Codex受信口 稼働開始(Codex botトークンで独立接続)")
    client.run(token, reconnect=True)                    # discord.py が自動再接続(TCP断は自力復帰)


def main():
    if "--selftest" in sys.argv:
        return selftest()
    once = "--once" in sys.argv
    was = None
    while True:
        up = token_present()
        if up != was:
            log("稼働(discord_codex_token.txt あり=接続する)" if up else
                "休眠(discord_codex_token.txt 未設置=Chami設置待ち・接続しない)")
            was = up
        if up:
            run_gateway()                                # 通常は戻ってこない(戻ったら下で再試行)
            log("受信ループが戻った=再接続を試みる")
            if once:
                break
            time.sleep(10)
            continue
        if once:
            break
        time.sleep(30)
    return 0


if __name__ == "__main__":
    sys.exit(main())
