#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""close_request の C-024 ゲート単体テスト。
実物照合(verify_proof)が「実在するものだけ通し、実在しないものは閉じさせない」ことを固定する。
run: PYTHONUTF8=1 python tests/test_close_request.py
"""
import os
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.normpath(os.path.join(HERE, ".."))
sys.path.insert(0, os.path.join(ROOT, "scripts", "llm"))

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

import close_request as C

fails = []


def check(name, cond):
    print(("PASS " if cond else "FAIL ") + name)
    if not cond:
        fails.append(name)


# 1) 実在するファイルは通る(生成物の実在)
ok, kind, _ = C.verify_proof("scripts/llm/close_request.py", root=ROOT)
check("T1 existing file -> ok/file", ok and kind == "file")

# 2) 実在しないファイルは通さない(=偽受領を弾く本丸)
ok, kind, _ = C.verify_proof("scripts/llm/__does_not_exist__.py", root=ROOT)
check("T2 missing file -> refuse", (not ok) and kind == "unverified")

# 3) 空 proof は通さない
ok, kind, _ = C.verify_proof("", root=ROOT)
check("T3 empty proof -> refuse", (not ok) and kind == "none")

# 4) work_audit に観測された msg_id は通る / 未観測は通さない(一時fixtureで判定経路を固定)
with tempfile.TemporaryDirectory() as d:
    audit = os.path.join(d, "work_audit.jsonl")
    with open(audit, "w", encoding="utf-8") as f:
        f.write('{"ts":"t","dept":"x","msg_id":"OBSERVED-123456","touched":["local/foo.md"]}\n')
    ok, kind, _ = C.verify_proof("OBSERVED-123456", root=d, audit_path=audit)
    check("T4a observed msg_id -> ok/observed", ok and kind == "observed")
    ok, kind, _ = C.verify_proof("NOTthere-999999", root=d, audit_path=audit)
    check("T4b unobserved msg_id -> refuse", not ok)
    # touched に現れる生成物名も実在扱い
    ok, kind, _ = C.verify_proof("local/foo.md", root=d, audit_path=audit)
    check("T4c touched-observed -> ok", ok)

# 5) ~.. / \\ 混じりの work_audit 形式パスも正規化して実在判定できる
ok, kind, _ = C.verify_proof("~scripts\\llm\\close_request.py", root=ROOT)
check("T5 ~-prefixed backslash path normalized -> ok/file", ok and kind == "file")

# 6) このリポジトリの実在 commit は通る(HEAD)
import subprocess
head = subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT,
                      capture_output=True, text=True).stdout.strip()
if head:
    ok, kind, _ = C.verify_proof(head, root=ROOT)
    check("T6 real commit -> ok/commit", ok and kind in ("commit", "file"))
    ok, _, _ = C.verify_proof("deadbeefdeadbeef", root=ROOT)
    check("T6b bogus commit-shaped -> refuse", not ok)

print()
if fails:
    print(f"{len(fails)} FAILED: {fails}")
    sys.exit(1)
print("ALL PASS")
