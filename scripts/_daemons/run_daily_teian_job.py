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
  ④publish の空配信ガードで止まるのは**異常ではなく設計どおりの停止**だ
    (新しい cid の room_comments は自動生成器が無い= 軍議の手当てが要る合図)。
    だから便では「落ちた」と断定せず、**exit と出力の末尾をそのまま**渡して読ませる。
    ★--publish-force は使わない(通常運用で禁止= 依頼本文に明記)。
  ⑤★**止まり方で宛先と間隔を変える**(2026-09-02 追加・C-046)。
    初日(09-02 07:00)の実測でこの穴が出た= 落ち方は空配信ガード(exit=2)だった。
    ところがこの起動器は「チェーンが非0」しか見ておらず、**閉じ条件(exit=0)を
    握っているのは改修部門αではない**(room_comments を埋めるのは軍議)。
    このままだと「当てる先の無い便」を改修部門αへ3日おきに永久に打ち続ける=
    まさに規律§3の「常に誤発火する安全網」を自分で作ることになる。だから:
      - **本当に落ちた**(guard 以外の非0) → 改修部門αへ / 3日おき
      - **空配信ガードで止まった**(exit=2 かつ publish の合図行) → **軍議へ** / 14日おき
        (閉じるのは room_comments が埋まった日= 鍵を持っている部屋へ出す)
      - **止まり方が変わった日は必ず1通**出す(guard→本当の故障 を黙って通さない)

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
GUARD_DEPT = "gunji"              # 空配信ガードの閉じ条件(room_comments)を握る部屋= 軍議
QUIET_DAYS = 3                    # 本当に落ちた時、便を出す間隔(日)
GUARD_QUIET_DAYS = 14             # 設計どおりの停止(空配信ガード)を思い出させる間隔(日)
TIMEOUT_SEC = 3600                # vision が全候補を舐めるので1時間見る

# ★publish が「未充填で止めた」時に必ず出す行(scripts/teian/run_daily_teian.py:189)。
#   ここは改修部門αの持ち場の文字列= 変わったら合致しなくなる。だから**合致しない側は
#   「本当に落ちた」へ倒す**(= 宛先が改修部門αになって鳴り続ける)。黙る側へは倒さない。
GUARD_MARK = "未充填の候補があり配信を止めた"
GUARD_CODE = 2


# ---------------------------------------------------------------- 純粋関数

def classify(code, out):
    """このランの止まり方。"ok" / "guard"(設計どおりの停止) / "fail"(本当に落ちた)。

    ★guard と判定するのは **exit=2 かつ publish の合図行がある** 時だけだ。
      exit だけで決めない= 他の工程がたまたま2で落ちた日を「設計どおり」と読むと、
      本物の故障が14日おきの静かな側へ沈む。
    """
    if code == 0:
        return "ok"
    if code == GUARD_CODE and GUARD_MARK in (out or ""):
        return "guard"
    return "fail"


def should_alert(state, kind, today,
                 quiet_days=QUIET_DAYS, guard_quiet_days=GUARD_QUIET_DAYS):
    """今日、便を出すべきか。★純粋関数(状態は dict をそのまま受ける)。

    出す= ①**止まり方が変わった日**(ok→guard、guard→fail、fail→ok…)= 節目は必ず1通。
          ②同じ止まり方が続いていて、前便から間隔(fail=3日 / guard=14日)以上。
    出さない= 成功が続いている日(静かなのが正常)/ 知らせた直後の同じ止まり方。

    ★間隔を止まり方で変える理由= guard は**閉じ条件を持つ部屋が別**(軍議の room_comments)で、
      埋まるまで何日でも続くのが正常な姿だ。3日おきに鳴らすと「いつもの奴」になって
      本物の故障まで読み飛ばされる(規律§3)。かといって永久に黙ると、止まったまま
      忘れられる= 2026-08-24〜09-01 の再演。だから**間隔を延ばす**で挟む。
    """
    st = state or {}
    was = str(st.get("last_kind") or ("ok" if st.get("last_ok", True) else "fail"))
    if kind != was:
        return True                  # 節目(直った日・壊れた初日・止まり方が変わった日)
    if kind == "ok":
        return False                 # 成功が続く= 静かなのが正常
    last = str(st.get("last_alert_date") or "")
    if not last:
        return True
    try:
        d0 = dt.datetime.strptime(last, "%Y-%m-%d").date()
        d1 = dt.datetime.strptime(today, "%Y-%m-%d").date()
    except Exception:
        return True                  # 日付が読めない= 黙らせる理由にしない(fail-open)
    return (d1 - d0).days >= (guard_quiet_days if kind == "guard" else quiet_days)


def alert_dept(kind):
    """その止まり方を**閉じられる**部屋。★「持ち主」ではなく「鍵を持つ側」へ出す。"""
    return GUARD_DEPT if kind == "guard" else DEPT


def build_body(kind, code, tail, today, streak):
    """便の本文。★推測を書かない= exit と出力の末尾をそのまま渡す。

    ★どの便にも**閉じ条件を1行で書く**(C-046)。閉じ方が書いていない警報は、
      受け取った側が「で、いつ終わるんだこれは」で止まり、二度目から読まれなくなる。
    """
    if kind == "ok":
        return (
            "自動(毎朝7時の提案日次チェーン)→ 改修部門α\n\n"
            "■ **戻った**。%s のランが成功した(exit=0)。\n"
            "  直前まで %s 日続けて止まっていた分は、これで閉じる。\n\n"
            "■ 出力の末尾:\n```\n%s\n```\n" % (today, streak, tail)
        )
    if kind == "guard":
        return (
            "自動(毎朝7時の提案日次チェーン)→ 軍議\n\n"
            "■ **配信が空配信ガードで止まっている**(exit=%s / %s・連続%s日目)。\n"
            "  これは故障ではなく**設計どおりの停止**だ= ④comments または room_comments が\n"
            "  未充填の候補があるので、publish が配信を拒んだ。\n"
            "  ★ただし止まっている間、提案決定ページの3択は**古いまま**出続ける。\n\n"
            "■ 出力の末尾(未充填の一覧はここ):\n```\n%s\n```\n\n"
            "■ **閉じ条件**= 一覧の cid に room_comments が埋まり、次の朝のランが exit=0 に\n"
            "  なること。埋まった翌朝、この線から「戻った」が1通出る(こちらの手はいらない)。\n"
            "■ 手で回すなら: `python scripts/teian/run_daily_teian.py`\n"
            "  ★`--publish-force` は使うな(空配信ガードC-038を潰す=空を配信面へ出す)。\n"
            "■ ★**埋める当てが無いなら、埋めないと返してくれ。**その時はこの見張りの\n"
            "  設計をこちら(イージス研究室)でやり直す= 閉じ条件の無い警報は畳むのが正しい。\n"
            "■ 全文ログ: local/_teian_daily.log\n"
            "■ 次の自動便: 埋まるまで %s 日おき(毎日は鳴らさない)。\n"
            % (code, today, streak, tail, GUARD_QUIET_DAYS)
        )
    return (
        "自動(毎朝7時の提案日次チェーン)→ 改修部門α\n\n"
        "■ **run_daily_teian.py が非0で終わった**(exit=%s / %s・連続%s日目)。\n"
        "  ★空配信ガード(exit=2+合図行)**ではない**落ち方だ= 本当に落ちている。\n"
        "  配信まで届いていない= 提案決定ページの3択が古いまま出る。\n\n"
        "■ 出力の末尾:\n```\n%s\n```\n\n"
        "■ **閉じ条件**= 次の朝のランが exit=0 になること。直った翌朝に1通「戻った」が出る。\n"
        "■ 手で回すなら: `python scripts/teian/run_daily_teian.py`\n"
        "  ★通常運用で `--publish-force` は使うな(空配信ガードC-038を潰す)。\n"
        "■ 全文ログ: local/_teian_daily.log\n"
        "■ 次の自動便: 直るまで %s 日おき(毎日は鳴らさない)。\n"
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


def dispatch_letter(body, dept=DEPT):
    os.makedirs(os.path.dirname(BODY), exist_ok=True)
    with io.open(BODY, "w", encoding="utf-8") as f:      # ★BOM無し(dispatchはutf-8で読む)
        f.write(body)
    env = dict(os.environ)
    env["PYTHONIOENCODING"] = "utf-8"
    r = subprocess.run([sys.executable, DISPATCH, "--dept", dept, "--direct",
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
    kind = classify(code, out)
    ok = (kind == "ok")
    tail = "\n".join((out or "(出力なし)").splitlines()[-25:])

    if a.dry_run:
        write_pulse("状態: --dry-run(配信していない) / exit=%s / 止まり方=%s" % (code, kind))
        log("--dry-run exit=%s kind=%s" % (code, kind))
        print(out)
        return code

    state = load_state()
    streak = 1 if ok else int(state.get("fail_streak") or 0) + 1
    alert = should_alert(state, kind, today)
    dept = alert_dept(kind)

    state["last_run_at"] = dt.datetime.now().strftime("%Y-%m-%dT%H:%M:%S")
    state["last_ok"] = ok
    state["last_kind"] = kind
    state["fail_streak"] = 0 if ok else streak
    if alert:
        acode, aout = dispatch_letter(build_body(
            kind, code, tail, today, int(state.get("fail_streak") or streak)), dept)
        # ★便が出せなかった時に日付を進めない= 次の起動で必ず出し直しになる(沈黙にしない)
        if acode == 0:
            state["last_alert_date"] = today
        log("%s へ便 exit=%s / %s" % (dept, acode, aout[:200]))
    save_state(state)

    label = {"ok": "成功", "guard": "★空配信ガードで停止(連続%s日目)" % streak,
             "fail": "★失敗(連続%s日目)" % streak}[kind]
    write_pulse("状態: %s / exit=%s%s"
                % (label, code, (" / %s へ便を出した" % dept) if alert else ""))
    log("チェーン exit=%s 止まり方=%s 便=%s" % (code, kind, dept if alert else "出さない"))
    return 0 if ok else code


if __name__ == "__main__":
    sys.exit(main())
