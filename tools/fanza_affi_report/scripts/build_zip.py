#!/usr/bin/env python3
"""納品zipを固める。固める前に check_no_secrets を必ず通す。

含めるもの: パッケージ本体 / run_report.py / config.example.ini /
            requirements.txt / README.md / tests / scripts(check_no_secrets)
含めないもの: config.ini(利用者の実値) / state / logs / __pycache__ / .bak
"""
from __future__ import annotations

import subprocess
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DIST = ROOT / "dist"

INCLUDE_DIRS = ["fanza_affi_report", "tests", "scripts"]
INCLUDE_FILES = ["run_report.py", "config.example.ini", "requirements.txt", "README.md"]
EXCLUDE_PARTS = {"__pycache__", "state", "logs", "dist"}
EXCLUDE_SUFFIX = {".pyc", ".bak", ".log"}
EXCLUDE_NAMES = {"config.ini"}


def _keep(p: Path) -> bool:
    if any(part in EXCLUDE_PARTS for part in p.parts):
        return False
    if p.suffix in EXCLUDE_SUFFIX or p.name in EXCLUDE_NAMES:
        return False
    return True


def main() -> int:
    # 1) 機密チェック(通らなければ止める)
    rc = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "check_no_secrets.py"), str(ROOT)]
    ).returncode
    if rc != 0:
        print("機密チェックに失敗。zipを作りません。")
        return rc

    # 2) 収集
    files: list[Path] = []
    for d in INCLUDE_DIRS:
        for p in (ROOT / d).rglob("*"):
            if p.is_file() and _keep(p):
                files.append(p)
    for f in INCLUDE_FILES:
        p = ROOT / f
        if p.exists():
            files.append(p)

    # 3) zip化
    DIST.mkdir(exist_ok=True)
    out = DIST / "fanza_affi_report.zip"
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        for p in sorted(files):
            z.write(p, arcname=str(Path("fanza_affi_report") / p.relative_to(ROOT)))
    print(f"[OK] 納品zip: {out}  ({len(files)}ファイル)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
