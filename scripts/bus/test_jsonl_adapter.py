#!/usr/bin/env python3
"""jsonl_adapter.py の検証。JSONL箱→バスの取り込みが安全・冪等であることを確かめる。

A1 取り込み: 箱の全行がバスにenqueueされ、箱ファイルは消える(退避処理済み)
A2 冪等: 同じ内容を2回取り込んでも二重にならない(msg_id主キー)・重複はdupで数える
A3 残置回収: 前回の .ingesting が残っていても次回に回収される(取り込み途中落ちからの復帰)
A4 E2E: 取り込み→claim→completeが一気通貫で回る
"""
import json
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from bus import Bus            # noqa: E402
from jsonl_adapter import ingest_box  # noqa: E402


def _mk_box(lines):
    d = tempfile.mkdtemp(prefix="adtest_")
    box = os.path.join(d, "hr-room.jsonl")
    with open(box, "w", encoding="utf-8") as f:
        for rec in lines:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    return box


def _rec(mid, body="x"):
    return {"msg_id": mid, "channel": "人事", "author": "chami", "content": body}


def a1_ingest():
    box = _mk_box([_rec("m1"), _rec("m2"), _rec("m3")])
    bus = Bus(os.path.join(os.path.dirname(box), "bus.db"))
    new, dup = ingest_box(bus, box, "hr-room")
    assert (new, dup) == (3, 0), f"取り込み結果={new},{dup}"
    assert not os.path.exists(box), "箱が退避されず残っている"
    stats = {r["status"]: r["n"] for r in bus.stats()}
    assert stats.get("pending") == 3
    return "A1 取り込み: 3件enqueue・箱は退避済み"


def a2_idempotent():
    box = _mk_box([_rec("m1"), _rec("m2")])
    bus = Bus(os.path.join(os.path.dirname(box), "bus.db"))
    ingest_box(bus, box, "hr-room")
    # 同じ内容の箱をもう一度作って取り込む→全部重複で弾かれる
    box2 = _mk_box([_rec("m1"), _rec("m2")])
    # 同じDBを使う
    bus2 = Bus(os.path.join(os.path.dirname(box), "bus.db"))
    new, dup = ingest_box(bus2, box2, "hr-room")
    assert (new, dup) == (0, 2), f"再取り込み={new},{dup}(全部重複のはず)"
    return "A2 冪等: 同一msg_idの再取り込みは全て重複スキップ"


def a3_recover_staging():
    box = _mk_box([_rec("m1")])
    d = os.path.dirname(box)
    # 前回の取り込み途中で残った .ingesting を模擬(m0が入っている)
    with open(box + ".ingesting", "w", encoding="utf-8") as f:
        f.write(json.dumps(_rec("m0"), ensure_ascii=False) + "\n")
    bus = Bus(os.path.join(d, "bus.db"))
    new, dup = ingest_box(bus, box, "hr-room")
    # m0(残置)とm1(今の箱)の両方が取り込まれる
    assert new == 2, f"残置回収を含めた新規={new}(m0+m1で2のはず)"
    assert not os.path.exists(box + ".ingesting"), "残置が回収後に消えていない"
    return "A3 残置回収: 前回の取り込み途中分も次回に回収される"


def a4_e2e():
    box = _mk_box([_rec("m1", "依頼A")])
    bus = Bus(os.path.join(os.path.dirname(box), "bus.db"))
    ingest_box(bus, box, "hr-room")
    c = bus.claim("hr-room", "hr-session")
    assert c and c["msg_id"] == "m1" and c["body"] == "依頼A"
    assert bus.complete(c["msg_id"]) is True
    assert bus.claim("hr-room", "hr-session") is None   # 処理済みは再配達されない
    return "A4 E2E: 取り込み→claim→completeが一気通貫"


def main():
    tests = [a1_ingest, a2_idempotent, a3_recover_staging, a4_e2e]
    ok = 0
    for t in tests:
        try:
            print(f"  PASS  {t()}")
            ok += 1
        except AssertionError as e:
            print(f"  FAIL  {t.__name__}: {e}")
        except Exception as e:
            print(f"  ERROR {t.__name__}: {type(e).__name__}: {e}")
    print(f"\n{ok}/{len(tests)} passed")
    return 0 if ok == len(tests) else 1


if __name__ == "__main__":
    sys.exit(main())
