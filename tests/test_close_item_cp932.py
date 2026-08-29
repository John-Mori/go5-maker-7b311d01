# -*- coding: utf-8 -*-
"""close_item.py が日本語Windowsの出口(cp932)で死なない/化けないことの検査
(2026-08-29 イージス研究室)。

なぜ在るか:
  台帳の要旨は1行しか起動文に出ない(HQ-0220③の痩身)。**中身は --show で開け**、と
  全部屋の起動文に書いてある。その --show が **🔥印の付いた行で UnicodeEncodeError で落ちていた**
  = `--list --dept aegis-gl` も丸ごと落ちる。閉じるための入口が閉じていた。

見るもの(★ソースの文字列一致では見ない。**実際に別プロセスで走らせて出口を通す**):
  A --show が落ちない・日本語が化けない
  B --list が落ちない
  C 🔥を含む行でも落ちない
  ★must-fail(C-053)= 出口の作法を**外した実装**(reconfigureを消した写し)を同じ条件で回すと赤くなる

  python tests/test_close_item_cp932.py
"""
import io
import os
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
TOOL = os.path.join(ROOT, "scripts", "llm", "close_item.py")
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

OK = [0]
NG = [0]


def check(name, cond, detail=""):
    (OK if cond else NG)[0] += 1
    print("%s %s%s" % ("PASS" if cond else "**FAIL**", name,
                       ("  | " + detail) if (detail and not cond) else ""))


def run(script, args):
    """★出口を cp932 に固定して走らせる= 日本語Windowsの本番と同じ条件。"""
    env = dict(os.environ)
    env["PYTHONIOENCODING"] = "cp932"
    # ★must-fail の写しは別の場所に置くので、import 先だけ本物へ通す
    #   (出口の作法= 検査したい所は本物のまま。ここは経路を通すためだけ)
    env["PYTHONPATH"] = os.path.join(ROOT, "scripts", "llm") + os.pathsep + env.get("PYTHONPATH", "")
    p = subprocess.run([sys.executable, script] + args, capture_output=True, env=env)
    return p.returncode, p.stdout.decode("utf-8", "replace") + p.stderr.decode("utf-8", "replace")


# 🔥印が付いていて、投入前に実際に落ちていたID(実測 2026-08-29)
BURN_ID = "DEF-aegis-gl-f6108cdd2b"

print("== A/B/C 本番の出口(cp932)で走らせる ==")
rc, out = run(TOOL, ["--show", BURN_ID])
check("C 🔥付きの行を --show しても落ちない", rc == 0 and "Traceback" not in out, out[-200:])
check("A 日本語が化けていない(症状が読める)", "症状/本文" in out, out[:120])

rc2, out2 = run(TOOL, ["--list", "--dept", "aegis-gl"])
check("B --list が落ちない", rc2 == 0 and "Traceback" not in out2, out2[-200:])
check("B --list に台帳のIDが並ぶ", BURN_ID in out2, out2[:120])

rc3, out3 = run(TOOL, ["--health"])
check("B --health が落ちない", rc3 == 0 and "Traceback" not in out3, out3[-200:])

# ------------------------------------------------- must-fail(C-053)
print("\n== must-fail(出口の作法を外すと赤くなるか) ==")
src = io.open(TOOL, encoding="utf-8").read()
# ★行を消して文法を壊すのではなく、**動く別の実装**へ戻す= reconfigureしない写し
broken = src.replace('sys.stdout.reconfigure(encoding="utf-8", errors="replace")',
                     "pass  # ★投入前の実装(出口を触らない)")
broken = broken.replace('sys.stderr.reconfigure(encoding="utf-8", errors="replace")',
                        "pass")
check("must-fail 写しが本物と違う(差し替えが効いている)", broken != src)

tmp = os.path.join(tempfile.mkdtemp(), "close_item.py")
io.open(tmp, "w", encoding="utf-8").write(broken)
# ★import 先を本物の scripts/llm へ通す(session_relay を読ませるため)
rc4, out4 = run(tmp, ["--show", BURN_ID])
check("must-fail 出口を外すと 🔥の行で落ちる", rc4 != 0 and "UnicodeEncodeError" in out4,
      "rc=%s / %s" % (rc4, out4[-200:]))

print("\n==== %d PASS / %d FAIL ====" % (OK[0], NG[0]))
sys.exit(1 if NG[0] else 0)
