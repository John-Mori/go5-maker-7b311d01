# -*- coding: utf-8 -*-
"""guard_destructive.py の受け入れ試験(イージス研究室・2026-08-29)。

★このテストを **Bashのコマンド行に直接書けない** ことがフックの穴を示している=
  止める形の文字列をコマンド行へ置くと、フック自身がテストの起動を止めてしまう。
  だからファイルに置いて `python tests/test_guard_destructive.py` で回す。

見るもの
  A 止める側 … exit 2 になるか / 文言が **UTF-8で読めるか**(cp932で化けない)
  B 通す側  … exit 0 か(誤発火が無いか)
  C 引用の中 … ヒアドキュメント/文字列リテラルの中の「危険な形」で誤発火しないか
"""
import json
import os
import subprocess
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HOOK = os.path.join(ROOT, "scripts", "hooks", "guard_destructive.py")

STOP = [
    "git reset --hard HEAD",
    "git clean -fd",
    "git checkout -- app.js",
    "git push --force origin main",
    "git branch -D feat/x",
    "cd /d/x && git reset --hard origin/main",
    # ★ヒアドキュメントでも、食わせる先がシェルなら**実行される**=止める
    "bash <<'EOF'\ngit reset --hard HEAD\nEOF",
    "sh <<EOF\ngit clean -fd\nEOF",
]

PASS = [
    "git push origin main",
    "git push --force-with-lease origin main",
    "git status",
    "git stash",
    "git branch -d feat/x",
    "git commit -m 'x'",
    "git checkout main",
    "rm -rf build/",                       # ★意図的に入れていない形
    "git log --oneline -5",
]

# ★C= 「実行しない文脈」に危険な形が現れるだけの便。ここが誤発火すると
#   テストも報告も書けなくなる= 常に誤発火する安全網は無視される(共通規律 §3)。
QUOTED = [
    "python - <<'PY'\nCASES = [\"git reset --hard HEAD\"]\nprint(CASES)\nPY",
    "python -c \"print('git branch -D feat/x')\"",
    "echo 'git clean -fd は危ないので使わない' >> docs/note.md",
]


def run(cmd):
    p = subprocess.run(
        [sys.executable, HOOK],
        input=json.dumps({"tool_name": "Bash",
                          "tool_input": {"command": cmd}}).encode("utf-8"),
        capture_output=True)
    return p.returncode, p.stderr


def readable(err):
    """stderr が UTF-8 として読めて、日本語の見出しが入っているか。"""
    try:
        t = err.decode("utf-8")
    except UnicodeDecodeError:
        return False
    return "【機構で停止】" in t


def main():
    ng = 0
    print("■A 止める側(期待= rc2 かつ 文言がUTF-8で読める)")
    for c in STOP:
        rc, err = run(c)
        ok = (rc == 2 and readable(err))
        ng += 0 if ok else 1
        print("  %-5s rc=%s 文言=%s  %s"
              % ("OK" if ok else "NG", rc,
                 "読めた" if readable(err) else "**化けている/無い**",
                 c.replace("\n", "\\n")))

    print("■B 通す側(期待= rc0)")
    for c in PASS:
        rc, _ = run(c)
        ok = (rc == 0)
        ng += 0 if ok else 1
        print("  %-5s rc=%s  %s" % ("OK" if ok else "NG", rc, c))

    print("■C 引用/ヒアドキュメントの中だけに現れる形(期待= rc0)")
    for c in QUOTED:
        rc, _ = run(c)
        ok = (rc == 0)
        ng += 0 if ok else 1
        print("  %-5s rc=%s  %s" % ("OK" if ok else "NG", rc,
                                    c.replace("\n", "\\n")[:70]))

    total = len(STOP) + len(PASS) + len(QUOTED)
    print("\n== %d/%d PASS / NG=%d ==" % (total - ng, total, ng))
    return 1 if ng else 0


if __name__ == "__main__":
    raise SystemExit(main())
