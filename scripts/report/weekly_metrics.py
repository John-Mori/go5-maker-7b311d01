#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""weekly_metrics — オーケストレーション週次メトリクス便(段階3・2026-07-20)。

狙い: 「システムが働いている様子」を週1で可視化し、静かな劣化を早く掴む。
  ・直近7日の部門別動静(discord_processed.jsonl)
  ・キュー深さ(ready/dead/done)・デッドレターの有無
  ・艦隊の生存スナップショット(常駐+dept_daemon)
  ・合鍵(トークン)健全性・認証/DLQアラートの状態

read-only集計のみ。--send で報告-通知(オタコン名義)へ投稿。無しは印字(検証用)。
utf-8厳守(cp932復号・BOMの罠を踏まない)。標準ライブラリのみ。
"""
import glob
import json
import os
import subprocess
import sys
import time
from datetime import datetime, timezone

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.normpath(os.path.join(HERE, "..", ".."))
LOCAL = os.path.join(ROOT, "local")
PERSONA_SEND = os.path.join(ROOT, "scripts", "discord", "persona_send.py")
PROCESSED = os.path.join(LOCAL, "discord_processed.jsonl")
QDB = os.path.join(LOCAL, "queue", "inbox.db")
CLAUDE_BIN = r"C:\Users\chami\.local\bin\claude.exe"
WEEK_SEC = 7 * 24 * 3600


def _parse_ts(s):
    try:
        return datetime.fromisoformat(str(s)).timestamp()
    except Exception:
        return None


def dept_activity_7d():
    """直近7日の部門別メッセージ件数(processed台帳から)。"""
    now = time.time()
    counts = {}
    try:
        for l in open(PROCESSED, encoding="utf-8", errors="replace"):
            if not l.strip():
                continue
            try:
                r = json.loads(l)
            except Exception:
                continue
            t = _parse_ts(r.get("ts"))
            if t is None or now - t > WEEK_SEC:
                continue
            d = r.get("dept") or "(不明)"
            counts[d] = counts.get(d, 0) + 1
    except OSError:
        return {}, 0
    total = sum(counts.values())
    return counts, total


def queue_stats():
    if not os.path.exists(QDB):
        return None
    try:
        sys.path.insert(0, os.path.join(ROOT, "scripts", "queue"))
        from leasequeue import LeaseQueue
        return LeaseQueue(QDB).stats()
    except Exception:
        return None


def fleet_snapshot():
    """常駐+dept_daemonの生存数(PowerShellでプロセス照会)。"""
    scripts = ["discord_gateway", "daemon_keeper", "dept_daemon", "absence_watchdog",
               "local_responder", "gemini_responder", "claude_responder", "office_daily"]
    try:
        cmd = ("Get-CimInstance Win32_Process -Filter \"Name='python.exe'\" | "
               "Select-Object -ExpandProperty CommandLine")
        p = subprocess.run(["powershell", "-NoProfile", "-Command", cmd],
                           capture_output=True, text=True, encoding="utf-8",
                           errors="replace", timeout=30)
        out = p.stdout or ""
        up = [s for s in scripts if (s + ".py") in out]
        dept_n = out.count("dept_daemon.py")
        return f"常駐 {len([s for s in up if s != 'dept_daemon'])}/7 + dept_daemon {dept_n}/9"
    except Exception:
        return "(照会不可)"


def token_health():
    tf = os.path.join(LOCAL, "cli_auth_token.txt")
    try:
        tok = open(tf, encoding="utf-8").read().strip()
    except OSError:
        return "★ファイル無し"
    if not tok:
        return "★空"
    env = dict(os.environ)
    env["CLAUDE_CODE_OAUTH_TOKEN"] = tok
    try:
        p = subprocess.run([CLAUDE_BIN, "--print", "--model", "sonnet", "ok"],
                           capture_output=True, text=True, encoding="utf-8",
                           errors="replace", timeout=120, env=env)
    except subprocess.TimeoutExpired:
        return "応答遅延(判定保留)"
    except Exception:
        return "照会不可"
    blob = (p.stdout or "") + (p.stderr or "")
    if p.returncode == 0 and (p.stdout or "").strip():
        return "正常"
    if any(k in blob for k in ("expired", "authenticate", "401", "Invalid")):
        return "★失効の疑い(要 claude setup-token)"
    return "★応答異常"


def alert_states():
    """認証/DLQの直近アラート状態(state fileから・read-only)。"""
    out = []
    ast = os.path.join(LOCAL, "_auth_alert_state.json")
    if os.path.exists(ast):
        try:
            st = json.load(open(ast, encoding="utf-8"))
            age_h = (time.time() - st.get("last", 0)) / 3600.0
            if age_h < 24 * 7:
                out.append(f"認証アラート発報あり({age_h:.0f}h前)")
        except Exception:
            pass
    wd = os.path.join(LOCAL, "discord_watchdog_state.json")
    if os.path.exists(wd):
        try:
            st = json.load(open(wd, encoding="utf-8"))
            if st.get("last_dead_count", 0) > 0:
                out.append(f"デッドレター{st['last_dead_count']}件")
            lh = st.get("link_health", {})
            down = [k for k, v in lh.items() if v == "down"]
            if down:
                out.append("リンクdown: " + "、".join(down))
        except Exception:
            pass
    return out or ["特筆事項なし"]


def build():
    now = datetime.now()
    acts, total = dept_activity_7d()
    top = sorted(acts.items(), key=lambda kv: -kv[1])[:8]
    qs = queue_stats()
    L = [f"📊 **週次メトリクス便** {now.strftime('%m/%d %H:%M')}(直近7日)"]
    L.append(f"①受信 計{total}件 / 部門別: " +
             ("、".join(f"{d}={n}" for d, n in top) if top else "受信なし"))
    if qs:
        L.append(f"②キュー: ready={qs['ready']} / done={qs['done']} / dead={qs['dead']}" +
                 (" ★dead要確認" if qs["dead"] else ""))
    L.append(f"③艦隊: {fleet_snapshot()}")
    L.append(f"④合鍵(トークン): {token_health()}")
    L.append("⑤特筆: " + " / ".join(alert_states()))
    return "\n".join(L[:20])


def main():
    text = build()
    print(text)
    if "--send" in sys.argv:
        tmp = os.path.join(LOCAL, "_weekly_metrics_body.txt")
        with open(tmp, "w", encoding="utf-8") as f:
            f.write(text)
        subprocess.run([sys.executable, PERSONA_SEND, "--dept", "report-notify",
                        "--persona", "オタコン", "--body-file", tmp],
                       capture_output=True, timeout=60)


if __name__ == "__main__":
    main()
