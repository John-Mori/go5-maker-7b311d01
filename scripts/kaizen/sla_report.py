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
import re
import statistics
import sys
import urllib.request
from datetime import datetime, timedelta, timezone

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.normpath(os.path.join(HERE, "..", ".."))
LOCAL = os.path.join(ROOT, "local")
HQ_ROOT = os.path.normpath(os.path.join(ROOT, "..", "00_AI-HQ"))
API = "https://discord.com/api/v10"
TARGET_P95_S = 900.0   # 本回答p95の目標=15分(Chami基準)
WATCH_P95_S = 600.0    # 様子見の下限=10分


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


def load_display_map():
    """org_registry.yml から dept(slug)→display_ja を作る(PyYAML不要の行走査)。
    引けない部屋は呼び出し側で生のチャンネル名にフォールバックする。"""
    m, cur = {}, None
    try:
        for ln in open(os.path.join(HQ_ROOT, "org_registry.yml"), encoding="utf-8"):
            mk = re.match(r"^  ([A-Za-z0-9_-]+):\s*$", ln.rstrip("\n"))
            if mk:
                cur = mk.group(1)
                continue
            if cur and "display_ja:" in ln:
                v = ln.split("display_ja:", 1)[1].split("#", 1)[0].strip()
                if v:
                    m[cur] = v
                cur = None
    except OSError:
        pass
    return m


def evaluate(rows, p95_all):
    """毎晩の通知に自動でQA判定を添える(Chami『これ読み取って評価できるように』2026-07-31)。
    基準= 本回答p95≤15分。n<5は統計的に不安定なので目標超過の断定はせず様子見に回す。"""
    fails, watch = [], []
    for r in rows:
        lats = r.get("lats")
        if not lats:
            continue
        n, worst = len(lats), max(lats)
        p95 = r.get("p95", worst)
        disp, un = r["disp"], r.get("un", 0)
        if n >= 5 and p95 > TARGET_P95_S:
            fails.append((p95, disp, f"{disp} p95={fmt(p95)}(n={n})"))
        elif worst > TARGET_P95_S or un or (n >= 5 and p95 > WATCH_P95_S):
            tag = f"最悪={fmt(worst)}"
            if n < 5:
                tag += "・低nで参考"
            if un:
                tag += f"・未応答{un}"
            watch.append(f"{disp} {tag}(n={n})")
    fails.sort(reverse=True)
    out = ["", "── QA自動評価 (基準: 本回答p95≤15分) ──"]
    out.append("目標超過(要対処): " + (" / ".join(t for _, _, t in fails) if fails else "なし"))
    if watch:
        out.append("様子見: " + " / ".join(watch))
    verdict = "達成" if p95_all <= TARGET_P95_S else "未達"
    tail = f" 主因は{fails[0][1]}。" if fails else ""
    out.append(f"全体: p95={fmt(p95_all)} → 目標{verdict}。{tail}")
    return out


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

    display = load_display_map()
    rows, all_lat = [], []
    for ch in channels:
        cid = str(ch.get("id", ""))
        if not cid.isdigit():
            continue
        disp = display.get(ch.get("dept", ""), ch.get("name", cid))
        try:
            msgs = api_get(f"/channels/{cid}/messages?limit=100", token)
        except Exception as e:
            rows.append({"name": ch.get("name", cid), "disp": disp, "lats": None,
                         "un": 0, "note": f"取得失敗:{type(e).__name__}"})
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
            rows.append({"name": ch.get("name", cid), "disp": disp, "lats": lats,
                         "un": unanswered, "note": f"未応答{unanswered}" if unanswered else ""})

    lines = [f"部屋別 応答時間 (直近{hours:g}時間・人間の発言→最初のBot応答)"]
    for r in rows:
        name, lats, note = r["name"], r["lats"], r["note"]
        if lats is None:
            lines.append(f"  {name}: {note}")
        elif not lats:
            lines.append(f"  {name}: 応答実績なし {note}")
        else:
            # method='inclusive'= p95が観測最悪値を超えない(既定のexclusiveは小n時に外挿し最悪値超えの偽p95を出す)
            p95 = statistics.quantiles(lats, n=20, method="inclusive")[-1] if len(lats) >= 2 else lats[0]
            r["p95"] = p95
            lines.append(f"  {name}: n={len(lats)} 中央値={fmt(statistics.median(lats))}"
                         f" p95={fmt(p95)} 最悪={fmt(max(lats))} {note}")
    if all_lat:
        p95a = statistics.quantiles(all_lat, n=20, method="inclusive")[-1] if len(all_lat) >= 2 else all_lat[0]
        lines.append(f"全体: n={len(all_lat)} 中央値={fmt(statistics.median(all_lat))}"
                     f" p95={fmt(p95a)} (目標: 受領≤60秒/本回答p95≤15分)")
        lines += evaluate(rows, p95a)
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
