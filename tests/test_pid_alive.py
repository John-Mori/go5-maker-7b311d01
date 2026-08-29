# -*- coding: utf-8 -*-
"""プロセス生存判定の受け入れ試験(イージス研究室・2026-08-30)。

★なぜ在るか
  2026-08-30 05:38-06:03、Discord受信(discord_gateway)が25分沈黙した。
  真因は「OpenProcess が成功した = 生きている」という判定。Windowsは終了済みの
  プロセスでも、プロセスオブジェクトへの参照が残る限りハンドルを開ける。
  結果 lock に残った**死んだPID**を生存と誤判定し、起動しようとする側が
  毎回「既に稼働中」と言って自死し続けた。

★何を守るか= 「生存判定は OpenProcess の成否で決めない」を機構で固定する。
  文字列一致ではなく**実際に殺したプロセスを渡して**確かめる(登録済み≠動く・規律§3)。

見る対象(このリポジトリで生存判定を書いている全て。2026-08-30に数え切った)
  1. scripts/queue/discord_gateway.py:_pid_alive   … 研究室HQが d32f95e で修理
  2. scripts/llm/inbox_waiter.py:_pid_alive        … 当室が修理(この便)
  3. scripts/_daemons/daemon_keeper.py:_pid_alive_win … 別方式(列挙済み集合)。
     ★こちらは OpenProcess を使っておらず、判定不能時は「生きている扱い」へ倒す
       fail-open。マーカーを殺さない方向にしか働かないので**設計として正しい**。
       修理対象ではないが、退行しないようここで縛っておく。

回し方
  python tests/test_pid_alive.py
"""
import os
import subprocess
import sys
import time

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "scripts", "llm"))
sys.path.insert(0, os.path.join(ROOT, "scripts", "queue"))
sys.path.insert(0, os.path.join(ROOT, "scripts", "_daemons"))


def make_dead_pid():
    """確実に死んだPIDを1つ作る(gateway の pid=13636 と同じ形= 強制終了)。"""
    p = subprocess.Popen([sys.executable, "-c", "import time;time.sleep(120)"])
    p.terminate()
    p.wait()
    time.sleep(0.5)
    return p.pid


def main():
    dead = make_dead_pid()
    mine = os.getpid()
    ng = 0
    rows = []

    def check(label, got, want):
        nonlocal ng
        ok = (got is want)
        if not ok:
            ng += 1
        rows.append(("OK" if ok else "NG", label, got, want))

    # --- 1/2 OpenProcess 方式の2本 ---
    import inbox_waiter
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "_gw", os.path.join(ROOT, "scripts", "queue", "discord_gateway.py"))
    # ★gateway は import だけで discord.py を要求するので、関数だけ取り出して見る。
    gw_alive = None
    try:
        src = open(spec.origin, encoding="utf-8").read()
        ns = {"os": os, "sys": sys}
        start = src.index("def _pid_alive(pid):")
        end = src.index("\ndef ", start + 10)
        exec(compile(src[start:end], spec.origin, "exec"), ns)
        gw_alive = ns["_pid_alive"]
    except Exception as e:                      # pragma: no cover
        rows.append(("NG", "discord_gateway._pid_alive の取り出し", repr(e), "取り出せる"))
        ng += 1

    targets = [("inbox_waiter._pid_alive", inbox_waiter._pid_alive)]
    if gw_alive:
        targets.append(("discord_gateway._pid_alive", gw_alive))

    for name, fn in targets:
        check("%s(死んだpid=%d)" % (name, dead), fn(dead), False)
        check("%s(自分のpid)" % name, fn(mine), True)
        check("%s(0)" % name, fn(0), False)
        check("%s(-1)" % name, fn(-1), False)
        check("%s(存在しない巨大pid)" % name, fn(999999999), False)

    # --- 3 列挙集合方式(別設計。fail-openを守っているか) ---
    import daemon_keeper as K
    check("daemon_keeper._pid_alive_win(pid, 集合に居る)", K._pid_alive_win(mine, {mine}), True)
    check("daemon_keeper._pid_alive_win(pid, 集合に無い)", K._pid_alive_win(dead, {mine}), False)
    check("daemon_keeper._pid_alive_win(pid, None=列挙不能)", K._pid_alive_win(dead, None), True)

    for st, label, got, want in rows:
        print("  %-3s %-52s 実測=%-6s 期待=%s" % (st, label, got, want))
    print("\n== %d/%d PASS / NG=%d ==(死んだpid=%d)" % (len(rows) - ng, len(rows), ng, dead))
    return 1 if ng else 0


if __name__ == "__main__":
    raise SystemExit(main())
