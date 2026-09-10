# -*- coding: utf-8 -*-
"""verify_teian_stopped.py の検査(must-fail 込み)。

★ソースの文字列一致では検査しない(規律§3)。**judge と run の分岐を実行で通す**=
  外へ出る手(dispatch / schtasks /DISABLE)だけ偽物に差し替え、判定と分岐は本物のまま回す。
★must-fail= 「壊した側」は判定表を差し替えた別実装で作る(C-053)= 本物のコードを壊さない。

走らせる= python scripts/_daemons/test_verify_teian_stopped.py
"""
import datetime as dt
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import verify_teian_stopped as V   # noqa: E402

TODAY = dt.date(2026, 9, 11)
YDAY = dt.date(2026, 9, 10)
NOW = dt.datetime(2026, 9, 11, 7, 30, 0)

ok = 0
ng = []


def check(name, cond):
    global ok
    if cond:
        ok += 1
    else:
        ng.append(name)


def fake(state="Disabled", last=YDAY, log=YDAY, pulse=YDAY):
    return lambda: {"task_state": state, "last_run": last, "log_last": log, "pulse_day": pulse}


class Spy(object):
    def __init__(self):
        self.sent = []
        self.disabled = 0

    def send(self, body):
        self.sent.append(body)
        return 0

    def disable(self):
        self.disabled += 1
        return 0


# ---------------------------------------------------------------- judge 単体
check("1 無効+全部きのう → unfired",
      V.judge("Disabled", YDAY, YDAY, YDAY, TODAY)[0] == "unfired")
check("2 タスクの前回実行が今日 → fired",
      V.judge("Disabled", TODAY, YDAY, YDAY, TODAY)[0] == "fired")
check("3 ログ末尾が今日 → fired",
      V.judge("Disabled", YDAY, TODAY, YDAY, TODAY)[0] == "fired")
check("4 脈が今日 → fired",
      V.judge("Disabled", YDAY, YDAY, TODAY, TODAY)[0] == "fired")
check("5 状態がReady(有効に戻された) → enabled",
      V.judge("Ready", YDAY, YDAY, YDAY, TODAY)[0] == "enabled")
check("6 状態がRunning → enabled",
      V.judge("Running", YDAY, YDAY, YDAY, TODAY)[0] == "enabled")
check("7 状態が読めない → unknown(黙らない)",
      V.judge(None, YDAY, YDAY, YDAY, TODAY)[0] == "unknown")
check("8 状態が読めない時は fired より unknown を優先(発火の証拠があっても状態不明)",
      V.judge(None, TODAY, TODAY, TODAY, TODAY)[0] == "unknown")
check("9 前回実行が無い(1度も走っていない) → unfired",
      V.judge("Disabled", None, None, None, TODAY)[0] == "unfired")
check("10 大文字小文字を問わない",
      V.judge("disabled", YDAY, YDAY, YDAY, TODAY)[0] == "unfired")
check("11 理由の1行が空でない",
      all(V.judge(*a)[1].strip() for a in [
          ("Disabled", YDAY, YDAY, YDAY, TODAY), ("Disabled", TODAY, YDAY, YDAY, TODAY),
          ("Ready", YDAY, YDAY, YDAY, TODAY), (None, YDAY, YDAY, YDAY, TODAY)]))

# ---------------------------------------------------------------- run の分岐
s = Spy()
v = V.run(logf=lambda _l: None, collect=fake(), send=s.send, disable_self=s.disable, now=NOW)
check("12 unfired= 1通だけ出す", v == "unfired" and len(s.sent) == 1)
check("13 unfired= 自分を降ろす(毎朝鳴らさない)", s.disabled == 1)
check("14 unfired の本文に「不発火を確認」が入る", "不発火を確認" in s.sent[0])

s = Spy()
v = V.run(logf=lambda _l: None, collect=fake(log=TODAY), send=s.send, disable_self=s.disable, now=NOW)
check("15 fired= 報告する", v == "fired" and len(s.sent) == 1)
check("16 fired= 自分は降りない(次の朝も見る)", s.disabled == 0)
check("17 fired の本文に「再発火」が入る", "再発火" in s.sent[0])

s = Spy()
v = V.run(logf=lambda _l: None, collect=fake(state="Ready"), send=s.send, disable_self=s.disable, now=NOW)
check("18 enabled= 報告して降りない", v == "enabled" and len(s.sent) == 1 and s.disabled == 0)

s = Spy()
v = V.run(logf=lambda _l: None, collect=fake(state=None), send=s.send, disable_self=s.disable, now=NOW)
check("19 unknown= 黙らずに報告し、降りない", v == "unknown" and len(s.sent) == 1 and s.disabled == 0)

s = Spy()
v = V.run(logf=lambda _l: None, collect=fake(), send=s.send, disable_self=s.disable, now=NOW, dry_run=True)
check("20 --dry-run= 送らない・降ろさない", v == "unfired" and not s.sent and s.disabled == 0)

# ---------------------------------------------------------------- 実物の読み取り
st, last = V._schtasks_query(V.TARGET_TASK)
check("21 実タスクの状態を実際に読める(値が返る)", st is not None)
check("22 実タスクは今 Disabled", st == "Disabled")
check("23 存在しないタスク名は (None,None)= 静かに真と誤らない",
      V._schtasks_query("go5_no_such_task_zzz") == (None, None))
lg = V._log_last_day()
check("24 _teian_daily.log の末尾日付を読める", isinstance(lg, dt.date))

# ---------------------------------------------------------------- must-fail
# 「壊した側」= 判定表だけを差し替えた別実装(本物は壊さない・C-053)。
def judge_broken(task_state, last_run, log_last, pulse_day, today):
    """状態しか見ない旧型= ログの再発火を見落とす(この検査が拾えることの証明)"""
    return ("unfired", "state only") if (task_state or "").lower() == "disabled" else ("enabled", "")


check("MF-1 壊した判定(状態だけ見る)は「ログが今日」を見落とす= 本物との差が出る",
      judge_broken("Disabled", YDAY, TODAY, YDAY, TODAY)[0] == "unfired"
      and V.judge("Disabled", YDAY, TODAY, YDAY, TODAY)[0] == "fired")


def judge_silent(task_state, last_run, log_last, pulse_day, today):
    """状態が読めない時に黙る側へ倒す実装= 事故の型(fail-open違反)"""
    if not task_state:
        return "unfired", "読めないので止まっていることにする"
    return V.judge(task_state, last_run, log_last, pulse_day, today)


check("MF-2 黙る側へ倒した実装は unfired を返す= 本物は unknown で鳴る",
      judge_silent(None, YDAY, YDAY, YDAY, TODAY)[0] == "unfired"
      and V.judge(None, YDAY, YDAY, YDAY, TODAY)[0] == "unknown")

# ---------------------------------------------------------------- 結果
print("PASS %d / FAIL %d" % (ok, len(ng)))
for n in ng:
    print("  FAIL:", n)
sys.exit(0 if not ng else 1)
