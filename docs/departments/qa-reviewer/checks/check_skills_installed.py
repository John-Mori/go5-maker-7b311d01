#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Claude skillの機能別配置を検査する。

旧方式の「docsに正本、.claudeへ手動copy」という二重管理は廃止した。
現役runtimeが読む互換配置には組織運営skillだけを置き、旧Web、YMM4、
goods skillが混入して自動候補になることを防ぐ。
"""
from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path


sys.stdout.reconfigure(encoding="utf-8", errors="replace")
HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[3]
MANIFEST = ROOT / "docs" / "departments" / "00_common" / "skills" / "placement.json"
INSTALLED = ROOT / ".claude" / "skills"


def _tracked() -> set[str]:
    result = subprocess.run(
        ["git", "ls-files", ".claude/skills"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    if result.returncode != 0:
        return set()
    return {line.strip().replace("\\", "/") for line in result.stdout.splitlines() if line.strip()}


def _frontmatter_name(path: Path) -> str | None:
    text = path.read_text(encoding="utf-8")
    match = re.search(r"(?m)^name:\s*([^\s]+)\s*$", text)
    return match.group(1) if match else None


def main() -> int:
    if not MANIFEST.is_file():
        print(f"FAIL: skill placement manifest missing: {MANIFEST}")
        return 1
    data = json.loads(MANIFEST.read_text(encoding="utf-8"))
    if data.get("schema_version") != 1:
        print("FAIL: unsupported skill placement schema")
        return 1
    expected = sorted(data.get("organization_runtime_skills", []))
    retired = set(data.get("retired_legacy_skills", []))
    actual = sorted(
        path.name for path in INSTALLED.iterdir()
        if path.is_dir() and (path / "SKILL.md").is_file()
    ) if INSTALLED.is_dir() else []
    tracked = _tracked()
    failures: list[str] = []

    if actual != expected:
        failures.append(f"配置不一致 expected={expected} actual={actual}")
    for name in expected:
        skill = INSTALLED / name / "SKILL.md"
        if not skill.is_file():
            failures.append(f"missing: {name}")
            continue
        if _frontmatter_name(skill) != name:
            failures.append(f"frontmatter name不一致: {name}")
        rel = f".claude/skills/{name}/SKILL.md"
        if tracked and rel not in tracked:
            failures.append(f"git未追跡: {rel}")
    leaked = retired.intersection(actual)
    if leaked:
        failures.append(f"旧skillが有効配置に残存: {sorted(leaked)}")

    if failures:
        print(f"FAIL: check_skills_installed ({len(failures)}件)")
        for failure in failures:
            print("  ", failure)
        return 1
    print(f"PASS: check_skills_installed (組織専用 {len(expected)}本・旧skill 0本)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

