#!/usr/bin/env python3
"""JSONL箱 ⇄ バス の橋渡し (Phase 1 パイロット・人事の箱だけで並走 / 2026-07-18)。

★正本のバスは scripts/queue/leasequeue.py(研究室裁定2026-07-18で一本化)。本アダプタ
  (JSONL箱→バスの移行部品)は bus.py 独自価値として、段階2の統合レビュー時に leasequeue
  側へ移植候補。それまでは検証済みの移行ロジックの参考実装として残置(本番未配線)。

なぜアダプタ方式か:
  本番の鳩(inbox_poller)は全部門が乗る共有インフラ=人事は触らない(改修の領分)。
  鳩はこれまで通り local/inbox/<dept>.jsonl に書き続ける。人事セッションはそのJSONLを
  **バスに取り込んでから**バス経由(claim→complete)で処理する。これにより:
    - 鳩・他部門は無変更(安全・ロールバック可能)
    - 人事の箱が「喪失/二重処理/再武装忘れ」に構造的に守られる最初の部門になる(パイロット)
    - バスの実運用データが貯まり、Phase1本統合(鳩のバス化・全部門展開=改修案件)の判断材料になる

取り込みの安全性:
  箱を os.replace で <box>.ingesting へアトミック退避してから全行をenqueue。
  enqueueは冪等(msg_id主キー)なので、途中でプロセスが落ちても .ingesting が残り、
  次回に再取り込みされて漏れない(取り込み途中の喪失が原理的に起きない)。

使い方:
  from jsonl_adapter import ingest_box
  n_new, n_dup = ingest_box(bus, "local/inbox/hr-room.jsonl", dept="hr-room")
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from bus import Bus  # noqa: E402


def ingest_box(bus, box_path, dept):
    """JSONL箱の中身をバスへ取り込む。戻り値=(新規取り込み件数, 重複で弾いた件数)。

    先に残置の .ingesting があれば(前回の取り込み途中で落ちた分)それを先に処理する。
    """
    total_new = total_dup = 0
    staging = box_path + ".ingesting"

    # 1) 前回の取り込み途中で残った分を先に回収(冪等なので二重取り込みにならない)
    if os.path.exists(staging):
        n, d = _drain_file(bus, staging, dept)
        total_new += n
        total_dup += d

    # 2) 今ある箱をアトミック退避してから取り込む
    if os.path.exists(box_path) and os.path.getsize(box_path) > 0:
        try:
            os.replace(box_path, staging)      # 同一ボリューム内でアトミック(Windows含む)
        except OSError:
            return (total_new, total_dup)
        n, d = _drain_file(bus, staging, dept)
        total_new += n
        total_dup += d
    return (total_new, total_dup)


def _drain_file(bus, path, dept):
    new = dup = 0
    try:
        lines = open(path, "r", encoding="utf-8").read().splitlines()
    except OSError:
        return (0, 0)
    for line in lines:
        line = line.strip()
        if not line:
            continue
        try:
            rec = json.loads(line)
        except ValueError:
            continue
        mid = rec.get("msg_id")
        if not mid:
            continue
        if bus.enqueue(mid, dept, rec.get("channel", ""), rec.get("author", ""),
                       rec.get("content", "")):
            new += 1
        else:
            dup += 1
    os.remove(path)                            # 全行enqueue後に削除(冪等ゆえ途中落ちても漏れない)
    return (new, dup)


def main():
    import argparse
    ap = argparse.ArgumentParser(description="JSONL箱をバスへ取り込む(人事パイロット)")
    ap.add_argument("--db", default="local/bus/bus.db")
    ap.add_argument("--box", required=True)
    ap.add_argument("--dept", required=True)
    args = ap.parse_args()
    bus = Bus(args.db)
    n, d = ingest_box(bus, args.box, args.dept)
    print(f"取り込み: 新規{n}件 / 重複スキップ{d}件 → {args.db}")


if __name__ == "__main__":
    main()
