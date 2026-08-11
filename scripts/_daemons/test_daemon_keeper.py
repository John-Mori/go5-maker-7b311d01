#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""daemon_keeper の安全な自動載せ替えに関する回帰テスト。

実行: python scripts/_daemons/test_daemon_keeper.py
"""
import ast
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


# ★C-042(2026-08-12 HQ裁定)= 「常駐が読むものを足したら、載せ替えの経路も同時に決めろ」。
#   dept_daemon が import する自作モジュールは**起動時に1回**解決されるだけなので、
#   WATCH_FILES に無い物だけを直した日は1体も載せ替わらない=「入れたのに効かない」。
#   実際に leasequeue / tone_gate / naming_gate / persona_send / dept_names の5本が
#   後から見つかっている=**人が気をつける方法では止まらない**(C-038)。だから機械が数える。
_IMPORT_DIRS = [("scripts", "llm"), ("scripts", "_common"), ("scripts", "discord"),
                ("scripts", "queue"), ("scripts", "_daemons"), ("scripts", "report")]


def _local_imports(path, root):
    """path が import している「このリポジトリ内の .py」を {名前: 絶対パス} で返す。

    ★実行せず ast で読むだけ(副作用ゼロ)。解決できない名前(stdlib・外部)は黙って捨てる。
    """
    try:
        tree = ast.parse(open(path, encoding="utf-8").read())
    except Exception:                                  # noqa: BLE001
        return {}
    names = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                names.add(alias.name.split(".")[0])
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            names.add(node.module.split(".")[0])
    found = {}
    for name in sorted(names):
        for parts in _IMPORT_DIRS:
            cand = os.path.join(root, *parts, name + ".py")
            if os.path.exists(cand):
                found[name] = os.path.normpath(cand)
                break
    return found


def unwatched_imports():
    """dept_daemon から辿れる自作モジュールのうち、WATCH_FILES に無いものを返す。

    ★直接importだけでなく**推移的に**辿る(session_relay が読む物も起動時に固定されるため)。
    """
    root = keeper.ROOT
    watched = {os.path.normpath(p).lower() for p in keeper.WATCH_FILES}
    seen, stack = {}, [keeper.DAEMON]
    while stack:
        for name, path in _local_imports(stack.pop(), root).items():
            if name not in seen:
                seen[name] = path
                stack.append(path)
    return sorted(os.path.relpath(p, root) for n, p in seen.items()
                  if p.lower() not in watched)


def main():
    check("dept_daemon が読む自作モジュールは全部 WATCH_FILES に載っている(C-042)",
          unwatched_imports() == [])
    if unwatched_imports():
        print("    載っていない: " + " / ".join(unwatched_imports()))
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
