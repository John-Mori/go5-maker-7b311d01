#!/usr/bin/env python3
"""turn_per_letter — **1便(Discordの手紙1通)を返すのに何ターン燃やしたか**を測る。読むだけ。

★なぜ要るか(2026-09-14 04時 quota_alarm DISPATCH-aegis-gl-1789326112874・イージス研究室)
  警報は「イージス研究室が週の 39.0%」と名指してきた。だが `quota_burn.py` が数える「便」は
  **transcript の usage 1行= APIの1ターン**であって、**Discordの手紙1通ではない**。
  実測(週・09/12 03:00 以降)= イージス研究室の受信は **61通**、うち17通は手番ゼロの既読ack
  (relayを1回も呼んでいない)= **返事を書いたのは44通**。それに対して usage は **1,630ターン**。
  = **1通あたり 37.0ターン**。研究室HQは 18.9、人事部門は 4.6 だった。
  つまり39%の正体は「手紙が多い」ではない(手紙の数では組織の17.1%しか占めていない)。
  **1通に掛けるターン数**だ。1ターンごとに約7万トークンの文脈を読み直すので、
  ターン数はそのまま課金枠の掛け算になる。

★この計器が quota_burn と違う所
  ・quota_burn = transcript だけを見る(手紙の数を知らない)。所有は研究室HQ= **こちらは触らない**。
  ・ここ       = transcript(ターン)と `local/queue/inbox.db`(手紙)を**突き合わせる**。
    分母から「手番ゼロ=無投稿」の便を外す= 既読ackは返事を書いていないので分母に入れない。

★何を数えていないか
  ・部屋のセッションが手紙以外(Chamiの直接の会話・手動実行)で燃やしたターンも分子に入る。
    = この値は「1通あたり」の**上限側**の見積もりだ。順位と傾きを見る物差しであって精算書ではない。
  ・重み付け・モデル係数は quota_burn の物をそのまま借りる(二重定義を作らない)。

使い方:
  python scripts/llm/turn_per_letter.py                 # 週(直前のリセット以降)
  python scripts/llm/turn_per_letter.py --hours 24      # 直近24時間
  python scripts/llm/turn_per_letter.py --dept aegis-gl # 1部門だけ
"""
import argparse
import collections
import json
import os
import sqlite3
import sys
from datetime import datetime, timedelta, timezone

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import quota_burn as qb                                             # noqa: E402

INBOX = os.path.join(qb.ROOT, "local", "queue", "inbox.db")
JST = qb.JST

# ★分母から外す便= 「手番ゼロ」= relayを呼ばずに既読だけ付けた物(完遂通知など)。
#   字面は dept_daemon が result 欄へ書く物。増えたらここへ足す。
NO_TURN_MARKS = ("手番ゼロ", "無投稿")


def letters(since_jst):
    """since 以降に受信した手紙を {dept: [受信数, 無投稿数]} で返す。"""
    out = collections.defaultdict(lambda: [0, 0])
    if not os.path.exists(INBOX):
        return out
    con = sqlite3.connect(f"file:{INBOX}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    try:
        rows = con.execute("select dept, result from queue where enqueued_at > ?",
                           (since_jst.timestamp(),)).fetchall()
    except sqlite3.Error:
        return out                      # ★読めない=空で返す。計器で配達を殺さない
    finally:
        con.close()
    for r in rows:
        d = r["dept"] or "?"
        out[d][0] += 1
        res = str(r["result"] or "")
        if any(m in res for m in NO_TURN_MARKS):
            out[d][1] += 1
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--hours", type=float, default=None, help="週でなく直近N時間で切る")
    ap.add_argument("--dept", default=None, help="1部門だけ")
    ap.add_argument("--top", type=int, default=20)
    ap.add_argument("--min-letters", type=int, default=1,
                    help="返事を書いた便がこれ未満の部屋は出さない(0除算と誤読を避ける)")
    args = ap.parse_args()

    now = datetime.now(JST)
    if args.hours:
        since = now - timedelta(hours=args.hours)
        window = f"直近 {args.hours:g} 時間"
    else:
        since = qb.last_reset(now)
        window = f"週(リセット {since:%m/%d(%a) %H:%M} 以降)"
    rows = qb.collect(since.astimezone(timezone.utc))
    dmap = qb.dept_map()

    turns = collections.Counter()
    wsum = collections.Counter()
    cread = collections.Counter()
    for r in rows:
        d = dmap.get(r[0], "?")
        turns[d] += 1
        wsum[d] += qb.weighted(r)
        cread[d] += r[5]
    lt = letters(since)
    total_w = sum(wsum.values()) or 1

    print(f"== 1便あたりのターン数 / {window} / いま {now:%m/%d %H:%M} JST ==")
    print("★分子= transcript の usage 行(APIのターン) / 分母= 受信箱の手紙のうち"
          "**手番ゼロでない**物")
    print("★『便』の語が2つの意味で使われている= ここでは手紙を『通』、APIを『ターン』と書き分ける\n")
    head = ("部門", "シェア", "ターン", "受信(通)", "無投稿", "応答(通)", "1通あたりターン")
    print("%-16s %6s %7s %8s %7s %8s %15s" % head)

    names = set(turns) | set(lt)
    if args.dept:
        names = {args.dept}
    out = []
    for d in names:
        recv, free = lt.get(d, [0, 0])
        ans = recv - free
        if ans < args.min_letters:
            continue
        out.append((turns[d] / ans, d, turns[d], recv, free, ans, wsum[d]))
    out.sort(reverse=True)
    for tpl, d, t, recv, free, ans, w in out[:args.top]:
        print("%-16s %5.1f%% %7d %8d %7d %8d %15.1f"
              % (d, 100 * w / total_w, t, recv, free, ans, tpl))
    if not out:
        print("(この窓に応答便が無い)")
        return 0

    tot_t = sum(o[2] for o in out)
    tot_a = sum(o[5] for o in out)
    print("\n合計= ターン %d / 応答 %d通 → **1通あたり %.1f ターン**"
          % (tot_t, tot_a, tot_t / max(1, tot_a)))
    print("★読み方= 1ターンごとに部屋の文脈まるごとを読み直す。"
          "1通あたりターンが2倍なら、同じ手紙の数でも枠は2倍燃える。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
