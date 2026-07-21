#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""read_notes — セッション宛ての写し(session-note)を読み、読了として箱から外す。

★2026-07-21 ORG-29で新設。
  ORG-24でデーモンの応答をセッションの箱へ写すようにしたが、**読了の概念が無かった**ため、
  同じ写しでwaiterが何度も鳴り、セッションは毎回同じものを読み直していた(実測3回)。
  「読んだら消す」を手順(心がけ)にすると必ず忘れる——今日それを何度も証明した。
  → **読むことと消すことを1つの道具にまとめる**。読めば必ず消える。消し忘れが原理的に起きない。

使い方:
  python scripts/llm/read_notes.py --dept hq            # 読んで読了にする
  python scripts/llm/read_notes.py --dept hq --peek     # 読むだけ(消さない)

★安全: 読了分は捨てずに `local/_work/session_notes_<dept>.jsonl` へ退避する
  (RULES「削除しない、退避する」)。後から追える。
"""
import argparse
import json
import os
import sys

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.normpath(os.path.join(HERE, "..", ".."))
LOCAL = os.path.join(ROOT, "local")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dept", required=True)
    ap.add_argument("--peek", action="store_true", help="読むだけで読了にしない")
    a = ap.parse_args()

    box = os.path.join(LOCAL, "inbox", f"{a.dept}.jsonl")
    if not os.path.exists(box) or os.path.getsize(box) == 0:
        print(f"[{a.dept}] 写しなし")
        return 0

    lines = [l for l in open(box, encoding="utf-8", errors="replace").read().splitlines() if l.strip()]
    notes, others = [], []
    for l in lines:
        try:
            r = json.loads(l)
        except Exception:
            others.append(l)          # 壊れた行は触らず残す(捨てない)
            continue
        (notes if r.get("type") in ("session-note", "followup") else others).append(l)

    if not notes:
        print(f"[{a.dept}] 写しなし(他の便 {len(others)}件は残置)")
        return 0

    for l in notes:
        r = json.loads(l)
        print(f"--- {r.get('type')} msg={r.get('msg_id')} ---")
        print(f"【Chami】{(r.get('content') or '')[:600]}")
        rep = r.get("daemon_reply")
        if rep:
            print(f"【{r.get('note','') or 'デーモン'}】")
            print(f"{rep[:900]}")
        print()

    if a.peek:
        print(f"[{a.dept}] --peek のため箱はそのまま({len(notes)}件)")
        return 0

    # 読了: 退避してから箱を「写し以外」だけにする
    arch = os.path.join(LOCAL, "_work", f"session_notes_{a.dept}.jsonl")
    try:
        os.makedirs(os.path.dirname(arch), exist_ok=True)
        with open(arch, "a", encoding="utf-8") as f:
            for l in notes:
                f.write(l + "\n")
    except OSError:
        print("★退避に失敗したので箱はそのままにする(消さない)")
        return 1
    with open(box, "w", encoding="utf-8") as f:
        for l in others:
            f.write(l + "\n")
    print(f"[{a.dept}] 写し{len(notes)}件を読了(退避先: {os.path.relpath(arch, ROOT)})"
          + (f" / 他の便{len(others)}件は残置" if others else ""))
    return 0


if __name__ == "__main__":
    sys.exit(main())
