#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""ledger_integrity.scan の自己検査(空PASSにしない=test-must-fail)。

わざと3種の壊れを仕込んだバイト列を作り、検出器が
undecodable / invalid-json / bom を**それぞれ1件ずつ**拾い、
正常行だけは good に数えることを確かめる。壊れを1つでも取りこぼしたら赤。
"""
import os
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import ledger_integrity as li  # noqa: E402

BOM = b"\xef\xbb\xbf"


def main():
    lines = [
        b'{"ok": 1}',                                  # 正常
        BOM + b'{"ok": 2}',                            # BOM(除去すれば読める)
        b'{"broken": ',                                # invalid-json
        b'{"mojibake": "\x95\x5c"}',                   # undecodable(cp932の生バイト)
        b'{"ok": 3}',                                  # 正常
    ]
    with tempfile.NamedTemporaryFile("wb", suffix=".jsonl", delete=False) as f:
        f.write(b"\n".join(lines))
        path = f.name
    try:
        good, issues = li.scan(path)
        kinds = sorted(k for _, k, _ in issues)
        # BOM行は「有効データ+警告」= good に数える(正常2 + BOM1)。壊れ2行はgoodに入らない。
        assert good == 3, f"正常+BOM=3のはず: got {good}"
        assert kinds == ["bom", "invalid-json", "undecodable"], f"検出種別が違う: {kinds}"
        # 正常のみのファイルはクリーン
        with tempfile.NamedTemporaryFile("wb", suffix=".jsonl", delete=False) as f2:
            f2.write(b'{"a":1}\n{"b":2}\n')
            clean = f2.name
        g2, iss2 = li.scan(clean)
        assert g2 == 2 and iss2 == [], f"クリーンなはず: {g2} {iss2}"
        os.unlink(clean)
    finally:
        os.unlink(path)
    print("PASS: undecodable/invalid-json/bom を各1件検出・正常2行を計上")


if __name__ == "__main__":
    main()
