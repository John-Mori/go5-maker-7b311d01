#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""dept_daemon の発火判定の回帰チェック(tests/test_dept_daemon_classify.py を呼ぶ薄い橋)。

背景= 2026-07-20「回します」と言って回さない事故。キーワード判定の取りこぼしを
キャラ自身の申告(WORK_MARKER)で回収する二段構えを、回帰として固定する。
"""
import os
import subprocess
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.normpath(os.path.join(HERE, "..", "..", "..", ".."))
TEST = os.path.join(ROOT, "tests", "test_dept_daemon_classify.py")

r = subprocess.run([sys.executable, TEST], capture_output=True, text=True,
                   encoding="utf-8", errors="replace",
                   env=dict(os.environ, PYTHONIOENCODING="utf-8"))
print((r.stdout or "").strip() or (r.stderr or "").strip())
sys.exit(r.returncode)
