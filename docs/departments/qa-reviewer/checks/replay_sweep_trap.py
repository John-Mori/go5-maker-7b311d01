#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""INC-86 罠の再現テスト (QA回帰・A-7)。本番に一切触れないサンドボックス実行。
検証3項 (2026-07-17 の独立検証と同一・全PASSが合格):
  (a) 箱の隣の退避ファイル (台帳外dept名) がsweepに食われない
  (b) 本物の部門箱 (脈なし) はmainへ回収される = フェイルオーバーが生きている (対策殺し確認・本命)
  (c) mainへ (a) の中身が混入しない
inbox_poller の import 前に GO5_LOCAL_DIR を差し替えるのが肝 (import時にLOCALが確定するため)。
"""
import importlib
import os
import shutil
import sys
import tempfile

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.normpath(os.path.join(HERE, "..", "..", "..", ".."))


def main():
    sandbox = tempfile.mkdtemp(prefix="qa_sweep_trap_")
    try:
        os.environ["GO5_LOCAL_DIR"] = sandbox
        os.makedirs(os.path.join(sandbox, "inbox"), exist_ok=True)
        os.makedirs(os.path.join(sandbox, "llm"), exist_ok=True)
        open(os.path.join(sandbox, "discord_inbox.jsonl"), "w").close()
        with open(os.path.join(sandbox, "inbox", "_qa_work.jsonl"), "w", encoding="utf-8") as f:
            f.write('{"msg_id":"PROBE-A","dept":"qa-reviewer"}\n')
        with open(os.path.join(sandbox, "inbox", "qa-reviewer.jsonl"), "w", encoding="utf-8") as f:
            f.write('{"msg_id":"PROBE-B","dept":"qa-reviewer"}\n')

        sys.path.insert(0, os.path.join(ROOT, "scripts", "discord"))
        if "inbox_poller" in sys.modules:
            del sys.modules["inbox_poller"]
        poller = importlib.import_module("inbox_poller")
        poller.sweep_stale_dept_boxes({"qa-reviewer", "system-engineer"})

        a = open(os.path.join(sandbox, "inbox", "_qa_work.jsonl"), encoding="utf-8").read()
        b = open(os.path.join(sandbox, "inbox", "qa-reviewer.jsonl"), encoding="utf-8").read().strip()
        m = open(os.path.join(sandbox, "discord_inbox.jsonl"), encoding="utf-8").read()

        ok_a = "PROBE-A" in a
        ok_b = (b == "" and "PROBE-B" in m)
        ok_c = "PROBE-A" not in m
        for label, ok, desc in (
            ("a", ok_a, "退避ファイル無傷"),
            ("b", ok_b, "脈なし本物箱は回収 (フェイルオーバー健在)"),
            ("c", ok_c, "mainへ罠の中身が混入しない"),
        ):
            print(f"  ({label}) {'PASS' if ok else 'FAIL'}: {desc}")
        if ok_a and ok_b and ok_c:
            print("PASS: replay_sweep_trap (INC-86 3項)")
            return 0
        print("FAIL: replay_sweep_trap")
        return 1
    finally:
        os.environ.pop("GO5_LOCAL_DIR", None)
        shutil.rmtree(sandbox, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
