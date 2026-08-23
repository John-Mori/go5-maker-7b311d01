# -*- coding: utf-8 -*-
"""朝のデザイン振り返り(毎朝8時JST)の発火配線の検査(2026-08-24 イージス研究室)。

守ること:
  ① 窓は **前日8:00〜当日8:00 JST**(定時起動)。8:00前に走っても未来を先取りしない
  ② 便は **フロント室宛**で、手順を写さず **§100(正本)を指す**・窓を明示する
  ③ 同じ窓で **二度起こさない**(定時起動と手動の予行が重なっても便は1本)
  ④ ★**脈は毎回書く**= 起こした日も、起こさなかった日も、投函に失敗した日も
     (「起こさなかった」と「起動器が死んだ」を区別できないと静かな死が見えない)
  ⑤ 投函に失敗したら状態を進めない(=次の起動で必ず再挑戦になる)

★作り方(§3): 外へ出る手(dispatch のsubprocess)だけ偽物にし、判定と分岐は本物のまま実行で通す。
★must-fail(C-053)= 壊した側は**動く別の実装**へ差し替える。

実行= python tests/test_frontend_design_review.py
"""
import datetime as dt
import io
import os
import shutil
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "scripts", "_daemons"))

import run_frontend_design_review as fr  # noqa: E402

RESULTS = []


def check(name, cond, detail=""):
    RESULTS.append((name, bool(cond), detail))
    print(("  PASS  " if cond else "  FAIL  ") + name + (("  << " + detail) if not cond and detail else ""))


def mustfail(name, fn, expect):
    got = fn()
    check("must-fail " + name, got == expect, f"got={got!r} want={expect!r}")


# ================================================================ ① 窓

print("\n--- ① 窓は前日8:00〜当日8:00(JST) ---")
_s, _e = fr.window_jst(dt.datetime(2026, 8, 25, 8, 0))
check("8:00ちょうどの起動= 前日8:00〜当日8:00",
      (_s, _e) == (dt.datetime(2026, 8, 24, 8, 0), dt.datetime(2026, 8, 25, 8, 0)), f"{_s}〜{_e}")
_s, _e = fr.window_jst(dt.datetime(2026, 8, 25, 8, 3, 12))
check("8:03の遅れ起動でも窓は同じ(境界は時刻で決まる)",
      (_s, _e) == (dt.datetime(2026, 8, 24, 8, 0), dt.datetime(2026, 8, 25, 8, 0)), f"{_s}〜{_e}")
_s, _e = fr.window_jst(dt.datetime(2026, 8, 25, 1, 30))
check("8:00前に走ったら未来を先取りしない(前々日8:00〜前日8:00)",
      (_s, _e) == (dt.datetime(2026, 8, 23, 8, 0), dt.datetime(2026, 8, 24, 8, 0)), f"{_s}〜{_e}")
check("窓は必ず24時間", (_e - _s) == dt.timedelta(days=1))
check("窓の鍵は終わりだけで決まる",
      fr.window_key(fr.window_jst(dt.datetime(2026, 8, 25, 8, 0))[1])
      == fr.window_key(fr.window_jst(dt.datetime(2026, 8, 25, 23, 59))[1]) == "2026-08-25T08")


# ================================================================ ② 便の中身

print("\n--- ② 便は §100 を指す(手順を写さない) ---")
_body = fr.build_body(dt.datetime(2026, 8, 24, 8, 0), dt.datetime(2026, 8, 25, 8, 0))
check("正本(§100)を指している", "design-preferences.md" in _body and "§100" in _body)
check("窓を明示している", "2026-08-24 08:00 〜 2026-08-25 08:00" in _body)
check("0件でも1行残せと書いてある", "今日はデザイン改修なし" in _body)
check("★手順の全文を抱えていない(短い)", len(_body) < 900, str(len(_body)))
check("宛先はフロント室", fr.DEPT == "frontend")


# ================================================================ ③〜⑤ 本物の main() を通す

print("\n--- ③〜⑤ 起こす/起こさない/失敗(本物の main・外へ出る手だけ偽物) ---")


def run_main(argv, fail=False, impl=None):
    """使い捨ての場所で main() を通す。戻り=(exit, 出した便の数, 脈の中身)"""
    tmp = tempfile.mkdtemp(prefix="fdr_")
    keep = (fr.LOG, fr.BODY, fr.PULSE, fr.STATE, fr.dispatch_letter)
    sent = []
    try:
        fr.LOG = os.path.join(tmp, "run.log")
        fr.BODY = os.path.join(tmp, "body.txt")
        fr.PULSE = os.path.join(tmp, "pulse.md")
        fr.STATE = os.path.join(tmp, "state.json")
        fr.dispatch_letter = impl or (lambda b: (sent.append(b), (1 if fail else 0), "")[1:])
        code = fr.main(argv)
        pulse = io.open(fr.PULSE, encoding="utf-8").read() if os.path.exists(fr.PULSE) else ""
        state = io.open(fr.STATE, encoding="utf-8").read() if os.path.exists(fr.STATE) else ""
        return code, len(sent), pulse, state
    finally:
        fr.LOG, fr.BODY, fr.PULSE, fr.STATE, fr.dispatch_letter = keep
        shutil.rmtree(tmp, ignore_errors=True)


def run_twice(argv2=None, force=False):
    """同じ場所で2回続けて走らせる(=定時起動と予行が重なった時)。戻り=出した便の数"""
    tmp = tempfile.mkdtemp(prefix="fdr2_")
    keep = (fr.LOG, fr.BODY, fr.PULSE, fr.STATE, fr.dispatch_letter)
    sent = []
    try:
        fr.LOG, fr.BODY = os.path.join(tmp, "run.log"), os.path.join(tmp, "body.txt")
        fr.PULSE, fr.STATE = os.path.join(tmp, "pulse.md"), os.path.join(tmp, "state.json")
        fr.dispatch_letter = lambda b: (sent.append(b), 0, "")[1:]
        base = ["--as-of", "2026-08-25T08:00"]
        fr.main(base)
        fr.main(base + (["--force"] if force else []))
        pulse = io.open(fr.PULSE, encoding="utf-8").read()
        return len(sent), pulse
    finally:
        fr.LOG, fr.BODY, fr.PULSE, fr.STATE, fr.dispatch_letter = keep
        shutil.rmtree(tmp, ignore_errors=True)


_code, _n, _pulse, _state = run_main(["--as-of", "2026-08-25T08:00"])
check("定時起動で1本起こす", (_code, _n) == (0, 1), f"{_code},{_n}")
check("起こしたら脈に残る", "起こした" in _pulse and "2026-08-25T08" in _pulse, _pulse)
check("起こしたら状態が進む", "2026-08-25T08" in _state, _state)

_n2, _pulse2 = run_twice()
check("★同じ窓で二度起こさない", _n2 == 1, str(_n2))
check("★起こさなかった日も脈は書かれる", "起こし済み" in _pulse2, _pulse2)

_n3, _ = run_twice(force=True)
check("--force なら起こし済みでも起こす", _n3 == 2, str(_n3))

_code4, _n4, _pulse4, _state4 = run_main(["--as-of", "2026-08-25T08:00"], fail=True)
check("投函に失敗したら 0 を返さない", _code4 != 0, str(_code4))
check("★失敗した日も脈は書かれる(失敗と分かる形で)", "投函に失敗" in _pulse4, _pulse4)
check("★失敗したら状態を進めない(次の起動で再挑戦になる)", _state4 == "", _state4)

_code5, _n5, _pulse5, _state5 = run_main(["--as-of", "2026-08-25T08:00", "--dry-run"])
check("--dry-run は投函しない", (_code5, _n5) == (0, 0), f"{_code5},{_n5}")
check("--dry-run でも脈は書かれる", "dry-run" in _pulse5, _pulse5)
check("--dry-run は状態を進めない", _state5 == "", _state5)


# ================================================================ must-fail

def _mf_calendar_day():
    """壊した側= **動く別の実装**「窓は暦の1日(前日0:00〜当日0:00)」。
    8:00の定時起動だと**当日0:00〜8:00の改修を毎日取りこぼす**。"""
    keep = fr.window_jst
    try:
        fr.window_jst = lambda now, hour=8: (
            now.replace(hour=0, minute=0, second=0, microsecond=0) - dt.timedelta(days=1),
            now.replace(hour=0, minute=0, second=0, microsecond=0))
        s, e = fr.window_jst(dt.datetime(2026, 8, 25, 8, 0))
        return (e.hour, e == dt.datetime(2026, 8, 25, 0, 0))
    finally:
        fr.window_jst = keep


def _mf_no_dedupe():
    """壊した側= 冪等を見ない実装(常に起こす)。同じ窓で2本出る=フロント室が二度起きる。"""
    keep = fr.should_wake
    try:
        fr.should_wake = lambda state, key, force=False: True
        n, _ = run_twice()
        return n
    finally:
        fr.should_wake = keep


def _mf_pulse_only_when_sent():
    """壊した側= 脈を「起こした時だけ」書く実装。
    起こさなかった日に脈が止まる= 静かな死と見分けがつかなくなる。"""
    keep = fr.write_pulse
    try:
        fr.write_pulse = lambda line: (None if "起こし済み" in line
                                       else keep(line))
        n, pulse = run_twice()
        return ("起こし済み" in pulse)
    finally:
        fr.write_pulse = keep


print("\n--- must-fail(動く別の実装へ差し替えて赤くなることを実行で確かめる) ---")
mustfail("暦の1日で切ると8:00起動が当日朝の改修を落とす", _mf_calendar_day, (0, True))
mustfail("冪等を見ない実装だと同じ窓で2本出る", _mf_no_dedupe, 2)
mustfail("脈を起こした時だけ書く実装だと、起こさない日に脈が止まる", _mf_pulse_only_when_sent, False)


# ================================================================ 判定

ng = [n for n, ok, _ in RESULTS if not ok]
print("\n===== %d件中 %d件PASS =====" % (len(RESULTS), len(RESULTS) - len(ng)))
if ng:
    print("FAIL — %d件: %s" % (len(ng), ng))
    sys.exit(1)
print("ALL PASS")
