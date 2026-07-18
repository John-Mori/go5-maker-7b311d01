#!/usr/bin/env python3
"""研究室セッションが「自分が研究室だ」と名乗る札を書く (presence hookとの対)。

使い方(研究室の起動手順・1回だけ):
  python scripts/hooks/claim_lab.py <session_id>
  session_idは自分のscratchpadパスのUUID部分
  (例: ...\\D--SougouStartFolder-go5-maker\\46c7212b-...\\scratchpad → 46c7212b-...)。

後から起動した研究室が名乗り直せば札は上書きされる(最新の名乗りが勝つ)。
部門セッションは名乗らないこと(名乗ると研究室の生存を偽装し、無人代打が永久に出なくなる)。
"""
import os
import re
import sys

ROOT = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
LAB_ID_FILE = os.path.join(ROOT, "local", "llm", "lab_session_id.txt")


def main():
    if len(sys.argv) < 2 or not re.fullmatch(r"[0-9a-f-]{8,64}", sys.argv[1]):
        print("usage: claim_lab.py <session_id (UUID)>")
        return 2
    os.makedirs(os.path.dirname(LAB_ID_FILE), exist_ok=True)
    with open(LAB_ID_FILE, "w", encoding="utf-8") as f:
        f.write(sys.argv[1] + "\n")
    print(f"研究室の札を更新: {sys.argv[1]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
