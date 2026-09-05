#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Discordのリンク/msg_id を渡すと**本文・投稿者・時刻**を返す読み取り口(2026-09-05 イージス研究室)。

発注= 経営企画室(keiei-kikaku)・DISPATCH-aegis-gl-1788576741680(Chami依頼)。
  現状の困り事= 開いた会話セッションは汎用取得(WebFetch)に認証が無く、Discordのアプリリンクを
  開けない。だから他室の実物(例: プラットフォームSE室 msg 1545617688938811503)を確認するのに
  毎回人の手を借りるしかなかった。
  → 便を届けているのと**同じbotトークン**で GET /channels/{ch}/messages/{id} を叩けば、
    本文も投稿者も時刻も取れる(bot_send.py / react.py が既に同じエンドポイントを叩いている)。

★この口は**読むだけ**。POST/PUT/PATCH/DELETE を一切持たない(検査 test_read_msg.py が機械で見る)。
★台帳(whatis.py)との役割分担:
    whatis.py  = 「その便は誰が何のために撃ったか」を**手元の台帳**から引く(通信しない)。
    read_msg.py= 「Discordに今どう出ているか」を**実物**から読む(通信する)。
  台帳に本文が無い便(2026-09-04より前 / 他室・他bot・人間の発言)はこちらでしか読めない。

使い方:
  python scripts/discord/read_msg.py https://discord.com/channels/<guild>/<ch>/<msg>
  python scripts/discord/read_msg.py 1545617688938811503            # 生のmsg_idでも可
  python scripts/discord/read_msg.py <msg_id> --channel プラットフォームse-一ノ瀬怜
  python scripts/discord/read_msg.py <msg_id> --json                # 機械で読む用
  python scripts/discord/read_msg.py <ch_id> --last 10              # その部屋の直近N件

★msg_id だけを渡された時のチャンネルの決め方(この順):
  1. --channel の指定(名前でもIDでも可)
  2. 手元の台帳から引く(send_audit の channel_id → inbox/processed の channel名 → 登録簿)
  3. それでも分からなければ登録簿の全チャンネルを順に叩いて探す(--no-scan で止められる)
"""
import argparse
import datetime
import io
import json
import os
import sys
import time
import urllib.error
import urllib.request

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.normpath(os.path.join(HERE, "..", ".."))
LOCAL = os.path.join(ROOT, "local")
API = "https://discord.com/api/v10"
CHANNELS = os.path.join(LOCAL, "discord_channels.json")
# msg_id → channel を引ける手元の台帳(上から順に当たる)。
LEDGERS = [
    ("send_audit", os.path.join(LOCAL, "llm", "send_audit.jsonl")),   # 我々が撃った便(channel_id有り)
    ("inbox", os.path.join(LOCAL, "discord_inbox.jsonl")),            # 未処理の受信
    ("processed", os.path.join(LOCAL, "discord_processed.jsonl")),    # 処理済みの受信
]
JST = datetime.timezone(datetime.timedelta(hours=9))


def read_token():
    """便を届けているのと同じbotトークン。★中身は絶対に表示しない。"""
    with io.open(os.path.join(LOCAL, "discord_bot_token.txt"), encoding="utf-8") as f:
        return f.read().strip()


def load_channels():
    """登録簿を [(id, name, dept), ...] で返す。"""
    try:
        rows = json.load(io.open(CHANNELS, encoding="utf-8"))
    except Exception:
        return []
    if isinstance(rows, dict):
        rows = rows.get("channels") or list(rows.values())
    out = []
    for r in rows:
        if isinstance(r, dict) and (r.get("id") or r.get("channel_id")):
            out.append((str(r.get("id") or r.get("channel_id")),
                        r.get("name") or "", r.get("dept") or ""))
    return out


def parse_target(arg):
    """引数から (channel_id, msg_id) を取り出す。

    リンク  .../channels/<guild>/<channel>/<msg> → 後ろ2つを採る
      ★先頭を採ると guild_id を掴む(whatis.py が 2026-09-03 に踏んだ実測バグ)。
    生ID    → (None, その値)。チャンネルは後で解決する。
    """
    import re
    nums = re.findall(r"\d{15,25}", str(arg or ""))
    if not nums:
        return None, ""
    if "discord.com" in str(arg) and len(nums) >= 3:
        return nums[-2], nums[-1]
    if len(nums) >= 2:                                  # channel/msg の2本組を素で貼られた形
        return nums[-2], nums[-1]
    return None, nums[-1]


def channel_from_ledgers(msg_id):
    """台帳から msg_id の居場所(channel_id)を引く。見つからなければ ('', '')。"""
    names = {n: cid for cid, n, _ in load_channels()}
    for label, path in LEDGERS:
        if not os.path.exists(path):
            continue
        try:
            for line in io.open(path, encoding="utf-8", errors="replace"):
                if msg_id not in line:
                    continue                            # 素の文字列一致で粗く絞る(速度のため)
                try:
                    o = json.loads(line)
                except Exception:
                    continue
                if str(o.get("msg_id") or "") != msg_id:
                    continue
                cid = str(o.get("channel_id") or "")
                if not cid:
                    cid = names.get(o.get("channel") or "", "")
                if cid:
                    return cid, label
        except OSError:
            continue
    return "", ""


def api(path, token, timeout=20):
    """GET専用。見つからない/権限が無い時は例外にせず (None, 理由) を返す。"""
    req = urllib.request.Request(
        API + path, method="GET",
        headers={"Authorization": "Bot " + token,
                 "User-Agent": "go5-org-read (personal, v1)"})
    for _ in range(3):
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                raw = r.read().decode("utf-8")
                return (json.loads(raw) if raw else None), ""
        except urllib.error.HTTPError as e:
            if e.code == 429:                           # レート制限=待って撃ち直す
                try:
                    wait = float(json.loads(e.read().decode("utf-8")).get("retry_after", 1))
                except Exception:
                    wait = 1.0
                time.sleep(min(wait, 10) + 0.3)
                continue
            return None, {403: "権限が無い(botがその部屋に居ない)",
                          404: "その部屋には無い"}.get(e.code, f"HTTP {e.code}")
        except Exception as e:
            return None, f"{type(e).__name__}"
    return None, "レート制限で3回とも取れなかった"


def fetch(msg_id, channel_id=None, token=None, scan=True, limit=60):
    """msg_id の実物を読む。返り値= {"ok":bool, ...}(印字はしない=他の道具から呼べる)。"""
    token = token or read_token()
    tried = []
    if channel_id:
        m, why = api(f"/channels/{channel_id}/messages/{msg_id}", token)
        if m:
            return {"ok": True, "channel_id": str(channel_id), "how": "指定/リンク", "msg": m}
        tried.append((str(channel_id), why))
    cid, label = channel_from_ledgers(msg_id)
    if cid and cid != str(channel_id or ""):
        m, why = api(f"/channels/{cid}/messages/{msg_id}", token)
        if m:
            return {"ok": True, "channel_id": cid, "how": f"台帳({label})", "msg": m}
        tried.append((cid, why))
    if scan:
        seen = {t[0] for t in tried}
        for c, _name, _dept in load_channels()[:limit]:
            if c in seen:
                continue
            m, why = api(f"/channels/{c}/messages/{msg_id}", token)
            if m:
                return {"ok": True, "channel_id": c, "how": "登録簿の総当たり", "msg": m}
            if why.startswith("HTTP"):                  # 404/403は「そこに無い」=普通の空振り
                tried.append((c, why))
            time.sleep(0.06)                            # 全体50req/s制限に対して十分緩い
    return {"ok": False, "msg_id": msg_id, "tried": tried,
            "reason": "どの部屋にも見つからない(消された便 / botが入っていない部屋 / IDが便でない)"}


def channel_label(cid):
    for c, name, dept in load_channels():
        if c == str(cid):
            return f"{name} (部門={dept or '不明'})"
    return "(登録簿に無いチャンネル)"


def jst(ts):
    try:
        return (datetime.datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
                .astimezone(JST).strftime("%Y-%m-%d %H:%M:%S JST"))
    except Exception:
        return str(ts or "")


def render(res, cid_hint=""):
    """人が読む形。★本文は端折らない(端折ると結局リンクを開き直すことになる)。"""
    if not res.get("ok"):
        print(f"■ 読めなかった msg={res.get('msg_id')}")
        print(f"  理由= {res.get('reason')}")
        for c, why in res.get("tried", [])[:6]:
            print(f"   - {c} {channel_label(c)}: {why}")
        print("  → 部屋が分かっているなら --channel <名前|ID> を付けると1発で引ける。")
        return 1
    m = res["msg"]
    a = m.get("author") or {}
    who = a.get("global_name") or a.get("username") or "(不明)"
    kind = "webhook" if m.get("webhook_id") else ("bot" if a.get("bot") else "人間")
    print(f"■ msg {m.get('id')}  ({res['how']}で解決)")
    print(f"  部屋  : {res['channel_id']} {channel_label(res['channel_id'])}")
    print(f"  投稿者: {who} [{kind}]")
    print(f"  時刻  : {jst(m.get('timestamp'))}"
          + (f" (編集 {jst(m.get('edited_timestamp'))})" if m.get("edited_timestamp") else ""))
    ref = (m.get("referenced_message") or {})
    if ref:
        print(f"  返信元: msg {ref.get('id')} / "
              f"{((ref.get('author') or {}).get('username') or '')} "
              f"「{(ref.get('content') or '')[:60].splitlines()[0] if ref.get('content') else ''}」")
    body = m.get("content") or ""
    print(f"  --- 本文 ({len(body)}字)")
    for line in body.split("\n"):
        print("  | " + line)
    for e in (m.get("embeds") or []):
        print(f"  --- 埋め込み: {e.get('title') or '(題なし)'}")
        for line in str(e.get("description") or "").split("\n"):
            print("  | " + line)
    for at in (m.get("attachments") or []):
        print(f"  --- 添付: {at.get('filename')} ({at.get('size')}B) {at.get('url')}")
    rs = m.get("reactions") or []
    if rs:
        marks = ", ".join(f"{(r.get('emoji') or {}).get('name')}×{r.get('count')}" for r in rs)
        print(f"  印   : {marks}")
    return 0


def recent(cid, token, n):
    """--last= その部屋の直近N件を並べる(どの便か分からない時の当たり付け)。"""
    msgs, why = api(f"/channels/{cid}/messages?limit={max(1, min(n, 100))}", token)
    if not msgs:
        print(f"■ 直近を読めなかった ch={cid}: {why}")
        return 1
    print(f"■ {cid} {channel_label(cid)} 直近{len(msgs)}件")
    for m in sorted(msgs, key=lambda x: x["id"]):
        a = m.get("author") or {}
        c = (m.get("content") or "").replace("\n", " ⏎ ")
        print(f"  {m['id']} {jst(m.get('timestamp'))[5:19]} "
              f"[{a.get('global_name') or a.get('username')}] {c[:160]}")
    return 0


def main():
    ap = argparse.ArgumentParser(description="Discordのリンク/msg_idから本文・投稿者・時刻を読む(読むだけ)")
    ap.add_argument("target", help="Discordリンク または msg_id(--last の時はチャンネルID/名前)")
    ap.add_argument("--channel", default="", help="部屋の名前かID(msg_idだけ渡す時の絞り込み)")
    ap.add_argument("--json", action="store_true", help="生のJSONで出す(機械で読む用)")
    ap.add_argument("--no-scan", action="store_true", help="登録簿の総当たりをしない")
    ap.add_argument("--last", type=int, default=0, help="その部屋の直近N件を並べる")
    a = ap.parse_args()

    names = {n: c for c, n, _ in load_channels()}
    hint = names.get(a.channel, a.channel if a.channel.isdigit() else "")
    if a.channel and not hint:
        print(f"チャンネルを解決できない: {a.channel}(登録簿の name か 数字IDで)")
        return 2
    link_cid, msg_id = parse_target(a.target)

    if a.last:
        cid = hint or link_cid or (msg_id if msg_id else "")
        cid = names.get(a.target, cid)
        if not cid:
            print("--last には部屋(名前かID)が要る")
            return 2
        return recent(cid, read_token(), a.last)

    if not msg_id:
        print("msg_idを取り出せない(15桁以上の数字が要る)。リンクごと貼っても良い。")
        return 2
    res = fetch(msg_id, channel_id=hint or link_cid, scan=not a.no_scan)
    if a.json:
        print(json.dumps(res, ensure_ascii=False, indent=1))
        return 0 if res.get("ok") else 1
    return render(res)


if __name__ == "__main__":
    sys.exit(main())
