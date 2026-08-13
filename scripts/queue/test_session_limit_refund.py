#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""上限エラーで便が死なないこと / dead を黙らせないことの検査(2026-08-14 イージス研究室)。

発注= 研究室HQ DISPATCH-aegis-gl-1786643264450。
壊れていた実物= 2026-08-14 01:04〜02:44 JST、Claude CLI のセッション上限で relay が rc=1 を
返し続け、**Chamiの便 msg 1537508993923154042 が deliveries=6 / status=dead** になった
(deadは二度と拾われない=黙って消える)。

受け入れ条件(HQ)=
  A. 上限エラーを模した失敗を**6回以上**通しても、便が dead にならず pending のまま残る。
  B. dead へ落ちた瞬間に通知が出る(ここではフックが呼ばれ、記録が残ることを見る)。

実行: python scripts/queue/test_session_limit_refund.py
"""
import os
import sys
import tempfile
import time

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "llm"))
from leasequeue import LeaseQueue  # noqa: E402

results = []

LIMIT_ERR = ("Claude CLIがエラーを返した(rc=1): "
             "You've hit your session limit · resets 2:40am (Etc/GMT-9)")


def check(name, cond):
    results.append((name, bool(cond)))
    print(f"  {'PASS' if cond else 'FAIL'}: {name}")


def status_of(q, msg_id):
    return q._db.execute(
        "SELECT status, deliveries, refunds FROM queue WHERE msg_id=?", (msg_id,)).fetchone()


def main():
    d = tempfile.mkdtemp(prefix="qa_limit_")
    path = os.path.join(d, "q.db")
    try:
        # --- A) 上限エラーは再配達の回数を消費しない ------------------------------
        q = LeaseQueue(path, lease_sec=1, max_deliveries=5)
        q.enqueue({"content": "Chamiの便", "author": "chami_fusoh"}, msg_id="M-limit", dept="pse")
        for i in range(8):                      # ★HQの条件は「6回以上」。8回通す
            c = q.claim(dept="pse", who="t")
            check(f"{i+1}回目も便が取れる(deadになっていない)", bool(c))
            if not c:
                break
            # 上限中は「今すぐ」再開してよい時刻を渡す(検査を待たせないため過去時刻)
            r = q.nack(c["id"], retry_after=time.time() - 1, refund=True)
            check(f"{i+1}回目は返金された", r["refunded"] is True)
        st = status_of(q, "M-limit")
        check("★8回の上限エラーを通しても pending のまま(dead でない)", st[0] == "pending")
        check("deliveries が上限(5)に達していない", st[1] <= 1)
        check("返金の回数が記録されている", st[2] == 8)

        # --- A-2) 返金には打ち止めがある(外部要因を名乗る無限ループを作らない) ----
        q2 = LeaseQueue(path, lease_sec=1, max_deliveries=5, max_refunds=2)
        q2.enqueue({"content": "毒"}, msg_id="M-cap", dept="pse2")
        for _ in range(2):
            c = q2.claim(dept="pse2", who="t")
            q2.nack(c["id"], retry_after=time.time() - 1, refund=True)
        c = q2.claim(dept="pse2", who="t")
        r = q2.nack(c["id"], retry_after=time.time() - 1, refund=True)
        check("★返金は max_refunds で打ち止め(以後は普通に数える)", r["refunded"] is False)

        # --- A-3) retry_after を渡した便は、その時刻まで claim されない -----------
        q3 = LeaseQueue(path, lease_sec=1)
        q3.enqueue({"content": "待たせる"}, msg_id="M-hold", dept="pse3")
        c = q3.claim(dept="pse3", who="t")
        q3.nack(c["id"], retry_after=time.time() + 3600, refund=True)
        check("★リセット時刻まで再配達されない(叩きに行かない)",
              q3.claim(dept="pse3", who="t") is None)
        # 手前に戻せば普通に取れる=永久に隠れるわけではない
        q3.nack(c["id"], retry_after=time.time() - 1)
        check("時刻を過ぎれば普通に取れる", bool(q3.claim(dept="pse3", who="t")))

        # --- A-4) 既定の nack は今までと1バイトも変わらない -----------------------
        q4 = LeaseQueue(path, lease_sec=1)
        q4.enqueue({"content": "従来"}, msg_id="M-old", dept="pse4")
        c = q4.claim(dept="pse4", who="t")
        q4.nack(c["id"])                                  # 引数なし=旧来の呼び方
        st = status_of(q4, "M-old")
        check("引数なしnackは返金しない(deliveries=1のまま)", st[1] == 1 and st[2] == 0)
        check("引数なしnackは即座に拾い直せる", bool(q4.claim(dept="pse4", who="t")))

        # --- B) dead へ落ちたら黙らない -------------------------------------------
        seen = []
        q5 = LeaseQueue(path, lease_sec=1, max_deliveries=2)
        q5.on_dead = lambda info: seen.append(info)
        q5.enqueue({"content": "毒便", "author": "chami_fusoh"}, msg_id="M-dead", dept="pse5")
        for _ in range(5):
            c = q5.claim(dept="pse5", who="t")
            if c:
                q5.nack(c["id"])                          # 返金しない=普通に数えられて死ぬ
        st = status_of(q5, "M-dead")
        check("前提: 返金なしなら従来どおり dead へ落ちる", st[0] == "dead")
        check("★dead の瞬間にフックが呼ばれた(通知が出せる)", len(seen) == 1)
        check("フックが便の中身を渡している", seen and seen[0]["msg_id"] == "M-dead")
        jl = os.path.join(d, "dead_letters.jsonl")
        check("★通知が失敗しても消えない記録がDBの隣に残る", os.path.exists(jl))

        # --- C) 上限エラーの判定と復帰時刻の読み取り -------------------------------
        from dept_daemon import session_limit_retry_after as sl
        now = time.mktime((2026, 8, 14, 2, 10, 0, 0, 0, -1))
        check("上限エラーだと判定できる", sl(LIMIT_ERR, now) is not None)
        t = time.localtime(sl(LIMIT_ERR, now))
        check("★`resets 2:40am` を 02:40 と読める(実物の文言)",
              (t.tm_hour, t.tm_min) == (2, 41))
        check("上限でないエラーは None(従来の数え方のまま)",
              sl("Claude CLIがエラーを返した(rc=2): boom", now) is None)
        check("タイムアウトは上限ではない", sl("600秒待ったが返事が無い", now) is None)
        past = time.mktime((2026, 8, 14, 3, 0, 0, 0, 0, -1))
        check("★既に過ぎた時刻は「翌日」ではなく直後(1日寝ない)",
              sl(LIMIT_ERR, past) - past <= 120)
        check("時刻が読めなくても上限なら待たせる(便を死なせない)",
              sl("You've hit your session limit", now) - now >= 60)

        ok = all(v for _, v in results)
        print(f"\n== {sum(v for _, v in results)}/{len(results)} PASS ==")
        return 0 if ok else 1
    finally:
        import shutil
        shutil.rmtree(d, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
