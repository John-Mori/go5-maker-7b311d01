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
import ast
import json
import os
import re
import subprocess
import sys
import time
import urllib.request

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)
except Exception:
    pass

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.normpath(os.path.join(HERE, "..", ".."))
SUP_LOG = os.path.join(ROOT, "local", "_daemons_supervisor.log")
STATE = os.path.join(ROOT, "local", "_deadman_state.json")
PERSONA_SEND = os.path.join(ROOT, "scripts", "discord", "persona_send.py")
# 外部dead-man(Cloudflare)へのビート。健全な間だけ叩く=途絶えたら「PCごと停止」とみなされる。
BEAT_URL = os.environ.get("GO5_DEADMAN_BEAT_URL", "https://deadman.trustsignalbot.workers.dev/beat")
BEAT_SECRET_FILE = os.path.join(ROOT, "local", "deadman_beat_secret.txt")

# ★2026-07-20 O1修正: supervise_daemons.ps1 が実際に管理する7常駐に一致させた。
#   旧リストは退役済み inbox_poller を含み、現行の daemon_keeper / discord_gateway を
#   欠いていた(=艦隊全滅検知が旧艦隊を見ていた・改善書P0-2)。
#   恒久解: O2でorg_registry.ymlから生成。それまではsupervisorのName列と手動一致。
EXPECTED = ["absence_watchdog", "local_responder", "gemini_responder",
            "office_daily", "claude_responder", "daemon_keeper", "discord_gateway"]

# ★★部屋の取り残しを数える(2026-08-08 イージス研究室 / 発注= 研究室HQ)。
#   なぜ要るか(実測): ククール-なかま会話は名簿へ 08-05 08:26 に足されたが、番人は 08-04 00:06
#   起動のまま=**番人の管理外**で走っていた(pid 50452 / 親 52596 は既に不在)。
#   死んでも誰も立て直さないのに、**警報も出ない**。1部屋の直しで終わらせず、
#   「取り残されている部屋を機械が数えて出す」= ここで数える。
#   ★誤発火する安全網は無視される(規律§3)ので、**所有者が別に居る部屋は数えない**:
KEEPER = os.path.join(ROOT, "scripts", "_daemons", "daemon_keeper.py")
CHANNELS = os.path.join(ROOT, "local", "discord_channels.json")
# 番人の名簿に無いのが**正しい**部門(=他の常駐が持っている / 意図して外している)。
ROSTER_OTHER_OWNER = {
    "router":      "通知の受け皿(部屋ではない)",
    "gemini":      "gemini_responder が所有(ホイミン/ベホップの3人部屋)",
    "llm-growth":  "local_responder(ローカルqwen)が所有=二重claim回避で意図的に外している",
    "meeting-a":   "会議部屋(セッションが直接入る)",
    "meeting-b":   "会議部屋(セッションが直接入る)",
}


def _dept_procs():
    """走っている dept_daemon を (dept, pid, ppid) で返す。番人のpid一覧も返す。

    戻り値: (procs, keeper_pids) / 測れない時は (None, None)。
    ★「番人の子か」で管理下かを判定する= mtimeのような当たっている値に乗らない(規律§3)。
    """
    if os.name != "nt":
        return None, None
    ps = ("Get-CimInstance Win32_Process -Filter \"Name='python.exe'\" | "
          "Select-Object ProcessId,ParentProcessId,CommandLine | ConvertTo-Json -Compress")
    try:
        out = subprocess.run(["powershell", "-NoProfile", "-Command", ps],
                             capture_output=True, text=True, timeout=60)
        rows = json.loads(out.stdout or "[]")
    except Exception:
        return None, None
    if isinstance(rows, dict):
        rows = [rows]
    procs, keepers = [], []
    for r in rows:
        cmd = r.get("CommandLine") or ""
        if "daemon_keeper" in cmd:
            keepers.append(r.get("ProcessId"))
            continue
        if "dept_daemon" not in cmd:
            continue
        m = re.search(r"--dept\s+(\S+)", cmd)
        if m:
            procs.append((m.group(1), r.get("ProcessId"), r.get("ParentProcessId")))
    return procs, keepers


def roster_gaps():
    """取り残されている部屋を数える。測れない時は None(黙る=狼少年にしない)。

    ①管理外= 走っているが**番人の子ではない**=死んでも立て直されないのに警報も出ない。
    ②不在  = 名簿に居るのにプロセスが無い(番人が生きている時だけ異常とみなす)。
    ③未配線= Discordに部屋が在るのに番人の名簿に無い(所有者が別に居る部屋は除く)。
    """
    procs, keepers = _dept_procs()
    if procs is None:
        return None
    try:
        with open(KEEPER, "r", encoding="utf-8") as f:
            depts = ast.literal_eval(
                re.search(r"^DEPTS = (\[[^\]]*\])\s*$", f.read(), re.M).group(1))
    except Exception:
        return None
    kset = set(p for p in keepers if p)
    unmanaged = sorted({d for d, _pid, ppid in procs if ppid not in kset})
    running = {d for d, _pid, _ppid in procs}
    absent = sorted(set(depts) - running) if kset else []
    unwired = []
    try:
        with open(CHANNELS, "r", encoding="utf-8") as f:
            for c in json.load(f):
                d = c.get("dept")
                if d and d not in depts and d not in ROSTER_OTHER_OWNER:
                    unwired.append(d)
    except Exception:
        pass
    return {"unmanaged": unmanaged, "absent": absent, "unwired": sorted(set(unwired)),
            "depts": len(depts), "running": len(procs), "keepers": sorted(kset)}


def roster_lines(g):
    """人が読む形にする。異常が無ければ空list。"""
    if not g:
        return []
    out = []
    if g["unmanaged"]:
        out.append("番人の管理外で走っている部屋 %d件= %s(死んでも立て直されない)"
                   % (len(g["unmanaged"]), ",".join(g["unmanaged"])))
    if g["absent"]:
        out.append("名簿に居るのにデーモンが居ない部屋 %d件= %s"
                   % (len(g["absent"]), ",".join(g["absent"])))
    if g["unwired"]:
        out.append("Discordに部屋が在るのに番人の名簿に無い %d件= %s"
                   % (len(g["unwired"]), ",".join(g["unwired"])))
    return out


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


def send_beat():
    """外部dead-man(Cloudflare)へビートを送る。健全時のみ呼ぶ=途絶=PCごと停止のシグナル。
    best-effort(ネット不通でも監視本体は止めない)。"""
    try:
        with open(BEAT_SECRET_FILE, "r", encoding="utf-8") as f:
            secret = f.read().strip()
    except Exception:
        return False  # 秘密未配置なら外部ビートはスキップ(ローカル監視は続行)
    if not secret:
        return False
    try:
        # ★User-Agent必須: 既定の "Python-urllib/x" は Cloudflare にbot扱いされ403になる
        #   (avatar-cdn-expiryと同族の罠)。明示UAで回避。
        req = urllib.request.Request(BEAT_URL, data=b"", method="POST",
                                     headers={"X-Beat-Secret": secret,
                                              "User-Agent": "go5-deadman-beat/1.0"})
        with urllib.request.urlopen(req, timeout=10) as r:
            return r.status in (200, 204)
    except Exception as e:
        print(f"外部ビート送信に失敗(監視は続行): {e}")
        return False


def check_roster(st, dry_run):
    """取り残された部屋を数えて、**増減した時だけ**出す(2026-08-08)。

    ★連投しない= 前回と同じ顔ぶれなら黙る(狼少年の回避・INC-79と同じ作法)。
    ★片付いたら1回だけ「解消」を出す=直ったことも機械が言う。
    """
    g = roster_gaps()
    if g is None:
        print("[roster] 測れなかったので黙る(プロセス一覧/名簿が読めない)")
        return
    lines = roster_lines(g)
    sig = "|".join(lines)
    prev = st.get("roster_sig")
    # ★--dry-run は状態を書き換えない。書くと「もう出した」ことになり、**本番の初回通知が
    #   黙る**(2026-08-08にここで実際に踏んだ。試しに走らせた痕跡が本番の判定を変えた)。
    if not dry_run:
        st["roster_sig"] = sig
        st["roster_at"] = _now()
    if not lines:
        if prev:
            notify("✅ 部屋の取り残しは解消 — 番人の名簿%d室・稼働%d体が一致しています。"
                   % (g["depts"], g["running"]), dry_run)
            print("[roster] 解消を通知")
        else:
            print("[roster] 取り残し0件(名簿%d室/稼働%d体)" % (g["depts"], g["running"]))
        return
    print("[roster] " + " / ".join(lines))
    if sig == prev:
        print("[roster] 前回と同じ顔ぶれなので通知しない(連投回避)")
        return
    notify("🟠 **部屋の取り残しを検出** — 番人(daemon_keeper)の管理から外れている部屋があります。\n"
           + "\n".join("・" + x for x in lines)
           + "\n※この形の穴は「無警報で取り残される」= 死んでも立て直されず警報も出ない状態です。"
             "\n対処: 番人を載せ替える(名簿の追従は2026-08-08版から自動)。", dry_run)
    print("[roster] 変化したので通知した")


def run_once(stale_min, dry_run):
    """supervisorのdead-man判定 →(独立に)部屋の取り残しの点検。

    ★取り残しの点検が失敗しても dead-man 本体は落とさない(監視の本業を巻き込まない)。
    ★状態は読み直してから触る= 本体側の `_save_state` に上書きされない。
    """
    rc = _run_supervisor(stale_min, dry_run)
    try:
        st = _load_state()
        check_roster(st, dry_run)
        _save_state(st)
    except Exception as e:
        print("[roster] 点検に失敗(dead-man本体は続行) %s" % type(e).__name__)
    return rc


def _run_supervisor(stale_min, dry_run):
    st = _load_state()
    was_down = st.get("status") == "down"
    is_down, reasons = assess(stale_min)

    # 健全(supervisor生存)な間だけ外部Workerへビート。dry-runでは送らない。
    if (not is_down) and (not dry_run):
        send_beat()

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
    ap.add_argument("--roster", action="store_true",
                    help="部屋の取り残しだけ数えて表示(送信しない)")
    a = ap.parse_args()
    if a.roster:
        g = roster_gaps()
        if g is None:
            print("測れなかった(プロセス一覧/名簿が読めない)")
            sys.exit(1)
        print("番人=%s / 名簿%d室 / 稼働%d体" % (",".join(str(k) for k in g["keepers"]) or "不在",
                                              g["depts"], g["running"]))
        lines = roster_lines(g)
        print("取り残し %d種" % len(lines))
        for x in lines:
            print("・" + x)
        sys.exit(0)
    if a.once:
        sys.exit(run_once(a.stale_min, a.dry_run))
    # 常駐モード
    while True:
        run_once(a.stale_min, a.dry_run)
        time.sleep(max(60, a.interval_min * 60))


if __name__ == "__main__":
    main()
