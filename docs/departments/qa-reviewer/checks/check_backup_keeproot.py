#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""backup_local_to_drive.ps1 の keepRoot が My Drive 直下へ退行しないことを確認する (QA回帰)。

根拠: 2026-09-16 Chami炎上。月次keepが '<MyDrive>\\go5-backup-keep' に落ちていた。
    正しくは '<MyDrive>\\...\\001_システムバックアップ\\go5-backup-keep'(=$destBase配下)。
    真因: keepRoot を $driveRoot.FullName から派生していた(旧: Join-Path $driveRoot.FullName 'go5-backup-keep')。
    恒久対策(C-038): keepRoot は $destBase 由来へ固定し、加えて ps1 実行時にも
    「keepRoot の親 == ドライブ直下」なら書き込み前 abort するガードを入れた。
    このチェックは、その2つの不変条件がソース上で崩れたら赤にする(退行検出)。
    ※ps1自体の実行にはGoogle Driveマウントが要り決定的に回らないため、ソース不変条件を検査する。
"""
import os
import re
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.normpath(os.path.join(HERE, "..", "..", "..", ".."))
PS1 = os.path.join(ROOT, "scripts", "maintenance", "backup_local_to_drive.ps1")

# 退行形: keepRoot をドライブ直下から派生している (これが炎上の真因)
BAD_DERIVE = re.compile(
    r"\$keepRoot\s*=\s*Join-Path\s+\$driveRoot\.FullName\s+['\"]go5-backup-keep['\"]"
)
# 正形: keepRoot は $destBase(=戦略バックアップフォルダ)配下から派生する
GOOD_DERIVE = re.compile(
    r"\$keepRoot\s*=\s*Join-Path\s+\$destBase\s+['\"]go5-backup-keep['\"]"
)
# 実行時ガード: keepRoot の親がドライブ直下なら abort する if 文が在ること
RUNTIME_GUARD = re.compile(
    r"\(Split-Path\s+\$keepRoot\s+-Parent\)\s*-eq\s+\$driveRoot\.FullName"
)


def main():
    if not os.path.exists(PS1):
        print("SKIP: check_backup_keeproot (backup_local_to_drive.ps1 が見つからない)")
        return 0
    with open(PS1, "r", encoding="utf-8") as f:
        src = f.read()

    problems = []
    if BAD_DERIVE.search(src):
        problems.append("keepRoot を $driveRoot.FullName 直下から派生している(2026-09-16炎上の退行形)")
    if not GOOD_DERIVE.search(src):
        problems.append("keepRoot を $destBase 配下から派生していない($destBase由来へ固定すること)")
    if not RUNTIME_GUARD.search(src):
        problems.append("実行時ガード((Split-Path $keepRoot -Parent) -eq $driveRoot.FullName)が無い")

    if problems:
        print("FAIL: check_backup_keeproot (backup keepRoot がMyDrive直下へ退行しうる)")
        for p in problems:
            print("  ", p)
        return 1
    print("PASS: check_backup_keeproot (keepRoot は $destBase 由来 + 実行時ガード有り)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
