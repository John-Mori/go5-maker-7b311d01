#!/usr/bin/env python3
"""Gemini(Google AI)にシステム知識付きで質問するCLI。(ask_local.pyのGemini版・トークン節約Chami承認2026-07-14)

使い方:
  python scripts/llm/ask_gemini.py "3導線クリック計測って何?"
  python scripts/llm/ask_gemini.py --model gemini-2.0-flash "デルタの⚠の意味は?"
前提: APIキーを local/gemini_api_key.txt に1行で保存(または環境変数 GEMINI_API_KEY)。
      無料枠なら gemini-2.0-flash / gemini-2.5-flash が実質タダ。知識= ask_localと共通(knowledge.md)。
"""
import json
import os
import sys
import urllib.request
import urllib.error

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.normpath(os.path.join(HERE, "..", ".."))
KNOWLEDGE = os.path.join(ROOT, "local", "llm", "knowledge.md")
KEY_FILE = os.path.join(ROOT, "local", "gemini_api_key.txt")
DEFAULT_MODEL = "gemini-2.0-flash"


def read_key():
    k = os.environ.get("GEMINI_API_KEY", "").strip()
    if k:
        return k
    if os.path.exists(KEY_FILE):
        with open(KEY_FILE, "r", encoding="utf-8") as f:
            return f.read().strip()
    return ""


def load_knowledge():
    if not os.path.exists(KNOWLEDGE):
        import subprocess
        subprocess.run([sys.executable, os.path.join(HERE, "build_knowledge.py")], check=False)
    try:
        with open(KNOWLEDGE, "r", encoding="utf-8") as f:
            return f.read()
    except Exception:
        return ""


def ask(question, model=DEFAULT_MODEL, system_extra=""):
    key = read_key()
    if not key:
        raise RuntimeError("GeminiのAPIキーが未設定です(local/gemini_api_key.txt か 環境変数GEMINI_API_KEY)")
    system = ("あなたはgo5-makerシステムの受付AIです。以下の知識だけを根拠に、日本語で簡潔(1〜4文)に答えてください。"
              "知識に無いことは推測せず「わからないので司令塔(Claude)に回します」と答えます。\n\n=== 知識 ===\n"
              + load_knowledge() + system_extra)
    url = ("https://generativelanguage.googleapis.com/v1beta/models/"
           + model + ":generateContent?key=" + key)
    payload = {
        "system_instruction": {"parts": [{"text": system}]},
        "contents": [{"role": "user", "parts": [{"text": question}]}],
        "generationConfig": {"temperature": 0.3, "maxOutputTokens": 512},
    }
    req = urllib.request.Request(url, data=json.dumps(payload).encode("utf-8"),
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=120) as r:
        d = json.loads(r.read())
    try:
        return d["candidates"][0]["content"]["parts"][0]["text"].strip()
    except Exception:
        # 安全フィルタ等で候補が無い場合
        return ""


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
    try:
        print(ask(q, model))
    except Exception as e:
        print(f"Gemini呼び出し失敗: {e}")
        sys.exit(2)


if __name__ == "__main__":
    main()
