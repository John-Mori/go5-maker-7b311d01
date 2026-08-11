# -*- coding: utf-8 -*-
"""便が「どれだけ待たされたか」を台帳から測る道具(2026-08-12 イージス研究室)。

なぜ要るか:
  DEF-aegis-gl-4e302214bb=「報告通知は死んでない、詰まってるだけだ」。あの時も今日も、
  詰まりの有無を確かめるのに **inbox.db を手でSQL照会**していた。同じ照会を毎回書くのは
  измеряる前に諦める理由になる(=誰も測らなくなる)。だから道具にする(C-019)。

★この道具が答える問いは1つ: **待ちなのか、処理が長いのか**。
  この2つは症状が同じ(Chamiから見ると「反応がない」)なのに、打つ手が正反対だ。
    ・待ちが長い  = 前の便が頭を塞いでいる(直列処理の頭詰まり)→ レーン・優先度の話
    ・処理が長い  = 掴んでから答えるまでが長い → 便の中身・モデル・作業量の話
  実測 2026-08-12: 直近3日の Chami便は**待ちがほぼ0**で、詰まるのは特定の部屋が
  重い便を連続処理している時間帯だけだった(08-11 17:02〜17:30 の改修α宛が15〜20分待ち)。

測り方(台帳から復元する):
  投入 = enqueued_at / 完了 = acked_at はそのまま列にある。**掴んだ時刻は列に無い**ので
  `掴んだ時刻 = lease_until - リース長` で復元する。リース長は部門の設定(session_relay なら
  hard_limit+余白、そうでなければ既定900秒)から引く。
  ★再配達された便(deliveries>=2)の lease_until は**最後に掴んだ時**のものなので、
    復元できるのは最後の掴みだけだ。初回の待ちはこれより長い= 出力に「再」印を付けて明示する。
    測れないものを測れたことにしない。

読み取り専用(mode=ro)。台帳には1バイトも書かない。
"""
import argparse
import collections
import datetime
import json
import os
import sqlite3
import sys

BASE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..")
DB = os.path.normpath(os.path.join(BASE, "local", "queue", "inbox.db"))
DEFAULT_LEASE = 900.0
CHAMI = "chami_fusoh"


def lease_by_dept():
    """部門ごとのリース長(秒)。読めなければ既定に倒す(fail-open=測れる範囲で測る)。"""
    out = {}
    try:
        sys.path.insert(0, os.path.normpath(os.path.join(BASE, "scripts", "llm")))
        from dept_daemon import DEPT_CONF, QUEUE_LEASE_MARGIN
        import session_relay
        hard = float(session_relay.hard_limit(True))
        for dept, conf in DEPT_CONF.items():
            out[dept] = (hard + QUEUE_LEASE_MARGIN) if conf.get("session_relay") else DEFAULT_LEASE
    except Exception:
        pass
    return out


def _author(body):
    try:
        return (json.loads(body).get("author") or "?") if isinstance(body, str) else "?"
    except Exception:
        return "?"


def rows(days, dept=None, chami_only=False):
    if not os.path.exists(DB):
        print(f"キューのDBが無い({DB})。")
        return []
    since = datetime.datetime.now().timestamp() - days * 86400
    con = sqlite3.connect(f"file:{DB}?mode=ro", uri=True, timeout=5)
    try:
        sql = ("SELECT id, dept, enqueued_at, acked_at, lease_until, deliveries, body "
               "FROM queue WHERE status='done' AND acked_at IS NOT NULL AND enqueued_at >= ?")
        args = [since]
        if dept:
            sql += " AND dept = ?"
            args.append(dept)
        raw = con.execute(sql + " ORDER BY id", args).fetchall()
    finally:
        con.close()
    leases = lease_by_dept()
    out = []
    for qid, d, enq, ack, lu, dlv, body in raw:
        who = _author(body)
        if chami_only and who != CHAMI:
            continue
        lease = leases.get(d, DEFAULT_LEASE)
        claim = (lu or 0) - lease
        # 復元が破綻した便(投入前に掴んだことになる等)は0へ丸める=負の待ちを報告しない。
        wait = max(0.0, claim - enq)
        proc = max(0.0, (ack - claim) if claim > enq else (ack - enq))
        out.append({"id": qid, "dept": d, "enq": enq, "wait": wait, "proc": proc,
                    "total": max(0.0, ack - enq), "dlv": dlv, "who": who})
    return out


def _pct(vals, p):
    if not vals:
        return 0.0
    s = sorted(vals)
    return s[min(len(s) - 1, int(len(s) * p / 100.0))]


def summary(recs):
    by = collections.defaultdict(list)
    for r in recs:
        by[r["dept"]].append(r)
    print("部門           件数  待ち中央 待ちp90 待ち最大 | 処理中央 処理最大  (分)")
    for dept, rs in sorted(by.items(), key=lambda kv: -_pct([x["wait"] for x in kv[1]], 90)):
        w = [x["wait"] / 60 for x in rs]
        p = [x["proc"] / 60 for x in rs]
        print("%-14s %4d  %7.1f %7.1f %8.1f | %8.1f %8.1f"
              % (dept, len(rs), _pct(w, 50), _pct(w, 90), max(w), _pct(p, 50), max(p)))
    allw = [x["wait"] / 60 for x in recs]
    if allw:
        print("-- 全体 %d件: 待ち中央 %.1f分 / p90 %.1f分 / 最大 %.1f分"
              % (len(recs), _pct(allw, 50), _pct(allw, 90), max(allw)))


def listing(recs, over_min):
    hit = [r for r in recs if r["total"] >= over_min * 60]
    if not hit:
        print(f"{over_min}分以上かかった便は無い。")
        return
    print(f"{over_min}分以上かかった便 {len(hit)}件(新しい順)")
    print("id      部門           投入          待ち   処理   合計  誰")
    for r in sorted(hit, key=lambda x: -x["enq"]):
        mark = "再" if r["dlv"] >= 2 else "  "
        print("%-7s %-14s %s %s%5.1f分 %5.1f分 %5.1f分  %s"
              % (r["id"], r["dept"],
                 datetime.datetime.fromtimestamp(r["enq"]).strftime("%m-%d %H:%M"),
                 mark, r["wait"] / 60, r["proc"] / 60, r["total"] / 60, r["who"]))
    if any(r["dlv"] >= 2 for r in hit):
        print("★「再」= 再配達された便。待ちは**最後に掴んだ時**からの復元なので、"
              "初回の待ちはこれより長い(台帳に初回の掴み時刻が無い)。")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=float, default=7)
    ap.add_argument("--dept")
    ap.add_argument("--chami-only", action="store_true", help="Chami本人の便だけ")
    ap.add_argument("--over", type=float, help="この分数以上かかった便を列挙する")
    a = ap.parse_args()
    recs = rows(a.days, a.dept, a.chami_only)
    if not recs:
        print("対象の便が無い。")
        return 0
    who = "Chami本人の便" if a.chami_only else "全ての便"
    print(f"=== 直近{a.days:g}日 / {who} / {len(recs)}件 ===")
    if a.over is not None:
        listing(recs, a.over)
    else:
        summary(recs)
    return 0


if __name__ == "__main__":
    sys.exit(main())
