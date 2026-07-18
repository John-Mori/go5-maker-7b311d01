#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""艦隊dead-man (恒久-1・2026-07-18) — 常駐supervisor自身の停止を独立に検知しDiscordへ通知する。

なぜ必要か (既存監視の唯一の穴):
  既に supervise_daemons.ps1 が6常駐を10分毎に「1個ずつ生存・欠けたら再起動」している(自己修復)。
  absence_watchdog.py が受信箱の滞留を検知して通知している。だが——
  **supervisor自身が止まったら誰も気づかない**。logonタスクが発火しない(INC-78型)・
  タスクが無効化・PCの状態でスケジューラが回らない、等で自己修復層ごと静かに死ぬ。
  supervisorが死ねば absence_watchdog も含む全常駐がやがて落ち、しかも「落ちた通知」すら出ない。
  = 現状の単一障害点。ここだけを、既存を重複せずに塞ぐ。

やること (最小・低誤検知):
  ・supervisorが毎回書く local/_daemons_supervisor.log の mtime を見る。
    supervisorは10分間隔なので、STALE_MIN(既定25分=2.5周期)を超えて更新が無ければ「supervisor停止」。
  ・加えて最新サイクルの各常駐が "ok" かを軽く点検し、欠落/連続再起動があれば併記。
  ・状態遷移でのみ通知(healthy->down で1回・down->healthy で復帰1回)。連投しない(INC-79 狼少年の回避)。
  ・通知は incident ch へ persona_send 経由。判定は読み取り専用(ログを消さない・書き換えない)。

限界(正直に明記):
  本チェッカーは「PCが起きていてログオン中」に走る前提(logonタスク or run_in_background)。
  Windows Update再起動→ロック画面(logon-gap)では、このチェッカー自身も走れないため
  「PCごと落ちた」ケースは検知できない=それは外部監視(Cloudflare cron等・恒久-1の次段)の領分。
  本チェッカーが塞ぐのは「PCは生きているのにsupervisor/常駐が死んだ」ケース。

使い方:
  python scripts/_daemons/deadman_check.py --once            # 1回判定(スケジューラ用)
  python scripts/_daemons/deadman_check.py --once --dry-run  # 送信せず判定結果だけ表示
  python scripts/_daemons/deadman_check.py --stale-min 25    # 常駐(既定=--once相当を15分間隔)

依存ゼロ(標準ライブラリ+ persona_send をsubprocess呼び)。utf-8。
"""
import argparse
import json
import os
import re
import subprocess
import sys
import time

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)
except Exception:
    pass

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.normpath(os.path.join(HERE, "..", ".."))
SUP_LOG = os.path.join(ROOT, "local", "_daemons_supervisor.log")
STATE = os.path.join(ROOT, "local", "_deadman_state.json")
PERSONA_SEND = os.path.join(ROOT, "scripts", "discord", "persona_send.py")

EXPECTED = ["inbox_poller", "absence_watchdog", "local_responder",
            "gemini_responder", "office_daily", "claude_responder"]


def _now():
    return time.strftime("%Y-%m-%d %H:%M:%S")


def _load_state():
    try:
        with open(STATE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {"status": "ok", "since": _now()}


def _save_state(st):
    os.makedirs(os.path.dirname(STATE), exist_ok=True)
    with open(STATE, "w", encoding="utf-8") as f:
        json.dump(st, f, ensure_ascii=False, indent=2)


def _tail(path, n=60):
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            return f.readlines()[-n:]
    except Exception:
        return []


def assess(stale_min):
    """(is_down: bool, reasons: list[str]) を返す。"""
    reasons = []
    if not os.path.exists(SUP_LOG):
        return True, ["supervisorログが存在しない(=一度も走っていない/パス相違)"]
    age_min = (time.time() - os.path.getmtime(SUP_LOG)) / 60.0
    if age_min > stale_min:
        reasons.append(f"supervisorが{age_min:.0f}分間ログを書いていない(閾値{stale_min}分・10分間隔で回るはず)=停止の疑い")
        return True, reasons
    # supervisorは生きている。最新サイクルで欠落/連続再起動の常駐があれば併記(downとはしない=supervisorが直す)。
    lines = _tail(SUP_LOG, 80)
    recent = "".join(lines)
    for name in EXPECTED:
        # 直近に "name: ok" が1つも無い かつ "name" 行自体はある → 異常の芽
        if re.search(re.escape(name) + r":\s*ok", recent) is None and name in recent:
            reasons.append(f"注意: 最新サイクルで {name} が ok になっていない(再起動中/欠落の可能性)")
    return False, reasons


def notify(text, dry_run):
    if dry_run:
        print("[dry-run] 送信内容:\n" + text)
        return True
    try:
        p = subprocess.run(
            [sys.executable, PERSONA_SEND, "--dept", "incident", "--persona", "オタコン", text],
            capture_output=True, text=True, timeout=60)
        ok = "204" in (p.stdout or "") or p.returncode == 0
        print((p.stdout or "").strip()[-200:])
        return ok
    except Exception as e:
        print(f"通知送信に失敗: {e}")
        return False


def run_once(stale_min, dry_run):
    st = _load_state()
    was_down = st.get("status") == "down"
    is_down, reasons = assess(stale_min)

    if is_down and not was_down:
        msg = ("🚨 **艦隊dead-man検知** — 常駐supervisorが停止している疑い。\n"
               + "\n".join("・" + r for r in reasons)
               + "\n自己修復層(supervise_daemons)が止まると、受信・応答・監視の全常駐がやがて落ちます。"
               + "\n対処: PCで `scripts\\_daemons\\register_daemons_logon_task.ps1` の再登録 or 手動起動を確認。")
        sent = notify(msg, dry_run)
        st = {"status": "down", "since": _now(), "alerted": bool(sent), "reasons": reasons}
        _save_state(st)
        print(f"[DOWN] 通知={'送信' if sent else '失敗'} / {reasons}")
        return 2

    if (not is_down) and was_down:
        msg = ("✅ 艦隊dead-man復帰 — supervisorのログ更新を再確認。監視・応答系は回復しています。")
        notify(msg, dry_run)
        st = {"status": "ok", "since": _now()}
        _save_state(st)
        print("[RECOVERED] 復帰通知を送信")
        return 0

    # 状態は前回と同じ。downの連投はしない。okでも注意点があればログにだけ出す。
    st["status"] = "down" if is_down else "ok"
    _save_state(st)
    if reasons and not is_down:
        print("[OK・注意あり] " + " / ".join(reasons))
    else:
        print("[DOWN・通知済(連投しない)]" if is_down else "[OK] supervisor生存・艦隊正常")
    return 2 if is_down else 0


def main():
    ap = argparse.ArgumentParser(description="艦隊dead-man(恒久-1)")
    ap.add_argument("--once", action="store_true", help="1回判定して終了(スケジューラ用)")
    ap.add_argument("--dry-run", action="store_true", help="送信せず判定だけ")
    ap.add_argument("--stale-min", type=int, default=25, help="supervisorログのstale閾値(分・既定25)")
    ap.add_argument("--interval-min", type=int, default=15, help="常駐時の判定間隔(分)")
    a = ap.parse_args()
    if a.once:
        sys.exit(run_once(a.stale_min, a.dry_run))
    # 常駐モード
    while True:
        run_once(a.stale_min, a.dry_run)
        time.sleep(max(60, a.interval_min * 60))


if __name__ == "__main__":
    main()
