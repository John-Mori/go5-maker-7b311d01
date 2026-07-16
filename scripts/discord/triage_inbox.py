"""main箱の未処理を仕分ける(研究室の転送前チェック)。

なぜ要るか:
  sweepが部門箱をmainへ回収すると、**部門が既に処理した控えまでmainへ落ちてくる**。
  研究室がそれを「未処理」と見て部門へ転送すると、部門は二度手間になり、
  最悪Chamiへ同じ返信が2回届く(2026-07-16に実際に発生=改修α2件・データ整理7件・人事2件)。
  「main箱に在る」は「未処理」を意味しない。**転送・応答の前に必ず処理済み台帳を引く。**

使い方:
  python scripts/discord/triage_inbox.py           # 仕分け表示のみ(既定・安全)
  python scripts/discord/triage_inbox.py --drop    # 処理済み済みの行をmain箱から除去(processedへは追記しない=二重記録を作らない)

出力: 各行を [処理済み] / [未処理] に分類し、dept別に集計する。
"""
import io
import json
import os
import sys

# Windowsの既定コンソール(cp932)は絵文字を出せず、printでUnicodeEncodeErrorになる。
# 仕分け結果に絵文字入りの本文が来ると落ちるので、出力を必ずUTF-8へ寄せる。
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

ROOT = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
LOCAL = os.path.join(ROOT, "local")
INBOX = os.path.join(LOCAL, "discord_inbox.jsonl")
PROCESSED = os.path.join(LOCAL, "discord_processed.jsonl")


def processed_ids():
    """処理済み台帳のmsg_idを集める。壊れた行は黙って飛ばす(台帳は複数セッションが追記する)。"""
    ids = set()
    if not os.path.exists(PROCESSED):
        return ids
    for line in io.open(PROCESSED, encoding="utf-8", errors="replace"):
        line = line.strip()
        if not line:
            continue
        try:
            mid = json.loads(line).get("msg_id")
            if mid:
                ids.add(str(mid))
        except Exception:
            continue
    return ids


def main() -> int:
    drop = "--drop" in sys.argv
    if not os.path.exists(INBOX) or os.path.getsize(INBOX) == 0:
        print("main箱: 空")
        return 0
    done = processed_ids()
    lines = [l for l in io.open(INBOX, encoding="utf-8").read().splitlines() if l.strip()]
    keep, already = [], []
    for l in lines:
        try:
            r = json.loads(l)
        except Exception:
            keep.append(l)
            continue
        mid = str(r.get("msg_id", ""))
        (already if mid in done else keep).append(l)
        mark = "処理済み" if mid in done else "未処理  "
        print(f"[{mark}] {r.get('ts','')[5:16]} {r.get('dept','?'):18} {(r.get('content','') or '(添付)')[:44]}")
    print(f"\n合計 {len(lines)} 件 = 未処理 {len(keep)} / 既に部門が処理済み {len(already)}")
    if already and not drop:
        print("→ 処理済みの行は転送・応答しないこと(--drop で main箱から除去できる)")
    if drop and already:
        with io.open(INBOX, "w", encoding="utf-8") as f:
            for l in keep:
                f.write(l + "\n")
        print(f"→ 処理済み {len(already)} 件をmain箱から除去した(processedへは追記しない=二重記録を作らない)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
