#!/usr/bin/env python3
"""司令塔ハートビート (Claudeセッション稼働中の生存信号・TTL付き)。

仕組み:
  - local/llm/claude_active.txt に現在時刻(ISO8601 UTC)を書き込む(mtimeが更新されればよい)
  - local_responder.py はこのファイルのmtimeが90秒以内なら「司令塔稼働中」と判断して待機する

設計意図(INC-091 対策1・絶対に崩さないこと):
  このループは**あえて有限**(TTL)にしてある。司令塔は「実際に仕事をしたタイミング」で
  このスクリプトを再起動して再武装する(=生きて働いているからこそ脈を打ち直す)。
  もし司令塔本体がフリーズ/暴走しても、このループはTTL満了で自然に終了し脈が止まる。
  すると90秒後にはローカルqwenが「司令塔不在」と判断して自動で受付を引き継ぐ。
  この安全機構は無条件の無限ループ(条件式に定数の真値を置く形)にした瞬間に壊れる=
  偽の生存信号を出し続け、本体が死んでいるのに誰も応答しない空白を生む(2026-07-14実際に発生)。
  **終了条件のない無限ループは絶対に使わない。必ず有限回数(for)で終わらせること。**

使い方:
  python scripts/llm/heartbeat.py                  # 20秒間隔・最大10分(30回)
  python scripts/llm/heartbeat.py --once            # 1回だけ書いて即終了(再武装用)
  python scripts/llm/heartbeat.py --minutes 5 --interval 10
  python scripts/llm/heartbeat.py --name research-room   # 部門常駐窓(claude_active_<name>.txt)
常駐(参考): scripts/llm/start_heartbeat.bat

部門セッション分離(2026-07-14): --name <dept> で部門窓用の脈ファイルを打つ。
  inbox_poller はこの脈が新鮮(90秒)な間だけ新着を local/inbox/<dept>.jsonl へ配達する。

限界前通知(INC-091 対策2): 本スクリプトの起動=再武装1回として記録し、直近3時間で
  9回以上(≒90分超の連続稼働)に達したら Discord総合受付(router)へ「引き継ぎ推奨」を
  自動発報する(2時間スロットル)。モデルの自覚に頼らずOS側の事実だけで判断する。
"""
import argparse
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
LOCAL = os.environ.get("GO5_LOCAL_DIR") or os.path.join(ROOT, "local")
BOT_SEND = os.path.join(ROOT, "scripts", "discord", "bot_send.py")

DEFAULT_MINUTES = 10.0
DEFAULT_INTERVAL = 20.0

# 限界前通知(INC-091 対策2)
REARM_WINDOW_SEC = 3 * 3600   # 再武装を数える窓=直近3時間
REARM_THRESHOLD = 9           # この回数以上で「長時間稼働」とみなす(≒90分超)
NOTIFY_COOLDOWN_SEC = 7200    # 通知は2時間に1回まで


def active_path(name):
    fn = "claude_active.txt" if name == "main" else f"claude_active_{name}.txt"
    return os.path.join(LOCAL, "llm", fn)


def touch(name="main"):
    p = active_path(name)
    os.makedirs(os.path.dirname(p), exist_ok=True)
    now = datetime.now(timezone.utc).isoformat()
    with open(p, "w", encoding="utf-8") as f:
        f.write(now + "\n")


def rearm_bookkeeping(name):
    """再武装1回を記録し、閾値超過ならDiscordへ限界前通知(失敗しても脈は止めない)。"""
    llm_dir = os.path.join(LOCAL, "llm")
    os.makedirs(llm_dir, exist_ok=True)
    log = os.path.join(llm_dir, f"heartbeat_rearm_{name}.log")
    now = time.time()
    try:
        lines = []
        if os.path.exists(log):
            with open(log, "r", encoding="utf-8") as f:
                lines = [l.strip() for l in f if l.strip()]
        lines.append(str(int(now)))
        lines = lines[-200:]  # 肥大防止
        with open(log, "w", encoding="utf-8") as f:
            f.write("\n".join(lines) + "\n")
        count = sum(1 for l in lines if l.isdigit() and int(l) >= now - REARM_WINDOW_SEC)
    except OSError:
        return
    if count < REARM_THRESHOLD:
        return
    mark = os.path.join(llm_dir, f"limit_notified_{name}.txt")
    try:
        last = float(open(mark, encoding="utf-8").read().strip() or 0) if os.path.exists(mark) else 0.0
    except (OSError, ValueError):
        last = 0.0
    if now - last < NOTIFY_COOLDOWN_SEC:
        return
    if os.environ.get("GO5_LOCAL_DIR"):
        print(f"heartbeat: (テストモード)限界前通知を抑止(再武装{count}回/3h)")
        return  # テスト隔離時は実Discordへ発報しない(bot_sendは実local/を読むため)
    msg = (f"⏳【限界前通知/INC-091対策】セッション[{name}]の連続稼働が長くなっています"
           f"(直近3hで再武装{count}回)。区切りの良い所で引き継ぎ(正本md/memory更新→新セッション)を推奨。"
           f"※開始直後のセッションならこの通知は無視してOK")
    try:
        subprocess.run([sys.executable, BOT_SEND, "--dept", "router", msg],
                       timeout=25, capture_output=True)
        with open(mark, "w", encoding="utf-8") as f:
            f.write(str(int(now)))
        print(f"heartbeat: 限界前通知を送信(再武装{count}回/3h)")
    except Exception:
        pass  # 通知は補助機能。失敗しても脈は打つ


def _safe_float(value, default, minimum):
    try:
        v = float(value)
    except (TypeError, ValueError):
        return default
    if v < minimum:
        return default
    return v


def parse_args(argv):
    p = argparse.ArgumentParser(description="司令塔ハートビート(TTL付き)")
    p.add_argument("--minutes", type=float, default=DEFAULT_MINUTES,
                    help=f"総寿命(分)。既定{DEFAULT_MINUTES}")
    p.add_argument("--interval", type=float, default=DEFAULT_INTERVAL,
                    help=f"書き込み間隔(秒)。既定{DEFAULT_INTERVAL}")
    p.add_argument("--once", action="store_true", help="1回だけ書いて即終了(再武装用)")
    p.add_argument("--name", default="main",
                    help="セッション名。main=司令塔(claude_active.txt)/部門窓はdept名(claude_active_<name>.txt)")
    p.add_argument("--verbose", action="store_true", help="毎回のtouchもprintする")
    args = p.parse_args(argv)
    # 不正値は安全な既定へフォールバック(0以下・非数)
    args.minutes = _safe_float(args.minutes, DEFAULT_MINUTES, minimum=0.01)
    args.interval = _safe_float(args.interval, DEFAULT_INTERVAL, minimum=0.5)
    return args


def main(argv=None):
    args = parse_args(sys.argv[1:] if argv is None else argv)
    rearm_bookkeeping(args.name)  # 起動=再武装1回(--once含む)。閾値超過で限界前通知

    if args.once:
        touch(args.name)
        print(f"heartbeat: 1回更新(--once, name={args.name})")
        return 0

    max_count = max(1, int(round((args.minutes * 60.0) / args.interval)))
    print(f"heartbeat開始[{args.name}]: {args.interval:g}秒間隔・最大{args.minutes:g}分({max_count}回)")
    count = 0
    reason = "TTL満了"
    try:
        # 旧設計(for i in seq 1 N; do touch; sleep S; done)を踏襲=touch直後に毎回sleepし、
        # 最終回のsleepも含めて合計 max_count*interval 秒でTTLが尽きる
        for _ in range(max_count):
            touch(args.name)
            count += 1
            if args.verbose:
                print(f"  touch {count}/{max_count}")
            time.sleep(args.interval)
    except KeyboardInterrupt:
        reason = "中断(Ctrl-C)"
    print(f"heartbeat終了[{args.name}]: {count}回更新・{reason}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
