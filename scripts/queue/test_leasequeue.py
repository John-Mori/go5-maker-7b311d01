#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""LeaseQueue の不変条件テスト。全PASSで、INC-85/86/94/103の故障類型が構造的に不可能なことを示す。

実行: python scripts/queue/test_leasequeue.py
"""
import os
import sys
import tempfile
import time

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from leasequeue import LeaseQueue  # noqa: E402

results = []


def check(name, cond):
    results.append((name, bool(cond)))
    print(f"  {'PASS' if cond else 'FAIL'}: {name}")


def main():
    d = tempfile.mkdtemp(prefix="qa_lq_")
    path = os.path.join(d, "q.db")
    try:
        # 1) 冪等: 同じmsg_idの二重投入は無視 (鳩の二度入れ→二重処理しない)
        q = LeaseQueue(path, lease_sec=1)
        check("enqueue 1件目は成功", q.enqueue({"content": "A"}, msg_id="M1", dept="qa"))
        check("enqueue 同msg_id 2件目は無視 (冪等)", q.enqueue({"content": "A2"}, msg_id="M1", dept="qa") is False)
        check("total=1 (二重投入されていない)", q.stats()["total"] == 1)

        # 2) claim→ack の基本
        c = q.claim(dept="qa")
        check("claim で内容が取れる", c and c["body"]["content"] == "A")
        check("claim後 ready=0 leased=1 (見えなくなった)", q.stats()["ready"] == 0 and q.stats()["leased"] == 1)
        c2 = q.claim(dept="qa")
        check("リース中は同じ行を二重取得しない (INC-85相当)", c2 is None)
        q.ack(c["id"])
        check("ack後 total=0 (処理済で消える)", q.stats()["total"] == 0)

        # 3) ★リース切れ自動再配布 (INC-94/86の核心): 処理せず放置=死んだワーカー
        q.enqueue({"content": "B"}, msg_id="M2", dept="qa")
        first = q.claim(dept="qa")
        check("Bをclaim (deliveries=1)", first and first["deliveries"] == 1)
        check("リース切れ前は再配布されない", q.claim(dept="qa") is None)
        time.sleep(1.1)  # lease_sec=1 を超える
        again = q.claim(dept="qa")
        check("★リース切れ後に自動再配布される (メッセージが消えない)", again and again["msg_id"] == "M2")
        check("再配布で deliveries=2 に増える", again["deliveries"] == 2)
        q.ack(again["id"])

        # 4) dept分離: 他部門のメッセージは取らない (誤配送しない)
        q.enqueue({"content": "C"}, msg_id="M3", dept="hr")
        check("別deptのclaimでは取れない", q.claim(dept="qa") is None)
        got = q.claim(dept="hr")
        check("正しいdeptなら取れる", got and got["msg_id"] == "M3")
        q.ack(got["id"])

        # 5) 毒メッセージの dead-letter (max_deliveries超で無限ループしない)
        # nackで手放す=「ワーカーが取ったが処理失敗した」を模擬 (実時間を待たずに再配布可)。
        # 厳密な lease_until<now 判定はINC-85の二重配布を防ぐ正しい設計なので、テスト側で
        # nackを使って毒メッセージの再配布ループを再現する。
        q2 = LeaseQueue(os.path.join(d, "q2.db"), lease_sec=900, max_deliveries=3)
        q2.enqueue({"content": "poison"}, msg_id="P1", dept="qa")
        seen = 0
        for _ in range(10):
            c = q2.claim(dept="qa")
            if c is None:
                break
            seen += 1
            q2.nack(c["id"])  # 処理失敗で手放す (毒=必ず失敗する状況)
        check("dead-letterで頭打ちになる (無限に配られない)", seen <= 3)
        check("dead件数が1", q2.stats()["dead"] == 1)
        check("dead_lettersで隔離内容を取り出せる", len(q2.dead_letters()) == 1)

        # 6) nack で即時手放し
        q3 = LeaseQueue(os.path.join(d, "q3.db"), lease_sec=900)
        q3.enqueue({"content": "D"}, msg_id="M4", dept="qa")
        c = q3.claim(dept="qa")
        q3.nack(c["id"])
        check("nack後は即座に再claimできる (長リースでも待たない)", q3.claim(dept="qa") is not None)

        ok = all(v for _, v in results)
        print(f"\n== {sum(v for _, v in results)}/{len(results)} PASS ==")
        return 0 if ok else 1
    finally:
        import shutil
        shutil.rmtree(d, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
