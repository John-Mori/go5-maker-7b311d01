#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""組織側の技能(skills)が受け渡し場所に留まらず、実際に読まれる場所へ入っているかを確認する (QA回帰)。

根拠: 2026-08-13 に組織側で技能5本を docs/departments/00_common/skills/ へ作り、
    README に「.claude/skills/ へ cp して初めて効いた」と自分で書いておきながら、
    その cp が**5日間打たれていなかった**(2026-08-18 イージス研究室が実測・commit 7fe4dd3 で解消)。
    正しい中身が、誰も読まないファイルの中で眠っていた=「入れた」で止まっていた典型。

見るもの(2つ):
  ① 受け渡し場所(docs/.../skills/<名>/SKILL.md)にある技能が、全て .claude/skills/ にも在り、
     **中身が1バイトも違わない**こと。片方だけ直すと、技能を呼んだ側と Read した側で別の手順が出る。
  ② 実装置き側が git 追跡されていること。未追跡は他セッションの clean で黙って消える
     (=次に気づくのは「また5日眠っていた」時になる)。
"""
import os
import subprocess
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.normpath(os.path.join(HERE, "..", "..", "..", ".."))
STAGING = os.path.join(ROOT, "docs", "departments", "00_common", "skills")
INSTALLED = os.path.join(ROOT, ".claude", "skills")


def _read(path):
    with open(path, "rb") as f:
        return f.read()


def main():
    if not os.path.isdir(STAGING):
        print("SKIP: check_skills_installed (受け渡し場所が無い)")
        return 0
    names = sorted(n for n in os.listdir(STAGING)
                   if os.path.exists(os.path.join(STAGING, n, "SKILL.md")))
    if not names:
        print("SKIP: check_skills_installed (受け渡し場所に技能が無い)")
        return 0

    tracked = set()
    r = subprocess.run(["git", "ls-files", ".claude/skills"], cwd=ROOT,
                       capture_output=True, text=True, encoding="utf-8", errors="replace")
    if r.returncode == 0:
        tracked = {p.strip().replace("\\", "/") for p in (r.stdout or "").splitlines() if p.strip()}

    ng = []
    for n in names:
        dst = os.path.join(INSTALLED, n, "SKILL.md")
        if not os.path.exists(dst):
            ng.append(f"{n}: 受け渡し場所にあるが .claude/skills/ に入っていない(cp が打たれていない)")
            continue
        if _read(os.path.join(STAGING, n, "SKILL.md")) != _read(dst):
            ng.append(f"{n}: 受け渡し場所と実装置きで中身が違う(片方だけ直した)")
        if tracked and f".claude/skills/{n}/SKILL.md" not in tracked:
            ng.append(f"{n}: .claude/skills/ 側が git 未追跡(clean で消える)")

    if ng:
        print(f"FAIL: check_skills_installed ({len(ng)}件)")
        for line in ng:
            print("  ", line)
        return 1
    print(f"PASS: check_skills_installed (技能 {len(names)}本が実装置き済・中身一致・追跡済)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
