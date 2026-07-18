#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""QA回帰チェック一括実行 (A-7)。開窓時とインフラ検証の依頼時に実行する。全PASSで exit 0。"""
import os
import subprocess
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
HERE = os.path.dirname(os.path.abspath(__file__))
CHECKS = [
    "check_channels_registry.py",
    "check_inbox_hygiene.py",
    "check_manifest_coverage.py",
    "replay_sweep_trap.py",
]


def main():
    env = dict(os.environ, PYTHONIOENCODING="utf-8")
    fails = 0
    for c in CHECKS:
        r = subprocess.run([sys.executable, os.path.join(HERE, c)], env=env,
                           capture_output=True, text=True, encoding="utf-8", errors="replace")
        out = (r.stdout or "").strip()
        if out:
            print(out)
        if r.returncode != 0:
            fails += 1
            if (r.stderr or "").strip():
                print(r.stderr.strip())
    print(f"== {len(CHECKS) - fails}/{len(CHECKS)} PASS ==")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
