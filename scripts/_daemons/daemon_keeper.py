#!/usr/bin/env python3
"""部門デーモンの番人 (恒久基盤R0・claude_code_agent_farm式の指数バックオフ+サーキットブレーカ)。

役割: DEPTS の各部門につき dept_daemon.py を1つ生かし続ける。
  - 死んだら再起動: バックオフ 10s→倍々→cap 300s(即時再起動ループでCPU/トークンを焼かない)
  - 60秒以上生きたらバックオフをリセット(健康に戻った)
  - 連続10回の早死(60秒未満)でサーキットオープン: その部門を1時間休止
    (壊れたまま無限再起動=flappingを止める。休止はログと/liveの欠落からwatchdogが拾う)
keeper自身は supervise_daemons.ps1 が10分毎に生かす(=二段構え。keeperが数秒級・superviseが最終保険)。

使い方: python scripts/_daemons/daemon_keeper.py   (引数なし=DEPTS全部門)
"""
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
DAEMON = os.path.join(ROOT, "scripts", "llm", "dept_daemon.py")

# R2全部門展開(2026-07-19 Chami承認「やって」)。機微部屋は対象外(PROTOCOL管轄)。
# ★総括本部4室(hq/aegis-gl/research-room/keiei-kikaku)は2026-07-20 Chami裁定で除外。
#   理由: 権能が無いデーモンは「回します/させます」しか言えず、**沈黙を隠す**。
#   指令室の職務は捌く・裁くことで、権能と全体文脈が要る=セッションの仕事。
#   留守なら沈黙してよい(absence_watchdogが15分で検知する)。偽の返事より沈黙が良い。
#   DEPT_CONFの定義は残す(手動起動や将来の再開に備える)。ここから外すだけ。
DEPTS = ["hq", "research-room", "hr-room", "hr-context", "qa-reviewer", "system-engineer", "product-scout", "shorts-analyst", "copy-director", "learning-coach", "data-org", "frontend", "ai-office", "llm-edu", "llm-qa", "platform-se", "consult-intel"]
BACKOFF_START = 10
BACKOFF_CAP = 300
HEALTHY_SEC = 60               # これ以上生きたら健康=バックオフリセット
BREAKER_FAILS = 10             # 連続早死がこの回数でサーキットオープン
BREAKER_COOL_SEC = 3600


def log(msg):
    print(f"{time.strftime('%H:%M:%S')} keeper: {msg}")


class Slot:
    def __init__(self, dept):
        self.dept = dept
        self.proc = None
        self.started = 0.0
        self.backoff = BACKOFF_START
        self.fails = 0
        self.open_until = 0.0   # サーキットオープン中はこの時刻まで再起動しない
        self.next_start = 0.0

    def spawn(self):
        self.proc = subprocess.Popen(
            [sys.executable, DAEMON, "--dept", self.dept], cwd=ROOT,
            stdout=open(os.path.join(ROOT, "local", "llm", f"dept_daemon_{self.dept}.log"), "a",
                        encoding="utf-8", errors="replace"),
            stderr=subprocess.STDOUT)
        self.started = time.time()
        log(f"{self.dept}: spawned pid={self.proc.pid}")

    def tick(self):
        now = time.time()
        if self.proc is not None and self.proc.poll() is None:
            if now - self.started >= HEALTHY_SEC and self.backoff != BACKOFF_START:
                self.backoff, self.fails = BACKOFF_START, 0  # 健康=リセット
            return
        # 死んでいる
        if self.proc is not None:
            lived = now - self.started
            rc = self.proc.returncode
            self.proc = None
            if lived < HEALTHY_SEC:
                self.fails += 1
                self.backoff = min(self.backoff * 2, BACKOFF_CAP)
            else:
                self.fails, self.backoff = 0, BACKOFF_START
            log(f"{self.dept}: died rc={rc} lived={int(lived)}s fails={self.fails} → {self.backoff}s後に再起動")
            if self.fails >= BREAKER_FAILS:
                self.open_until = now + BREAKER_COOL_SEC
                self.fails = 0
                log(f"{self.dept}: ★サーキットオープン({BREAKER_COOL_SEC // 60}分休止)")
            self.next_start = now + self.backoff
            return
        if now < self.open_until or now < self.next_start:
            return
        try:
            self.spawn()
        except Exception as e:
            log(f"{self.dept}: spawn失敗 {type(e).__name__}")
            self.next_start = now + self.backoff


def reap_orphans():
    """自分の管理下にない既存のdept_daemonを起動前に掃除する(2026-07-20 実測事故への恒久対処)。

    何が起きたか: keeperをkillしても**子のdept_daemonは生き残る**(孤児化)。そこへ新keeperが
    起動すると各部門をもう1つ立てるので、全13部門が二重になった。二重化=同じ便に2つの
    デーモンが応答しうる状態で、今日わざわざ塞いだ二重応答の穴が別経路で開く。
    dept_daemonの所有者はkeeper唯一(RULES §3 1領域1オーナー)なので、
    **起動時点で走っているdept_daemonは全て前世代の残骸**とみなして落としてよい。
    ※supervise_daemons.ps1 の重複排除はkeeper/gateway等が対象で、その子までは見ない。
    """
    if os.name != "nt":
        return
    try:
        out = subprocess.run(
            ["powershell", "-NoProfile", "-Command",
             "Get-CimInstance Win32_Process -Filter \"Name='python.exe'\" | "
             "Where-Object { $_.CommandLine -match 'dept_daemon' } | "
             "ForEach-Object { $_.ProcessId }"],
            capture_output=True, text=True, timeout=30)
        pids = [p.strip() for p in (out.stdout or "").split() if p.strip().isdigit()]
    except Exception as e:
        log(f"孤児掃除スキップ({type(e).__name__})=現行動作のまま続行")
        return
    if not pids:
        return
    log(f"起動前の孤児dept_daemonを掃除: {len(pids)}件 pids={','.join(pids)}")
    for pid in pids:
        try:
            subprocess.run(["taskkill", "/PID", pid, "/F"], capture_output=True, timeout=15)
        except Exception:
            pass
    time.sleep(2)   # ポート(18800番台)が解放されるのを待ってから自分の分を立てる


def main():
    reap_orphans()
    slots = [Slot(d) for d in DEPTS]
    log(f"起動 depts={DEPTS}")
    while True:
        for s in slots:
            try:
                s.tick()
            except Exception as e:
                log(f"{s.dept}: tick失敗 {type(e).__name__}")
        time.sleep(2)


if __name__ == "__main__":
    main()
