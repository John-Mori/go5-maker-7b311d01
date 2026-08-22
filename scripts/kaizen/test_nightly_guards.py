#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""nightly_guards.run_guards の自己検査(空PASSにしない=test-must-fail)。

壊れた台帳を食わせた門番が returncode!=0(鳴る)を返し、
正常な台帳では 0(黙る)を返すことを確かめる。門番が本当に鳴るかの実行検査。
"""
import os
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import nightly_guards as ng  # noqa: E402

PY = sys.executable
LEDGER = os.path.join(HERE, "ledger_integrity.py")


def main():
    # 壊れ行(不正JSON)を含む台帳 → 門番は rc!=0
    with tempfile.NamedTemporaryFile("wb", suffix=".jsonl", delete=False) as f:
        f.write(b'{"ok":1}\n{"broken":\n')
        broken = f.name
    # 正常な台帳 → 門番は rc==0
    with tempfile.NamedTemporaryFile("wb", suffix=".jsonl", delete=False) as f:
        f.write(b'{"ok":1}\n{"ok":2}\n')
        clean = f.name
    try:
        res = ng.run_guards([
            ("broken-ledger", [PY, LEDGER, broken]),
            ("clean-ledger", [PY, LEDGER, clean]),
        ])
        by = {n: rc for n, rc, _ in res}
        assert by["broken-ledger"] != 0, f"壊れ台帳で門番が鳴らなかった: {by}"
        assert by["clean-ledger"] == 0, f"正常台帳で誤発火した: {by}"
    finally:
        os.unlink(broken)
        os.unlink(clean)
    print("PASS: 壊れ台帳で門番rc!=0(鳴る) / 正常台帳でrc==0(黙る)")


if __name__ == "__main__":
    main()
