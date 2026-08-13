#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""dead へ落ちた便が「その部屋へ」出るかを**実行で**通す検査(2026-08-14 イージス研究室)。

なぜ要るか= `c9cef61` で DLQ の**まとめ警報**の宛先を2室(通知受付+HQ)に絞った。その裁定の
**前提条件**は「当該部門へは `on_dead` が個別に出す」だ。ところが `on_dead` の受け側
(`dept_daemon.Daemon._dead_letter_notice`)は**本番で1度も発火していない**
(`local/queue/dead_letters.jsonl` 不在・2026-08-14 03:49 HQ再確認)。
= 前提条件そのものが**未検証のまま**で、実deadが来た日が初検証になる。
共通規律§3「今その状態が無いから実行できない、は、**その状態を作って渡す**」の適用だ。

やり方= 外へ出る手(送信=`subprocess`・ログ書き込み=`log`・書き込み先=`LOCAL`)だけ偽物にし、
**判定・本文組み立て・宛先は本物のまま**回す。Discordへは1通も出ない。

実行: python scripts/queue/test_dead_letter_notice.py
"""
import os
import sys
import tempfile
import time

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "llm"))
from leasequeue import LeaseQueue      # noqa: E402
import dept_daemon as dd               # noqa: E402

results = []
DEPT = "aegis-gl"


def check(name, cond):
    results.append((name, bool(cond)))
    print(f"  {'PASS' if cond else 'FAIL'}: {name}")


class SendSpy:
    """`subprocess` の代役。**送らずに**呼ばれた引数だけ控える。

    dept_daemon は `subprocess.run([...])` の形でしか使わないので、run だけ持てば足りる。
    boom=True にすると送信が例外を投げる= 呼び側が握り潰す設計かどうかを実行で見られる。
    """

    def __init__(self, boom=False):
        self.calls = []
        self.boom = boom

    def run(self, argv, **kw):
        self.calls.append(list(argv))
        if self.boom:
            raise OSError("送信そのものが落ちた(実行で再現)")

        class R:
            returncode = 0
            stdout = ""
            stderr = ""
        return R()


def notify(info, dry_run=False, boom=False):
    """本物の `_dead_letter_notice` を1回だけ通し、(送信の引数, 出た本文, ログ行) を返す。

    偽物にするのは**外へ出る手だけ**= 送信(subprocess)・ログ・書き込み先(LOCAL)。
    本文の組み立ても宛先の決定も本物が走る。
    """
    spy = SendSpy(boom=boom)
    logs = []
    tmp = tempfile.mkdtemp(prefix="dlnotice_")
    o_sub, o_log, o_local = dd.subprocess, dd.log, dd.LOCAL
    dd.subprocess, dd.log, dd.LOCAL = spy, (lambda dept, msg: logs.append((dept, msg))), tmp
    try:
        d = dd.Daemon(DEPT, dry_run=dry_run)
        d._dead_letter_notice(info)
    finally:
        dd.subprocess, dd.log, dd.LOCAL = o_sub, o_log, o_local
    body = ""
    p = os.path.join(tmp, "_work", "dead_letter_notice_%s.txt" % DEPT)
    if os.path.exists(p):
        body = open(p, encoding="utf-8").read()
    return spy.calls, body, logs


def main():
    print("=== A) 通知の受け側(_dead_letter_notice)を実行で通す ===")
    info = {"ts": time.time(), "id": 9001, "msg_id": "1537508993923154042",
            "dept": DEPT, "deliveries": 6,
            "body": {"author": "chami_fusoh",
                     "content": "1528653749747191882\n1番困る部類の出来事。反応がない。"}}
    calls, body, logs = notify(info)

    check("★通知が1本だけ出た(実発火)", len(calls) == 1)
    argv = calls[0] if calls else []
    check("★宛先は当該部門= aegis-gl(ここが2室に絞った前提条件)",
          "--dept" in argv and argv[argv.index("--dept") + 1] == DEPT)
    check("名義は機械(人格ではない)",
          "--persona" in argv and argv[argv.index("--persona") + 1] == dd.MACHINE_PERSONA)
    check("実行するのは persona_send.py",
          any(str(a).endswith("persona_send.py") for a in argv))
    check("本文はファイル渡し(長文で欠けない)", "--body-file" in argv)

    print("  -- 出た本文(実物) --")
    for ln in body.splitlines():
        print("   | " + ln)
    check("★本文に便のidが入る(dlq_toolで引ける)", "1537508993923154042" in body)
    check("差出人が読める", "chami_fusoh" in body)
    check("中身の頭が読める(何の便が消えたか分かる)", "1番困る部類の出来事" in body)
    check("何回試して諦めたかが出る", "6回" in body)
    check("★二度と拾われないことが書いてある(待たせない)", "二度と拾われない" in body)
    check("次の一手(dlq_tool)への道が書いてある", "dlq_tool.py" in body)
    check("改行は潰してある(引用が1行に収まる)",
          "\n" not in body.split("> ")[1].split("\n")[0] if "> " in body else False)
    check("ログにも残る(通知が出せなくても追える)",
          any("dead-letter" in m for _, m in logs))

    print("=== B) 壊れた入力でも黙らない(fail-open) ===")
    calls2, body2, _ = notify({"msg_id": None, "deliveries": None, "body": "文字列で来た"})
    check("bodyがdictでなくても例外を出さず通知は出る", len(calls2) == 1)
    check("差出人が取れない時は「不明」と書く(推測で埋めない)", "不明" in body2)
    check("本文が空でも「(本文なし)」で出す", "(本文なし)" in body2)

    calls3, _, _ = notify(info, boom=True)
    check("★送信そのものが落ちても例外を外へ出さない(キューを止めない)", len(calls3) == 1)

    calls4, _, _ = notify(info, dry_run=True)
    check("dry_runでは1通も出ない(検証便で部屋を汚さない)", len(calls4) == 0)

    print("=== C) 実deadから通知まで、繋いだまま流す(端から端) ===")
    d = tempfile.mkdtemp(prefix="dlq_e2e_")
    path = os.path.join(d, "q.db")
    q = LeaseQueue(path, lease_sec=1, max_deliveries=2)
    spy = SendSpy()
    logs = []
    tmp = tempfile.mkdtemp(prefix="dle2e_")
    o_sub, o_log, o_local = dd.subprocess, dd.log, dd.LOCAL
    dd.subprocess, dd.log, dd.LOCAL = spy, (lambda dept, msg: logs.append((dept, msg))), tmp
    try:
        daemon = dd.Daemon(DEPT, dry_run=False)
        q.on_dead = daemon._dead_letter_notice      # ★dept_daemon.py:5403 と同じ配線
        q.enqueue({"content": "この部屋、応答できる?", "author": "chami_fusoh"},
                  msg_id="M-e2e", dept=DEPT)
        for _ in range(5):
            c = q.claim(dept=DEPT, who="t")
            if c:
                q.nack(c["id"])                     # 返金なし= 普通に数えられて死ぬ
    finally:
        dd.subprocess, dd.log, dd.LOCAL = o_sub, o_log, o_local
    st = q._db.execute("SELECT status FROM queue WHERE msg_id='M-e2e'").fetchone()
    check("前提: 便は dead まで落ちた", st and st[0] == "dead")
    check("★実deadで通知が出た= 2室に絞った前提条件は成立する", len(spy.calls) == 1)
    check("★その通知は当該部門(aegis-gl)へ向いている",
          bool(spy.calls) and spy.calls[0][spy.calls[0].index("--dept") + 1] == DEPT)
    jl = os.path.join(d, "dead_letters.jsonl")
    check("通知と別に、消えない記録がDBの隣に残る", os.path.exists(jl))
    e2e_body = ""
    p = os.path.join(tmp, "_work", "dead_letter_notice_%s.txt" % DEPT)
    if os.path.exists(p):
        e2e_body = open(p, encoding="utf-8").read()
    check("記録と通知が同じ便を指している(取り違えない)",
          "M-e2e" in e2e_body and "M-e2e" in open(jl, encoding="utf-8").read())

    ng = [n for n, ok in results if not ok]
    print(f"\n{len(results) - len(ng)}/{len(results)} PASS")
    if ng:
        for n in ng:
            print("  FAIL: " + n)
        return 1
    print("★deadの個別通知は実行で通した(本番の初発火を待たずに検証済)。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
