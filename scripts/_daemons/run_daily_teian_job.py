# -*- coding: utf-8 -*-
"""毎朝7:00(JST)の起動器= 提案候補の日次チェーン(scripts/teian/run_daily_teian.py)を回す。

なぜ在るか(2026-09-02・イージス研究室 / 発注= 改修部門α(オタコン) msg DISPATCH-aegis-gl-1788297884562):
  提案決定ページの「3択が出ない」の真因= 配信データ teian/latest.json が 2026-08-24 のまま
  **8日間止まっていた**。ページ側は正常で、日次チェーンを回すスケジューラが家PCに1本も
  無かった(schtasks で該当なしを実測)。**手で回さなければ何日でも静かに腐る**=C-038の対象。

★この起動器がチェーン本体を抱えないこと:
  中身(退避→再生成→引継ぎ→vision→配信)は run_daily_teian.py = 改修部門αの持ち場。
  ここは**発火と、死んだ時に気づける形**だけを持つ。直す場所を2か所にしない。

★設計の芯= 「腐ったのに誰も気づかない」を二度作らないこと。
  ①**脈は毎回書く**(成功しても失敗しても)。PULSE を producers.json へ登録してあるので、
    起動器ごと死んだ日は absence_watchdog が age で拾う(C-042の対)。
    脈が無い日 = 「今日は何も無かった」ではなく「起動器が死んだ」と読める形にするのが目的。
  ②**失敗を黙って飲まない**。チェーンが非0で落ちたら改修部門αへ便を1本出す。
  ③★ただし**毎日鳴らさない**。同じ壊れ方が続く間ずっと鳴らす網は読まれなくなる
    (規律§3「常に誤発火する安全網は無視される」)。**壊れた初日**と、その後は
    **3日おき**にだけ出す。直った日は必ず1回「戻った」を出す(C-046の閉じ方A)。
  ④publish の空配信ガードで止まるのは**異常ではなく設計どおりの停止**でもある
    (新しい cid の room_comments は自動生成器が無い= 軍議の手当てが要る合図)。
    だから便では「落ちた」と断定せず、**exit と出力の末尾をそのまま**渡して読ませる。
    ★--publish-force は使わない(通常運用で禁止= 依頼本文に明記)。

登録= scripts/_daemons/register_teian_daily_task.ps1(タスク名 go5_teian_daily_0700)
手で試す= python scripts/_daemons/run_daily_teian_job.py --dry-run
本物を1回= python scripts/_daemons/run_daily_teian_job.py
"""
import argparse
import datetime as dt
import io
import json
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
CHAIN = os.path.join(ROOT, "scripts", "teian", "run_daily_teian.py")
DISPATCH = os.path.join(ROOT, "scripts", "llm", "dispatch.py")
LOG = os.path.join(ROOT, "local", "_teian_daily.log")
BODY = os.path.join(ROOT, "local", "_work", "teian_daily_alert_body.txt")
# ★脈(毎回書く)。producers.json の teian_daily が age で見張る。
PULSE = os.path.join(ROOT, "local", "_work", "teian_daily_pulse.md")
STATE = os.path.join(ROOT, "local", "_work", "teian_daily_state.json")

DEPT = "system-engineer"          # チェーン本体(scripts/teian/)の持ち主= 改修部門α
QUIET_DAYS = 3                    # 同じ壊れ方が続く間、便を出す間隔(日)
TIMEOUT_SEC = 3600                # vision が全候補を舐めるので1時間見る


# ---------------------------------------------------------------- 純粋関数

def should_alert(state, ok, today, quiet_days=QUIET_DAYS):
    """今日、改修部門αへ便を出すべきか。★純粋関数(状態は dict をそのまま受ける)。

    出す= ①失敗した初日(前回は成功していた) ②失敗が続いていて前便から quiet_days 日以上
          ③**直った日**(前回が失敗・今回が成功)= 閉じる便を必ず1回出す(C-046の閉じ方A)。
    出さない= 成功が続いている日(静かなのが正常)/ 失敗2〜3日目(既に知らせてある)。
    """
    st = state or {}
    was_ok = bool(st.get("last_ok", True))
    if ok:
        return not was_ok            # 直った日だけ知らせる
    if was_ok:
        return True                  # 壊れた初日
    last = str(st.get("last_alert_date") or "")
    if not last:
        return True
    try:
        d0 = dt.datetime.strptime(last, "%Y-%m-%d").date()
        d1 = dt.datetime.strptime(today, "%Y-%m-%d").date()
    except Exception:
        return True                  # 日付が読めない= 黙らせる理由にしない(fail-open)
    return (d1 - d0).days >= quiet_days


def build_body(ok, code, tail, today, streak):
    """改修部門αへの便。★推測を書かない= exit と出力の末尾をそのまま渡す。"""
    if ok:
        return (
            "自動(毎朝7時の提案日次チェーン)→ 改修部門α\n\n"
            "■ **戻った**。%s のランが成功した(exit=0)。\n"
            "  直前まで %s 日続けて落ちていた分は、これで閉じる。\n\n"
            "■ 出力の末尾:\n```\n%s\n```\n" % (today, streak, tail)
        )
    return (
        "自動(毎朝7時の提案日次チェーン)→ 改修部門α\n\n"
        "■ **run_daily_teian.py が非0で終わった**(exit=%s / %s・連続%s日目)。\n"
        "  配信まで届いていない可能性がある= 提案決定ページの3択が古いまま出る。\n"
        "  ★ただし publish の**空配信ガードで止まった**なら、これは設計どおりの停止だ\n"
        "  (新しい cid の room_comments に自動生成器が無い= 軍議の手当て待ち)。\n"
        "  どちらかは下の出力で判る。こちらでは断定しない。\n\n"
        "■ 出力の末尾:\n```\n%s\n```\n\n"
        "■ 手で回すなら: `python scripts/teian/run_daily_teian.py`\n"
        "  ★通常運用で `--publish-force` は使うな(空配信ガードC-038を潰す)。\n"
        "■ 全文ログ: local/_teian_daily.log\n"
        "■ 次の自動便: 直るまで %s 日おき(毎日は鳴らさない)。直った日に1回「戻った」を出す。\n"
        % (code, today, streak, tail, QUIET_DAYS)
    )


# ---------------------------------------------------------------- 外へ出る手

def log(msg):
    line = "%s %s" % (dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S"), msg)
    print(line, flush=True)
    os.makedirs(os.path.dirname(LOG), exist_ok=True)
    with io.open(LOG, "a", encoding="utf-8") as f:
        f.write(line + "\n")


def write_pulse(state_line):
    """★毎回書く脈。成功した日も落ちた日も、ここが更新されるのが「生きている」印。
    更新が止まる= 起動器ごと死んだ= 2026-08-24〜09-01 と同じ形。そこを見張るための1枚。"""
    os.makedirs(os.path.dirname(PULSE), exist_ok=True)
    with io.open(PULSE, "w", encoding="utf-8") as f:
        f.write("# 提案の日次チェーン 起動器の脈(毎回上書き)\n\n"
                "最終走行: %s\n%s\n"
                % (dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S"), state_line))


def load_state():
    try:
        with io.open(STATE, encoding="utf-8-sig") as f:
            return json.load(f)
    except Exception:
        return {}


def save_state(state):
    os.makedirs(os.path.dirname(STATE), exist_ok=True)
    with io.open(STATE, "w", encoding="utf-8") as f:
        f.write(json.dumps(state, ensure_ascii=False, indent=1))


def run_chain(extra_args=()):
    """チェーン本体を1回回す。戻り=(exit code, 出力)。★テストはここだけ偽物へ差し替える。"""
    env = dict(os.environ)
    env["PYTHONIOENCODING"] = "utf-8"       # ★タスク実行時のcp932化けを作らない
    try:
        r = subprocess.run([sys.executable, CHAIN] + list(extra_args),
                           cwd=ROOT, capture_output=True, text=True,
                           encoding="utf-8", errors="replace", env=env,
                           timeout=TIMEOUT_SEC)
        return r.returncode, ((r.stdout or "") + (r.stderr or "")).strip()
    except subprocess.TimeoutExpired:
        return 124, "★%s秒で打ち切った(TimeoutExpired)" % TIMEOUT_SEC


def dispatch_letter(body):
    os.makedirs(os.path.dirname(BODY), exist_ok=True)
    with io.open(BODY, "w", encoding="utf-8") as f:      # ★BOM無し(dispatchはutf-8で読む)
        f.write(body)
    env = dict(os.environ)
    env["PYTHONIOENCODING"] = "utf-8"
    r = subprocess.run([sys.executable, DISPATCH, "--dept", DEPT, "--direct",
                        "--from-dept", "aegis-gl", "--audience", "ai",
                        "--from", "自動(毎朝7時の提案日次チェーン)",
                        "--body-file", BODY],
                       cwd=ROOT, capture_output=True, text=True,
                       encoding="utf-8", errors="replace", env=env)
    return r.returncode, (r.stdout or r.stderr or "").strip()


def main(argv=None):
    ap = argparse.ArgumentParser(description="提案候補の日次チェーンを回す(発火と死の検知だけを持つ)")
    ap.add_argument("--dry-run", action="store_true",
                    help="チェーンへ --dry-run を渡す(配信しない)。便も出さない")
    a = ap.parse_args(argv)

    today = dt.datetime.now().strftime("%Y-%m-%d")
    code, out = run_chain(["--dry-run"] if a.dry_run else ())
    ok = (code == 0)
    tail = "\n".join((out or "(出力なし)").splitlines()[-25:])

    if a.dry_run:
        write_pulse("状態: --dry-run(配信していない) / exit=%s" % code)
        log("--dry-run exit=%s" % code)
        print(out)
        return code

    state = load_state()
    streak = 1 if ok else int(state.get("fail_streak") or 0) + 1
    alert = should_alert(state, ok, today)

    state["last_run_at"] = dt.datetime.now().strftime("%Y-%m-%dT%H:%M:%S")
    state["last_ok"] = ok
    state["fail_streak"] = 0 if ok else streak
    if alert:
        acode, aout = dispatch_letter(build_body(
            ok, code, tail, today, int(state.get("fail_streak") or streak)))
        # ★便が出せなかった時に日付を進めない= 次の起動で必ず出し直しになる(沈黙にしない)
        if acode == 0:
            state["last_alert_date"] = today
        log("改修部門αへ便 exit=%s / %s" % (acode, aout[:200]))
    save_state(state)

    write_pulse("状態: %s / exit=%s%s"
                % ("成功" if ok else "★失敗(連続%s日目)" % streak, code,
                   " / 改修部門αへ便を出した" if alert else ""))
    log("チェーン exit=%s ok=%s 便=%s" % (code, ok, "出した" if alert else "出さない"))
    return 0 if ok else code


if __name__ == "__main__":
    sys.exit(main())
