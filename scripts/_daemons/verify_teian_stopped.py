# -*- coding: utf-8 -*-
"""凍結した提案日次チェーン(go5_teian_daily_0700)が **本当に発火しないこと** を翌朝に1回だけ実測する。

なぜ在るか(2026-09-10・イージス研究室 / 発注= 研究室HQ経由の 5chシステム改修部門α):
  09-10 07:26 に日次チェーンを止めた(schtasks /Change /DISABLE + producers.json の retired)。
  だが**止めた側の申告(State=Disabled)は「登録しただけ」の一種**だ。規律§3=
  「安全網は登録だけで完了にせず、本番と同じ発火条件を1回通して確認する」。
  本番の発火条件は **翌朝07:00** で、こちらから起こせない。だから
  「翌朝もう一度見る」を**人の記憶ではなく機械**に持たせる(§3「心がけに任せない」)。

見るもの(4つ・どれか1つでも今日なら「再発火」)
  ① タスクの状態      : Disabled のままか(誰かが /ENABLE で戻していないか)
  ② タスクの前回実行  : LastRunTime が今日ではないか
  ③ チェーンのログ    : local/_teian_daily.log の末尾行が今日ではないか
  ④ 起動器の脈        : local/_work/teian_daily_pulse.md の mtime が今日ではないか
  ★①②はタスク側、③④は起動器側= **止めた手と別の面から**見る(台帳一致ではなく実物)。

鳴らし方
  - **不発火だった日に1回だけ報告し、自分を /DISABLE する**。毎朝「今日も止まっています」を
    出す網は読まれなくなる(規律§3「常に誤発火する安全網は無視される」)。閉じ方はC-046。
  - **再発火・状態が戻っている・判定不能** の時は報告して**自分は生かしたまま**にする。
    判定不能で黙るのが最悪= 可用性側は fail-open(喋る側へ倒す)。

登録  = scripts/_daemons/register_teian_stopcheck_task.ps1(タスク名 go5_teian_stopcheck_0730)
外す  = schtasks /Change /TN go5_teian_stopcheck_0730 /DISABLE(削除しない)
手で= python scripts/_daemons/verify_teian_stopped.py --dry-run   (送らない・自分も止めない)
検査  = python scripts/_daemons/test_verify_teian_stopped.py
"""
import argparse
import datetime as dt
import io
import os
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
DISPATCH = os.path.join(ROOT, "scripts", "llm", "dispatch.py")
CHAIN_LOG = os.path.join(ROOT, "local", "_teian_daily.log")
PULSE = os.path.join(ROOT, "local", "_work", "teian_daily_pulse.md")
LOG = os.path.join(ROOT, "local", "_teian_stop_verify.log")
BODY = os.path.join(ROOT, "local", "_work", "teian_stopcheck_body.txt")

TARGET_TASK = "go5_teian_daily_0700"     # 凍結した当のタスク
SELF_TASK = "go5_teian_stopcheck_0730"   # この検査自身(不発火を見たら自分を止める)
REPORT_DEPT = "aegis-gl"                 # 止めた当室へ返す(発注元=改修部門αへは当室が人格で返す)


# ---------------------------------------------------------------- 判定(純粋)
def judge(task_state, last_run, log_last, pulse_day, today):
    """今日 07:00 に発火したかを判定する。戻り= (verdict, 理由の1行)

    verdict= unfired / fired / enabled / unknown
    引数はすべて **日付(dt.date) か None**、task_state は文字列か None。
    ★ここに副作用を置かない= 検査は入力を差し替えてこの分岐をそのまま通す。
    """
    if not task_state:
        # 状態が読めない= 止まっている証拠が無い。黙らずに上げる(fail-open)。
        return "unknown", "タスクの状態を読めなかった(schtasks が応答しない)"
    if task_state.lower() != "disabled":
        return "enabled", "タスクが %s へ戻っている(誰かが有効化した)" % task_state
    hits = []
    if last_run == today:
        hits.append("タスクの前回実行が今日(%s)" % last_run)
    if log_last == today:
        hits.append("_teian_daily.log の末尾が今日(%s)" % log_last)
    if pulse_day == today:
        hits.append("teian_daily_pulse.md の更新が今日(%s)" % pulse_day)
    if hits:
        return "fired", "無効のはずが発火した= " + " / ".join(hits)
    return "unfired", "前回実行=%s / ログ末尾=%s / 脈=%s (どれも今日ではない)" % (
        last_run, log_last, pulse_day)


# ---------------------------------------------------------------- 実物を読む
def _schtasks_query(task):
    """(state, last_run_date) を返す。読めなければ (None, None)。"""
    try:
        p = subprocess.run(
            ["schtasks", "/Query", "/TN", task, "/V", "/FO", "LIST"],
            capture_output=True, timeout=60)
    except Exception:                                   # noqa: BLE001
        return None, None
    if p.returncode != 0:
        return None, None
    # ロケールで見出しが日本語/英語のどちらにもなる= 値の形で拾う(見出し文字列に依存しない)
    out = p.stdout.decode("cp932", "replace") + p.stdout.decode("utf-8", "replace")
    state = None
    for word in ("Disabled", "Ready", "Running", "無効", "準備完了", "実行中"):
        if re.search(r"(?m)^(Status|Scheduled Task State|状態|スケジュールされたタスクの状態)\s*:\s*%s" % word, out):
            state = {"無効": "Disabled", "準備完了": "Ready", "実行中": "Running"}.get(word, word)
            break
    m = re.search(r"(?m)^(Last Run Time|前回の実行時刻)\s*:\s*(\d{4})/(\d{1,2})/(\d{1,2})", out)
    last = dt.date(int(m.group(2)), int(m.group(3)), int(m.group(4))) if m else None
    return state, last


def _log_last_day():
    """local/_teian_daily.log の末尾行の日付。無ければ None。"""
    try:
        with io.open(CHAIN_LOG, encoding="utf-8", errors="replace") as f:
            lines = [ln for ln in f.read().splitlines() if ln.strip()]
    except Exception:                                   # noqa: BLE001
        return None
    for ln in reversed(lines):
        m = re.match(r"^(\d{4})-(\d{2})-(\d{2}) ", ln)
        if m:
            return dt.date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
    return None


def _pulse_day():
    try:
        return dt.datetime.fromtimestamp(os.path.getmtime(PULSE)).date()
    except Exception:                                   # noqa: BLE001
        return None


def collect_real():
    state, last = _schtasks_query(TARGET_TASK)
    return {"task_state": state, "last_run": last,
            "log_last": _log_last_day(), "pulse_day": _pulse_day()}


# ---------------------------------------------------------------- 外へ出る手
def send_real(body):
    with io.open(BODY, "w", encoding="utf-8") as f:
        f.write(body)
    cmd = [sys.executable, DISPATCH, "--dept", REPORT_DEPT, "--from", "提案日次チェーン停止の検査",
           "--from-dept", REPORT_DEPT, "--audience", "ai", "--body-file", BODY]
    p = subprocess.run(cmd, cwd=ROOT, capture_output=True, timeout=180)
    return p.returncode


def disable_self_real():
    p = subprocess.run(["schtasks", "/Change", "/TN", SELF_TASK, "/DISABLE"],
                       capture_output=True, timeout=60)
    return p.returncode


def _append_log(line):
    try:
        os.makedirs(os.path.dirname(LOG), exist_ok=True)
        with io.open(LOG, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:                                   # noqa: BLE001
        pass


# ---------------------------------------------------------------- 本体
def run(collect=collect_real, send=send_real, disable_self=disable_self_real,
        now=None, dry_run=False, logf=None):
    now = now or dt.datetime.now()
    got = collect()
    verdict, why = judge(got["task_state"], got["last_run"], got["log_last"],
                         got["pulse_day"], now.date())
    head = {"unfired": "不発火を確認", "fired": "★再発火", "enabled": "★タスクが有効に戻っている",
            "unknown": "判定不能"}[verdict]
    body = ("[提案日次チェーン停止の検査] %s\n%s\n"
            "対象= %s / 検査= scripts/_daemons/verify_teian_stopped.py / 記録= local/_teian_stop_verify.log"
            % (head, why, TARGET_TASK))
    sent = None
    stopped = None
    if not dry_run:
        sent = send(body)
        # ★不発火の日だけ自分を降ろす= 毎朝「今日も止まっています」を出さない(C-046 閉じ方B)。
        #   再発火・有効化・判定不能は**生かしたまま**(次の朝も見る)。
        if verdict == "unfired":
            stopped = disable_self()
    (logf or _append_log)("%s verdict=%s sent=%s self_disabled=%s | %s"
                          % (now.strftime("%Y-%m-%d %H:%M:%S"), verdict, sent, stopped, why))
    print(body)
    return verdict


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true", help="送らない・自分も止めない(判定だけ)")
    a = ap.parse_args()
    v = run(dry_run=a.dry_run)
    return 0 if v == "unfired" else 2


if __name__ == "__main__":
    sys.exit(main())
