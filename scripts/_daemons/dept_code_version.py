#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""keeper配下の**部門常駐32体**が、今どの版のコードで走っているかを測る道具。

なぜ要るか(2026-08-23 06:13 プラットフォームSE msg DISPATCH-aegis-gl-1787433194319)=
  一ノ瀬怜「今この部屋(platform-se)の精霊が走っているコードを私は**測れていない**
  (mtimeは状態の代理にするな=C-041)」。その通りだった。
  supervise_daemons.ps1 が見ている常駐7本には `local/_daemon_codever/<name>.txt` の控えが
  在るのに、**keeper配下の部門常駐には控えが無かった**= 版を知りたい者は毎回その場の
  ワンライナー(プロセスの起動時刻を目で見る)を書くしかなく、それは共通規律§1が名指しで
  禁じている数え方だ。しかも起動時刻は代理でしかない(未コミットの編集が見えない)。
  → keeper が起動の瞬間に控えるようにした(`daemon_keeper._record_codever`)。ここはその読み手。

測り方=
  ① 今の版 = `daemon_code_version.code_hash(dept_daemon.py)`(閉包の中身のsha1)。★正本はあちら。
  ② 走っているプロセスの pid と起動時刻を数える。
  ③ 控え `local/_daemon_codever/dept_<dept>.txt` の pid が②と一致したら、
     控えのsha1と①を比べる= **プロセスが実際に読んだコードとの比較**(硬い)。
  ④ 控えが無い/pidが違う(この機構より前から走っている)時だけ、
     `git_commit_epoch` と `dirty_mtime` を起動時刻と比べる= **1回だけの物差し**。
     載せ替われば控えが出来て以後は③へ移る(=不明な相手は数パスで消える)。

使い方=
  python scripts/_daemons/dept_code_version.py            # 全部門(旧だけ見たいなら --old)
  python scripts/_daemons/dept_code_version.py --dept platform-se
検査= python scripts/_daemons/test_dept_code_version.py
"""
import argparse
import os
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
sys.path.insert(0, HERE)
import daemon_code_version as dcv        # noqa: E402  ★版の定義はこちらが正本
import daemon_keeper as dk               # noqa: E402  ★部門の名簿と控えの場所はあちらが正本

DAEMON = dk.DAEMON

# 判定の言葉。★「不明」を「現行」へ丸めない(C-041=一度の観測を状態の代理にするな)。
CUR, OLD, GUESS_CUR, GUESS_OLD, DEAD, UNKNOWN = (
    "現行", "★旧", "現行(推定)", "★旧(推定)", "居ない", "不明")


def read_record(dept, codever_dir=None):
    """控えを (sha1, 起動epoch, pid) で返す。無い/壊れていれば (None, 0.0, 0)。★純粋関数。"""
    path = os.path.join(codever_dir or dk.CODEVER_DIR, f"dept_{dept}.txt")
    try:
        with open(path, encoding="utf-8") as f:
            parts = f.read().strip().split("\t")
    except OSError:
        return None, 0.0, 0
    if len(parts) < 3 or not parts[0]:
        return None, 0.0, 0
    try:
        return parts[0], float(parts[1]), int(parts[2])
    except ValueError:
        return None, 0.0, 0


def verdict(cur_hash, rec, alive, changed_at):
    """1部門ぶんの判定。★純粋関数(ここに副作用を持たせない=検査で全枝を通すため)。

    cur_hash    今の版のsha1
    rec         (sha1, 起動epoch, pid) = read_record の戻り
    alive       (pid, 起動epoch) 走っているプロセス。居なければ None
    changed_at  閉包が最後に**中身として**変わった時刻(commit または未コミット編集の新しい方)
    """
    if not alive:
        return DEAD
    pid, started = alive
    rec_hash, _rec_started, rec_pid = rec
    if rec_hash and rec_pid == pid:
        return CUR if rec_hash == cur_hash else OLD
    # ★控えが無い相手= この機構より前から走っている。1回だけ時刻で測る。
    if not changed_at or not started:
        return UNKNOWN
    return GUESS_OLD if changed_at > started else GUESS_CUR


def alive_dept_procs():
    """{dept: (pid, 起動epoch)}。測れなければ None。

    ★`daemon_keeper._alive_dept_pids` は起動時刻を返さない(pidと部門だけ)。
      ここは**起動時刻が要る**ので自前で1回引く。★重ねているのは「数え方」であって
      「判定」ではない(判定は上の verdict / 版の定義は daemon_code_version 一本)。
    """
    if os.name != "nt":
        return None
    ps = ("Get-CimInstance Win32_Process -Filter \"Name='python.exe'\" | "
          "Where-Object { $_.CommandLine -match 'dept_daemon' } | ForEach-Object { "
          "$e = [int64](($_.CreationDate.ToUniversalTime() - [datetime]'1970-01-01')"
          ".TotalSeconds); \"$($_.ProcessId)`t$e`t$($_.CommandLine)\" }")
    try:
        out = subprocess.run(["powershell", "-NoProfile", "-Command", ps],
                             capture_output=True, text=True, timeout=60)
    except Exception:                                   # noqa: BLE001
        return None
    found = {}
    for ln in (out.stdout or "").splitlines():
        parts = ln.split("\t", 2)
        if len(parts) < 3 or not parts[0].strip().isdigit():
            continue
        m = re.search(r"--dept\s+([A-Za-z0-9_\-]+)", parts[2])
        if not m:
            continue
        try:
            found[m.group(1)] = (int(parts[0]), float(parts[1]))
        except ValueError:
            continue
    return found


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dept", help="1部門だけ見る")
    ap.add_argument("--old", action="store_true", help="現行でない部門だけ出す")
    a = ap.parse_args()
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:                                   # noqa: BLE001
        pass

    cur = dcv.code_hash(DAEMON)
    changed_at = max(dcv.git_commit_epoch(DAEMON), dcv.dirty_mtime(DAEMON))
    procs = alive_dept_procs()
    if procs is None:
        print("測れない(プロセスを数えられなかった)")
        return 2
    depts = [a.dept] if a.dept else dk.DEPTS
    rows, n_old = [], 0
    for d in depts:
        v = verdict(cur, read_record(d), procs.get(d), changed_at)
        if v not in (CUR, GUESS_CUR):
            n_old += 1
        if a.old and v in (CUR, GUESS_CUR):
            continue
        pid = procs.get(d, (0, 0))[0]
        rows.append(f"{d}\t{v}\tpid={pid or '-'}\t控え={read_record(d)[0] or '-'}")
    print(f"今の版= {cur}\t部門={len(depts)}\t現行でない={n_old}")
    print("\n".join(rows))
    return 0


if __name__ == "__main__":
    sys.exit(main())
