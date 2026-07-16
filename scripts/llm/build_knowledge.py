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
    os.path.join(ROOT, "docs", "departments", "00_common", "faq_knowledge.md"),
    os.path.join(ROOT, "docs", "departments", "personas", "INDEX.md"),
]


CORPUS = os.path.join(ROOT, "local", "corpus", "chami.jsonl")
LESSONS = os.path.join(ROOT, "local", "llm", "lessons.jsonl")
MAX_CHARS = 40000  # 知識パックの上限。超えたら直近発言から間引く(教訓は削らない)

# 知識パックは機微も含める(Chami明示2026-07-13「プライバシーとかいいよ」・local内で完結し
# 外部送信なし)。機微の印(corpusのsensitive)が効くのはNotion等への外部送出のみ。


def _load_corpus():
    """発言コーパス(local/corpus/chami.jsonl)を読む。無ければ build_corpus.py を自動実行。

    旧実装は local/discord_inbox_processed.jsonl(2026-07-15で更新停止)を直接読んでいたため、
    **部門制移行後のChami発言が1件も学習に入っていなかった**。コーパスは新旧台帳を
    msg_id重複排除で統合したものなので、この穴が構造的に塞がる。
    """
    import json
    import subprocess
    # 「無ければ生成」ではなく**毎回更新**する。今回直した穴の正体は
    # 「知識が古い元データから作られていた」ことなので、生成の度に元を最新化して再発を断つ。
    # build_corpus.py は追記のみ・冪等なので何度呼んでも安全(494件で一瞬)。
    subprocess.run([sys.executable, os.path.join(HERE, "build_corpus.py")], check=False)
    if not os.path.exists(CORPUS):
        return []
    rows = []
    with open(CORPUS, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                rows.append(json.loads(line))
            except Exception:
                continue
    return rows


def recent_conversation(limit=40):
    """コーパスからChamiの直近発言を記憶として抽出。コーパスは時系列順(壊れたtsは最古扱い)。"""
    rows = _load_corpus()[-limit:]
    if not rows:
        return ""
    lines = [f"[{(r.get('ts') or '')[:10]} {r.get('channel','')}] {r.get('content','')[:160]}" for r in rows]
    return ("## 40_recent Chamiとの最近のやりとり(コーパスから自動抽出・日次更新)\n"
            "以下はChamiがDiscordで実際に話した内容の抜粋。文脈理解と「前に言ってたあれ」への応答に使う。\n- "
            + "\n- ".join(lines))


def lessons_section(limit=20):
    """採点済みの誤答を教訓として焼き込む(L2・設計書§4.2)。

    qwenは説明より事例で効く。「質問→誤答→正しい答え→なぜ間違えたか」を1件ずつ見せる。
    lessons.jsonl が無い間は何も出さない(L2未着手でも壊れない)。
    """
    import json
    if not os.path.exists(LESSONS):
        return ""
    rows = []
    with open(LESSONS, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                d = json.loads(line)
            except Exception:
                continue
            if d.get("verdict") != "bad" or not d.get("correction"):
                continue
            rows.append(d)
    rows = rows[-limit:]
    if not rows:
        return ""
    items = []
    for d in rows:
        items.append(
            f"- 質問: {(d.get('q') or '')[:120]}\n"
            f"  - 誤答(繰り返さない): {(d.get('a') or '')[:120]}\n"
            f"  - 正しい答え: {(d.get('correction') or '')[:160]}\n"
            f"  - なぜ間違えたか: {(d.get('why') or '')[:120]}"
        )
    return ("## 30_lessons 過去に間違えた事例(最優先で守る)\n"
            "同じ質問が来たら「正しい答え」を答える。「誤答」は二度と言わない。\n"
            + "\n".join(items))


def main():
    os.makedirs(OUT_DIR, exist_ok=True)
    parts = []
    for p in SOURCES:
        if os.path.exists(p):
            with open(p, "r", encoding="utf-8") as f:
                parts.append(f"<!-- source: {os.path.relpath(p, ROOT)} -->\n" + f.read().strip())
        else:
            print(f"warn: 見つからない {p}")

    # 層の順序(設計書§4.3): 固定知識 → 教訓 → 直近発言。
    # 教訓を直近発言より前に置くのは、後ろほど埋もれるから(=守ってほしい規則を先に見せる)。
    lessons = lessons_section()
    if lessons:
        parts.append(lessons)

    limit = 40
    body = ""
    while True:
        chunks = list(parts)
        conv = recent_conversation(limit)
        if conv:
            chunks.append(conv)
        body = "\n\n---\n\n".join(chunks)
        # 上限超過は直近発言から間引く。教訓と固定知識は削らない(=質の順に捨てる)。
        if len(body) <= MAX_CHARS or limit <= 5:
            break
        limit -= 5

    out = os.path.join(OUT_DIR, "knowledge.md")
    with open(out, "w", encoding="utf-8") as f:
        f.write(body + "\n")
    n_less = lessons.count("- 質問:") if lessons else 0
    print(f"生成OK: {out} ({len(body)}文字 / 直近発言{limit}件 / 教訓{n_less}件)")


if __name__ == "__main__":
    main()
