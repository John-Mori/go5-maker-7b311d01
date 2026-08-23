#!/usr/bin/env python3
"""quota_alarm — 週の課金枠の燃え方を**自前の量**で見張り、危ない時だけ鳴らす。

★発注(2026-08-23 研究室HQ msg 1540938360464474273 → イージス研究室)
  「`quota_burn.py` を定刻に載せろ。★鳴らす引き金に『Chamiが画面を見て%を教える』を使うな
   (人間を計器にするな)。自前で持てる量= 重み付き換算の週累計。**先週の同時刻との比**で
   鳴らせば外部の%は要らない。どうしても%が要るなら週1回だけ画面の実測で較正し、以後は
   換算値で外挿。その場合は必ず"推定"と明示させろ。C-046= 鳴った時に打てる手を一緒に出せ。」

★測る量(全部こちらが自分で持てる)
  1. **週累計の重み付き換算値**(`quota_burn.weighted` の合計)。単位は無い=比を見るための量。
  2. **先週の同じ経過時間までの累計**。倍率 = 今週 / 先週。
  3. (任意)較正点があれば「推定 %」。★出力には必ず **推定** と書く。

★鳴らし方(常に誤発火する安全網は無視される・共通規律§3)
  - 既定の閾値= 先週比 1.30倍 以上、**または** 推定%の枯渇時刻が次のリセットより前。
  - 鳴るのは**便を1本出す時だけ**。落ち着いていれば台帳へ1行残して黙る。
  - 同じ警報を鳴らし続けない= `--quiet-hours`(既定12時間)の間は再送しない。
  - ★C-046= 鳴らす本文に**打てる手**(quota_guard.ps1 の1行と、いま食っている上位の部屋)を必ず入れる。

使い方:
  python scripts/llm/quota_alarm.py                 # 見張り1回(定刻タスクはこれ)
  python scripts/llm/quota_alarm.py --dry-run       # 鳴らさずに判定だけ見る
  python scripts/llm/quota_alarm.py --calibrate 46  # 画面の「すべてのモデル」%を1回だけ教える
"""
import argparse
import json
import os
import subprocess
import sys
from datetime import datetime, timedelta, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, HERE)
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import quota_burn as qb                                            # noqa: E402

JST = qb.JST
LOCAL = os.path.join(ROOT, "local")
LEDGER = os.path.join(LOCAL, "llm", "quota_burn.jsonl")
CALIB = os.path.join(LOCAL, "_quota_calibration.json")
STAMP = os.path.join(LOCAL, "_quota_alarm_last.json")
DISPATCH = os.path.join(ROOT, "scripts", "llm", "dispatch.py")
GUARD = r"scripts\_daemons\quota_guard.ps1"

RATIO_ALARM = 1.30          # 先週の同時刻比。これ以上で鳴らす
# ★24時間。理由は「うるさいから」ではなく**この警報自体が枠を食うから**(2026-08-23 実測):
#   8/23 05〜10時の窓で **投函 159件 → API便 4,609回**= 1投函あたり平均 29往復。
#   週全体が 10,083便なので、**便を1本増やすたびに週の約0.3%が消える。**
#   12時間ごとに鳴らすと、それだけで週 4% を見張りが食う=見張りが病気になる。
QUIET_HOURS = 24.0          # 同じ警報を鳴らし直さない時間


def window_total(start, end):
    """[start, end) の重み付き換算合計と便数。"""
    rows = qb.collect(start.astimezone(timezone.utc))
    rows = [r for r in rows if r[2].astimezone(JST) < end]
    return sum(qb.weighted(r) for r in rows), len(rows)


def by_dept(start, end, top=5):
    rows = qb.collect(start.astimezone(timezone.utc))
    rows = [r for r in rows if r[2].astimezone(JST) < end]
    dm = qb.dept_map()
    tot = sum(qb.weighted(r) for r in rows) or 1.0
    agg = {}
    for r in rows:
        k = dm.get(r[0], "手動/不明")
        agg[k] = agg.get(k, 0.0) + qb.weighted(r)
    return [(k, v / tot * 100) for k, v in sorted(agg.items(), key=lambda x: -x[1])[:top]]


def read_json(path, default=None):
    try:
        with open(path, encoding="utf-8-sig") as f:
            return json.load(f)
    except Exception:
        return default


def write_json(path, doc):
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(doc, f, ensure_ascii=False, indent=1)
    os.replace(tmp, path)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true", help="鳴らさず判定だけ(本文を画面に出す)")
    # ★検証用(共通規律§3)= **外へ出る手だけ偽物にし、判定と分岐は本物のまま回す**。
    #   dispatch.py を実際に subprocess で起動し、投函だけ止める(--dry-run を渡す)。
    #   「送る処理を呼ばない」テストは配線を1本も見ていないので、それはしない。
    ap.add_argument("--send-dry", action="store_true",
                    help="dispatch.py まで本当に起動するが、投函だけ止める(配線の検証)")
    ap.add_argument("--calibrate", type=float, default=None,
                    help="使用状況画面の『すべてのモデル』の%%。週1回だけ渡す")
    ap.add_argument("--ratio", type=float, default=RATIO_ALARM)
    ap.add_argument("--quiet-hours", type=float, default=QUIET_HOURS)
    a = ap.parse_args()

    now = datetime.now(JST)
    start = qb.last_reset(now)
    nxt = start + timedelta(days=7)
    elapsed_h = (now - start).total_seconds() / 3600.0
    span_h = 168.0

    cur_w, cur_n = window_total(start, now)

    # 先週の「同じ経過時間まで」= 同じ形の窓どうしを比べる(片方だけ長い比較をしない)
    prev_start = start - timedelta(days=7)
    prev_w, prev_n = window_total(prev_start, prev_start + timedelta(hours=elapsed_h))
    ratio = (cur_w / prev_w) if prev_w > 0 else None

    if a.calibrate is not None:
        write_json(CALIB, {"ts": now.isoformat(), "week_start": start.isoformat(),
                           "used_pct": a.calibrate, "weighted": cur_w,
                           "note": "画面の実測。以後はこの比で外挿する=出る%は推定"})
        print("較正を記録: 使用 %.1f%% ↔ 換算 %.0f (週 %s〜)"
              % (a.calibrate, cur_w, start.strftime("%m/%d")))

    # 推定%(較正点が**同じ週**に在る時だけ。無ければ %の話は一切しない=推測で埋めない)
    est_pct = eta = None
    cal = read_json(CALIB)
    if cal and cal.get("week_start") == start.isoformat() and cal.get("weighted"):
        per_unit = float(cal["used_pct"]) / float(cal["weighted"])
        est_pct = cur_w * per_unit
        rate = est_pct / elapsed_h if elapsed_h > 0 else 0
        if rate > 0 and est_pct < 100:
            eta = now + timedelta(hours=(100 - est_pct) / rate)

    time_pct = elapsed_h / span_h * 100

    print("== quota_alarm / %s JST ==" % now.strftime("%m/%d %H:%M"))
    print("週の経過= %.1f/168時間(%.1f%%) / 換算= %.0f(便 %d)" % (elapsed_h, time_pct, cur_w, cur_n))
    if ratio is None:
        print("先週の同区間= 記録が無い(比較なし)")
    else:
        print("先週の同区間= %.0f(便 %d) → **今週は %.2f倍**" % (prev_w, prev_n, ratio))
    if est_pct is None:
        print("推定%= 出さない(今週の較正点が無い。--calibrate <画面の%> を1回だけ渡すと出る)")
    else:
        print("★推定 使用 %.1f%%(較正 %s の外挿= **推定値**。正はChamiの画面)"
              % (est_pct, (cal.get("ts") or "")[:16]))
        if eta:
            print("★推定 100%%到達 %s / 次のリセット %s"
                  % (eta.strftime("%m/%d %H:%M"), nxt.strftime("%m/%d %H:%M")))

    reasons = []
    if ratio is not None and ratio >= a.ratio:
        reasons.append("先週の同区間の %.2f倍(閾値 %.2f)" % (ratio, a.ratio))
    if eta is not None and eta < nxt:
        reasons.append("推定で %s に枯渇= 次のリセット %s まで %.1f日 止まる"
                       % (eta.strftime("%m/%d %H:%M"), nxt.strftime("%m/%d %H:%M"),
                          (nxt - eta).total_seconds() / 86400))

    tops = by_dept(now - timedelta(hours=24), now)

    rec = {"ts": now.isoformat(), "elapsed_h": round(elapsed_h, 2),
           "weighted": round(cur_w), "n": cur_n,
           "prev_weighted": round(prev_w), "prev_n": prev_n,
           "ratio": round(ratio, 3) if ratio else None,
           "est_pct": round(est_pct, 1) if est_pct else None,
           "alarm": bool(reasons), "reasons": reasons}
    os.makedirs(os.path.dirname(LEDGER), exist_ok=True)
    with open(LEDGER, "a", encoding="utf-8") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")

    if not reasons:
        print("→ 静か。台帳へ1行だけ残して黙る。")
        return 0

    print("→ ★警報: " + " / ".join(reasons))

    last = read_json(STAMP, {})
    if last.get("ts"):
        try:
            age = (now - datetime.fromisoformat(last["ts"])).total_seconds() / 3600.0
            if age < a.quiet_hours:
                print("   (前回 %.1f時間前に鳴らした= %.0f時間は鳴らし直さない)" % (age, a.quiet_hours))
                return 0
        except ValueError:
            pass

    body = [
        "【定刻の見張り(quota_alarm) → イージス研究室】週の課金枠の燃え方が閾値を超えた。",
        "",
        "■ なぜ鳴らしたか",
    ] + ["  ・" + r for r in reasons] + [
        "",
        "■ 自前で持っている量(外部の%に依存しない)",
        "  週の経過 %.1f/168時間(%.1f%%) / 換算 %.0f(便 %d)" % (elapsed_h, time_pct, cur_w, cur_n),
        "  先週の同区間 %.0f(便 %d)" % (prev_w, prev_n),
    ]
    if est_pct is not None:
        body.append("  ★推定 使用 %.1f%%(較正点からの外挿= **推定**。正はChamiの画面)" % est_pct)
    body += [
        "",
        "■ 直近24時間で食っている部屋(重み付き換算のシェア)",
    ] + ["  %5.1f%%  %s" % (p, k) for k, p in tops] + [
        "",
        "■ いま打てる手(C-046= 閉じ方をここに書く)",
        "  1. 朝の定刻をずらす   : powershell -File %s -Action stagger" % GUARD,
        "  2. 朝の定刻を1日止める: powershell -File %s -Action thin" % GUARD,
        "  3. 戻す               : powershell -File %s -Action restore" % GUARD,
        "  4. 部屋のモデルを落とす: local/_model_override.json の enabled を true にして部屋を書く",
        "     (会話の部屋と真因追跡はOpusのまま= C-014。落とすのは機械が機械へ出す便だけ)",
        "",
        "  ★閉じ方= 次の巡回で先週比が閾値を下回れば自動で静かになる(この便は再送しない)。",
        "  詳しい内訳= python scripts/llm/quota_burn.py --by dept / --by hour",
    ]
    text = "\n".join(body)

    if a.dry_run:
        print("---- dry-run: 送らない本文 ----")
        print(text)
        return 0

    path = os.path.join(LOCAL, "_quota_alarm_body.txt")
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)
    cmd = [sys.executable, DISPATCH, "--dept", "aegis-gl", "--direct",
           "--from", "quota_alarm(定刻)", "--audience", "ai", "--body-file", path]
    if a.send_dry:
        cmd.append("--dry-run")
        print("   ★--send-dry: dispatch.py は本当に起動するが投函はしない")
    p = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")
    print("   dispatch rc=%s %s" % (p.returncode, (p.stdout or p.stderr or "").strip()[:200]))
    if p.returncode == 0:
        write_json(STAMP, {"ts": now.isoformat(), "reasons": reasons})
    return 0


if __name__ == "__main__":
    sys.exit(main())
