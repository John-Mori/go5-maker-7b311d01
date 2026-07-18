#!/usr/bin/env python3
"""bus.py の検証テスト。設計書§3提案Aが主張する不変条件を実測で確かめる。

証明する不変条件:
  T1 冪等: 同じmsg_idを二重投入しても1件しか入らない(INC-87=二重処理の根治)
  T2 排他: pendingが1件のとき2回claimしても2回目はNone(同じ行を二重に取らない)
  T3 並行排他: Nスレッドが同時にclaimしても、取得msg_idの重複ゼロ・取りこぼしゼロ
  T4 リース失効: 処理中に落ちた(=completeしない)claimはsweepでpendingに戻り再claimできる(自動再配達)
  T5 完了の隙間なし: claim→completeでstatus=done、pendingは残らない(mvドレイン窓の消滅)

実行: python scripts/bus/test_bus.py   (全PASSで exit 0)
"""
import os
import sys
import tempfile
import threading
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from bus import Bus  # noqa: E402


def _fresh_db():
    d = tempfile.mkdtemp(prefix="bustest_")
    return os.path.join(d, "bus.db")


def t1_idempotent():
    bus = Bus(_fresh_db())
    assert bus.enqueue("m1", "hr-room", body="a") is True
    assert bus.enqueue("m1", "hr-room", body="a-dup") is False   # 同じidは弾かれる
    got = [bus.claim("hr-room", "w") for _ in range(3)]
    n = sum(1 for g in got if g)
    assert n == 1, f"二重投入で{n}件claimできた(冪等でない)"
    return "T1 冪等: 同一msg_idは1件のみ"


def t2_exclusive_single():
    bus = Bus(_fresh_db())
    bus.enqueue("m1", "hr-room")
    a = bus.claim("hr-room", "wA")
    b = bus.claim("hr-room", "wB")
    assert a and a["msg_id"] == "m1"
    assert b is None, "pending1件なのに2回claimできた(排他でない)"
    return "T2 排他: pending1件は1回しか取れない"


def t3_concurrent():
    bus = Bus(_fresh_db())
    N = 200
    for i in range(N):
        bus.enqueue(f"m{i}", "hr-room")
    got = []
    lock = threading.Lock()

    def worker(wid):
        while True:
            c = bus.claim("hr-room", f"w{wid}")
            if not c:
                # pendingが尽きた可能性。念のためもう一度だけ確認して抜ける
                c2 = bus.claim("hr-room", f"w{wid}")
                if not c2:
                    break
                c = c2
            with lock:
                got.append(c["msg_id"])
            time.sleep(0.0005)

    threads = [threading.Thread(target=worker, args=(k,)) for k in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert len(got) == len(set(got)), f"重複claim発生: 取得{len(got)}件・ユニーク{len(set(got))}件"
    assert len(set(got)) == N, f"取りこぼし: {N}件中{len(set(got))}件しか取れていない"
    return f"T3 並行排他: 8スレッドで{N}件を重複0・取りこぼし0"


def t4_lease_expiry():
    bus = Bus(_fresh_db())
    bus.enqueue("m1", "hr-room")
    c = bus.claim("hr-room", "wDead", lease_sec=0.1)   # 短いが有効なリースで取得→この後completeせず放置(=落ちた体)
    assert c and c["msg_id"] == "m1"
    assert bus.claim("hr-room", "wOther") is None      # リース有効中は他ワーカーは取れない
    time.sleep(0.15)                                   # リース満了を待つ
    moved = bus.sweep_expired()                        # 失効した分をpendingへ回収(=再配達)
    assert moved == 1, f"sweepで戻った件数={moved}(期待1)"
    again = bus.claim("hr-room", "wAlive")             # 再配達されたので別ワーカーが取れる
    assert again and again["msg_id"] == "m1"
    assert again["attempts"] == 2, f"attempts={again['attempts']}(再配達で2のはず)"
    return "T4 リース失効: 落ちたclaimはsweepで再配達される(有効リース中は他が取れない)"


def t5_complete_no_gap():
    bus = Bus(_fresh_db())
    bus.enqueue("m1", "hr-room")
    c = bus.claim("hr-room", "w")
    assert bus.complete(c["msg_id"]) is True
    assert bus.claim("hr-room", "w") is None            # doneは二度と配られない
    stats = {(r["status"]): r["n"] for r in bus.stats()}
    assert stats.get("done") == 1 and "pending" not in stats
    assert bus.complete(c["msg_id"]) is False           # 二重完了は効かない(冪等)
    return "T5 完了: claim→completeでdone・pendingは残らない"


def main():
    tests = [t1_idempotent, t2_exclusive_single, t3_concurrent, t4_lease_expiry, t5_complete_no_gap]
    ok = 0
    for t in tests:
        try:
            msg = t()
            print(f"  PASS  {msg}")
            ok += 1
        except AssertionError as e:
            print(f"  FAIL  {t.__name__}: {e}")
        except Exception as e:
            print(f"  ERROR {t.__name__}: {type(e).__name__}: {e}")
    print(f"\n{ok}/{len(tests)} passed")
    return 0 if ok == len(tests) else 1


if __name__ == "__main__":
    sys.exit(main())
