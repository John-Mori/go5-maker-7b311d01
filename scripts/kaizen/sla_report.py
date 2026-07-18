#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""部屋別の応答時間レポート (P6・応答性改善書2026-07-18・QA起草/Chami承認「実装して」)。

各チャンネルの直近メッセージをDiscord APIから読み(読み取りのみ)、
「人間の発言 → その後最初のBot/Webhook応答」までの秒数を部屋別に集計する。
体感論争を数字で終わらせるための計測器。目標値: 受領≤60秒 / 本回答p95≤15分(在宅時)。

使い方:
  python scripts/kaizen/sla_report.py                # 直近24時間
  python scripts/kaizen/sla_report.py --hours 6      # 直近6時間
  python scripts/kaizen/sla_report.py --send         # 結果を品質管理chへMk.II名義で送る
"""
import json
import os
import statistics
import sys
import urllib.request
from datetime import datetime, timedelta, timezone

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.normpath(os.path.join(HERE, "..", ".."))
LOCAL = os.path.join(ROOT, "local")
API = "https://discord.com/api/v10"


def api_get(path, token):
    req = urllib.request.Request(f"{API}{path}", headers={
        "Authorization": f"Bot {token}", "User-Agent": "go5-sla-report/1.0"})
    with urllib.request.urlopen(req, timeout=20) as r:
        return json.loads(r.read().decode("utf-8"))


def is_bot(m):
    return bool(m.get("webhook_id")) or bool(m.get("author", {}).get("bot"))


def fmt(sec):
    if sec is None:
        return "—"
    if sec < 90:
        return f"{sec:.0f}秒"
    return f"{sec / 60:.1f}分"


def main():
    hours = 24.0
    send = "--send" in sys.argv
    if "--hours" in sys.argv:
        try:
            hours = float(sys.argv[sys.argv.index("--hours") + 1])
        except (IndexError, ValueError):
            pass
    token = open(os.path.join(LOCAL, "discord_bot_token.txt"), encoding="utf-8").read().strip()
    channels = json.load(open(os.path.join(LOCAL, "discord_channels.json"), encoding="utf-8"))
    cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)

    rows, all_lat = [], []
    for ch in channels:
        cid = str(ch.get("id", ""))
        if not cid.isdigit():
            continue
        try:
            msgs = api_get(f"/channels/{cid}/messages?limit=100", token)
        except Exception as e:
            rows.append((ch.get("name", cid), None, f"取得失敗:{type(e).__name__}"))
            continue
        msgs.sort(key=lambda m: m.get("timestamp", ""))  # 古→新
        lats, unanswered = [], 0
        for i, m in enumerate(msgs):
            if is_bot(m):
                continue
            try:
                mt = datetime.fromisoformat(m["timestamp"])
            except (KeyError, ValueError):
                continue
            if mt < cutoff:
                continue
            reply = next((x for x in msgs[i + 1:] if is_bot(x)), None)
            if reply is None:
                unanswered += 1
                continue
            try:
                lat = (datetime.fromisoformat(reply["timestamp"]) - mt).total_seconds()
            except (KeyError, ValueError):
                continue
            if lat >= 0:
                lats.append(lat)
        if lats or unanswered:
            all_lat.extend(lats)
            rows.append((ch.get("name", cid), lats, f"未応答{unanswered}" if unanswered else ""))

    lines = [f"部屋別 応答時間 (直近{hours:g}時間・人間の発言→最初のBot応答)"]
    for name, lats, note in rows:
        if lats is None:
            lines.append(f"  {name}: {note}")
        elif not lats:
            lines.append(f"  {name}: 応答実績なし {note}")
        else:
            p95 = statistics.quantiles(lats, n=20)[-1] if len(lats) >= 2 else lats[0]
            lines.append(f"  {name}: n={len(lats)} 中央値={fmt(statistics.median(lats))}"
                         f" p95={fmt(p95)} 最悪={fmt(max(lats))} {note}")
    if all_lat:
        p95a = statistics.quantiles(all_lat, n=20)[-1] if len(all_lat) >= 2 else all_lat[0]
        lines.append(f"全体: n={len(all_lat)} 中央値={fmt(statistics.median(all_lat))}"
                     f" p95={fmt(p95a)} (目標: 受領≤60秒/本回答p95≤15分)")
    else:
        lines.append("対象期間に人間の発言がありません。")
    text = "\n".join(lines)
    print(text)
    if send:
        import subprocess
        with open(os.path.join(LOCAL, "_sla_report_body.txt"), "w", encoding="utf-8") as f:
            f.write(text)
        subprocess.run([sys.executable, os.path.join(ROOT, "scripts", "discord", "persona_send.py"),
                        "--dept", "qa-reviewer", "--persona", "メタルギアMk.II",
                        "--body-file", os.path.join(LOCAL, "_sla_report_body.txt")],
                       timeout=60)
    return 0


if __name__ == "__main__":
    sys.exit(main())
