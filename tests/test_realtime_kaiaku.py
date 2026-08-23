# -*- coding: utf-8 -*-
"""改悪スタンプの実時間検知の検査(2026-08-24 イージス研究室)。

何を守る検査か:
  Chamiが `改悪` を押した瞬間に部屋を起こす経路(discord_gateway の on_raw_reaction_add →
  reaction_watch --only-kind kaiaku)が、次の4つを満たし続けること。
    ① 実時間で鳴るのは **改悪だけ**(炎上・再発・ゴラッソ・表に無い絵文字では鳴らない)
    ② gateway は絵文字の表を**持たない**(reaction_watch の WATCH が唯一の正本)
    ③ 実時間の一報は**朝8時の巡回の材料を1件も食わない**(台帳が別・一覧を書かない)
    ④ 同じスタンプで二度出さない(冪等)

★作り方の方針(§3): 文字列一致では固めない。**入力を差し替えて経路を実行で通す**。
  外へ出る手(Discord API・dispatch・一覧のファイル)だけ偽物にし、判定と分岐は本物のまま回す。
★must-fail(C-053)= 壊した側は**動く別の実装**へ差し替える(行を消して文法を壊すのは偽の緑)。

実行= python tests/test_realtime_kaiaku.py
"""
import io
import json
import os
import shutil
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "scripts", "discord"))
sys.path.insert(0, os.path.join(ROOT, "scripts", "queue"))

import reaction_watch as rw  # noqa: E402

RESULTS = []


def check(name, cond, detail=""):
    RESULTS.append((name, bool(cond), detail))
    print(("  PASS  " if cond else "  FAIL  ") + name + (("  << " + detail) if not cond and detail else ""))


def mustfail(name, fn, expect):
    """壊した側(動く別の実装)を入れると期待どおり壊れることを確かめる。"""
    got = fn()
    check("must-fail " + name, got == expect, f"got={got!r} want={expect!r}")


# ================================================================ ① 実時間の対象

KAIAKU_ID = "1541110670748156014"
SAIHATSU_ID = "1531748428827201772"
GOLAZO_ID = "1531756076154753195"

print("\n--- ① 実時間で鳴るのは改悪だけ ---")
check("改悪(ID一致)は鳴る", rw.realtime_kind({"id": KAIAKU_ID, "name": "kaiaku"}) == "kaiaku")
check("改悪は絵文字が改名されてもIDで鳴る",
      rw.realtime_kind({"id": KAIAKU_ID, "name": "kaiaku_v2"}) == "kaiaku")
check("再発では鳴らない", rw.realtime_kind({"id": SAIHATSU_ID, "name": "saihatsu"}) is None)
check("ゴラッソでは鳴らない", rw.realtime_kind({"id": GOLAZO_ID, "name": "golazo"}) is None)
check("炎上🔥では鳴らない", rw.realtime_kind({"id": "", "name": "🔥"}) is None)
check("表に無い絵文字では鳴らない", rw.realtime_kind({"id": "999", "name": "kaiaku"}) is None)
check("素の❤️では鳴らない", rw.realtime_kind({"id": "", "name": "❤️"}) is None)
check("改悪は監視の表(WATCH)にちゃんと居る",
      rw.watched({"id": KAIAKU_ID, "name": "kaiaku"}) is not None)


def _mf_all_kinds():
    """動く別の実装= 「4種類ぜんぶ実時間で鳴らす」版。①の否定側が本物かを確かめる。"""
    keep = rw.REALTIME_KINDS
    try:
        rw.REALTIME_KINDS = tuple(w["kind"] for w in rw.WATCH)
        return rw.realtime_kind({"id": SAIHATSU_ID, "name": "saihatsu"})
    finally:
        rw.REALTIME_KINDS = keep


def _mf_name_only():
    """動く別の実装= 「名前だけで照合する」版。IDで弾いている実測を出す。"""
    keep = rw.watched
    try:
        rw.watched = lambda emo: next(
            (w for w in rw.WATCH if w["name"] == str(emo.get("name") or "")), None)
        return rw.realtime_kind({"id": "999", "name": "kaiaku"})   # 別IDの同名絵文字
    finally:
        rw.watched = keep


mustfail("全種類を実時間にすると再発でも鳴る", _mf_all_kinds, "saihatsu")
mustfail("名前だけで照合すると別IDの同名で鳴る", _mf_name_only, "kaiaku")
check("must-fail の後始末: 既定は改悪だけ", rw.REALTIME_KINDS == ("kaiaku",))
check("must-fail の後始末: watched は元に戻っている",
      rw.realtime_kind({"id": "999", "name": "kaiaku"}) is None)


# ================================================================ ② gateway は表を持たない

print("\n--- ② gateway は絵文字の表を持たない(正本は reaction_watch) ---")
import discord_gateway as gw  # noqa: E402

check("gateway 経由でも改悪は鳴る",
      gw.realtime_stamp_kind(KAIAKU_ID, "kaiaku") == "kaiaku")
check("gateway 経由でも再発は鳴らない",
      gw.realtime_stamp_kind(SAIHATSU_ID, "saihatsu") is None)


def _mf_table_without_kaiaku():
    """動く別の実装= 正本の表から改悪を抜いた版。
    gateway が自前の表を持っていたら、ここでも鳴ってしまう(=二重管理の検出)。"""
    keep_w, keep_id, keep_ch = rw.WATCH, rw.WATCH_BY_ID, rw.WATCH_BY_CHAR
    try:
        rw.WATCH = [w for w in keep_w if w["kind"] != "kaiaku"]
        rw.WATCH_BY_ID = {w["id"]: w for w in rw.WATCH if w["id"]}
        rw.WATCH_BY_CHAR = {w["name"]: w for w in rw.WATCH if not w["id"]}
        return gw.realtime_stamp_kind(KAIAKU_ID, "kaiaku")
    finally:
        rw.WATCH, rw.WATCH_BY_ID, rw.WATCH_BY_CHAR = keep_w, keep_id, keep_ch


mustfail("正本から改悪を抜くと gateway も鳴らなくなる", _mf_table_without_kaiaku, None)
check("must-fail の後始末: gateway はまた改悪で鳴る",
      gw.realtime_stamp_kind(KAIAKU_ID, "kaiaku") == "kaiaku")


# ================================================================ ③④ 巡回を実行で通す

MSGS = [
    {"id": "9001", "timestamp": "2026-08-24T00:45:00+00:00", "content": "改悪の元投稿",
     "author": {"username": "kdb"},
     "reactions": [{"emoji": {"id": KAIAKU_ID, "name": "kaiaku"}}]},
    {"id": "9002", "timestamp": "2026-08-24T00:46:00+00:00", "content": "再発の元投稿",
     "author": {"username": "kdb"},
     "reactions": [{"emoji": {"id": SAIHATSU_ID, "name": "saihatsu"}}]},
]


class FakeApi(object):
    """外へ出る手(Discord API)だけ偽物にする。判定・分岐は本物のまま通す。"""

    def __init__(self, token=None):
        self.calls = 0
        self.errors = []
        self.rate_limited = 0
        self.pages = {}          # cid -> 何回目か(2回目以降は空= 取り切った)

    def get(self, path):
        self.calls += 1
        if "/messages/" in path and "/reactions/" in path:
            return [{"username": "chami_fusoh", "id": rw.CHAMI_USER_ID, "bot": False}]
        if "/messages?" in path:
            cid = path.split("/")[2]
            n = self.pages.get(cid, 0)
            self.pages[cid] = n + 1
            return list(MSGS) if n == 0 else []
        return {"guild_id": "1498341160207515678"}


def run_watch(argv, tmp, sent, digests):
    """reaction_watch.main() を実行で通す。台帳はtmpへ、投函と一覧は記録するだけ。"""
    keep = {k: getattr(rw, k) for k in
            ("Api", "read_token", "load_channels", "send", "write_kaizen_digest",
             "stack_open_defects", "LEDGER", "REALTIME_LEDGER")}
    keep_argv = sys.argv
    try:
        rw.Api = FakeApi
        rw.read_token = lambda: "fake-token"
        rw.load_channels = lambda: (
            [{"id": "111", "name": "aegis-gl", "dept": "aegis-gl"}], "fake")
        rw.send = lambda dept, body, dry_run, sender=None, tag="": (
            sent.append({"dept": dept, "body": body, "sender": sender, "tag": tag}) or True)
        rw.write_kaizen_digest = lambda kbody, count, dry_run: (
            digests.append(count) or True)
        rw.stack_open_defects = lambda items, guild_id, dry_run: (0, 0, "")
        rw.LEDGER = os.path.join(tmp, "reaction_seen.jsonl")
        rw.REALTIME_LEDGER = os.path.join(tmp, "reaction_realtime_seen.jsonl")
        sys.argv = ["reaction_watch.py"] + argv
        buf, keep_out = io.StringIO(), sys.stdout
        sys.stdout = buf
        try:
            rc = rw.main()
        finally:
            sys.stdout = keep_out
        return rc, buf.getvalue()
    finally:
        for k, v in keep.items():
            setattr(rw, k, v)
        sys.argv = keep_argv


def rows(path):
    if not os.path.exists(path):
        return []
    with open(path, encoding="utf-8") as f:
        return [json.loads(l) for l in f if l.strip()]


print("\n--- ③ 実時間の一報は朝の巡回の材料を食わない ---")
tmp = tempfile.mkdtemp(prefix="rt_kaiaku_")
try:
    L = os.path.join(tmp, "reaction_seen.jsonl")
    R = os.path.join(tmp, "reaction_realtime_seen.jsonl")

    sent, digests = [], []
    rc, out = run_watch(["--only-kind", "kaiaku", "--hours", "2"], tmp, sent, digests)
    check("実時間: 正常終了", rc == 0, f"rc={rc}")
    check("実時間: 投函は1本だけ", len(sent) == 1, f"{len(sent)}本")
    check("実時間: 改悪の件だけが本文に載る",
          bool(sent) and "改悪の元投稿" in sent[0]["body"] and "再発の元投稿" not in sent[0]["body"])
    check("実時間: 一報だと分かる断り書きが付く",
          bool(sent) and "実時間の一報" in sent[0]["body"])
    check("実時間: 名乗りが朝の巡回と違う",
          bool(sent) and "実時間検知" in (sent[0]["sender"] or ""))
    check("実時間: 一覧(朝の脈)は書かない", digests == [], f"{digests}")
    check("実時間: 専用台帳に1件", len(rows(R)) == 1, f"{len(rows(R))}件")
    check("実時間: 朝の台帳は空のまま", rows(L) == [], f"{len(rows(L))}件")

    sent2, digests2 = [], []
    rc2, _ = run_watch(["--only-kind", "kaiaku", "--hours", "2"], tmp, sent2, digests2)
    check("④ 冪等: 二度目は投函しない", sent2 == [], f"{len(sent2)}本")
    check("④ 冪等: 台帳も増えない", len(rows(R)) == 1, f"{len(rows(R))}件")

    sent3, digests3 = [], []
    rc3, _ = run_watch(["--hours", "24"], tmp, sent3, digests3)
    check("朝の巡回: 投函は1本", len(sent3) == 1, f"{len(sent3)}本")
    check("★朝の巡回: 実時間で出した改悪も**もう一度**載る(一覧と集計の材料を落とさない)",
          bool(sent3) and "改悪の元投稿" in sent3[0]["body"] and "再発の元投稿" in sent3[0]["body"])
    check("朝の巡回: 断り書きは付かない",
          bool(sent3) and "実時間の一報" not in sent3[0]["body"])
    check("朝の巡回: 一覧を書く(2件)", digests3 == [2], f"{digests3}")
    check("朝の巡回: 朝の台帳へ2件", len(rows(L)) == 2, f"{len(rows(L))}件")
    check("朝の巡回: 実時間の台帳は増えない", len(rows(R)) == 1, f"{len(rows(R))}件")
finally:
    shutil.rmtree(tmp, ignore_errors=True)


def _mf_shared_ledger():
    """動く別の実装= 「台帳を1つにまとめる」版(素直に見えるが穴が開く)。
    実時間で出した改悪が朝の巡回から消え、**一覧と集計から丸ごと落ちる**ことを実測で出す。
    戻り値= 朝の巡回の本文に改悪が載ったか。"""
    tmp2 = tempfile.mkdtemp(prefix="rt_shared_")
    try:
        keep = rw.REALTIME_LEDGER
        sent_a, dig_a = [], []
        run_watch(["--only-kind", "kaiaku", "--hours", "2"], tmp2, sent_a, dig_a)
        # ★ここが差し替え= 実時間も朝と同じ台帳を使う版にして、朝の巡回を回す
        shutil.copyfile(os.path.join(tmp2, "reaction_realtime_seen.jsonl"),
                        os.path.join(tmp2, "reaction_seen.jsonl"))
        sent_b, dig_b = [], []
        run_watch(["--hours", "24"], tmp2, sent_b, dig_b)
        rw.REALTIME_LEDGER = keep
        return bool(sent_b) and "改悪の元投稿" in sent_b[0]["body"]
    finally:
        shutil.rmtree(tmp2, ignore_errors=True)


print("\n--- must-fail(台帳を分けている理由の実測) ---")
mustfail("台帳を1つにすると朝の一覧から改悪が消える", _mf_shared_ledger, False)


# ================================================================ 判定

ng = [n for n, ok, _ in RESULTS if not ok]
print("\n===== %d件中 %d件PASS =====" % (len(RESULTS), len(RESULTS) - len(ng)))
if ng:
    print("FAIL — %d件: %s" % (len(ng), ng))
    sys.exit(1)
print("ALL PASS")
