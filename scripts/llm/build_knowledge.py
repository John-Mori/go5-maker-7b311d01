#!/usr/bin/env python3
"""ローカルLLM用の知識パック生成。

system-brief.md(正本)+ペルソナ台帳を結合して local/llm/knowledge.md を作る。
構成変更時に再実行すれば受付係の知識が更新される(モデル再作成は不要=毎回システムプロンプトとして注入)。
使い方: python scripts/llm/build_knowledge.py
"""
import os
import sys

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.normpath(os.path.join(HERE, "..", ".."))
OUT_DIR = os.path.join(ROOT, "local", "llm")
SOURCES = [
    os.path.join(ROOT, "docs", "departments", "00_common", "system-brief.md"),
    os.path.join(ROOT, "docs", "departments", "personas", "INDEX.md"),
]


def main():
    os.makedirs(OUT_DIR, exist_ok=True)
    parts = []
    for p in SOURCES:
        if os.path.exists(p):
            with open(p, "r", encoding="utf-8") as f:
                parts.append(f"<!-- source: {os.path.relpath(p, ROOT)} -->\n" + f.read().strip())
        else:
            print(f"warn: 見つからない {p}")
    body = "\n\n---\n\n".join(parts)
    out = os.path.join(OUT_DIR, "knowledge.md")
    with open(out, "w", encoding="utf-8") as f:
        f.write(body + "\n")
    print(f"生成OK: {out} ({len(body)}文字)")


if __name__ == "__main__":
    main()
