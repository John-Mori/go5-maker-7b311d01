# -*- coding: utf-8 -*-
"""dispatch の合成id 衝突で便が無警報で消える穴の検査(2026-08-24 イージス研究室)。

何が壊れていたか(発注= 研究室HQ DISPATCH-aegis-gl-1787501611568 / HQ-0208):
  `q.enqueue()` は投入できた時だけ True を返す(msg_id が UNIQUE・重複は False)。
  ところが dispatch.py 385行はその戻り値を読まず、392〜393行は成否に関係なく「投函」と印字していた。
  = `DISPATCH-<部門>-<ミリ秒>` が被った便は**消えたまま成功と印字**される(C-048違反・沈黙の事故)。

この検査が守ること:
  ① 通常時の id は **1文字も変わらない**(`DISPATCH-<dept>-<ミリ秒>`。既存の引用を壊さない)
  ② **同じミリ秒に2本**出しても2本ともキューに届く(2本目は `-2` で逃げる)
  ③ 便の中の msg_id と行の msg_id が**食い違わない**
  ④ 逃がしきれなかったら **成功と印字しない**・戻り値も False(fail-loud)

★作り方(§3): 文字列一致では固めない。**外へ出る手(Discord投稿・時計)だけ偽物**にし、
  判定と分岐と実際のSQLiteへの投入は本物のまま通す。
★must-fail(C-053)= 壊した側は**動く別の実装**(戻り値を読まない旧実装)へ差し替える。

実行= python tests/test_dispatch_id_collision.py
"""
import io
import json
import os
import shutil
import sqlite3
import sys
import tempfile
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "scripts", "llm"))
sys.path.insert(0, os.path.join(ROOT, "scripts", "queue"))

import dispatch as dp  # noqa: E402

RESULTS = []


def check(name, cond, detail=""):
    RESULTS.append((name, bool(cond), detail))
    print(("  PASS  " if cond else "  FAIL  ") + name + (("  << " + detail) if not cond and detail else ""))


def mustfail(name, fn, expect):
    """壊した側(動く別の実装)を入れると期待どおり壊れることを確かめる。"""
    got = fn()
    check("must-fail " + name, got == expect, f"got={got!r} want={expect!r}")


# ================================================================ ① 純粋関数

print("\n--- ① enqueue_unique(純粋関数) ---")


def _taken(*ids):
    """指定の id だけ既に埋まっているキューの真似。戻り=(enqueue, 載った本文の一覧)"""
    used = set(ids)
    landed = []

    def enqueue(body, mid):
        if mid in used:
            return False
        used.add(mid)
        landed.append((mid, body))
        return True

    return enqueue, landed


_en, _landed = _taken()
_ok, _mid, _n = dp.enqueue_unique(_en, "DISPATCH-hq-1787501611568", lambda m: m)
check("通常は1回で通る", (_ok, _n) == (True, 1), f"{_ok},{_n}")
check("★通常時の id は1文字も変わらない", _mid == "DISPATCH-hq-1787501611568", _mid)

_en, _landed = _taken("DISPATCH-hq-1787501611568")
_ok, _mid, _n = dp.enqueue_unique(_en, "DISPATCH-hq-1787501611568", lambda m: m)
check("被ったら -2 で逃げる", (_ok, _mid, _n) == (True, "DISPATCH-hq-1787501611568-2", 2), _mid)

_en, _landed = _taken("X", "X-2", "X-3")
_ok, _mid, _n = dp.enqueue_unique(_en, "X", lambda m: m)
check("3本被っても -4 まで行けば通る", (_ok, _mid) == (True, "X-4"), _mid)

# ★本文は**確定した id で作り直す**= 便の中の msg_id が行の msg_id と食い違わないこと
_en, _landed = _taken("Y")
_ok, _mid, _n = dp.enqueue_unique(_en, "Y", lambda m: json.dumps({"msg_id": m}))
check("本文は確定した id で作り直される",
      json.loads(_landed[0][1])["msg_id"] == _landed[0][0] == _mid, str(_landed))

# ★全部埋まっている= 載せられない。id を返さない(=1件も入っていない)
_full = ["Z"] + [f"Z-{i}" for i in range(2, dp.ID_COLLISION_MAX + 1)]
_en, _landed = _taken(*_full)
_ok, _mid, _n = dp.enqueue_unique(_en, "Z", lambda m: m)
check("逃がしきれなければ False", _ok is False, str(_ok))
check("失敗時は id を返さない", _mid == "", repr(_mid))
check("上限まで試している", _n == dp.ID_COLLISION_MAX and _landed == [], f"{_n},{_landed}")


# ================================================================ ② 本物の dispatch() を通す

print("\n--- ② 同じミリ秒に2本(本物の dispatch・SQLiteも本物) ---")

FIXED_MS = 1787501611568


def two_in_same_ms(impl=None):
    """時計を止めて dispatch() を2回通す。戻り=(キューの行, 戻り値の一覧, 出力)"""
    tmp = tempfile.mkdtemp(prefix="dpcollide_")
    keep_db, keep_post, keep_time = dp.QUEUE_DB, dp.post_work_to_channel, time.time
    keep_impl = dp.enqueue_unique
    buf = io.StringIO()
    keep_out = sys.stdout
    try:
        dp.QUEUE_DB = os.path.join(tmp, "inbox.db")
        dp.post_work_to_channel = lambda *a, **k: ""      # 外へ出る手だけ止める
        time.time = lambda: FIXED_MS / 1000.0             # ★同じミリ秒を強制(本番で起きる衝突)
        if impl is not None:
            dp.enqueue_unique = impl
        sys.stdout = buf
        rets = [dp.dispatch("hq", "検査(イージス研究室)", "1本目", audience="ai"),
                dp.dispatch("hq", "検査(イージス研究室)", "2本目", audience="ai")]
        sys.stdout = keep_out
        con = sqlite3.connect(dp.QUEUE_DB)
        rows = con.execute("SELECT msg_id, body FROM queue ORDER BY id").fetchall()
        con.close()
        return rows, rets, buf.getvalue()
    finally:
        sys.stdout = keep_out
        dp.QUEUE_DB, dp.post_work_to_channel, time.time = keep_db, keep_post, keep_time
        dp.enqueue_unique = keep_impl
        shutil.rmtree(tmp, ignore_errors=True)


_rows, _rets, _out = two_in_same_ms()
check("★同じミリ秒の2本が2本とも届く", len(_rows) == 2, f"rows={len(_rows)}")
check("1本目の id は従来の形のまま", _rows[0][0] == f"DISPATCH-hq-{FIXED_MS}", _rows[0][0])
check("2本目だけ -2 で逃げている", _rows[1][0] == f"DISPATCH-hq-{FIXED_MS}-2", _rows[1][0])
check("本文が別物として2本残る",
      sorted(json.loads(b)["content"] for _, b in _rows) == ["1本目", "2本目"])
check("行の id と便の中の msg_id が一致", all(json.loads(b)["msg_id"] == m for m, b in _rows))
check("戻り値も実際に載った id", [r[1] for r in _rets] == [_rows[0][0], _rows[1][0]], str(_rets))
check("2本とも ok=True", all(r[0] for r in _rets))
check("衝突したことは黙らずに印字する", "id衝突" in _out, _out.strip()[-200:])


print("\n--- ③ 逃がしきれない時は成功と印字しない(fail-loud) ---")


def all_taken():
    """base と -2..-N を全部埋めた状態で dispatch() を1本出す。"""
    tmp = tempfile.mkdtemp(prefix="dpfull_")
    keep_db, keep_post, keep_time = dp.QUEUE_DB, dp.post_work_to_channel, time.time
    buf, keep_out = io.StringIO(), sys.stdout
    try:
        dp.QUEUE_DB = os.path.join(tmp, "inbox.db")
        dp.post_work_to_channel = lambda *a, **k: ""
        time.time = lambda: FIXED_MS / 1000.0
        from leasequeue import LeaseQueue
        q = LeaseQueue(dp.QUEUE_DB)
        base = f"DISPATCH-hq-{FIXED_MS}"
        for m in [base] + [f"{base}-{i}" for i in range(2, dp.ID_COLLISION_MAX + 1)]:
            q.enqueue(json.dumps({"msg_id": m}), msg_id=m, dept="hq")
        q.close()
        sys.stdout = buf
        ret = dp.dispatch("hq", "検査(イージス研究室)", "溢れる便", audience="ai")
        sys.stdout = keep_out
        con = sqlite3.connect(dp.QUEUE_DB)
        n = con.execute("SELECT COUNT(*) FROM queue").fetchone()[0]
        con.close()
        return ret, n, buf.getvalue()
    finally:
        sys.stdout = keep_out
        dp.QUEUE_DB, dp.post_work_to_channel, time.time = keep_db, keep_post, keep_time
        shutil.rmtree(tmp, ignore_errors=True)


_ret, _n, _out2 = all_taken()
check("載らなかったら ok=False", _ret[0] is False, str(_ret))
check("載らなかったら id を返さない", _ret[1] == "", repr(_ret[1]))
check("★「投函」と嘘をつかない", "キューへ投函 msg=" not in _out2, _out2.strip()[-200:])
check("入っていないことを大声で言う", "入っていない" in _out2, _out2.strip()[-200:])
check("キューは増えていない", _n == dp.ID_COLLISION_MAX, str(_n))


# ================================================================ must-fail

def _mf_swallow():
    """壊した側= **戻り値を読まない旧実装**(動く別の実装)。1回投げて成功と答える。"""
    def swallow(enqueue, base_id, build_body, max_tries=None):
        enqueue(build_body(base_id), base_id)
        return True, base_id, 1

    rows, rets, out = two_in_same_ms(impl=swallow)
    # 2本目は無警報で消え、しかも ok=True と印字される= 直した穴そのもの
    return (len(rows), all(r[0] for r in rets), "id衝突" in out)


print("\n--- must-fail(戻り値を読まない旧実装に戻すと2本目が消える) ---")
mustfail("旧実装だと1本しか残らないのに成功と答える", _mf_swallow, (1, True, False))


# ================================================================ 判定

ng = [n for n, ok, _ in RESULTS if not ok]
print("\n===== %d件中 %d件PASS =====" % (len(RESULTS), len(RESULTS) - len(ng)))
if ng:
    print("FAIL — %d件: %s" % (len(ng), ng))
    sys.exit(1)
print("ALL PASS")
