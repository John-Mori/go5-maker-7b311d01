#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""台帳 local/discord_channels.json の不変条件チェック (QA回帰・A-7)。
不変条件: 各行に name/id/dept が揃う・idは17-20桁数字・id重複なし・dept重複なし。
dept重複はINC相当 (受信箱の共有=返信先の取り違え。学習ルーム1/2で実害を確認済み 2026-07-16)。
"""
import json
import os
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
ROOT = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "..", ".."))
REG = os.path.join(ROOT, "local", "discord_channels.json")


def main():
    errs = []
    try:
        chs = json.load(open(REG, encoding="utf-8"))
    except Exception as e:
        print(f"FAIL: 台帳が読めない: {e}")
        return 1
    if not isinstance(chs, list) or not chs:
        print("FAIL: 台帳が空か配列でない")
        return 1
    ids, depts = {}, {}
    for i, c in enumerate(chs):
        name, cid, dept = c.get("name"), str(c.get("id", "")), c.get("dept")
        if not name:
            errs.append(f"行{i}: nameが空")
        if not (cid.isdigit() and 17 <= len(cid) <= 20):
            errs.append(f"行{i} ({name}): id形式不正 [{cid}]")
        if not dept:
            errs.append(f"行{i} ({name}): deptが空")
        if cid in ids:
            errs.append(f"id重複: {cid} ({ids[cid]} / {name})")
        ids[cid] = name
        if dept in depts:
            errs.append(f"dept重複: {dept} ({depts[dept]} / {name}) = 受信箱共有・返信先取り違えの穴")
        depts[dept] = name
    if errs:
        print(f"FAIL: check_channels_registry ({len(errs)}件)")
        for e in errs:
            print("  -", e)
        return 1
    print(f"PASS: check_channels_registry ({len(chs)}ch・id/dept重複なし)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
