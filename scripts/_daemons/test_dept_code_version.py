#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""部門常駐の「版の控え」の検査(記録する側=daemon_keeper / 読む側=dept_code_version)。

なぜ要るか= 2026-08-23 プラットフォームSE「今この部屋の精霊がどの版で走っているか測れていない」。
  控えが無い間、版の答えはその場のワンライナー(起動時刻を目で見る)しか無かった=共通規律§1が
  名指しで禁じている数え方だ。控えを作ったので、その控えが**本当に中身を追っているか**を見る。

★must-fail を実行で入れてある(文字列一致の保険だけにしない= test-must-fail SKILL の警告)。
  ① 読むコードを差し替えたら控えのsha1が**変わる**ことを見る(定数を書いていたら赤)。
  ② 控えの置き場を書けない所にしても**起動は続く**ことを見る(帳簿でfail-closedしていたら赤)。
走らせ方= python scripts/_daemons/test_dept_code_version.py
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
sys.path.insert(0, HERE)
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:                                       # noqa: BLE001
    pass
import daemon_keeper as dk               # noqa: E402
import dept_code_version as dcver         # noqa: E402

fails = []
TMP = os.path.join(ROOT, "local", "_work", "_codever_test")


def check(name, got, want):
    ok = (got == want)
    print(("  PASS " if ok else "  FAIL ") + name + ("" if ok else f"  got={got!r} want={want!r}"))
    if not ok:
        fails.append(name)


os.makedirs(TMP, exist_ok=True)

# ── 1. 控えの読み取り(純粋関数) ────────────────────────────────────
print("=== 1. 控えの読み取り(read_record) ===")
check("控えが無ければ空で返す", dcver.read_record("nosuchdept", TMP), (None, 0.0, 0))
with open(os.path.join(TMP, "dept_a.txt"), "w", encoding="utf-8") as f:
    f.write("abc123\t1700000000\t555\n")
check("正しい控えは3つに割れる", dcver.read_record("a", TMP), ("abc123", 1700000000.0, 555))
for bad, label in (("abc123\n", "列が足りない"), ("\t1\t2\n", "sha1が空"),
                   ("abc\tx\ty\n", "数字でない")):
    with open(os.path.join(TMP, "dept_b.txt"), "w", encoding="utf-8") as f:
        f.write(bad)
    check(f"壊れた控えは空で返す({label})", dcver.read_record("b", TMP), (None, 0.0, 0))

# ── 2. 判定(純粋関数・全枝) ───────────────────────────────────────
print("=== 2. 判定(verdict) ===")
NOW, BEFORE, AFTER = 1000.0, 900.0, 1100.0
check("プロセスが居ない", dcver.verdict("H", ("H", NOW, 7), None, AFTER), dcver.DEAD)
check("★控えのpidが一致 + 同じ版= 現行",
      dcver.verdict("H", ("H", NOW, 7), (7, NOW), AFTER), dcver.CUR)
check("★控えのpidが一致 + 違う版= 旧",
      dcver.verdict("H", ("OLD", NOW, 7), (7, NOW), AFTER), dcver.OLD)
check("★他人の控え(pid違い)を自分の版として採らない",
      dcver.verdict("H", ("H", NOW, 999), (7, NOW), AFTER) in (dcver.CUR, dcver.OLD), False)
check("控え無し + 起動後にコードが変わった= 旧(推定)",
      dcver.verdict("H", (None, 0.0, 0), (7, NOW), AFTER), dcver.GUESS_OLD)
check("控え無し + コードは起動より古い= 現行(推定)",
      dcver.verdict("H", (None, 0.0, 0), (7, NOW), BEFORE), dcver.GUESS_CUR)
check("★測れない時は現行へ丸めない(不明のまま)",
      dcver.verdict("H", (None, 0.0, 0), (7, NOW), 0.0), dcver.UNKNOWN)

# ── 3. 記録する側を**実行で**通す(外へ出る手=Popen だけ偽物) ──────────
print("=== 3. 起動の瞬間に控えが書かれる(Slot.spawn を実行) ===")


class FakeProc:
    def __init__(self, pid):
        self.pid = pid

    def poll(self):
        return None


def spawn_once(dept, pid, codever_dir, daemon_path=None):
    """本物の Slot.spawn を、プロセス起動だけ偽物にして通す。判定と書き込みは本物。"""
    orig_popen, orig_dir, orig_daemon = dk.subprocess.Popen, dk.CODEVER_DIR, dk.DAEMON
    dk.subprocess.Popen = lambda *a, **k: FakeProc(pid)
    dk.CODEVER_DIR = codever_dir
    if daemon_path:
        dk.DAEMON = daemon_path
    dk._codever_cache["stamp"] = None       # 版のキャッシュを空にする(前の答えを再利用しない)
    try:
        s = dk.Slot(dept)
        s.spawn()
        return s
    finally:
        dk.subprocess.Popen, dk.CODEVER_DIR, dk.DAEMON = orig_popen, orig_dir, orig_daemon


s1 = spawn_once("_selftest", 4242, TMP)
h1, st1, p1 = dcver.read_record("_selftest", TMP)
check("起動したら控えが出来る", bool(h1), True)
check("控えのpidは立ち上げたプロセスのもの", p1, 4242)
check("控えの起動時刻はプロセスの起動時刻", int(st1), int(s1.started))
check("★控えの版は dept_daemon の今の版と一致する", h1, dk._dept_code_hash())
check("★読み手が『現行』と言う", dcver.verdict(h1, (h1, st1, p1), (4242, st1), 0.0), dcver.CUR)

# ★must-fail①= 読むコードを差し替えたら控えの版が**変わる**(定数や固定文字なら赤になる)
s2 = spawn_once("_selftest2", 4243, TMP,
                daemon_path=os.path.join(ROOT, "scripts", "_daemons", "daemon_code_version.py"))
h2 = dcver.read_record("_selftest2", TMP)[0]
check("mustfail_別のコードを起動したら控えの版は違う値になる", h2 == h1, False)
check("mustfail_その時ちゃんと『旧』と言う", dcver.verdict(h1, (h2, 0.0, 4243), (4243, 0.0), 0.0),
      dcver.OLD)

# ★must-fail②= 控えが書けなくても起動は続く(帳簿で常駐を止めない=fail-open)
s3 = spawn_once("_selftest3", 4244, os.path.join(TMP, "\0bad"))
check("mustfail_控えを書けなくても起動している", s3.proc.pid, 4244)
check("mustfail_その部門は『不明』であって現行ではない",
      dcver.verdict("H", dcver.read_record("_selftest3", TMP), (4244, 0.0), 0.0), dcver.UNKNOWN)

# ── 4. 版の定義を2箇所に持たない ─────────────────────────────────
print("=== 4. 版の定義は daemon_code_version 一本 ===")
src = open(os.path.join(HERE, "daemon_keeper.py"), encoding="utf-8", errors="replace").read()
check("keeper は版の計算を借りている", "daemon_code_version" in src, True)
check("★keeper が自前でハッシュを作っていない", "hashlib" in src, False)
check("控えの置き場は keeper が持つ1つだけ", src.count("CODEVER_DIR = "), 1)

# 後始末(検査が置いていったゴミを残さない)
for d in ("_selftest", "_selftest2", "_selftest3"):
    for p in (os.path.join(TMP, f"dept_{d}.txt"),
              os.path.join(ROOT, "local", "llm", f"dept_daemon_{d}.log")):
        try:
            os.remove(p)
        except OSError:
            pass

if __name__ == "__main__":
    print(f"\nFAIL — {len(fails)}件: {fails}" if fails else "\nALL PASS")
    sys.exit(1 if fails else 0)
