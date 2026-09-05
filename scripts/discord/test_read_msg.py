#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Discord読み取り口(read_msg.py)の回帰検査(2026-09-05 イージス研究室)。

発注= 経営企画室 DISPATCH-aegis-gl-1788576741680(Chami依頼)。
見る物は4つ:
  A. **読むだけ**であること(POST/PUT/PATCH/DELETE を1つも持たない)= 事故の芽を機械で潰す。
  B. リンク/生ID の解釈(★リンクは後ろから2つ= guild_id を掴まない。whatis.py が 2026-09-03 に踏んだ穴)。
  C. チャンネルの決め方(--channel/リンク → 台帳 → 総当たり)の順序と、--no-scan が本当に撃たないこと。
  D. must-fail(C-053)= リンク解釈を**動く別実装**(先頭を採る旧バグ)へ差し替えると赤くなる。
  E. 実物(発注書が名指しした msg 1545617688938811503)を実際に読む。★通信する唯一の項。
     トークンが無い環境では E だけ skip(黙って緑にはしない=画面に skip と出す)。

実行: python scripts/discord/test_read_msg.py (全PASSで exit 0)
"""
import ast
import importlib.util
import io
import json
import os
import sys
import tempfile

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, HERE)
P = F = S = 0


def ok(cond, name):
    global P, F
    if cond:
        P += 1
        print("PASS", name)
    else:
        F += 1
        print("FAIL", name)


def skip(name):
    global S
    S += 1
    print("SKIP", name)


import read_msg  # noqa: E402

SRC = io.open(os.path.join(HERE, "read_msg.py"), encoding="utf-8").read()

# --- A 読むだけ(書き込みの口を持たない) ------------------------------------------------
tree = ast.parse(SRC)
methods = set()
for c in ast.walk(tree):
    if isinstance(c, ast.Call):
        for kw in c.keywords:
            if kw.arg == "method" and isinstance(kw.value, ast.Constant):
                methods.add(kw.value.value)
ok(methods <= {"GET"}, f"A-1 HTTPメソッドはGETだけ(実測={sorted(methods) or 'なし'})")
ok(not any(isinstance(c, ast.Call) and any(kw.arg == "data" for kw in c.keywords)
           for c in ast.walk(tree)), "A-2 リクエストにbody(data=)を積む所が無い= 書き込まない")
ok(all(not ("print(" in ln and "token" in ln) for ln in SRC.split("\n")),
   "A-3 トークンを印字する行が1つも無い(合鍵を画面へ出さない)")

# --- B リンク/生IDの解釈 ---------------------------------------------------------------
G, C, M = "1525640000000000000", "1528653749747191882", "1545617688938811503"
ok(read_msg.parse_target(f"https://discord.com/channels/{G}/{C}/{M}") == (C, M),
   "B-1 リンクは (channel, msg)= 後ろ2つを採る(guild_idを掴まない)")
ok(read_msg.parse_target(M) == (None, M), "B-2 生のmsg_idはチャンネル未定で返る")
ok(read_msg.parse_target("これ何? " + M) == (None, M), "B-3 文に混ざったIDも拾う")
ok(read_msg.parse_target("なにも無い") == (None, ""), "B-4 IDが無ければ空(例外を出さない)")
ok(read_msg.parse_target(f"https://discord.com/channels/{G}/{C}/{M}")[0] != G,
   "B-5 ★guild_idをチャンネルとして返さない(2026-09-03の実測バグの再発防止)")

# --- C チャンネルの決め方 ---------------------------------------------------------------
tmp = tempfile.mkdtemp(prefix="readmsg_test_")
led_id = os.path.join(tmp, "byid.jsonl")      # channel_id を持つ台帳(send_audit型)
led_name = os.path.join(tmp, "byname.jsonl")  # channel名しか無い台帳(inbox型)
io.open(led_id, "w", encoding="utf-8").write(
    json.dumps({"msg_id": M, "channel_id": C, "channel": "x"}, ensure_ascii=False) + "\n")
real_name = next((n for c, n, _ in read_msg.load_channels() if c == C), "")
io.open(led_name, "w", encoding="utf-8").write(
    json.dumps({"msg_id": M, "channel": real_name}, ensure_ascii=False) + "\n")
_LED = read_msg.LEDGERS
read_msg.LEDGERS = [("byid", led_id)]
ok(read_msg.channel_from_ledgers(M) == (C, "byid"), "C-1 台帳の channel_id から引ける")
read_msg.LEDGERS = [("byname", led_name)]
ok(read_msg.channel_from_ledgers(M) == ((C, "byname") if real_name else ("", "")),
   "C-2 channel名しか無い台帳は登録簿で名前→IDに直して引ける")
read_msg.LEDGERS = [("byid", led_id)]
ok(read_msg.channel_from_ledgers("9" * 19) == ("", ""), "C-3 知らないIDは空で返る(嘘をつかない)")

calls = []


def fake_api(path, token, timeout=20):
    calls.append(path)
    return ({"id": M, "content": "本文", "author": {"username": "u"}}, "") \
        if f"/channels/{C}/messages/{M}" in path else (None, "その部屋には無い")


_api = read_msg.api
read_msg.api = fake_api
calls.clear()
r = read_msg.fetch(M, channel_id=C, token="dummy")
ok(r["ok"] and r["how"] == "指定/リンク" and len(calls) == 1,
   "C-4 チャンネルが分かっていれば1回のGETで済む(総当たりへ落ちない)")
calls.clear()
r = read_msg.fetch(M, token="dummy")
ok(r["ok"] and r["how"].startswith("台帳") and len(calls) == 1,
   "C-5 チャンネル未指定でも台帳で引ければ1回のGETで済む")
read_msg.LEDGERS = [("byid", os.path.join(tmp, "no_such.jsonl"))]
calls.clear()
r = read_msg.fetch(M, token="dummy")
ok(r["ok"] and r["how"] == "登録簿の総当たり" and len(calls) > 1,
   "C-6 台帳に無ければ登録簿を総当たりして見つける")
calls.clear()
r = read_msg.fetch(M, token="dummy", scan=False)
ok(not r["ok"] and len(calls) == 0,
   "C-7 --no-scan(scan=False)は1本もGETを撃たない")
calls.clear()
r = read_msg.fetch("9" * 19, token="dummy")
ok(not r["ok"] and "見つからない" in r["reason"],
   "C-8 どこにも無い時は ok=False と理由を返す(空の本文で誤魔化さない)")
read_msg.api = _api
read_msg.LEDGERS = _LED

ok(read_msg.jst("2026-09-05T02:12:53.000000+00:00").startswith("2026-09-05 11:12:53"),
   "C-9 時刻はJSTで出る(UTCのまま出すと実物と突き合わせられない)")

# --- D must-fail(C-053= 壊した側は動く別実装) -------------------------------------------
OLD = 'return nums[-2], nums[-1]'
assert SRC.count(OLD) >= 1, "must-fail の当たり所が無い= 検査の前提が崩れている"
mpath = os.path.join(tmp, "read_msg_mutant.py")
io.open(mpath, "w", encoding="utf-8").write(
    SRC.replace(OLD, 'return nums[0], nums[-1]  # 変異: 先頭を採る(2026-09-03の旧バグ)', 1))
spec = importlib.util.spec_from_file_location("read_msg_mutant", mpath)
mut = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mut)
ok(mut.parse_target(f"https://discord.com/channels/{G}/{C}/{M}")[0] == G,
   "D-1 must-fail リンク解釈を旧バグへ戻すと guild_id を掴む(=B-1/B-5は本当に効いている)")
ok(mut.parse_target(M) == (None, M),
   "D-2 must-fail 変異は生ID経路を壊していない(偽の赤でない)")

# --- E 実物(発注書が名指しした便を実際に読む) --------------------------------------------
if os.path.exists(os.path.join(ROOT, "local", "discord_bot_token.txt")):
    res = read_msg.fetch(M, scan=False)
    ok(res.get("ok"), f"E-1 実物 msg {M} をDiscordから読めた(発注書が名指しした便)")
    if res.get("ok"):
        m = res["msg"]
        ok(len(m.get("content") or "") > 100, "E-2 本文が取れている(head120字の切り身ではない)")
        ok(bool((m.get("author") or {}).get("username")), "E-3 投稿者が取れている")
        ok(read_msg.jst(m.get("timestamp")).endswith("JST"), "E-4 時刻が取れている(JST)")
        ok(res["channel_id"] == C, "E-5 部屋= プラットフォームse-一ノ瀬怜 に解決した")
else:
    skip("E 実物の読み取り= botトークンが無い環境なので撃たない")

print(f"\n合計 PASS={P} FAIL={F} SKIP={S}")
sys.exit(0 if F == 0 else 1)
