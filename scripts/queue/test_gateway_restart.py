#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""discord_gateway の二段自己回復を、Discord/Task Schedulerへ触れずに実行する。

1) client.run が例外終了・正常帰還しても同一プロセスで再試行する。
2) プロセス自体が消えた時の supervisor 登録周期は1分に固定する。
"""
import os
import sys
import tempfile


try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.normpath(os.path.join(HERE, "..", ".."))
TMP = tempfile.mkdtemp(prefix="gateway_restart_")
os.environ["GO5_LOCAL_DIR"] = os.path.join(TMP, "local")
sys.path.insert(0, HERE)
import discord_gateway as gw  # noqa: E402

PASS = FAIL = 0


def check(name, cond, extra=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print("PASS", name)
    else:
        FAIL += 1
        print("FAIL", name, extra)


class SequenceRun:
    def __init__(self, values):
        self.values = list(values)
        self.calls = 0

    def __call__(self):
        value = self.values[self.calls]
        self.calls += 1
        if isinstance(value, BaseException):
            raise value
        return value


def clock(values):
    it = iter(values)
    return lambda: next(it)


# 例外→正常帰還のどちらも再試行し、認証エラーだけは停止する。
run = SequenceRun([RuntimeError("socket died"), 0, 3])
sleeps = []
rc = gw.serve_gateway_forever(run_once=run, sleep_fn=sleeps.append,
                              monotonic_fn=clock([0, 1, 10, 11, 20, 21]))
check("例外終了と正常帰還を同一プロセスで再試行", run.calls == 3, str(run.calls))
check("短時間失敗は2秒→4秒の上限付きbackoff", sleeps == [2, 4], str(sleeps))
check("認証エラーは無限再試行せずrc=3", rc == 3, str(rc))

# 60秒以上生きた接続の後はbackoffを最小へ戻す。
run = SequenceRun([0, 0, 0, 2])
sleeps = []
rc = gw.serve_gateway_forever(
    run_once=run, sleep_fn=sleeps.append,
    monotonic_fn=clock([0, 1, 10, 80, 90, 91, 100, 101]))
check("安定稼働後は再接続待ちを最小へ戻す", sleeps == [2, 4, 2], str(sleeps))
check("Intent不備は無限再試行せずrc=2", rc == 2, str(rc))

# 明示停止は復活させない。
run = SequenceRun([KeyboardInterrupt()])
sleeps = []
rc = gw.serve_gateway_forever(run_once=run, sleep_fn=sleeps.append,
                              monotonic_fn=clock([0]))
check("明示停止は再接続しない", rc == 130 and sleeps == [], f"rc={rc} sleeps={sleeps}")

# 最終保険の登録値。実タスクは触らず、再登録時の契約だけを固定する。
reg = os.path.join(ROOT, "scripts", "_daemons", "register_daemons_logon_task.ps1")
src = open(reg, encoding="utf-8").read()
check("外部supervisorの登録周期は1分",
      "-RepetitionInterval (New-TimeSpan -Minutes 1)" in src and
      "-RepetitionInterval (New-TimeSpan -Minutes 10)" not in src)

print(f"\n{PASS} PASS / {FAIL} FAIL")
sys.exit(1 if FAIL else 0)
