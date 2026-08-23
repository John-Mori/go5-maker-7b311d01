# -*- coding: utf-8 -*-
"""codever_history.jsonl を**正しい分母で**数え直す(観測の集計だけ・警報は出さない)。

なぜ要るか(2026-08-23 研究室HQ指摘):
  サンプラは1時間ごとに1行積む。だが**静かな夜は `behind: []` ばかり積もる**ので、
  「行数」を分母にすると「2時間超は実在しない」という結論が**自動的に出る**=silent green。
  ★分母は **「版が動いた回数」**だ。遅れは**版が動いた後の窓にしか現れない**。

★HQの案は `newest` の変化で窓を切る、だったが **`newest` は "%H:%M" で日付が無い**
  (実物= `{"newest": "09:33"}`)。日をまたぐと同じ時刻が再来して窓を取り違える。
  だから窓の切れ目は **`cur`(版のhash)の変化**で見る。こちらは日付に依存しない。
  ★取りこぼしの向き= 1時間の中で2回展開すると1回に潰れる(分母が小さくなる)。
    分母が小さい=比率は**悪い側**に出る=安全な方向へ倒れる。逆には倒れない。

★閾値(2時間)はここに書かない。`relay_health.py` の `CODEVER_STALE_SEC` を**借りる**
  (判定の正本は検査14=`check_codever` の1つだけにする)。読めなければ数えずに黙る。

使い方: python scripts/_daemons/codever_report.py
"""
import io
import json
import os
import sys

PJ = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
HIST = os.path.join(PJ, "local", "_state", "codever_history.jsonl")
HQ_SCRIPTS = r"D:\SougouStartFolder\00_AI-HQ\scripts"


def stale_sec():
    """2時間の閾値を検査14から借りる。読めなければ None(=数えない)。"""
    try:
        if HQ_SCRIPTS not in sys.path:
            sys.path.insert(0, HQ_SCRIPTS)
        import relay_health
        return int(relay_health.CODEVER_STALE_SEC)
    except Exception:
        return None


def rows():
    out = []
    if not os.path.exists(HIST):
        return out
    for ln in io.open(HIST, encoding="utf-8"):
        ln = ln.strip()
        if not ln:
            continue
        try:
            out.append(json.loads(ln))
        except Exception:
            continue
    return out


def windows(rs):
    """`cur` の変化で窓に切る。返り値= [(版, その窓の行たち)]。"""
    out = []
    for r in rs:
        if out and out[-1][0] == r.get("cur"):
            out[-1][1].append(r)
        else:
            out.append((r.get("cur"), [r]))
    return out


def main():
    rs = rows()
    if not rs:
        print("履歴が無い: %s" % HIST)
        return 0
    sec = stale_sec()
    ws = windows(rs)
    # ★分母= 版が動いた回数。**最初の窓は「動いたのを見た」ではない**ので除く。
    moved = len(ws) - 1
    quiet = sum(1 for r in rs if not r.get("behind"))
    print("行数=%d (うち遅れ0の行=%d) / 版=%d種 / ★版が動いたのを見た回数=%d"
          % (len(rs), quiet, len(ws), moved))
    print("  期間 %s 〜 %s" % (rs[0].get("ts"), rs[-1].get("ts")))
    if sec is None:
        print("★閾値を借りられない(relay_health.py が読めない)=2時間超は数えない")
        return 0
    lim = sec // 60
    if moved <= 0:
        print("★まだ版が動いていない=**分母が0。2時間超が実在するかは、まだ何も言えない。**")
        print("  (遅れ0の行がいくら積もっても『収束した』の証拠にはならない=静かな窓)")
        return 0
    bad = []
    for ver, group in ws[1:]:
        worst = 0
        for r in group:
            for b in (r.get("behind") or []):
                worst = max(worst, int(b.get("min") or 0))
        if worst > lim:
            bad.append((ver, group[0].get("ts"), worst))
    print("★%d分超が残った展開= %d回 / %d回" % (lim, len(bad), moved))
    for ver, ts, worst in bad:
        print("  %s 版%s 最悪%d分" % (ts, ver, worst))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
