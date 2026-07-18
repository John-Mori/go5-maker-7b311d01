#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""所有権黒板 (恒久-6・2026-07-18) — 並行セッションの重複実装とgit衝突を防ぐ最小の共有黒板。

なぜ作るか (実証済みの痛み):
  2026-07-18、同じ日に4つの部門が同じOSS調査・同じ恒久対策設計書を並行で作り、
  受信キュー(恒久-4)は研究室が実装済みなのに改修αが再実装しかけた。競合監視も、
  αがUIを実装した後にβが設計済みと判明した(今週の重複)。原因は一つ:
  **「誰が何に着手しているか」を着手前に見る場所が無い**こと。crewAI/MetaGPTが
  hierarchical process / shared memory で解いているのと同じ問題を、新ツール無しで
  最小再現する: 1つのJSONL + 「着手前にcheck、着手時にclaim」の規約。

設計:
  ・保存 = local/ownership.jsonl (追記専用・同一PCの全セッションが共有するファイルシステム上)。
    重複は「同一PC上の並行セッション間」で起きるので、ネット不要のローカルファイルが最速で十分。
  ・各行 = 1イベント {ts, topic, owner, status, doc, note}。あるtopicの"現在"は最新イベント。
  ・status = claimed(着手中) / blocked / done(解放)。done は所有を手放した状態。

使い方 (着手フロー):
  python scripts/ownership.py check "競合 監視"          # 着手前に必ず: 誰かが持ってないか(部分一致)
  python scripts/ownership.py claim competitor-monitoring --owner system-engineer-b --doc "docs/..." --note "GAS実装"
  python scripts/ownership.py list                        # 生きてる所有(claimed/blocked)の一覧
  python scripts/ownership.py release competitor-monitoring --owner system-engineer-b
  python scripts/ownership.py status kuma-monitor blocked --owner system-engineer --note "Chami裁定待ち"

終了コード: check は「空き=0 / 誰かが所有=2」。claim は他人が所有中なら警告して 2 で止まる(--force で上書き)。
依存ゼロ (標準ライブラリのみ)・utf-8。※本ファイルは.ps1ではないので日本語可(ASCII縛りはps1のみ)。
"""
import argparse
import json
import os
import sys
import time

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.normpath(os.path.join(HERE, ".."))
BOARD = os.path.join(ROOT, "local", "ownership.jsonl")

ACTIVE = ("claimed", "blocked")


def _now():
    return time.strftime("%Y-%m-%dT%H:%M:%S")


def _norm(s):
    return "".join(ch for ch in str(s or "").lower() if ch.isalnum())


def _load():
    """topic -> 最新イベント の辞書(現在状態)。"""
    cur = {}
    if not os.path.exists(BOARD):
        return cur
    with open(BOARD, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                r = json.loads(line)
            except Exception:
                continue
            t = r.get("topic")
            if t:
                cur[t] = r  # 追記順=時系列なので後勝ち=最新
    return cur


def _append(rec):
    os.makedirs(os.path.dirname(BOARD), exist_ok=True)
    with open(BOARD, "a", encoding="utf-8") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")


def _match(cur, query):
    """query(topic名 or キーワード)に一致する現在イベントを返す(部分一致・正規化)。"""
    q = _norm(query)
    hits = []
    for t, r in cur.items():
        hay = _norm(t) + _norm(r.get("note", "")) + _norm(r.get("doc", ""))
        if q and q in hay:
            hits.append(r)
    return hits


def cmd_check(a):
    cur = _load()
    hits = [r for r in _match(cur, a.topic) if r.get("status") in ACTIVE]
    if not hits:
        print(f"空き: '{a.topic}' に一致する着手中の所有はありません。claim して着手してよいです。")
        return 0
    print(f"⚠ '{a.topic}' に一致する着手中の所有が {len(hits)} 件あります:")
    for r in hits:
        print(f"  - [{r.get('status')}] {r.get('topic')} / owner={r.get('owner')} / {r.get('doc','')} / {r.get('note','')} ({r.get('ts')})")
    print("→ 同じものなら着手せず所有者と調整。別物なら別のtopic名でclaimを。")
    return 2


def cmd_claim(a):
    cur = _load()
    ex = cur.get(a.topic)
    # 別人が着手中の同一topicは事故。--force が無ければ止める。
    if ex and ex.get("status") in ACTIVE and ex.get("owner") != a.owner and not a.force:
        print(f"⚠ '{a.topic}' は既に {ex.get('owner')} が {ex.get('status')} 中です({ex.get('ts')})。")
        print(f"   note={ex.get('note','')} doc={ex.get('doc','')}")
        print("   同じ作業なら着手しない。どうしても取る場合は --force。別作業なら別名でclaim。")
        return 2
    # 近い名前の別topicが生きていれば注意喚起(重複の芽)
    near = [r for r in _match(cur, a.topic) if r.get("status") in ACTIVE and r.get("topic") != a.topic]
    if near:
        print(f"※ 参考: 名前が近い着手中の所有が {len(near)} 件あります(別物か確認を):")
        for r in near:
            print(f"    - {r.get('topic')} / {r.get('owner')} / {r.get('note','')}")
    _append({"ts": _now(), "topic": a.topic, "owner": a.owner, "status": "claimed",
             "doc": a.doc or "", "note": a.note or ""})
    print(f"claimed: '{a.topic}' → {a.owner}")
    return 0


def cmd_release(a):
    cur = _load()
    ex = cur.get(a.topic)
    if not ex:
        print(f"'{a.topic}' は黒板にありません。")
        return 1
    _append({"ts": _now(), "topic": a.topic, "owner": a.owner or ex.get("owner", ""),
             "status": "done", "doc": ex.get("doc", ""), "note": a.note or ex.get("note", "")})
    print(f"released(done): '{a.topic}'")
    return 0


def cmd_status(a):
    cur = _load()
    ex = cur.get(a.topic)
    _append({"ts": _now(), "topic": a.topic, "owner": a.owner or (ex.get("owner", "") if ex else ""),
             "status": a.status, "doc": (ex.get("doc", "") if ex else ""), "note": a.note or (ex.get("note", "") if ex else "")})
    print(f"status: '{a.topic}' → {a.status}")
    return 0


def cmd_list(a):
    cur = _load()
    rows = sorted(cur.values(), key=lambda r: r.get("ts", ""))
    if a.all:
        show = rows
    else:
        show = [r for r in rows if r.get("status") in ACTIVE]
    if not show:
        print("(着手中の所有はありません)" if not a.all else "(黒板は空です)")
        return 0
    for r in show:
        print(f"[{r.get('status'):8}] {r.get('topic'):32} owner={r.get('owner','?'):20} {r.get('doc','')}  {r.get('note','')}")
    return 0


def main():
    p = argparse.ArgumentParser(description="所有権黒板(恒久-6)")
    sub = p.add_subparsers(dest="cmd", required=True)

    pc = sub.add_parser("check", help="着手前に: そのtopicを誰かが持ってないか(部分一致)")
    pc.add_argument("topic")
    pc.set_defaults(fn=cmd_check)

    pcl = sub.add_parser("claim", help="着手時に: 所有を宣言")
    pcl.add_argument("topic")
    pcl.add_argument("--owner", required=True)
    pcl.add_argument("--doc", default="")
    pcl.add_argument("--note", default="")
    pcl.add_argument("--force", action="store_true")
    pcl.set_defaults(fn=cmd_claim)

    pr = sub.add_parser("release", help="完了時に: 所有を手放す(done)")
    pr.add_argument("topic")
    pr.add_argument("--owner", default="")
    pr.add_argument("--note", default="")
    pr.set_defaults(fn=cmd_release)

    ps = sub.add_parser("status", help="状態変更(claimed/blocked/done)")
    ps.add_argument("topic")
    ps.add_argument("status", choices=["claimed", "blocked", "done"])
    ps.add_argument("--owner", default="")
    ps.add_argument("--note", default="")
    ps.set_defaults(fn=cmd_status)

    pl = sub.add_parser("list", help="所有一覧(既定=着手中のみ / --all=全部)")
    pl.add_argument("--all", action="store_true")
    pl.set_defaults(fn=cmd_list)

    a = p.parse_args()
    sys.exit(a.fn(a))


if __name__ == "__main__":
    main()
