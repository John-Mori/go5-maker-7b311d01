#!/usr/bin/env python3
"""ローカルLLM(Ollama)にシステム知識付きで質問するCLI。

使い方:
  python scripts/llm/ask_local.py "3導線クリック計測って何?"
  python scripts/llm/ask_local.py --model qwen3:8b "デルタの⚠の意味は?"
前提: Ollamaが起動中(http://localhost:11434)。知識= local/llm/knowledge.md(無ければ build_knowledge.py を自動実行)。
"""
import json
import os
import subprocess
import sys
import urllib.request

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.normpath(os.path.join(HERE, "..", ".."))
KNOWLEDGE = os.path.join(ROOT, "local", "llm", "knowledge.md")
DEFAULT_MODEL = "qwen3:4b"


def load_knowledge():
    if not os.path.exists(KNOWLEDGE):
        subprocess.run([sys.executable, os.path.join(HERE, "build_knowledge.py")], check=False)
    with open(KNOWLEDGE, "r", encoding="utf-8") as f:
        return f.read()


def ask(question, model=DEFAULT_MODEL, system_extra=""):
    system = ("あなたはgo5-makerシステムの「ローカルqwen」です。以下の知識だけを根拠に、日本語で簡潔(1〜4文)に答えてください。"
              "知識に無いことは推測せず「わからないので司令塔(Claude)に回します」と答えます。"
              # ★なりすまし厳禁(Chami指摘2026-07-14「アメスのフリしてビビった」)。他人格を名乗るとChamiが混乱する。
              "重要: あなたは絶対に自分以外の人格(アメス/アロンソ/デブライネ/咲季/コーチ/先生 等)を名乗ってはいけません。"
              "「アメスです」等と自称せず、常に自分が『ローカルqwen』であると述べます。"
              "他人格を呼ぶ発言(例『アメス！』)には、あなたが代わりに演じず『それは司令塔(Claude)側の◯◯に回します』と述べるだけにします。/no_think\n\n=== 知識 ===\n"
              + load_knowledge() + system_extra)
    payload = {"model": model, "stream": False, "think": False,
               "messages": [{"role": "system", "content": system},
                            {"role": "user", "content": question}],
               "options": {"temperature": 0.3, "num_ctx": 8192}}
    req = urllib.request.Request("http://localhost:11434/api/chat",
                                 data=json.dumps(payload).encode("utf-8"),
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=300) as r:
        d = json.loads(r.read())
    msg = (d.get("message") or {}).get("content", "")
    # qwen3のthinkingブロックが残った場合は除去
    if "</think>" in msg:
        msg = msg.split("</think>", 1)[1]
    return msg.strip()


def main():
    args = sys.argv[1:]
    model = DEFAULT_MODEL
    if args and args[0] == "--model" and len(args) >= 2:
        model = args[1]
        args = args[2:]
    q = " ".join(args) if args else sys.stdin.read().strip()
    if not q:
        print("質問が空です。")
        sys.exit(1)
    print(ask(q, model))


if __name__ == "__main__":
    main()
