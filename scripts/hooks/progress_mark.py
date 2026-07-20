#!/usr/bin/env python
"""progress_mark — 進捗印(既読/着手/即答)を**正しいタイミングで**押すhook。

★2026-07-21 Chami「私が既読と着手をどのタイミングでつけて欲しいという記憶はありますか?」
  → 記録されていた。正本= `docs/departments/00_common/rules/運用細則_セッションと起床.md` §37
     (4段・2026-07-19 Chami発案「即答」新設・QA合意):

     📮送信(sendms) = 鳩が配達時に**自動**            → 届いた証明(Claudeが見たとは限らない)
     ✅既読(kidoku) = **起床して読んだ直後**に自分で押す → 読んだ・返答/作業はこれから
     💬即答(sokutou)= **その場の返事で完結した時**に押す → 「読んだだけ」との曖昧さ解消
     👀着手(chakusyu)= **本格的な作業を始める時**に押す

  狙い= Chamiの画面から **未達/届いたが無人/読んだ/即答済み/着手済み** が判別できること。

★研究室HQ Vol.4の初版(react_mark)はこれを守れていなかった:
  ターン終了時に**既読と着手をまとめて押していた**。4つの印は時系列を表す信号なのに、
  同時に押せば時系列が消える。さらに雑談だけのターンでも着手が付き=**嘘の印**になる。
  「機構化した」ことだけ正しく、**中身が仕様と違った**。本ファイルがその訂正。

phase:
  read   … UserPromptSubmit(受け取った瞬間)      → 既読
  work   … PostToolUse で作業系ツールを使った時   → 着手(1ターン1回)
  end    … Stop(ターン終了時)                    → 着手が無ければ 即答

★fail-open: 何が失敗してもセッションは止めない(exit 0)。
"""
import json
import os
import subprocess
import sys

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.normpath(os.path.join(HERE, "..", ".."))
LOCAL = os.path.join(ROOT, "local")
REACT_MARK = os.path.join(ROOT, "scripts", "discord", "react_mark.py")
sys.path.insert(0, os.path.join(ROOT, "scripts", "llm"))

# 「本格的な作業」とみなすツール。読むだけ(Read/Grep/Glob)は着手ではない=読んでいる最中に
# 着手を押すと、調べただけで終わった時に嘘になる。
WORK_TOOLS = {"Edit", "Write", "NotebookEdit", "Bash", "PowerShell"}


def turn_flag(dept):
    return os.path.join(LOCAL, "llm", f"progress_turn_{dept}.flag")


def main():
    try:
        payload = json.load(sys.stdin)
    except Exception:
        return
    phase = sys.argv[1] if len(sys.argv) > 1 else "read"
    try:
        from session_rooms import dept_of_payload
        dept, _ = dept_of_payload(payload)
    except Exception:
        return
    if not dept:
        return

    if phase == "work":
        if payload.get("tool_name") not in WORK_TOOLS:
            return
        if os.path.exists(turn_flag(dept)):
            return                      # このターンでは既に着手を押した
        kinds = "着手"
    elif phase == "end":
        if os.path.exists(turn_flag(dept)):
            try:
                os.remove(turn_flag(dept))   # ターン終了=次のターンのために倒す
            except OSError:
                pass
            return                      # 着手済み=即答は押さない(排他)
        kinds = "即答"
    else:
        kinds = "既読"

    try:
        subprocess.run([sys.executable, REACT_MARK, "--dept", dept, "--kinds", kinds],
                       capture_output=True, timeout=45)
    except Exception:
        return
    if phase == "work":
        try:
            os.makedirs(os.path.dirname(turn_flag(dept)), exist_ok=True)
            open(turn_flag(dept), "w").close()
        except OSError:
            pass


if __name__ == "__main__":
    try:
        main()
    except Exception:
        pass
    sys.exit(0)
