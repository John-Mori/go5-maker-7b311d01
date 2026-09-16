#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""部屋の権限登録簿(test_dept_daemon_classify.py の名簿検査)が**黙っていない**ことの変異テスト。

★2026-09-16 イージス研究室。名簿に3室を足し、Cへ2室を足し、同居を1室許した手番で書いた。
  名簿を実物へ合わせる修正は、やり過ぎると「現物をそのまま書き写すだけの検査」になって
  検出力が0になる(`?v=` の混在検査が --to 940 で全部揃えると何も捕まえなくなるのと同じ形。
  ad研究室モドリッチ 2026-09-16 の指摘)。だから**合わせた直後に、わざと壊して赤を見る**。

★偽物にするのは **DEPT_CONF の中身だけ**= 検査の判定・分岐は本物が最後まで走る。
  ソースの文字列一致では測らない(それは検査ではなく保険だ)。
  子プロセスで dept_daemon を**先に**import して DEPT_CONF を書き換え、その後に
  本物の tests/test_dept_daemon_classify.py を runpy で走らせる(sys.modules 経由で刺さる)。

    python tests/test_dept_firing_registry_mutations.py
"""
import os
import subprocess
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.normpath(os.path.join(HERE, ".."))
TEST = os.path.join(HERE, "test_dept_daemon_classify.py")

RUNNER = r'''
import os, runpy, sys
sys.path.insert(0, os.path.join(%(root)r, "scripts", "llm"))
import dept_daemon as D
exec(%(mutate)r)
try:
    runpy.run_path(%(test)r, run_name="__main__")
except SystemExit as e:
    sys.exit(e.code if isinstance(e.code, int) else 1)
sys.exit(0)
'''

# (名前, DEPT_CONFへの変異, 期待する赤の見出し)。空文字の変異=無変異(緑の確認)。
CASES = [
    ("無変異(現物のまま)", "", None),
    ("新しい部屋に work_scope を与える",
     'D.DEPT_CONF["yosou-room"] = {"work_scope": True}',
     "★work_scope を持つ部屋の登録簿"),
    ("既にある部屋から work_scope を剥がす",
     'D.DEPT_CONF["web-research"].pop("work_scope", None)',
     "★work_scope を持つ部屋の登録簿"),
    ("宣言も権限も無い部屋を増やす(aegis-gl 8/5 と同型)",
     'D.DEPT_CONF["yosou-room"] = {"persona": "誰か"}',
     "★work_scopeも conversation_only 宣言も無い部屋"),
    ("関係の無い部屋に forward_all を付ける(main箱が汚れる形)",
     'D.DEPT_CONF["qa-reviewer"]["forward_all"] = True',
     "★forward_allはmain箱を読む対話セッションが居る部屋のみ"),
    ("work_scope と conversation_only を同居させる",
     'D.DEPT_CONF["qa-reviewer"]["conversation_only"] = True',
     "work_scopeと conversation_only の同居は learning-coach のみ"),
    ("local-lab から forward_all を剥がす(登録した理由が消えた形)",
     'D.DEPT_CONF["local-lab"].pop("forward_all", None)',
     "★forward_allはmain箱を読む対話セッションが居る部屋のみ"),
]


def run(mutate):
    src = RUNNER % {"root": ROOT, "test": TEST, "mutate": mutate}
    r = subprocess.run([sys.executable, "-c", src], capture_output=True, text=True,
                       encoding="utf-8", errors="replace", cwd=ROOT,
                       env=dict(os.environ, PYTHONIOENCODING="utf-8"))
    return r.returncode, (r.stdout or "") + (r.stderr or "")


def main():
    bad = 0
    for name, mutate, want in CASES:
        rc, out = run(mutate)
        if want is None:
            ok = rc == 0 and "PASS" in out
            print(("  ✓ " if ok else "  ✗ ") + name + f" → rc={rc}")
        else:
            # ★ここが肝= import で落ちた赤は検査ではない。**判定の赤**だけを受理する。
            hit = want in out
            judged = out.lstrip().startswith("FAIL ") or "\nFAIL " in out
            ok = rc == 1 and hit and judged
            print(("  ✓ " if ok else "  ✗ ") + name
                  + f" → rc={rc} 判定FAIL={judged} 見出し一致={hit}")
        if not ok:
            bad += 1
            for ln in out.strip().splitlines()[:6]:
                print("      | " + ln)
    print(("FAIL " if bad else "PASS ") + f"登録簿の変異 {len(CASES) - bad}/{len(CASES)}")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
