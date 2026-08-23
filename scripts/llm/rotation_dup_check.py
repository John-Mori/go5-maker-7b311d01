# -*- coding: utf-8 -*-
"""世代交代の「同じ引き金が二度鳴る」を見つける正本(2026-08-24 イージス研究室)。

★何のために足したか(品質管理部門の監査 2026-08-23 節を受けた恒久ガード・C-038/C-056):
  7/30〜8/23の request_log 19,114行を品質管理部門が走査し、「同一evidenceが複数回出る交代」を
  3件見つけた。だが**実物を読み直すと、3件は2種類の別物**だった:

    ① 2026-07-30 改修部門α ×2 = **交代は正しく撃たれ、新セッションの作成が 429 で落ちた**。
       02:14:22 `new session失敗 rc=1 … api_error_status:429 … pre_rotating=True`
       → 対応表は旧セッションのままなので、次の便が同じ判定をして**もう一度撃つ**。
       これは**正当な再挑戦**だ。ここを冪等で潰すと、交代できないまま部屋が居座る
       (=可用性に関わる所は fail-open。潰す方が害が大きい)。
    ② 2026-08-22 研究室HQ ×1 = `手動交代 reason=cli` が10分後に**同じ old / 同じ gen** で再出現。
       前後の completed も gen=16 のまま= **交代が対応表に乗っていない**(ORG-46/ORG-47 の型)。
       これが本物の二重発火。恒久対策は同日 17:09:47 の commit 9dc5275 で入っている。

  つまり「同一evidenceの重複」だけを数えると①と②が混ざる。**混ざった数字は直しを誤らせる**
  (①へ冪等ガードを当てると、429で落ちた交代が二度と撃たれなくなる)。
  だからここでは **間に失敗の記録があるか** で2つを割り、②だけを問題として返す。

★限界(黙っても「交代は全部健全」ではない):
  - 見ているのは `local/llm/request_log.jsonl` の**起点行だけ**。交代した後の中身の質は見ない。
  - evidence が**完全一致**した時だけ組にする。文言が1文字でも変われば別物として通る。
  - 既定の窓は直近7日。それより古い事故はここでは鳴らない(過去は監査の担当)。

使い方:
    python scripts/llm/rotation_dup_check.py            # 直近7日
    python scripts/llm/rotation_dup_check.py --days 30
"""
import argparse
import io
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
REQUEST_LOG = os.path.join(ROOT, "local", "llm", "request_log.jsonl")

# 交代の「起点行」= この2つで始まる evidence(session_relay.py が書く形)
START_PREFIXES = ("事前交代", "手動交代")

# ★①(正当な再挑戦)の印= 起点行の後に、その部屋で交代そのものが転んだ記録が残っている。
#   session_relay.py は新セッションの作成に失敗すると
#   `new session失敗 rc=… pre_rotating=True` を state=failed で書く。
RETRY_MARKERS = ("new session失敗", "pre_rotating=True")


def load_rows(path=None):
    """request_log を読む。壊れた行は黙って飛ばす(台帳は追記専用なので途中行が欠けうる)。"""
    path = path or REQUEST_LOG
    rows = []
    try:
        with io.open(path, encoding="utf-8-sig", errors="replace") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    rows.append(json.loads(line))
                except ValueError:
                    continue
    except OSError:
        return []
    return rows


def is_start(row):
    return (row.get("state") == "rotated"
            and str(row.get("evidence") or "").startswith(START_PREFIXES))


def is_retry_marker(row):
    ev = str(row.get("evidence") or "")
    return row.get("state") == "failed" and any(m in ev for m in RETRY_MARKERS)


def scan(rows=None, days=7, since=None):
    """★判定の正本。戻り= (見た起点行の数, 本物の二重発火のリスト)。

    本物 = 同じ部屋で **evidence が完全一致する起点行**が2回以上出ていて、
           かつ **その間にその部屋の失敗の記録が無い**もの。
    間に失敗があるものは「429などで転んだ交代の正当な再挑戦」として数えない。
    """
    rows = load_rows() if rows is None else rows
    if since is None and days is not None:
        import datetime as _dt
        since = (_dt.datetime.now() - _dt.timedelta(days=days)).strftime("%Y-%m-%dT%H:%M:%S")
    rows = [r for r in rows if since is None or str(r.get("ts") or "") >= since]
    rows.sort(key=lambda r: str(r.get("ts") or ""))

    seen = {}          # (部屋, evidence) -> 直前に見た起点行の ts
    failed_after = {}  # 部屋 -> その部屋で最後に失敗を見た ts
    n_start, hits = 0, []
    for r in rows:
        dept = r.get("dept")
        ts = str(r.get("ts") or "")
        if is_retry_marker(r):
            failed_after[dept] = ts
            continue
        if not is_start(r):
            continue
        n_start += 1
        key = (dept, str(r.get("evidence") or ""))
        prev = seen.get(key)
        if prev is not None:
            last_fail = failed_after.get(dept, "")
            if not (prev < last_fail <= ts):
                hits.append({"dept": dept, "first": prev, "dup": ts,
                             "evidence": str(r.get("evidence") or "")})
        seen[key] = ts
    return n_start, hits


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=7)
    a = ap.parse_args(argv)
    n, hits = scan(days=a.days)
    print("直近%d日の交代の起点行= %d件 / 本物の二重発火= %d件" % (a.days, n, len(hits)))
    for h in hits:
        print("  ★%s %s → %s に同一の引き金が再出現: %s"
              % (h["dept"], h["first"], h["dup"], h["evidence"][:110]))
    return 1 if hits else 0


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    sys.exit(main())
