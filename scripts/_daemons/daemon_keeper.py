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
DEPTS = ["hq", "hr-room", "hr-context", "qa-reviewer", "system-engineer",
         "product-scout", "shorts-analyst", "copy-director", "learning-coach"]
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


def main():
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
