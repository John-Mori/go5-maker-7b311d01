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

        # 2) claim→ack の基本 (2026-07-18統合: ackは行を消さずdone=台帳として残る)
        c = q.claim(dept="qa", who="tester")
        check("claim で内容が取れる", c and c["body"]["content"] == "A")
        check("claim後 ready=0 leased=1 (見えなくなった)", q.stats()["ready"] == 0 and q.stats()["leased"] == 1)
        c2 = q.claim(dept="qa")
        check("リース中は同じ行を二重取得しない (INC-85相当)", c2 is None)
        check("ack=True", q.ack(c["id"], result="返信済") is True)
        st = q.stats()
        check("ack後 done=1 (台帳として残る=INC-103)", st["done"] == 1 and st["ready"] == 0 and st["leased"] == 0)
        check("二重ackはFalse", q.ack(c["id"]) is False)
        # ★done行が残るから、鳩の再起動等で同msg_idが再投入されても冪等照合が生きる
        check("ack後の同msg_id再投入も無視される (再起動跨ぎの二重処理防止)",
              q.enqueue({"content": "A3"}, msg_id="M1", dept="qa") is False)

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
        c = q3.claim(dept="qa")
        check("nack後は即座に再claimできる (長リースでも待たない)", c is not None)
        q3.ack(c["id"])

        # 7) extend: 長い処理のリース延長 (2026-07-18統合)
        q4 = LeaseQueue(os.path.join(d, "q4.db"), lease_sec=1)
        q4.enqueue({"content": "long"}, msg_id="L1", dept="qa")
        c = q4.claim(dept="qa")
        check("extend=True", q4.extend(c["id"], lease_sec=60) is True)
        time.sleep(1.1)
        check("延長後はリース切れ扱いにならない", q4.claim(dept="qa") is None)
        q4.ack(c["id"])

        # 8) stale_pending: 一度もclaimされない放置の検出 (部門が死んでいる時の救済)
        q4.enqueue({"content": "ghost"}, msg_id="G1", dept="ghost-dept")
        time.sleep(0.2)
        sp = q4.stale_pending(older_sec=0.1)
        check("未claim放置が検出される", any(r["msg_id"] == "G1" for r in sp))
        check("新しい行や処理済みは検出されない", not q4.stale_pending(older_sec=3600))

        # 8.5) reroute: 未claim放置のエスカレート (sweep相当・2026-07-18 QA追加)
        # ※G1(ghost)はテスト10の前提として触らず、専用メッセージで検証する
        q5r = LeaseQueue(os.path.join(d, "q5r.db"), lease_sec=900)
        q5r.enqueue({"content": "orphan"}, msg_id="O1", dept="dead-dept")
        time.sleep(0.15)
        oid = q5r.stale_pending(older_sec=0.1)[0]["id"]
        check("rerouteでdeptを付け替えられる", q5r.reroute(oid, "router") is True)
        rc = q5r.claim(dept="router")
        check("付け替え先のdeptでclaimできる (リースも解放済)", rc is not None and rc["msg_id"] == "O1")
        check("処理済み行へのrerouteは効かない", q5r.ack(rc["id"]) and q5r.reroute(rc["id"], "qa") is False)

        # 8.7) abandoned: nack済み行もエスカレ対象に拾う (研究室指摘のエッジ・2026-07-18)
        qa2 = LeaseQueue(os.path.join(d, "qa2.db"), lease_sec=900)
        qa2.enqueue({"content": "nacked"}, msg_id="N1", dept="qa")
        qa2.enqueue({"content": "working"}, msg_id="N2", dept="qa")
        c1 = qa2.claim(dept="qa")              # 最古優先=N1
        c2 = qa2.claim(dept="qa")              # 次=N2 (両方リース中)
        qa2.nack(c1["id"])                     # N1だけ手放す=deliveries=1でリース失効状態
        time.sleep(0.15)
        ab = qa2.abandoned(older_sec=0.1)
        ids = [r["msg_id"] for r in ab]
        check("abandonedはnack済み行(N1)を拾う (stale_pendingの検出外)", "N1" in ids)
        check("abandonedはリース有効の処理中行(N2)を含まない", "N2" not in ids)
        check("stale_pendingはN1を拾えない (エッジの実証)",
              "N1" not in [r["msg_id"] for r in qa2.stale_pending(older_sec=0.1)])

        # 9) next_counter: 表示用連番の原子的採番 (INC-99/100二重の根治)
        check("counter 1", q4.next_counter("INC") == 1)
        check("counter 2", q4.next_counter("INC") == 2)
        check("counter 別名は独立", q4.next_counter("REQ") == 1)

        # 10) purge_done: 古いdoneだけ消える (台帳の掃除)
        n = q4.purge_done(older_sec=0)   # 全doneが対象
        check("purge_doneでdone行だけ掃除される", n >= 1 and q4.stats()["done"] == 0)
        check("pending(ghost)は残る", q4.stats()["ready"] == 1)

        # 11) ★並行claim: 2スレッドで40件を取り合い、重複ゼロ・取りこぼしゼロ
        import threading
        q5 = LeaseQueue(os.path.join(d, "q5.db"), lease_sec=60)
        for i in range(40):
            q5.enqueue({"i": i}, msg_id=f"R{i}", dept="race")
        got, lock = [], threading.Lock()

        def racer(name):
            mine = LeaseQueue(os.path.join(d, "q5.db"), lease_sec=60)
            while True:
                r = mine.claim(dept="race", who=name)
                if r is None:
                    break
                with lock:
                    got.append(r["msg_id"])
                mine.ack(r["id"])
            mine.close()

        ts = [threading.Thread(target=racer, args=(f"t{i}",)) for i in range(2)]
        [t.start() for t in ts]
        [t.join() for t in ts]
        check("並行claimで40件ちょうど1回ずつ (重複/取りこぼしゼロ)",
              len(got) == 40 and len(set(got)) == 40)

        ok = all(v for _, v in results)
        print(f"\n== {sum(v for _, v in results)}/{len(results)} PASS ==")
        return 0 if ok else 1
    finally:
        import shutil
        shutil.rmtree(d, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
