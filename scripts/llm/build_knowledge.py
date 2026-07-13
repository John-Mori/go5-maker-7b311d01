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


SENSITIVE_DEPTS = ("dream-care", "past-room")  # 機微部屋は学習対象から恒久除外


def recent_conversation(limit=40):
    """Discordの処理済みログからChamiの直近発言を記憶として抽出(機微部屋は除外)。Phase1学習(2026-07-13)。"""
    import json
    p = os.path.join(ROOT, "local", "discord_inbox_processed.jsonl")
    if not os.path.exists(p):
        return ""
    rows = []
    for line in open(p, encoding="utf-8"):
        try:
            d = json.loads(line)
        except Exception:
            continue
        if d.get("dept") in SENSITIVE_DEPTS or not (d.get("content") or "").strip():
            continue
        rows.append(f"[{(d.get('ts') or '')[:10]} {d.get('channel','')}] {d['content'][:160]}")
    rows = rows[-limit:]
    if not rows:
        return ""
    return ("## 7. Chamiとの最近のやりとり(自動抽出の記憶・機微部屋除外)\n"
            "以下はChamiがDiscordで実際に話した内容の抜粋。文脈理解と「前に言ってたあれ」への応答に使う。\n- "
            + "\n- ".join(rows))


def main():
    os.makedirs(OUT_DIR, exist_ok=True)
    parts = []
    for p in SOURCES:
        if os.path.exists(p):
            with open(p, "r", encoding="utf-8") as f:
                parts.append(f"<!-- source: {os.path.relpath(p, ROOT)} -->\n" + f.read().strip())
        else:
            print(f"warn: 見つからない {p}")
    conv = recent_conversation()
    if conv:
        parts.append(conv)
    body = "\n\n---\n\n".join(parts)
    out = os.path.join(OUT_DIR, "knowledge.md")
    with open(out, "w", encoding="utf-8") as f:
        f.write(body + "\n")
    print(f"生成OK: {out} ({len(body)}文字)")


if __name__ == "__main__":
    main()
