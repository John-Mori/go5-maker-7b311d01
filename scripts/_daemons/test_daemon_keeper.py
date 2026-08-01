#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""daemon_keeper の安全な自動載せ替えに関する回帰テスト。

実行: python scripts/_daemons/test_daemon_keeper.py
"""
import importlib.util
import os
import sqlite3
import sys
import tempfile
import time

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
HERE = os.path.dirname(os.path.abspath(__file__))
SPEC = importlib.util.spec_from_file_location(
    "daemon_keeper_under_test", os.path.join(HERE, "daemon_keeper.py"))
keeper = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(keeper)

results = []


def check(name, cond):
    results.append((name, bool(cond)))
    print(f"  {'PASS' if cond else 'FAIL'}: {name}")


def make_db(path):
    con = sqlite3.connect(path)
    con.execute(
        "CREATE TABLE queue (id INTEGER PRIMARY KEY, dept TEXT, "
        "status TEXT, lease_until REAL)")
    return con


class FakeProc:
    def __init__(self):
        self.kills = 0

    def poll(self):
        return None

    def kill(self):
        self.kills += 1


class FakeSlot:
    def __init__(self):
        self.proc = FakeProc()
        self.backoff = 99
        self.fails = 3
        self.open_until = 1
        self.next_start = 1
        self.started = 1


def exercise_reload(busy_value, first_seen=None):
    """外部状態を差し替えて maybe_reload を1回だけ試す。"""
    original_watch = keeper._watch_stamp
    original_inflight = keeper._inflight_depts
    original_debounce = keeper.RELOAD_DEBOUNCE_SEC
    original_min = keeper.RELOAD_MIN_INTERVAL_SEC
    original_log = keeper.log
    try:
        stamp = time.time() - 120
        keeper._watch_stamp = lambda: stamp
        keeper._inflight_depts = lambda: busy_value
        keeper.RELOAD_DEBOUNCE_SEC = 0
        keeper.RELOAD_MIN_INTERVAL_SEC = 0
        keeper.log = lambda _msg: None
        state = {"stamp": stamp - 1}
        if first_seen is not None:
            state["first_seen"] = first_seen
        slot = FakeSlot()
        proc = slot.proc
        keeper.maybe_reload([slot], state)
        return proc.kills, slot, state
    finally:
        keeper._watch_stamp = original_watch
        keeper._inflight_depts = original_inflight
        keeper.RELOAD_DEBOUNCE_SEC = original_debounce
        keeper.RELOAD_MIN_INTERVAL_SEC = original_min
        keeper.log = original_log


def main():
    with tempfile.TemporaryDirectory(prefix="qa_keeper_") as d:
        db = os.path.join(d, "inbox.db")
        con = make_db(db)
        now = time.time()
        con.executemany(
            "INSERT INTO queue(id,dept,status,lease_until) VALUES(?,?,?,?)",
            [
                (1, "hq", "pending", now + 60),
                (2, "hq", "pending", now + 30),
                (3, "aegis-gl", "pending", now),
                (4, "expired", "pending", now - 1),
                (5, "done-room", "done", now + 60),
                (6, "dead-room", "dead", now + 60),
            ])
        con.commit()
        con.close()

        check("未来leaseのpendingを処理中として検出",
              keeper._inflight_depts(db, now) == ["aegis-gl", "hq"])

        con = sqlite3.connect(db)
        con.execute("UPDATE queue SET lease_until=? WHERE status='pending'", (now - 1,))
        con.commit()
        con.close()
        check("期限切れ・done・deadは処理中に含めない",
              keeper._inflight_depts(db, now) == [])
        check("DBなしは判定不能(None)としてfail-closed",
              keeper._inflight_depts(os.path.join(d, "missing.db"), now) is None)

        bad = os.path.join(d, "bad.db")
        sqlite3.connect(bad).close()
        check("schema異常も判定不能(None)としてfail-closed",
              keeper._inflight_depts(bad, now) is None)

        kills, _slot, state = exercise_reload(["hq"])
        check("処理中は載せ替えずkillしない", kills == 0 and "last_reload" not in state)

        kills, _slot, state = exercise_reload(
            ["hq"], first_seen=time.time() - keeper.RELOAD_FORCE_AFTER_SEC - 60)
        check("45分超でも処理中は強制killしない", kills == 0 and "last_reload" not in state)

        kills, _slot, state = exercise_reload(None)
        check("queue判定不能時もkillしない", kills == 0 and "last_reload" not in state)

        kills, slot, state = exercise_reload([])
        check("処理中なしの時だけ載せ替える",
              kills == 1 and slot.proc is None and "last_reload" in state)

    ok = all(v for _, v in results)
    print(f"\n== {sum(v for _, v in results)}/{len(results)} PASS ==")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
