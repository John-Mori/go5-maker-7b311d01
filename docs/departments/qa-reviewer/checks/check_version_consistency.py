#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""index.html の ?v= 参照が全て同一であることを確認する (QA回帰)。
根拠: 2026-07-20 に5版が混在し push 6回全赤(CLAUDE.md §3 / bump.mjs 参照)。
    部分バンプは古いJSがスマホにキャッシュされ続ける不可逆事故になる。
    node scripts/bump.mjs --check が exit 0 = 一致 / exit 3 = 混在。
"""
import os
import subprocess
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.normpath(os.path.join(HERE, "..", "..", "..", ".."))
BUMP = os.path.join(ROOT, "scripts", "bump.mjs")


def main():
    if not os.path.exists(BUMP):
        print("SKIP: check_version_consistency (bump.mjs が見つからない)")
        return 0
    r = subprocess.run(
        ["node", BUMP, "--check"],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
        cwd=ROOT,
    )
    out = (r.stdout or "").strip()
    err = (r.stderr or "").strip()
    if r.returncode == 0:
        # 現在値を添える (例: 現在 v=426 / 参照 8 箇所 / 混在 なし)
        print(f"PASS: check_version_consistency ({out.splitlines()[0] if out else 'OK'})")
        return 0
    print("FAIL: check_version_consistency (?v= 混在)")
    if err:
        for line in err.splitlines():
            print("  ", line)
    return 1


if __name__ == "__main__":
    sys.exit(main())
