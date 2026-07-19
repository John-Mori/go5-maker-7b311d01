#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""起動時の復帰報告 (O1・改善書P0-7)。

PCが再起動した後、最初にこれが走った時に「前回シャットダウンの理由」+ 艦隊の自己点検を
報告-通知部屋へ**1回だけ**投稿する。モニターを消していても、起きた時に何が起きたか分かる
(2026-07-19: Chamiは離席中のWindows Update再起動を、事後のエラーダイアログで初めて知った)。

冪等: 現在のブート時刻を state に記録し、同じブートでは二度投稿しない。
起動経路: supervise_daemons.ps1 が毎パス --once で呼ぶ(ブート後10分以内に1回発火)。
これ自体は失敗しても supervisor を巻き込まない(全例外を飲む)。標準ライブラリ+PowerShell/persona_send のみ。

使い方:
  python scripts/_daemons/boot_report.py --once            # 新しいブートなら1回投稿
  python scripts/_daemons/boot_report.py --once --dry-run  # 送らず内容だけ表示
  python scripts/_daemons/boot_report.py --once --force    # 同じブートでも強制投稿(点検用)
"""
import json
import os
import subprocess
import sys
import time

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)
except Exception:
    pass

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.normpath(os.path.join(HERE, "..", ".."))
LOCAL = os.path.join(ROOT, "local")
STATE = os.path.join(LOCAL, "_boot_report_state.json")
PERSONA_SEND = os.path.join(ROOT, "scripts", "discord", "persona_send.py")
STATUS_PS1 = os.path.join(HERE, "status.ps1")
QDB = os.path.join(LOCAL, "queue", "inbox.db")
REPORT_DEPT = "report-notify"
PERSONA = "オタコン"


def _ps(cmd, timeout=30):
    """PowerShellを1回叩いてstdoutを返す。失敗は空文字(呼び側は空を許容)。"""
    try:
        r = subprocess.run(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", cmd],
                           capture_output=True, text=True, timeout=timeout)
        return (r.stdout or "").strip()
    except Exception:
        return ""


def boot_id():
    """このブートを一意に表す文字列(最終起動時刻)。取れなければ空。"""
    return _ps("(Get-CimInstance Win32_OperatingSystem).LastBootUpTime.ToString('yyyy-MM-dd HH:mm:ss')")


def shutdown_reasons():
    """直近2日の再起動/シャットダウン関連イベントを新しい順に最大5件。"""
    cmd = (
        "$e = Get-WinEvent -FilterHashtable @{LogName='System'; Id=1074,6006,6008,41; "
        "StartTime=(Get-Date).AddDays(-2)} -ErrorAction SilentlyContinue | "
        "Sort-Object TimeCreated | Select-Object -Last 5; "
        "$e | ForEach-Object { '{0} [{1}] {2}' -f $_.TimeCreated.ToString('MM-dd HH:mm'), "
        "$_.Id, ((($_.Message -split \"`n\")[0]).Trim()) }"
    )
    out = _ps(cmd)
    return [l for l in out.splitlines() if l.strip()]


def queue_health():
    """キュー深さの一行サマリ(fail-open)。"""
    if not os.path.exists(QDB):
        return "queue: (DB無し)"
    try:
        import sqlite3
        con = sqlite3.connect(f"file:{QDB}?mode=ro", uri=True, timeout=2)
        try:
            now = time.time()
            def n(q, a=()):
                try:
                    return con.execute(q, a).fetchone()[0]
                except Exception:
                    return "?"
            pend = n("SELECT COUNT(*) FROM queue WHERE status='pending' AND lease_until<?", (now,))
            dead = n("SELECT COUNT(*) FROM queue WHERE status='dead'")
            return f"queue: 未処理={pend} / dead={dead}"
        finally:
            con.close()
    except Exception:
        return "queue: (照会不可)"


def fleet_line():
    """常駐プロセスの生存を一行で(status.ps1の中核を軽く再現)。"""
    scripts = ["discord_gateway.py", "daemon_keeper.py", "dept_daemon.py", "absence_watchdog.py",
               "local_responder.py", "gemini_responder.py", "claude_responder.py", "office_daily.py"]
    cmd = ("Get-CimInstance Win32_Process -Filter \"Name='python.exe'\" | "
           "Select-Object -ExpandProperty CommandLine")
    out = _ps(cmd)
    up = []
    for s in scripts:
        cnt = out.count(s)
        if cnt:
            up.append(f"{s.replace('.py','')}x{cnt}" if s == "dept_daemon.py" else s.replace(".py", ""))
    return "常駐: " + (" / ".join(up) if up else "(まだ起動していない=supervisorが復旧中)")


def load_state():
    try:
        with open(STATE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def save_state(st):
    os.makedirs(os.path.dirname(STATE), exist_ok=True)
    with open(STATE, "w", encoding="utf-8") as f:
        json.dump(st, f, ensure_ascii=False, indent=1)


def send(text, dry_run):
    if dry_run:
        print("[dry-run] 送信内容:\n" + text)
        return True
    try:
        p = subprocess.run([sys.executable, PERSONA_SEND, "--dept", REPORT_DEPT, "--persona", PERSONA, text],
                           capture_output=True, text=True, timeout=60)
        return "204" in (p.stdout or "") or p.returncode == 0
    except Exception as e:
        print(f"送信失敗: {e}")
        return False


def run(dry_run=False, force=False):
    bid = boot_id()
    if not bid:
        print("ブート時刻を取得できず(スキップ)")
        return 0
    st = load_state()
    if st.get("boot") == bid and not force:
        print(f"同じブート({bid})=報告済み。何もしない。")
        return 0
    reasons = shutdown_reasons()
    body = (
        f"🖥 **復帰報告**(自動): PCの最終起動 {bid}。\n"
        + ("前回シャットダウン/再起動の記録:\n" + "\n".join("・" + r for r in reasons)
           if reasons else "前回シャットダウンの記録は見つからず(クリーンな停止/ログ範囲外)。")
        + f"\n{fleet_line()}\n{queue_health()}\n"
        + "詳細は `powershell scripts\\_daemons\\status.ps1`。異常時の全停止は panic_stop.ps1。"
    )
    ok = send(body, dry_run)
    if ok and not dry_run:
        save_state({"boot": bid, "reported_at": time.strftime("%Y-%m-%d %H:%M:%S")})
    print(f"[{'DRY' if dry_run else ('SENT' if ok else 'FAIL')}] boot={bid} reasons={len(reasons)}")
    return 0


def main():
    dry = "--dry-run" in sys.argv
    force = "--force" in sys.argv
    try:
        return run(dry_run=dry, force=force)
    except Exception as e:
        # supervisorを巻き込まない: 何があっても正常終了
        print(f"boot_report 例外(無視): {type(e).__name__}: {e}")
        return 0


if __name__ == "__main__":
    sys.exit(main())
