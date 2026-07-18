#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""local/inbox/ の衛生チェック (QA回帰・A-7)。
不変条件: inbox直下の.jsonlは台帳のdept名のみ (台帳外の名前=INC-86の罠の再来。
sweepガードで食われはしないが、置いた本人は配達も回収もされない箱を見張ることになる)。
"""
import json
import os
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
ROOT = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "..", ".."))


def main():
    reg = os.path.join(ROOT, "local", "discord_channels.json")
    inbox = os.path.join(ROOT, "local", "inbox")
    depts = {str(c.get("dept", "")) for c in json.load(open(reg, encoding="utf-8"))}
    errs, seen = [], 0
    if os.path.isdir(inbox):
        for fn in sorted(os.listdir(inbox)):
            if not fn.endswith(".jsonl"):
                continue
            seen += 1
            dept = fn[: -len(".jsonl")]
            if dept not in depts:
                errs.append(f"台帳外の箱: local/inbox/{fn} (INC-86の罠。退避は local/_work/ へ)")
    if errs:
        print(f"FAIL: check_inbox_hygiene ({len(errs)}件)")
        for e in errs:
            print("  -", e)
        return 1
    print(f"PASS: check_inbox_hygiene (箱{seen}個・全て台帳内のdept名)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
