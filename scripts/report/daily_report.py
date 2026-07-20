#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""daily_report — 日次報告便 (報告-通知部門の核心職務・Chami裁定2026-07-19)。

裁定 (学習ルーム1 msg 1528068853337292930・Chami原文):
  1A: 常駐維持+日次報告便。**「こちらからやめると言わない限り続けて」= 設計書§3.4の
      撤退基準 (3便無反応で停止裁定) は無効**。Chamiが止めるまで続ける。
  2A修正: **毎日2便 (0:00 と 8:00)**。0時=日付が変わった合図 / 8時=朝に残タスクを再把握。
      内容の重複は問題ない (Chami明言)。
  実装方式: 設計書§3.4はTTL起床のマーカー方式だったが、固定時刻の指定により
  スケジュールタスク方式 (go5_sla_nightlyと同パターン) へ。report-notifyセッションの
  生死に依存せず毎日届く=「セッションが閉じている日は便が出ない」の限界も同時に解消。

内容 (設計書§3.4準拠・20行以内・オタコン名義):
  ①前日の各部門ch動静 (discord_processed.jsonl のdept別件数)
  ②ちゃみ確認待ち (HQ QA STATUSのopen行から抽出)
  ③自動系の異常有無 (鳩の脈・死んだ窓・キューのdead letter・watchdog直近発報)
  ※④P3軽微進捗の集約はv1未実装 (正直に明記)。

使い方: python scripts/report/daily_report.py [--send] (--send無しは印字のみ=検証用)
"""
import glob
import json
import os
import subprocess
import sys
import time
from datetime import datetime, timezone, timedelta

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.normpath(os.path.join(HERE, "..", ".."))
LOCAL = os.path.join(ROOT, "local")
HQ_STATUS = r"D:\SougouStartFolder\00_AI-HQ\departments\qa\STATUS.md"
WINDOW_SKIP = ("router", "llm-growth", "gemini")


def dept_activity(hours=24):
    """discord_processed.jsonl から直近hours時間のdept別件数。"""
    cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)
    counts = {}
    p = os.path.join(LOCAL, "discord_processed.jsonl")
    if os.path.exists(p):
        for l in open(p, encoding="utf-8"):
            if not l.strip():
                continue
            try:
                d = json.loads(l)
                ts = datetime.fromisoformat(str(d.get("ts", "")).replace("Z", "+00:00"))
                if ts.tzinfo is None:          # tz無しの行はUTCとみなす (naive/aware比較エラー回避)
                    ts = ts.replace(tzinfo=timezone.utc)
            except (ValueError, TypeError):
                continue
            if ts >= cutoff:
                counts[d.get("dept", "?")] = counts.get(d.get("dept", "?"), 0) + 1
    return dict(sorted(counts.items(), key=lambda x: -x[1]))


def chami_pending():
    """HQ QA STATUSのopen表から「ちゃみ」が待ち先の行を抽出 (機械可読な範囲の正直な近似)。"""
    out = []
    try:
        for l in open(HQ_STATUS, encoding="utf-8"):
            if l.startswith("|") and "ちゃみ" in l and ("待ち" in l or "| ちゃみ" in l):
                cells = [c.strip() for c in l.split("|")]
                if len(cells) > 1 and cells[1] and not cells[1].startswith("-"):
                    out.append(cells[1][:40])
    except OSError:
        pass
    return out[:5]


CLAUDE_BIN = r"C:\Users\chami\.local\bin\claude.exe"


def token_health():
    """合鍵(cli_auth_token)が生きているか安価なpingで"事前"確認する(段階1・INC-109の教訓)。
    失効を放置すると全デーモンが黙って死に、lab_reviveが無効な今でも一次応答が止まる。
    毎日2便で先回り検知し、失効の兆しを報告-通知へ出す=「気づいた時には手遅れ」を防ぐ。"""
    tf = os.path.join(LOCAL, "cli_auth_token.txt")
    try:
        tok = open(tf, encoding="utf-8").read().strip()
    except OSError:
        return "🔑合鍵: ★ファイル無し(要 claude setup-token)"
    if not tok:
        return "🔑合鍵: ★空(要 claude setup-token)"
    # ★狼少年防止: タイムアウト≠失効(コールドスタートは60s超あり)。アラームは"実際の認証エラー
    #   文言"が出た時だけ。タイムアウトは「遅延・判定保留」に留める。失効は401で速く返る(遅延ではない)。
    env = dict(os.environ)
    env["CLAUDE_CODE_OAUTH_TOKEN"] = tok
    try:
        p = subprocess.run([CLAUDE_BIN, "--print", "--model", "sonnet", "ok"],
                           capture_output=True, text=True, encoding="utf-8",
                           errors="replace", timeout=120, env=env)
    except subprocess.TimeoutExpired:
        return "🔑合鍵: 応答遅延(判定保留・起動が重いだけの可能性)"
    except Exception:
        return "🔑合鍵: 照会不可"
    blob = (p.stdout or "") + (p.stderr or "")
    if p.returncode == 0 and (p.stdout or "").strip():
        return "🔑合鍵: 正常"
    if any(k in blob for k in ("expired", "authenticate", "401", "Invalid")):
        return "🔑合鍵: ★失効の疑い(要 claude setup-token 再認証)"
    return "🔑合鍵: ★応答異常(要確認)"


def system_health():
    now = time.time()
    lines = []
    p = os.path.join(LOCAL, "llm", "poller_active.txt")
    age = now - os.path.getmtime(p) if os.path.exists(p) else 9e9
    lines.append(f"鳩: {'正常' if age < 300 else '★停止疑い(' + str(int(age)) + '秒)'}")
    dead = 0
    for f in glob.glob(os.path.join(LOCAL, "llm", "claude_active_*.txt")):
        dept = os.path.basename(f)[len("claude_active_"):-4]
        if dept in WINDOW_SKIP:
            continue
        a = now - os.path.getmtime(f)
        if 20 * 60 <= a < 12 * 3600:
            dead += 1
    lines.append(f"死んだ窓: {dead}件" if dead else "窓: 異常なし")
    try:
        sys.path.insert(0, os.path.join(ROOT, "scripts", "queue"))
        from leasequeue import LeaseQueue
        st = LeaseQueue(os.path.join(LOCAL, "queue", "inbox.db")).stats()
        lines.append(f"キュー: ready={st['ready']} dead={st['dead']}"
                     + (" ★dead letter要確認" if st["dead"] else ""))
    except Exception:
        lines.append("キュー: 照会不可")
    lines.append(token_health())   # ★段階1: 合鍵の事前健全性チェック
    return lines


def build_report():
    now = datetime.now()
    label = "0時便 (日付が変わった合図)" if now.hour < 4 else "8時便 (朝の残タスク再把握)"
    acts = dept_activity(24)
    pend = chami_pending()
    health = system_health()
    L = [f"■日次報告便 {now.strftime('%m/%d %H:%M')} — {label}"]
    L.append("①直近24hの動静: " + (
        "、".join(f"{d}={n}件" for d, n in list(acts.items())[:6]) if acts else "受信なし"))
    if pend:
        L.append("②ちゃみ確認待ち:")
        for x in pend:
            L.append(f"  ・{x}")
    else:
        L.append("②ちゃみ確認待ち: なし (QA台帳上)")
    L.append("③自動系: " + " / ".join(health))
    # ④P3軽微進捗の集約はv1未実装。定型の断り文言はChami指示(2026-07-20 msg=1528419155231903764)で廃止。
    return "\n".join(L[:20])


def main():
    text = build_report()
    print(text)
    if "--send" in sys.argv:
        tmp = os.path.join(LOCAL, "_daily_report_body.txt")
        with open(tmp, "w", encoding="utf-8") as f:
            f.write(text)
        r = subprocess.run([sys.executable, os.path.join(ROOT, "scripts", "discord", "persona_send.py"),
                            "--dept", "report-notify", "--persona", "オタコン", "--body-file", tmp],
                           capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=60)
        print((r.stdout or "").strip().splitlines()[-1] if r.stdout else f"送信失敗 rc={r.returncode}")
        return 0 if r.returncode == 0 else 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
