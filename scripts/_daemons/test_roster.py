#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""名簿の追従(番人)と、取り残された部屋の点検(dead-man)のテスト(2026-08-08 イージス研究室)。

発注= 研究室HQ 2026-08-08 20:24。原文の要点=
  「**keeperの名簿に載っていない部屋は無警報で取り残される**という形の穴だ。
    1部屋の直しで終わらせず、**取り残されている部屋を機械が数えて出す**ところまで持っていってくれ。」

★ここで固めるのは2つ=
  ①番人が**再起動を待たずに**名簿の増減へ追従する(かつ、二重化・巻き込みkillを作らない)
  ②取り残しを**機械が数える**(かつ、所有者が別に居る部屋で誤発火しない=狼少年にしない)

実行: python scripts/_daemons/test_roster.py
"""
import importlib.util
import json
import os
import sys
import tempfile
import time

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
HERE = os.path.dirname(os.path.abspath(__file__))


def _load(name, fname):
    spec = importlib.util.spec_from_file_location(name, os.path.join(HERE, fname))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


keeper = _load("keeper_under_test", "daemon_keeper.py")
dm = _load("deadman_under_test", "deadman_check.py")

PASS = FAIL = 0


def check(name, cond):
    global PASS, FAIL
    if cond:
        PASS += 1
        print("  ok  %s" % name)
    else:
        FAIL += 1
        print("  NG  %s" % name)


def _roster_file(body, age_sec=120):
    """DEPTS 行を持つ一時ファイルを作る(mtimeを過去へずらす=編集は落ち着いている)。"""
    p = os.path.join(tempfile.mkdtemp(prefix="roster_"), "keeper.py")
    with open(p, "w", encoding="utf-8") as f:
        f.write(body)
    old = time.time() - age_sec
    os.utime(p, (old, old))
    return p


class FakeProc:
    def __init__(self):
        self.kills = 0

    def poll(self):
        return None

    def kill(self):
        self.kills += 1


class FakeSlot:
    def __init__(self, dept):
        self.dept = dept
        self.proc = FakeProc()
        self.backoff = self.fails = self.open_until = self.next_start = self.started = 0


# ============ 1) 名簿の読み直し(壊れた名簿を採用しない) ============
FIVE = '"a", "b", "c", "d", "e"'
p = _roster_file('X = 1\nDEPTS = [%s, "f"]\nY = 2\n' % FIVE)
check("DEPTS行を読み直せる", keeper._read_depts_file(p) == ["a", "b", "c", "d", "e", "f"])
check("重複は1つに畳む(二重化の芽を潰す)",
      keeper._read_depts_file(_roster_file('DEPTS = [%s, "a"]\n' % FIVE))
      == ["a", "b", "c", "d", "e"])
check("★編集直後(落ち着く前)は採用しない",
      keeper._read_depts_file(_roster_file('DEPTS = [%s]\n' % FIVE, age_sec=0)) is None)
check("★極端に短い名簿は壊れているとみなして採用しない",
      keeper._read_depts_file(_roster_file('DEPTS = ["a", "b"]\n')) is None)
check("DEPTS行が無ければ採用しない",
      keeper._read_depts_file(_roster_file('DEPTS_OLD = [1]\n')) is None)
check("文字列以外が混ざっていたら採用しない",
      keeper._read_depts_file(_roster_file('DEPTS = [%s, 7]\n' % FIVE)) is None)
check("ファイルが無ければ採用しない",
      keeper._read_depts_file(os.path.join(HERE, "no_such_file.py")) is None)


# ============ 2) 追従(増えた/減った) ============
def adopt(want, depts, busy=(), throttle=False):
    """maybe_adopt を1回試す。戻り= (slots, 掃除された部門, killされたSlot, state)。"""
    killed_for, orig_kill = [], keeper._kill_orphans_for
    orig_read, orig_inf, orig_log = (keeper._read_depts_file, keeper._inflight_depts, keeper.log)
    try:
        keeper._kill_orphans_for = lambda d: (killed_for.append(d), 0)[1]
        keeper._read_depts_file = lambda: want
        keeper._inflight_depts = lambda: busy
        keeper.log = lambda _m: None
        slots = [FakeSlot(d) for d in depts]
        state = {"roster_at": time.time()} if throttle else {}
        keeper.maybe_adopt(slots, state)
        return slots, killed_for, state
    finally:
        keeper._kill_orphans_for = orig_kill
        keeper._read_depts_file = orig_read
        keeper._inflight_depts = orig_inf
        keeper.log = orig_log


slots, killed, st = adopt(["hq", "kukuru-nakama"], ["hq"])
check("★名簿に増えた部門は番人の再起動を待たず採用される",
      [s.dept for s in slots] == ["hq", "kukuru-nakama"])
check("★立てる前に、その部門の孤児だけを掃除する(全体reapで29体を巻き込まない)",
      killed == ["kukuru-nakama"])

slots, killed, st = adopt(["hq", "kukuru-nakama"], ["hq"], throttle=True)
check("読み直しは間隔で間引く(毎周ではプロセス一覧を叩かない)",
      [s.dept for s in slots] == ["hq"] and killed == [])

slots, _k, _s = adopt(None, ["hq"])
check("名簿が読めない時は今の名簿のまま(fail-safe)", [s.dept for s in slots] == ["hq"])

slots, _k, _s = adopt(["hq"], ["hq", "retired"])
check("名簿から外れた部門は停止する", [s.dept for s in slots] == ["hq"])

slots, _k, _s = adopt(["hq"], ["hq", "retired"], busy=["retired"])
check("★便を処理中の部門は、名簿から外れても落とさない",
      [s.dept for s in slots] == ["hq", "retired"])

slots, _k, _s = adopt(["hq"], ["hq", "retired"], busy=None)
check("★処理中か判定できない時は落とさない(fail-closed)",
      [s.dept for s in slots] == ["hq", "retired"])


# ============ 3) 取り残しを数える ============
def gaps(procs, keepers, depts, channels):
    """roster_gaps を、外の世界(プロセス一覧・名簿・ch表)を差し替えて試す。"""
    tmp = tempfile.mkdtemp(prefix="gaps_")
    kf = os.path.join(tmp, "daemon_keeper.py")
    with open(kf, "w", encoding="utf-8") as f:
        f.write("DEPTS = %s\n" % json.dumps(depts))
    cf = os.path.join(tmp, "channels.json")
    with open(cf, "w", encoding="utf-8") as f:
        json.dump([{"name": d, "id": "1", "dept": d} for d in channels], f)
    orig = (dm._dept_procs, dm.KEEPER, dm.CHANNELS)
    try:
        dm._dept_procs = lambda: (procs, keepers)
        dm.KEEPER, dm.CHANNELS = kf, cf
        return dm.roster_gaps()
    finally:
        dm._dept_procs, dm.KEEPER, dm.CHANNELS = orig


DEPTS3 = ["hq", "copy-director", "kukuru-nakama"]
g = gaps([("hq", 10, 99), ("copy-director", 11, 99), ("kukuru-nakama", 50452, 52596)],
         [99], DEPTS3, DEPTS3)
check("★番人の子でない部屋を「管理外」として数える(実測の kukuru-nakama と同じ形)",
      g["unmanaged"] == ["kukuru-nakama"] and g["absent"] == [] and g["unwired"] == [])
check("数えた実物の内訳も返す(名簿数・稼働数・番人pid)",
      g["depts"] == 3 and g["running"] == 3 and g["keepers"] == [99])

g = gaps([("hq", 10, 99)], [99], DEPTS3, DEPTS3)
check("名簿に居るのにデーモンが居ない部屋を数える",
      g["absent"] == ["copy-director", "kukuru-nakama"])

g = gaps([("hq", 10, 99)], [], ["hq"], ["hq"])
check("★番人が不在の時は「不在」を数えない(番人ごと落ちている=別の警報の領分)",
      g["absent"] == [] and g["unmanaged"] == ["hq"])

g = gaps([("hq", 10, 99)], [99], ["hq"], ["hq", "llm-growth", "gemini", "router",
                                         "meeting-a", "meeting-b"])
check("★所有者が別に居る部屋では誤発火しない(常に鳴る安全網は無視される)",
      g["unwired"] == [] and dm.roster_lines(g) == [])

g = gaps([("hq", 10, 99)], [99], ["hq"], ["hq", "new-room"])
check("Discordに部屋が在るのに名簿に無い部屋を数える", g["unwired"] == ["new-room"])

orig = dm._dept_procs
try:
    dm._dept_procs = lambda: (None, None)
    check("プロセス一覧が測れない時は None(推測で数えない)", dm.roster_gaps() is None)
finally:
    dm._dept_procs = orig


# ============ 4) 出し方(連投しない・解消も1回言う) ============
def run_roster(g, prev_sig, dry=False):
    sent, orig_g, orig_n = [], dm.roster_gaps, dm.notify
    try:
        dm.roster_gaps = lambda: g
        dm.notify = lambda text, _dry: (sent.append(text), True)[1]
        st = {"roster_sig": prev_sig} if prev_sig is not None else {}
        dm.check_roster(st, dry)
        return sent, st
    finally:
        dm.roster_gaps, dm.notify = orig_g, orig_n


BAD = {"unmanaged": ["kukuru-nakama"], "absent": [], "unwired": [],
       "depts": 30, "running": 30, "keepers": [1]}
CLEAN = {"unmanaged": [], "absent": [], "unwired": [],
         "depts": 30, "running": 30, "keepers": [1]}
sent, st = run_roster(BAD, None)
check("取り残しを見つけたら1回出す", len(sent) == 1 and "kukuru-nakama" in sent[0])
check("顔ぶれを覚える(次の判定に使う)", st["roster_sig"])
sig = st["roster_sig"]
sent, _st = run_roster(BAD, sig)
check("★前回と同じ顔ぶれなら黙る(狼少年にしない)", sent == [])
sent, _st = run_roster(CLEAN, sig)
check("片付いたら「解消」を1回だけ出す", len(sent) == 1 and "解消" in sent[0])
sent, _st = run_roster(CLEAN, None)
check("最初から取り残しゼロなら何も出さない", sent == [])
sent, _st = run_roster(None, sig)
check("測れなかった時は何も出さない(黙る)", sent == [])
sent, st = run_roster(BAD, None, dry=True)
check("★--dry-run は状態を書き換えない(試し撃ちが本番の初回通知を黙らせない)",
      "roster_sig" not in st)

print("\n%d passed / %d failed" % (PASS, FAIL))
sys.exit(1 if FAIL else 0)
