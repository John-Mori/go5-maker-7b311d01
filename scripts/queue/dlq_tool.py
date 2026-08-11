# -*- coding: utf-8 -*-
"""デッドレター(status='dead')を人が読んで片付けるための道具。

なぜ要るか(2026-08-12 イージス研究室):
  配送に5回失敗した便は status='dead' へ隔離される。ところが警報側(absence_watchdog の
  check_dead_letters)は**件数の増分**でしか鳴らなかったので、一度基準が追いつくと
  その滞留は永久に見えなくなる。実測= Chami本人の便3通が2026-07-30から**13日間**
  誰にも読まれず、誰にも警報されずに残っていた(うち1通は「この部屋、応答できる?」)。
  → 滞留そのものを見る警報(check_stale_dead)を足した。**その警報を止める手段がこれ**。
     ★足した機構の運用も機構にする(共通規律§3)= 鳴らしっぱなしにできる警報は無視される。

使い方:
  python scripts/queue/dlq_tool.py --list                 # 手当て待ちの一覧(既済も含めるなら --all)
  python scripts/queue/dlq_tool.py --show 1099            # 1件の全文
  python scripts/queue/dlq_tool.py --ack 1099 --by "ケヴィン・デ・ブライネ" --note "改修αへ回した"

★--ack は status を動かさない(dead のまま)。result 列へ手当ての印を書くだけ=
  既存の dead 件数・台帳としての過去を書き換えない(共通規律§4「台帳は追記」)。
★再配送はここでやらない。読んだ人が **dispatch.py で正しい部屋へ出し直す**のが正。
  13日前の便を機械が黙って生き返らせると、受け取った部屋は文脈のない依頼を掴む。
"""
import argparse
import datetime
import json
import os
import sqlite3
import sys

BASE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..")
DB = os.path.normpath(os.path.join(BASE, "local", "queue", "inbox.db"))


def _jst(epoch):
    try:
        return datetime.datetime.fromtimestamp(float(epoch)).strftime("%Y-%m-%d %H:%M:%S")
    except (TypeError, ValueError):
        return "?"


def _brief(body, limit=90):
    """本文JSONから「誰が何と言ったか」だけ取り出す。壊れていても落ちない。"""
    try:
        d = json.loads(body)
    except Exception:
        return (str(body) or "")[:limit].replace("\n", " ")
    who = d.get("author") or "?"
    text = (d.get("content") or "").replace("\n", " ")
    return f"{who}: {text[:limit]}"


def cmd_list(con, show_all):
    where = "status='dead'" if show_all else "status='dead' AND (result IS NULL OR result='')"
    rows = con.execute(
        f"SELECT id, dept, enqueued_at, deliveries, result, body FROM queue "
        f"WHERE {where} ORDER BY enqueued_at").fetchall()
    if not rows:
        print("手当て待ちのデッドレターは無い。" if not show_all else "デッドレターは1件も無い。")
        return 0
    print(f"{len(rows)}件(古い順)")
    for qid, dept, enq, dlv, result, body in rows:
        mark = "済" if result else "未"
        print(f"[{mark}] id={qid} {dept} {_jst(enq)} 配送{dlv}回")
        print(f"      {_brief(body)}")
        if result:
            print(f"      手当て= {result}")
    return 0


def cmd_show(con, qid):
    row = con.execute(
        "SELECT id, msg_id, dept, enqueued_at, deliveries, status, result, body "
        "FROM queue WHERE id=?", (qid,)).fetchone()
    if not row:
        print(f"id={qid} は無い。")
        return 1
    keys = ["id", "msg_id", "dept", "enqueued_at", "deliveries", "status", "result", "body"]
    for k, v in zip(keys, row):
        print(f"{k}= {_jst(v) if k == 'enqueued_at' else v}")
    return 0


def cmd_ack(con, qid, by, note):
    row = con.execute("SELECT status, result FROM queue WHERE id=?", (qid,)).fetchone()
    if not row:
        print(f"id={qid} は無い。")
        return 1
    if row[0] != "dead":
        print(f"id={qid} は status={row[0]} だ(deadではない)。触らない。")
        return 1
    if row[1]:
        print(f"id={qid} は既に手当て済み= {row[1]}")
        return 0
    stamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    mark = f"handled {stamp} by {by}: {note}"
    con.execute("UPDATE queue SET result=? WHERE id=? AND status='dead'", (mark, qid))
    con.commit()
    print(f"id={qid} に手当ての印を付けた= {mark}")
    return 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--list", action="store_true")
    ap.add_argument("--all", action="store_true", help="手当て済みも出す")
    ap.add_argument("--show", type=int)
    ap.add_argument("--ack", type=int)
    ap.add_argument("--by", default="")
    ap.add_argument("--note", default="")
    a = ap.parse_args()
    if not os.path.exists(DB):
        print(f"キューのDBが無い({DB})。")
        return 2
    con = sqlite3.connect(DB, timeout=5)
    con.execute("PRAGMA busy_timeout=3000")
    try:
        if a.ack is not None:
            if not a.by or not a.note:
                print("--ack には --by と --note が要る(誰がどう片付けたかが残らないと印の意味が無い)。")
                return 2
            return cmd_ack(con, a.ack, a.by, a.note)
        if a.show is not None:
            return cmd_show(con, a.show)
        return cmd_list(con, a.all)
    finally:
        con.close()


if __name__ == "__main__":
    sys.exit(main())
