#!/usr/bin/env python3
"""work_model_check — **work便(作業agent)が実際にどのモデルで動いたか**を部門×モデルで数える。
読むだけ・何も変更しない。

★なぜ要るか(2026-08-23 研究室HQ)
  ②「work だけ Sonnet(hq / 改修部門α / プラットフォームSE の3室)」の受け入れ判定に、
  `quota_burn.py --by model`(組織全体の sonnet便数)を使う話になっていた。**これでは判定できない。**

  1. work便は `dept_daemon` が `claude --print` で**その都度新しいセッション**として起こす
     (`dept_daemon.py:5061`)。sid は部屋の見張り(`context_watch.jsonl`)に載らないので、
     `quota_burn --by dept` では **全部「手動/不明」へ落ちる**= 部屋ごとに見えない。
  2. 組織全体の sonnet便には**サブエージェント(agent-*)と手作業のセッションが混ざる**。
     実測(08/22 15:00〜08/23 15:00)= sonnet 941便の内訳は 研究室メイン 547 / 手動/不明 394 で、
     **3室の relay便は 5,295便すべて Opus**。②の効き目は、この混ざった数字の中では埋もれる。

  → **work便には専用の台帳がある**= `local/llm/work_audit.jsonl`(`_audit_work()` が
     便ごとに `dept` と `model` を実測で書いている)。②の判定はここを数えるのが正しい。
     これは自己申告ではなく、起動時に渡した `--model` の値そのものだ。

使い方:
  python scripts/llm/work_model_check.py                       # 直近24時間
  python scripts/llm/work_model_check.py --hours 24 --ago 24   # 24時間前に終わる24時間の窓(前後比較)
  python scripts/llm/work_model_check.py --dept hq,system-engineer,platform-se
"""
import argparse
import collections
import io
import json
import os
import sys
from datetime import datetime, timedelta, timezone

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

JST = timezone(timedelta(hours=9))
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
AUDIT = os.path.join(ROOT, "local", "llm", "work_audit.jsonl")


def load(start, end):
    """[start, end] (JST) の work便を読む。ts はJSTのナイーブ文字列で書かれている。"""
    out = []
    if not os.path.exists(AUDIT):
        return out
    with io.open(AUDIT, encoding="utf-8-sig", errors="replace") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except ValueError:
                continue                      # 壊れた行は数えない(黙って落とさず末尾で件数を出す)
            ts = rec.get("ts") or ""
            try:
                dt = datetime.fromisoformat(ts).replace(tzinfo=JST)
            except ValueError:
                continue
            if start <= dt <= end:
                out.append((dt, rec.get("dept") or "?", rec.get("model") or "?",
                            rec.get("rc"), rec.get("sec") or 0,
                            rec.get("relay_reason")))
    return out


def short(m):
    return (m or "?").replace("claude-", "")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--hours", type=float, default=24.0, help="窓の長さ(時間)")
    ap.add_argument("--ago", type=float, default=0.0, help="窓の右端をN時間前へずらす")
    ap.add_argument("--dept", default=None, help="部門で絞る(カンマ区切りのslug)")
    a = ap.parse_args()

    now = datetime.now(JST)
    end = now - timedelta(hours=a.ago)
    start = end - timedelta(hours=a.hours)
    rows = load(start, end)
    want = {s.strip() for s in a.dept.split(",")} if a.dept else None
    if want:
        rows = [r for r in rows if r[1] in want]

    print("== work便(作業agent)のモデル内訳 / %s 〜 %s JST%s ==" % (
        start.strftime("%m/%d %H:%M"), end.strftime("%m/%d %H:%M"),
        (" / 部門= " + ",".join(sorted(want))) if want else ""))
    print("台帳= local/llm/work_audit.jsonl(dept_daemon が便ごとに実測で書いた model)")
    if not rows:
        print("この窓に work便が無い")
        return

    per = collections.defaultdict(collections.Counter)
    models = collections.Counter()
    reasons = collections.Counter()
    for _dt, dept, model, _rc, _sec, reason in rows:
        per[dept][short(model)] += 1
        models[short(model)] += 1
        reasons[reason or "(記録前の便)"] += 1

    cols = [m for m, _ in models.most_common()]
    print()
    print("%-18s %6s  %s" % ("部門", "work便", "  ".join("%-14s" % c for c in cols)))
    for dept, cnt in sorted(per.items(), key=lambda x: -sum(x[1].values())):
        tot = sum(cnt.values())
        cells = "  ".join("%-14s" % (("%d" % cnt[c]) if cnt[c] else "-") for c in cols)
        print("%-18s %6d  %s" % (dept[:18], tot, cells))
    print("%-18s %6d  %s" % ("== 合計", len(rows),
                             "  ".join("%-14s" % models[c] for c in cols)))
    son = sum(v for k, v in models.items() if "sonnet" in k)
    print()
    print("★sonnetのwork便= %d / %d (%.1f%%)" % (son, len(rows), son / len(rows) * 100))

    # ★★2026-08-23 研究室HQ発注(msg DISPATCH-aegis-gl-1787469264964)。
    #   「sonnetが増えた/増えない」だけでは **①配線が死んでいる ②守りが食った
    #   ③守りが効かず落としてはいけない便まで落ちた** の3つが同じ顔で出る。
    #   ③は品質事故なのに「大成功」に見える= **理由の内訳が要る。**
    #   語は `dept_daemon.work_relay_decide` が返した1語をそのまま台帳へ載せた物。
    print()
    print("== ②を適用しなかった理由の内訳(relay_reason) ==")
    labels = {"ok": "Sonnetへ落とした", "not_work": "作業便でない", "chami": "Chami本人の便=守った",
              "marker": "🔥/炎上/インシデント=守った", "not_listed": "②の名簿に無い部屋",
              "error": "判定不能=高い方で回した",
              "(記録前の便)": "★理由を書く前の便(2026-08-23 17時より前)"}
    for k, v in reasons.most_common():
        print("  %-28s %5d (%.1f%%)  %s"
              % (k, v, v / len(rows) * 100, labels.get(k, "")))
    known = len(rows) - reasons.get("(記録前の便)", 0)
    if known == 0:
        print("\n★この窓は全便が『理由を書く前』= 帯の判定はできない(まだ標本が無い)。")
        return
    dropped = reasons.get("ok", 0)
    pct = dropped / known * 100
    print("\n★理由の在る便 %d 本のうち Sonnetへ落ちたのは %d 本 (%.1f%%)" % (known, dropped, pct))
    # ★帯は研究室HQが queue経路の実測(全便225/作業便62・Chami27%・マーカー29%・落とす43.5%)
    #   から出した予測。**分母が違う**(あちらはqueueテーブルの便だけ)ので目安として使う。
    if pct < 10:
        print("  → ★**ほぼ0**= まだどこかで死んでいる。上の内訳で『どの語で止まったか』を見ろ。")
    elif pct > 90:
        print("  → ★**ほぼ10割**= 守り(Chami便・🔥)が効いていない=**品質事故**。即差し戻し。")
    elif 40 <= pct <= 60:
        print("  → ★**予測帯(4〜6割)の中**= 配線は生きている。**合格。**")
    else:
        print("  → 帯(4〜6割)の外だが0でも10割でもない= 便の中身の偏り。内訳で説明が付くか見ろ。")


if __name__ == "__main__":
    main()
