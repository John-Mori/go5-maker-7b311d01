#!/usr/bin/env python3
"""Chami発言コーパスの生成(L1・改善設計書§4.1)。

処理済み台帳(新旧2本)から Chami の発言を msg_id で重複排除して
local/corpus/chami.jsonl へ**追記のみ**で集約する。知識パック(build_knowledge.py)と
将来の分析・Notion窓は、台帳ではなくこのコーパスを読む。

なぜ台帳を直接読まないか:
- 台帳が2本に割れている(discord_processed.jsonl=現役 / discord_inbox_processed.jsonl=7/15停止)。
  build_knowledge.py は旧台帳だけを見ていたため、部門制移行後のChami発言が学習に入っていなかった。
- 台帳は「処理したかの控え」で、同じmsg_idが2件入りうる(INC-87で実証)。コーパス側で1発言1行に正す。
- 台帳は将来アーカイブへ退ける(設計書§7)。コーパスが残れば過去の発言は失われない。

追記のみ = 台帳側を一切変更しない(読むだけ)。何度実行しても結果は同じ(冪等)。
使い方: python scripts/llm/build_corpus.py
"""
import io
import json
import os
import re
import sys

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.normpath(os.path.join(HERE, "..", ".."))
LEDGERS = [
    os.path.join(ROOT, "local", "discord_processed.jsonl"),          # 現役
    os.path.join(ROOT, "local", "discord_inbox_processed.jsonl"),    # 旧(2026-07-15で停止)
]
OUT = os.path.join(ROOT, "local", "corpus", "chami.jsonl")

# ★許可リスト方式(denylistではない)。ここに無い部屋は既定で sensitive=True。
# 理由: 機微部屋の一覧が inbox_poller / gemini_responder / local_responder の3箇所で
# 食い違っていた(2026-07-17実測。future-roomはlocal_responderしか守っていない)。
# 同じ一覧を写すと必ずドリフトし、いつか機微が外へ出る。このプロジェクトは同じ穴を
# INC-62で踏んでおり、恒久対策は許可リスト方式(CLAUDE.md「クラウド同期は許可リスト方式=
# 新キーは既定で同期しない」)。新設の部屋は黙って除外される側に倒す。
WORK_DEPTS = frozenset({
    "research-room", "system-engineer", "system-engineer-b", "learning-coach",
    "kaizen-analyst", "report-notify", "incident", "ai-office", "product-scout",
    "llm-qa", "llm-growth", "gemini", "router", "meeting-a", "qa-reviewer",
    "data-org", "imagegen", "copy-director", "shorts-analyst",
})


_ISO = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}")


def ts_key(ts):
    """並べ替え用のキー。ISO形式でないtsは「最古」に倒す。

    台帳には ts='t' の行が実在する(接続テストの残骸・2026-07-17実測)。素の文字列比較だと
    't' > '2' で**テストの残骸が最新扱いになり、知識パックの「最近の発言」を占領する**。
    生のtsは truth として残し、順序だけを守る。
    """
    return ts if _ISO.match(ts or "") else ""


def is_sensitive(dept):
    """機微か。許可リストに無いものは全て機微扱い(既定で外に出さない)。

    この印が効くのは外部送出(Notion窓)の可否。知識パックは機微も含める
    (Chami明示2026-07-13「プライバシーとかいいよ」・local内で完結し外部送信なし)。
    """
    return (dept or "") not in WORK_DEPTS


def load_existing_ids():
    if not os.path.exists(OUT):
        return set()
    ids = set()
    with io.open(OUT, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                ids.add(json.loads(line)["msg_id"])
            except Exception:
                continue
    return ids


def read_ledgers():
    """新旧台帳を読み、msg_id単位で1件に正す。先に見たものを採用(内容は同一)。"""
    rows = {}
    for p in LEDGERS:
        if not os.path.exists(p):
            print(f"warn: 台帳が無い {os.path.relpath(p, ROOT)}")
            continue
        with io.open(p, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    d = json.loads(line)
                except Exception:
                    continue
                mid = d.get("msg_id")
                content = (d.get("content") or "").strip()
                if not mid or not content:
                    continue
                if mid in rows:
                    continue
                rows[mid] = {
                    "ts": d.get("ts") or "",
                    "msg_id": mid,
                    "source": "discord",
                    "author": d.get("author") or "",
                    "channel": d.get("channel") or "",
                    "dept": d.get("dept") or "",
                    "content": content,
                    "reply_to": d.get("reply_to") or None,
                    "sensitive": is_sensitive(d.get("dept")),
                }
    return rows


def main():
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    known = load_existing_ids()
    rows = read_ledgers()
    fresh = [r for mid, r in rows.items() if mid not in known]
    fresh.sort(key=lambda r: (ts_key(r["ts"]), r["msg_id"]))
    if fresh:
        with io.open(OUT, "a", encoding="utf-8") as f:
            for r in fresh:
                f.write(json.dumps(r, ensure_ascii=False) + "\n")
    total = len(known) + len(fresh)
    sens = sum(1 for r in fresh if r["sensitive"])
    print(f"コーパス追記 {len(fresh)}件 (うち機微 {sens}件) / 累計 {total}件 → {os.path.relpath(OUT, ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
