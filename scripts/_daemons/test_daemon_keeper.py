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
    def __init__(self, dept="hq"):
        self.dept = dept
        self.proc = FakeProc()
        self.backoff = 99
        self.fails = 3
        self.open_until = 1
        self.next_start = 1
        self.started = 1


def exercise_reload(busy_value, first_seen=None):
    """外部状態を差し替えて maybe_reload を1回だけ試す。"""
    kills, slots, state, _stamp = exercise_wave([busy_value], depts=["hq"],
                                                first_seen=first_seen)
    return kills[0]["hq"], slots[0], state


def exercise_wave(busy_seq, depts=("hq",), first_seen=None):
    """★部門ごとの載せ替え(波)を、周回ごとの busy を変えながら試す(2026-08-08)。

    busy_seq= 1周ごとの `_inflight_depts()` の戻り値。戻り値は
      ([{dept: kill回数} を周回ごとに], slots, state)。
    """
    original_watch = keeper._watch_stamp
    original_inflight = keeper._inflight_depts
    original_debounce = keeper.RELOAD_DEBOUNCE_SEC
    original_min = keeper.RELOAD_MIN_INTERVAL_SEC
    original_log = keeper.log
    try:
        stamp = time.time() - 120
        keeper._watch_stamp = lambda: stamp
        keeper.RELOAD_DEBOUNCE_SEC = 0
        keeper.RELOAD_MIN_INTERVAL_SEC = 0
        keeper.log = lambda _msg: None
        state = {"stamp": stamp - 1}
        if first_seen is not None:
            state["first_seen"] = first_seen
        slots = [FakeSlot(d) for d in depts]
        procs = {s.dept: s.proc for s in slots}
        history = []
        for busy in busy_seq:
            keeper._inflight_depts = lambda b=busy: b
            keeper.maybe_reload(slots, state)
            history.append({d: p.kills for d, p in procs.items()})
        return history, slots, state, stamp
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

        # ---- ★部門ごとの載せ替え(波・2026-08-08) ----
        # 旧実装は「30体全部が同時に暇」を待っていたので、対話の部屋が便を握っている間
        # 無関係な部門まで古い版で走り続けた。busyな部門だけ次の周回へ回すのが新しい形。
        hist, slots, state, stamp = exercise_wave(
            [["hq"]], depts=["hq", "copy-director", "system-engineer-b"])
        check("busyな部門だけ飛ばし、暇な部門はその場で載せ替える",
              hist[-1] == {"hq": 0, "copy-director": 1, "system-engineer-b": 1})
        check("配り終えていないので波は残る(stampは進めない)",
              state.get("wave", {}).get("pending") == ["hq"] and "stamp" in state
              and state["stamp"] < state["wave"]["stamp"])

        hist, slots, state, stamp = exercise_wave(
            [["hq"], ["hq"], []], depts=["hq", "copy-director"])
        check("busyが続く間は同じ部門を待ち続ける(暇な方は1回だけ)",
              hist[1] == {"hq": 0, "copy-director": 1})
        check("暇になった周回で残りが載り、波が閉じる",
              hist[2] == {"hq": 1, "copy-director": 1} and "wave" not in state)
        # 波を閉じる時に stamp を新しい版へ進める(=同じ版でもう一度載せ替えない)
        check("配り終えたら stamp が新しい版へ進む",
              state["stamp"] == stamp and "last_reload" in state)

        # 同じ波の中で、既に載せ替えた部門を二度killしない(再起動地獄の再発防止)
        hist, slots, state, stamp = exercise_wave(
            [[], [], []], depts=["hq", "copy-director"])
        check("同じ波では各部門を1回しかkillしない",
              hist[-1] == {"hq": 1, "copy-director": 1})

    ok = all(v for _, v in results)
    print(f"\n== {sum(v for _, v in results)}/{len(results)} PASS ==")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
