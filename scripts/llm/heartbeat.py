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
常駐(参考): scripts/llm/start_heartbeat.bat
"""
import argparse
import os
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
CLAUDE_ACTIVE = os.path.join(LOCAL, "llm", "claude_active.txt")

DEFAULT_MINUTES = 10.0
DEFAULT_INTERVAL = 20.0


def touch():
    os.makedirs(os.path.dirname(CLAUDE_ACTIVE), exist_ok=True)
    now = datetime.now(timezone.utc).isoformat()
    with open(CLAUDE_ACTIVE, "w", encoding="utf-8") as f:
        f.write(now + "\n")


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
    p.add_argument("--verbose", action="store_true", help="毎回のtouchもprintする")
    args = p.parse_args(argv)
    # 不正値は安全な既定へフォールバック(0以下・非数)
    args.minutes = _safe_float(args.minutes, DEFAULT_MINUTES, minimum=0.01)
    args.interval = _safe_float(args.interval, DEFAULT_INTERVAL, minimum=0.5)
    return args


def main(argv=None):
    args = parse_args(sys.argv[1:] if argv is None else argv)

    if args.once:
        touch()
        print("heartbeat: 1回更新(--once)")
        return 0

    max_count = max(1, int(round((args.minutes * 60.0) / args.interval)))
    print(f"heartbeat開始: {args.interval:g}秒間隔・最大{args.minutes:g}分({max_count}回)")
    count = 0
    reason = "TTL満了"
    try:
        # 旧設計(for i in seq 1 N; do touch; sleep S; done)を踏襲=touch直後に毎回sleepし、
        # 最終回のsleepも含めて合計 max_count*interval 秒でTTLが尽きる
        for _ in range(max_count):
            touch()
            count += 1
            if args.verbose:
                print(f"  touch {count}/{max_count}")
            time.sleep(args.interval)
    except KeyboardInterrupt:
        reason = "中断(Ctrl-C)"
    print(f"heartbeat終了: {count}回更新・{reason}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
