# -*- coding: utf-8 -*-
"""呼称の**持続ドリフト**を台帳から拾う(イージス研究室 / 2026-08-31)。

なぜ要るか:
  改善提案部門(トトリ)が「一ノ瀬」(裸の姓)呼び22件を実測し、機構側の手当てを回してきた
  (msg 1543872521093521478)。実測を当室でも取り直した結果、**回送の根因は1つ違っていた**=
  22件は素通りしていない。呼称ゲートは全部 `reason="override_allowed" / expected=["怜"]` で
  **違反と判定し、台帳へ書いていた**(`local/llm/naming_audit.jsonl`)。
  素通りしていたのは判定ではなく**読み手**だ= この台帳を読む機構が1つも無い(実測=
  `naming_audit` を参照するコードは書き手2本(dept_daemon / output_gates)だけ)。
  → 「鳴っている≠届いている」(共通規律§4)。**書きっぱなしの台帳は監視ではない。**

何を「ドリフト」と呼ぶか(★件数だけで鳴らさない理由):
  台帳の判定行は306行(2026-07-31〜08-31)。件数の閾値だけで鳴らすと**常に鳴る**=
  常に誤発火する安全網は無視される(§3)。だから3つ揃った時だけドリフトと呼ぶ:
    ① 直近 WINDOW_DAYS 日で MIN_COUNT 件以上   … 今も続いている
    ② MIN_DAYS 日以上にまたがる                … 一度の観測を状態の代理にしない(C-041)
    ③ MIN_PERSONAS 人以上の人格が使っている     … 1人のクセではなく**組織へ伝播した**形
  ★増分ではなく**持続**で見る= 件数が増えなくても、居座っている形は居座ったまま出る
    (増分だけの監視は滞留を見逃す)。

しきい値の根拠(実測・2026-08-31の台帳):
  (5,3,2) で7件が挙がる= 読める量。トトリが持ち込んだ「一ノ瀬」が**指定せずとも1位**に出る
  (件18/日6/人7)。狙い撃ちの検査ではないことの証拠として、この数字を残しておく。

自動置換はしない:
  正しい形は文脈で変わる(「一ノ瀬怜さんが」と紹介する文まで潰す)。ここは**数えて見せるだけ**。
  直すのは人事部門(呼称ルール.json と人格文脈)であって、この機構ではない。

使い方:
    python scripts/llm/naming_drift_check.py            … 今の持続ドリフトを表で見る
    python scripts/llm/naming_drift_check.py --days 30  … 窓を変える
"""
import argparse
import collections
import datetime as dt
import io
import json
import os
import sys

PJ = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
AUDIT = os.path.join(PJ, "local", "llm", "naming_audit.jsonl")

WINDOW_DAYS = 14
MIN_COUNT = 5
MIN_DAYS = 3
MIN_PERSONAS = 2


def load_rows(path=None):
    """台帳から**判定行だけ**読む。★壊れた行で落ちない(1行の事故で監視を止めない)。

    event="naming_fix" は機械が直した行= ドリフトではなく**直った跡**なので数えない。
    """
    out = []
    try:
        with io.open(path or AUDIT, encoding="utf-8") as f:
            for ln in f:
                ln = ln.strip()
                if not ln:
                    continue
                try:
                    r = json.loads(ln)
                except Exception:
                    continue
                if r.get("event") == "naming" and r.get("found") and r.get("target"):
                    out.append(r)
    except OSError:
        return []
    return out


def _aggregate(rows, end, window):
    """(target, found) ごとに窓の中を畳む。

    ★端の扱い= `end` を含む `window` 日(end 当日を1日目と数える)。既定の end は台帳の最終日
      であって「今日」ではない= 台帳が数日止まっていても、止まる前の窓をそのまま見せる
      (「今日」を基準にすると、書き手が死んだ時に**静かに0件=健康**へ倒れる)。
    """
    if not rows:
        return {}
    days_of = [r["ts"][:10] for r in rows if r.get("ts")]
    if not days_of:
        return {}
    try:
        end_d = dt.date.fromisoformat(end or max(days_of))
    except ValueError:
        return {}

    agg = collections.defaultdict(
        lambda: {"count": 0, "days": set(), "personas": set(),
                 "reasons": collections.Counter(), "expected": [],
                 "first": "", "last": ""})
    for r in rows:
        ts = str(r.get("ts") or "")
        try:
            d = dt.date.fromisoformat(ts[:10])
        except ValueError:
            continue
        if not (0 <= (end_d - d).days < window):
            continue
        a = agg[(r["target"], r["found"])]
        a["count"] += 1
        a["days"].add(ts[:10])
        a["personas"].add(str(r.get("persona") or ""))
        a["reasons"][str(r.get("reason") or "")] += 1
        if not a["expected"]:
            a["expected"] = list(r.get("expected") or [])
        a["first"] = min(a["first"] or ts, ts)
        a["last"] = max(a["last"], ts)
    return agg


def _unreadable(a):
    """★実際の形が台帳に無い行= 直す先が読めない(実測=窓14日で2組8件)。

    呼称ゲートが台帳へ書く `found` は「見つかった**土台の**形」であって、**実際に使われた形
    ではない**。例= 「モドリッチさん」は違反(呼び捨てが正)だが、台帳には
    found="モドリッチ" / expected=["モドリッチ"] と残る= 読むと
    「モドリッチをモドリッチと呼ぶな」という無意味な文になる。
    ★これは判定の誤りではなく**台帳の表現力不足**だ(ゲートは正しく違反にしている)。
    直す先が読み取れない警報は、受け手が無視する側へ倒れる(§3)ので**鳴らさない**。
    ただし黙って捨てもしない= `unreadable()` で件数だけ見せ、ゲート側の宿題として残す。
    """
    return a["found"] in (a["expected"] or [])


def unreadable(rows=None, end=None, window=WINDOW_DAYS):
    """鳴らせない(=台帳から直す先が読めない)組を件数順で返す。理由は `_unreadable`。"""
    rows = load_rows() if rows is None else rows
    out = []
    for (target, found), a in _aggregate(rows, end, window).items():
        a = dict(a, target=target, found=found)
        if _unreadable(a):
            out.append({"target": target, "found": found,
                        "expected": a["expected"], "count": a["count"]})
    out.sort(key=lambda d: (-d["count"], d["target"]))
    return out


def scan(rows=None, end=None, window=WINDOW_DAYS,
         min_count=MIN_COUNT, min_days=MIN_DAYS, min_personas=MIN_PERSONAS):
    """持続ドリフトを件数の多い順で返す。

    戻り値= [{"target","found","expected","count","days","personas","first","last","reasons"}]
    """
    rows = load_rows() if rows is None else rows
    out = []
    for (target, found), a in _aggregate(rows, end, window).items():
        if _unreadable(dict(a, target=target, found=found)):
            continue
        if (a["count"] >= min_count and len(a["days"]) >= min_days
                and len(a["personas"]) >= min_personas):
            out.append({
                "target": target, "found": found, "expected": a["expected"],
                "count": a["count"], "days": len(a["days"]),
                "personas": sorted(p for p in a["personas"] if p),
                "first": a["first"], "last": a["last"],
                "reasons": dict(a["reasons"]),
            })
    out.sort(key=lambda d: (-d["count"], d["target"], d["found"]))
    return out


def sig(drifts):
    """ドリフトの顔ぶれ。同じ顔ぶれを二度知らせないための版(件数は入れない=

    1件増えるたびに鳴り直すと、それは件数アラームと同じ騒がしさになる)。
    """
    return "|".join(sorted("%s>%s" % (d["target"], d["found"]) for d in drifts))


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=WINDOW_DAYS)
    ap.add_argument("--json", action="store_true")
    ns = ap.parse_args(argv)
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    rows = load_rows()
    ds = scan(rows, window=ns.days)
    un = unreadable(rows, window=ns.days)
    if ns.json:
        print(json.dumps({"drifts": ds, "unreadable": un},
                         ensure_ascii=False, indent=2))
        return 0
    print("台帳の判定行 %d / 窓%d日 / しきい値 件%d 日%d 人%d"
          % (len(rows), ns.days, MIN_COUNT, MIN_DAYS, MIN_PERSONAS))
    if not ds:
        print("持続ドリフトなし")
    for d in ds:
        print("- %s を **%s** と呼んでいる(正=%s): 件%d 日%d 人%d [%s〜%s]"
              % (d["target"], d["found"], "/".join(d["expected"]) or "?",
                 d["count"], d["days"], len(d["personas"]),
                 d["first"][:10], d["last"][:10]))
        print("    使っている人格= %s" % "、".join(d["personas"]))
    if un:
        # ★鳴らさない分を**見えるところに**残す。0件に見せると、次に読む者が
        #   「台帳は健康」と誤読する(C-041)。
        print("(鳴らせない %d件= 台帳に実際の形が無く直す先が読めない: %s)"
              % (sum(u["count"] for u in un),
                 "、".join("%s>%s" % (u["target"], u["found"]) for u in un)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
