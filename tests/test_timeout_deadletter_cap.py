# -*- coding: utf-8 -*-
"""打ち切り便の再走打ち止め(トークン浪費対策 2026-09-03・Chami指示)の回帰試験。

背景= 重い会話便(opus+文脈61k)が hard=600秒で毎回打ち切られ、nackで再配達される
      たびに 600秒の生成+世代交代を丸ごと捨てる。max_deliveries(5)回まで=莫大な浪費。
恒久策= plain timeout が2回に達したら走らせ直さず dead へ隔離する(通知は出る=沈黙にしない)。

2つを実行で見る=
  (A) leasequeue.fail_dead: pending の便を dead にし、on_dead(通知フック)を1回だけ呼ぶ。
      既に dead / 存在しない便には False を返し、通知を呼ばない(二重通知しない)。
  (B) dept_daemon.timeout_should_dead: plain timeout が cap 回で True。
      1回目・上限待ち(retry_after)・timeout以外は False(=従来どおり再走/返金)。

must-fail= 旧コード(.bak)には fail_dead も timeout_should_dead も無い →
           AttributeError で赤くなるのを先に見る(空PASSでないことの証明)。
走らせ方= python tests/test_timeout_deadletter_cap.py
"""
import os
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "scripts", "queue"))
sys.path.insert(0, os.path.join(ROOT, "scripts", "llm"))

fails = []


def chk(name, cond):
    print(("PASS " if cond else "FAIL ") + name)
    if not cond:
        fails.append(name)


# --- (A) leasequeue.fail_dead -------------------------------------------------
import leasequeue  # noqa: E402

db = os.path.join(tempfile.mkdtemp(), "t.db")
q = leasequeue.LeaseQueue(db)
seen = []
q.on_dead = lambda info: seen.append(info)

q.enqueue({"content": "重い便"}, msg_id="m1", dept="x")
c = q.claim(dept="x")
chk("A0 claimできる", c is not None and c["msg_id"] == "m1")
ok = q.fail_dead(c["id"])
chk("A1 fail_deadがTrueを返す", ok is True)
chk("A2 on_deadが1回だけ呼ばれた(部屋へ通知=沈黙にしない)", len(seen) == 1)
chk("A3 もう pending は無い(deadへ隔離された=再走しない)", q.claim(dept="x") is None)
ok2 = q.fail_dead(c["id"])
chk("A4 既にdeadなら2度目はFalse", ok2 is False)
chk("A5 二重通知しない(on_deadは増えない)", len(seen) == 1)

# --- (B) dept_daemon.timeout_should_dead -------------------------------------
import dept_daemon  # noqa: E402

CAP = dept_daemon.TIMEOUT_MAX_DELIVERIES
f = dept_daemon.timeout_should_dead
chk("B0 capは2(1回は一過性を許容)", CAP == 2)
chk("B1 plain timeout が cap回=dead(浪費停止)", f("timeout", None, CAP) is True)
chk("B2 plain timeout 1回目=まだ再走(一過性ハングを許す)", f("timeout", None, 1) is False)
chk("B3 セッション上限待ち(retry_after)はdeadにしない=返金対象・浪費でない",
    f("timeout", 9999999999, CAP) is False)
chk("B4 timeout以外(配送失敗等)はdeadにしない=C-035広げない", f("dispatch_fail", None, 99) is False)
chk("B5 境界: cap未満はFalse / cap以上はTrue",
    f("timeout", None, CAP - 1) is False and f("timeout", None, CAP + 3) is True)

n = 13
print("\n%d FAIL / %d checks" % (len(fails), n))
sys.exit(1 if fails else 0)
