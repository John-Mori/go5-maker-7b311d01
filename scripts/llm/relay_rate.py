#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""回送レート計 = どの部屋が、どれだけ他室へ回しているかを request_log.jsonl の実測で出す。

なぜ在るか= 2026-08-02 Chami「すぐ他に回そうとする癖があるな…構造的な問題だよこれは」
(DEF-hq-2c62407ee9)の恒久側。同じ叱責が 2026-09-16 に再発した(「回しすぎ」)=
規律の文言(共通規律§3.8)だけでは止まらなかった、ということ。心がけに任せず数える。

読むだけ。何も書かない。何も送らない。

  python scripts/llm/relay_rate.py                 # 全部屋・直近24時間と14日
  python scripts/llm/relay_rate.py --dept local-lab
  python scripts/llm/relay_rate.py --hours 24 --json

★この値を各部屋の起動文へ自動で載せる口(dept_daemon/session_relay)は**基盤**=
  イージス研究室 / プラットフォームSEの職責。ここは数える側だけを持つ。
"""
import argparse
import collections
import datetime
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
LOG = os.path.join(ROOT, "local", "llm", "request_log.jsonl")


def _sender(request_id):
    """'ESC-local-lab-DISPATCH-local-lab-1549786371537899664' → 'local-lab'。

    回送便の request_id は ESC-<送り元>-<msg_id> だが、dispatch を経由したものは
    間に '-DISPATCH-<送り元>' が挟まる。末尾の数字IDを落としてから、その節を剥がす。
    """
    body = request_id[4:]                     # 'ESC-' を落とす
    head = body.rsplit("-", 1)[0]             # 末尾の msg_id を落とす
    cut = head.find("-DISPATCH-")
    return head[:cut] if cut > 0 else head


def load(path=LOG):
    """ESC便(=他室へ回された便)を request_id ごとに1件へ畳んで返す。"""
    if not os.path.exists(path):
        return []
    rows = {}
    with open(path, "rb") as f:
        for raw in f.read().decode("utf-8").splitlines():
            try:
                d = json.loads(raw)
            except Exception:
                continue                      # 壊れた行は数から落とす(数えたと言わない)
            rid = d.get("request_id", "")
            if not rid.startswith("ESC-") or rid in rows:
                continue                      # 同じ便の state 遷移は1件として数える
            rows[rid] = (_sender(rid), d.get("dept", "?"), d.get("ts", ""))
    return sorted(rows.values(), key=lambda r: r[2])


def since(rows, hours):
    edge = (datetime.datetime.now() - datetime.timedelta(hours=hours)).strftime("%Y-%m-%dT%H:%M:%S")
    return [r for r in rows if r[2] >= edge]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dept", help="この部屋だけを見る(スラッグ)")
    ap.add_argument("--hours", type=int, default=24)
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args()
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    rows = load()
    win = since(rows, a.hours)
    long = since(rows, 24 * 14)
    by_room = collections.Counter(s for s, _, _ in win)

    if a.dept:
        n = by_room.get(a.dept, 0)
        share = (100.0 * n / len(win)) if win else 0.0
        out = {"dept": a.dept, "hours": a.hours, "count": n,
               "total_all_rooms": len(win), "share_pct": round(share, 1),
               "count_14d": sum(1 for s, _, _ in long if s == a.dept),
               "to": dict(collections.Counter(t for s, t, _ in win if s == a.dept))}
        print(json.dumps(out, ensure_ascii=False) if a.json
              else f"{a.dept}: 直近{a.hours}時間で {n} 件を他室へ回した"
                   f"(全部屋合計 {len(win)} 件の {share:.0f}%)/ 直近14日 {out['count_14d']} 件"
                   + ("\n  宛先= " + ", ".join(f"{k} {v}件" for k, v in out["to"].items()) if out["to"] else ""))
        return

    if a.json:
        print(json.dumps({"hours": a.hours, "total": len(win),
                          "by_room": dict(by_room)}, ensure_ascii=False))
        return
    print(f"回送便(ESC) 直近{a.hours}時間= {len(win)} 件 / 直近14日= {len(long)} 件")
    for room, n in by_room.most_common():
        to = collections.Counter(t for s, t, _ in win if s == room)
        print(f"  {n:4d}  {room} → " + ", ".join(f"{k}({v})" for k, v in to.most_common()))
    if not win:
        print("  (この窓では0件)")


if __name__ == "__main__":
    main()
