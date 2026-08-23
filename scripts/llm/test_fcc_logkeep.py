#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""FCCサーバログの退避と掃除の検査。 2026-08-23(イージス研究室)

実行: python scripts/llm/test_fcc_logkeep.py

★なぜ足したか(研究室HQ msg 1541080512603357318)
  `fcc-server` は `~/.fcc/logs/server.log` を**起動のたびに上書き**する。
  13:29 の実務便のログが 22:35 の起こし直しで1行も残らず消えた=走行の証跡が静かに死ぬ。
  HQが止血(起こす前にコピー)を入れたが、**検査が無い**=次に誰かが `start_server` を
  書き換えたら黙って元へ戻る。恒久=「掃除の方針」と「この検査」の2つ。

★方針(コード側の定数が正本)= 日数 KEEP_DAYS を主に、本数の床 KEEP_MIN と天井 KEEP_MAX。
★must-fail(C-053)= 退避/掃除を**動く別の実装**(=止血が入る前の「何もしない」版)へ戻し、
  検査が赤くなることを確かめる。行を消して文法を壊すのは偽の緑だ。
★外へ出る手(fcc-server の起動)だけ偽物にし、**判定と分岐は本物のまま**回す。
"""
import os
import shutil as _real_shutil
import subprocess as _real_subprocess
import sys
import tempfile
import time

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import fcc_launch as fl   # noqa: E402

results = []
DAY = 86400.0


def check(name, cond):
    results.append((name, bool(cond)))
    print(f"  {'PASS' if cond else 'FAIL'}: {name}")


class _Sandbox(object):
    """`HOME` を差し替えて `<tmp>/.fcc/logs/` を本物と同じ形で作る。"""

    def __enter__(self):
        self.tmp = tempfile.mkdtemp(prefix="fcclog_")
        self.prev_home = fl.HOME
        fl.HOME = self.tmp
        self.logdir = os.path.join(self.tmp, ".fcc", "logs")
        os.makedirs(self.logdir)
        return self

    def __exit__(self, *a):
        fl.HOME = self.prev_home
        _real_shutil.rmtree(self.tmp, ignore_errors=True)
        return False

    def write_log(self, text="2026-08-23 13:29 実務便のログ\n"):
        p = os.path.join(self.logdir, "server.log")
        with open(p, "w", encoding="utf-8") as f:
            f.write(text)
        return p

    def rotations(self):
        return sorted(n for n in os.listdir(self.logdir) if fl._ROT_RE.match(n))

    def put_rotation(self, name, age_days):
        p = os.path.join(self.logdir, name)
        with open(p, "w", encoding="utf-8") as f:
            f.write("old\n")
        t = time.time() - age_days * DAY
        os.utime(p, (t, t))
        return p


# --- ① 方針そのもの(純関数・ファイルに触らない) -----------------------------
now = 1_700_000_000.0
old = [("server.log.20260101_00%04d" % i, now - (30 + i) * DAY) for i in range(30)]
check("① 床= 新しい方から KEEP_MIN 本は、何日経っていても残す",
      len(old) - len(fl._drop_list(old, now)) == fl.KEEP_MIN)
young = [("server.log.20260801_00%04d" % i, now - i * 60.0) for i in range(fl.KEEP_MAX + 7)]
check("① 天井= KEEP_MAX を超えた分は、若くても捨てる",
      len(young) - len(fl._drop_list(young, now)) == fl.KEEP_MAX)
mixed = [("server.log.20260810_000001", now - 1 * DAY),
         ("server.log.20260801_000001", now - (fl.KEEP_DAYS + 1) * DAY)]
check("① 日数= 床の中なら古くても残る(2本しか無い時に全滅しない)",
      fl._drop_list(mixed, now) == [])
many = [("server.log.20260810_%06d" % i, now - 1 * DAY) for i in range(fl.KEEP_MIN)]
many += [("server.log.20260701_%06d" % i, now - (fl.KEEP_DAYS + 5) * DAY) for i in range(4)]
check("① 日数= 床を超えた古い物は捨てる",
      sorted(fl._drop_list(many, now)) == sorted(n for n, _ in many[fl.KEEP_MIN:]))
check("① 捨てる列に `server.log` 本体は構造上入らない(形が違う)",
      fl._ROT_RE.match("server.log") is None
      and fl._ROT_RE.match("server.log.20260823_224201") is not None)

# --- ② 退避= 中身が1バイトも変わらずコピーされ、元は残る --------------------
with _Sandbox() as sb:
    src = sb.write_log()
    before = open(src, "rb").read()
    dst = fl._keep_prev_server_log()
    check("② 退避が1本出来る", dst and os.path.exists(dst) and len(sb.rotations()) == 1)
    check("② 中身がバイト単位で一致する", dst and open(dst, "rb").read() == before)
    check("② 元の server.log は消えていない・中身も同じ",
          os.path.exists(src) and open(src, "rb").read() == before)

# --- ③④ 空・不在では退避しない(掃除だけ回る) -------------------------------
with _Sandbox() as sb:
    open(os.path.join(sb.logdir, "server.log"), "w").close()
    check("③ サイズ0なら退避しない", fl._keep_prev_server_log() is None and not sb.rotations())
with _Sandbox() as sb:
    check("④ server.log が無くても例外を投げず None を返す",
          fl._keep_prev_server_log() is None and not sb.rotations())

# --- ⑤ 掃除= 実物のファイルで、残る物と消える物を数える ---------------------
with _Sandbox() as sb:
    for i in range(fl.KEEP_MIN + 5):
        sb.put_rotation("server.log.20260701_%06d" % i, fl.KEEP_DAYS + 3 + i)
    sb.write_log()
    keep_body = os.path.join(sb.logdir, "server.log.keepme")   # 形が違う=退避ではない
    other = os.path.join(sb.logdir, "other.log")
    for p in (keep_body, other):
        open(p, "w").close()
    gone = fl._cleanup_old_server_logs()
    check("⑤ 古い退避が消え、新しい方から KEEP_MIN 本だけ残る",
          len(gone) == 5 and len(sb.rotations()) == fl.KEEP_MIN)
    check("⑤ `server.log` 本体は消えない",
          os.path.exists(os.path.join(sb.logdir, "server.log")))
    check("⑤ 退避の形をしていないファイルには触らない",
          os.path.exists(keep_body) and os.path.exists(other))

# --- ⑥ 配線= start_server を通した時に退避が増える(関数単体ではなく経路) ----
class _WhichShim(object):
    """`shutil.which` だけ偽物。copy2 等は本物へ素通し(=退避の中身は本物が作る)。"""

    def __init__(self, exe):
        self._exe = exe

    def __getattr__(self, k):
        return getattr(_real_shutil, k)

    def which(self, name):
        return self._exe if name == "fcc-server" else _real_shutil.which(name)


class _PopenShim(object):
    DEVNULL = _real_subprocess.DEVNULL
    calls = []

    def __getattr__(self, k):
        return getattr(_real_subprocess, k)

    def Popen(self, argv, **kw):
        _PopenShim.calls.append(argv)
        return object()          # ★外へ出る手だけ偽物= 本物の fcc-server は起こさない


def _with_fake_launcher(fn):
    prev = (fl.shutil, fl.subprocess, fl.server_alive)
    fl.shutil, fl.subprocess = _WhichShim("C:/dummy/fcc-server.exe"), _PopenShim()
    fl.server_alive = lambda timeout=3: True
    try:
        return fn()
    finally:
        fl.shutil, fl.subprocess, fl.server_alive = prev


with _Sandbox() as sb:
    sb.write_log()
    _PopenShim.calls = []
    _with_fake_launcher(lambda: fl.start_server(wait=1))
    check("⑥ start_server が実際に fcc-server を起こそうとした(経路を通った)",
          len(_PopenShim.calls) == 1)
    check("⑥ その1回で退避が1本増えている(配線が生きている)", len(sb.rotations()) == 1)

# --- ⑦ must-fail(C-053)= 止血が入る前の「動く別の実装」へ戻すと赤くなるか ---
def _noop_keep():
    """★止血が入る前の実装そのもの= 退避しない(動く。ただ何もしないだけ)。"""
    return None


with _Sandbox() as sb:
    sb.write_log()
    _prev = fl._keep_prev_server_log
    fl._keep_prev_server_log = _noop_keep
    try:
        _PopenShim.calls = []
        _with_fake_launcher(lambda: fl.start_server(wait=1))
        _no_rot = (len(sb.rotations()) == 0 and len(_PopenShim.calls) == 1)
    finally:
        fl._keep_prev_server_log = _prev
    check("⑦ must-fail: 退避を『何もしない』へ戻すと、起動しても退避が1本も増えない",
          _no_rot)
    check("⑦ 復元済み: 本物へ戻すとまた退避が1本出来る",
          fl._keep_prev_server_log is _prev
          and fl._keep_prev_server_log() and len(sb.rotations()) == 1)

with _Sandbox() as sb:
    for i in range(fl.KEEP_MIN + 5):
        sb.put_rotation("server.log.20260701_%06d" % i, fl.KEEP_DAYS + 3 + i)
    _prev_clean = fl._cleanup_old_server_logs
    fl._cleanup_old_server_logs = lambda now=None: []    # ★掃除が無い版=HQの止血そのもの
    try:
        fl._keep_prev_server_log()
        _still = len(sb.rotations())
    finally:
        fl._cleanup_old_server_logs = _prev_clean
    check("⑦ must-fail: 掃除を外すと古い退避が %d本 残ったまま(無限に増える)" % (fl.KEEP_MIN + 5),
          _still == fl.KEEP_MIN + 5)
    fl._cleanup_old_server_logs()
    check("⑦ 復元済み: 本物の掃除を回すと KEEP_MIN 本まで落ちる",
          len(sb.rotations()) == fl.KEEP_MIN)

check("⑧ HOME を戻し忘れていない(本物の ~/.fcc を汚していない)",
      fl.HOME == os.path.expanduser("~"))

ng = [n for n, ok in results if not ok]
print(f"\n{len(results) - len(ng)}/{len(results)} PASS")
if ng:
    print("FAILED: " + " / ".join(ng))
sys.exit(1 if ng else 0)
