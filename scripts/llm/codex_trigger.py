# -*- coding: utf-8 -*-
"""codex_trigger — Codex名指し検知(純関数)。behop_trigger.py のCodex版 (2026-09-05 platform-se)。

なぜ切り出すか= 検知ロジックを codex_responder.py から分けると、Discord接続なしで検査できる。
Codex専用部屋(dept=='codex')では responder が全発言を受けるが、将来 他部屋から名指しで
Codexへ回す時にこの判定を使う(べホップと同じ設計)。
"""
import os

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.normpath(os.path.join(HERE, "..", ".."))
LOCAL = os.environ.get("GO5_LOCAL_DIR") or os.path.join(ROOT, "local")
BOT_ID_FILE = os.path.join(LOCAL, "discord_codex_bot_id.txt")   # 任意(あればメンションでも拾う)

# 呼び名(仮)。正式な人格名・呼称は人事部門(hr-room)が決める= ここは検知トークンのみ。
TOKENS = ("codex", "コーデックス", "コーデクス")


def _mention_ids():
    try:
        return {open(BOT_ID_FILE, encoding="utf-8").read().strip()}
    except OSError:
        return set()


def is_codex_mentioned(content):
    """本文に Codex への名指し(名前 or メンション)が含まれるか。"""
    c = (content or "").lower()
    if any(t.lower() in c for t in TOKENS):
        return True
    for bid in _mention_ids():
        if bid and (f"<@{bid}>" in content or f"<@!{bid}>" in content):
            return True
    return False
