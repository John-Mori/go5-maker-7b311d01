# -*- coding: utf-8 -*-
"""keeper 自身を**便を落とさずに**載せ替える(2026-08-08 イージス研究室)。

なぜ要るか=
  keeper は WATCH_FILES を見て子(dept_daemon)を載せ替えるが、**自分自身は監視していない**。
  だから daemon_keeper.py を直しても、keeper を1回落とすまで永久に古い版で走る。
  一方で keeper の起動時 `reap_orphans()` は**走っている dept_daemon を全部kill**する
  (前世代の残骸を必ず掃除するため=二重応答の穴を塞ぐ設計)。
  → **暇な瞬間に落として、暇なうちに立て直す**以外に安全な載せ替え方が無い。

やること(全部ガード付き)=
  1 `_inflight_depts()` が空(=どの部門も便を握っていない)になるまで待つ。
    ★判定不能(None)は「暇」とみなさない=絶対に待つ側へ倒す(fail-closed)。
  2 その瞬間に keeper を落とし、**すぐ**同じ形(隠しウィンドウ)で立て直す。
    supervise_daemons.ps1 の復活は最大10分後で、その間に窓が閉じるので当てにしない。
  3 新しい keeper が別pidで立ち、dept_daemon が再び全部立ったことを**数えて**確かめる。

★副作用(意図している)= 新しい keeper は孤児を掃除して全部門を立て直すので、
  **その時点の dept_daemon.py が全30体に載る**。今日の版を配る手段でもある。
★最悪でも便は消えない= LeaseQueue は ack されなければ lease 満了で再配達する
  (deliveries が1増えるだけ)。それでも「握っている最中に落とさない」を1で守る。

使い方=
  python scripts/_daemons/reload_keeper.py --detach [--wait-min 120] [--dry-run]

★★**自室のセッションから前景で走らせるな。永久に待つ**(2026-08-13 実測・2回続けて失敗)。
  1 の「暇な窓」は**全部門が便を握っていない瞬間**だ。ところが自室(便を処理している部屋)は
  **自分のターンが終わるまで inflight のまま**=待っている側が待たれている側でもある。
  さらにハーネスの背景タスクは**ターンが終わると一緒に落ちる**ので、暇になった瞬間には
  もう誰も待っていない。実測= 08:20 と 08:58 の2回とも `待機中(処理中=aegis-gl)` で止まった。
  → **`--detach` を付けろ。**自分を隠しプロセスとして産み直して即座に戻るので、
    ターンが終わって自室が便を離した瞬間に、生き残った子が窓を掴む。
"""
import argparse
import importlib.util
import json
import os
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
SPEC = importlib.util.spec_from_file_location(
    "daemon_keeper_for_reload", os.path.join(HERE, "daemon_keeper.py"))
keeper = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(keeper)

KEEPER_REL = r"scripts\_daemons\daemon_keeper.py"
KEEPER_LOG = r"local\_daemon_keeper.log"
SELF_REL = r"scripts\_daemons\reload_keeper.py"
SELF_LOG = r"local\_reload_keeper.log"


def say(msg):
    print("%s reload_keeper: %s" % (time.strftime("%H:%M:%S"), msg), flush=True)


def _ps(cmd):
    return subprocess.run(["powershell", "-NoProfile", "-Command", cmd],
                          capture_output=True, text=True,
                          encoding="utf-8", errors="replace").stdout or ""


def procs(needle):
    """コマンドラインに needle を含む python.exe の pid 一覧。"""
    out = _ps("Get-CimInstance Win32_Process -Filter \"Name='python.exe'\" | "
              "Where-Object { $_.CommandLine -match '%s' } | "
              "ForEach-Object { $_.ProcessId }" % needle)
    return [int(p) for p in out.split() if p.strip().isdigit()]


def start_keeper():
    """supervise_daemons.ps1 と**同じ形**で隠し起動する(起動経路を2本持たない)。"""
    cmd = ('cmd /c cd /d "%s" && python "%s" >> "%s" 2>&1'
           % (ROOT, KEEPER_REL, os.path.join(ROOT, KEEPER_LOG)))
    _ps("$sh = New-Object -ComObject WScript.Shell; "
        "$sh.Run('%s', 0, $false)" % cmd.replace("'", "''"))


def detach(argv):
    """自分自身を隠しプロセスとして産み直す(呼び出し側のターンが終わっても生き残る)。

    ★keeper の start_keeper() と**同じ形**で起動する(起動経路を2本持たない)。
    """
    args = " ".join('"%s"' % x if " " in x else x for x in argv)
    cmd = ('cmd /c cd /d "%s" && python "%s" %s >> "%s" 2>&1'
           % (ROOT, SELF_REL, args, os.path.join(ROOT, SELF_LOG)))
    _ps("$sh = New-Object -ComObject WScript.Shell; "
        "$sh.Run('%s', 0, $false)" % cmd.replace("'", "''"))


def main():
    ap = argparse.ArgumentParser(description="keeperを暇な瞬間に載せ替える")
    ap.add_argument("--detach", action="store_true",
                    help="★自分を隠しプロセスへ産み直して即座に戻る"
                         "(自室のセッションから呼ぶ時は必須=docstring参照)")
    ap.add_argument("--wait-min", type=float, default=120.0,
                    help="暇な窓をこの分数だけ待つ(既定120分)")
    ap.add_argument("--poll-sec", type=float, default=5.0)
    ap.add_argument("--dry-run", action="store_true",
                    help="窓を待って、落とす直前で止める(何もkillしない)")
    a = ap.parse_args()

    if a.detach:
        rest = [x for x in sys.argv[1:] if x != "--detach"]
        detach(rest)
        say("隠しプロセスへ産み直した。経過は %s を見ろ(このターンが終わってから窓を掴む)"
            % SELF_LOG)
        return 0

    before = procs("daemon_keeper")
    say("いまのkeeper pid=%s / dept_daemon=%d体" % (before, len(procs("dept_daemon"))))
    if not before:
        say("keeperが走っていない。supervise_daemons.ps1 の担当なので、ここでは触らない。")
        return 1

    deadline = time.time() + a.wait_min * 60
    last_log = 0.0
    while True:
        busy = keeper._inflight_depts()
        if busy == []:
            break
        if time.time() > deadline:
            say("★%.0f分待ったが暇な窓が来なかった。何もせず終わる(処理中=%s)"
                % (a.wait_min, "判定不能" if busy is None else ",".join(busy[:6])))
            return 2
        if time.time() - last_log > 300:
            last_log = time.time()
            say("待機中(処理中=%s)" % ("判定不能" if busy is None else ",".join(busy[:6])))
        time.sleep(a.poll_sec)

    if a.dry_run:
        say("暇な窓が来た。--dry-run なのでここで止める。")
        return 0

    say("★暇な窓が来た= keeperを載せ替える")
    for pid in before:
        subprocess.run(["taskkill", "/PID", str(pid), "/F"], capture_output=True)
    time.sleep(1.5)
    start_keeper()

    # ---- 立ったことを数えて確かめる(自己申告で終わらせない) ----
    after, kids = [], []
    for _ in range(40):                     # 最大~80秒
        time.sleep(2)
        after = [p for p in procs("daemon_keeper") if p not in before]
        kids = procs("dept_daemon")
        if after and len(kids) >= len(keeper.DEPTS):
            break
    ok = bool(after) and len(kids) >= len(keeper.DEPTS)
    say("%s 新keeper pid=%s / dept_daemon=%d体(期待%d体)"
        % ("成功=" if ok else "★未達=", after, len(kids), len(keeper.DEPTS)))
    print(json.dumps({"ok": ok, "old": before, "new": after,
                      "dept_daemons": len(kids), "expected": len(keeper.DEPTS)},
                     ensure_ascii=False))
    return 0 if ok else 3


if __name__ == "__main__":
    sys.exit(main())
