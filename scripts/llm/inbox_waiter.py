#!/usr/bin/env python3
"""受信箱ウェイター (チャイム線・イベント駆動ウェイク / 2026-07-15)。

役割:
  各Claude Codeセッションが「番犬」として飼うバックグラウンドプロセス。
  自分の受信箱を短間隔で見張り、**新着が入った瞬間に自分から終了する**。
  Claude Codeは起動したバックグラウンドプロセスの終了で task-notification を出し、
  そのセッションを自動で1ターン起こす → これを「チャイム」として使う。
  待機中は純Pythonのファイル監視だけ=Claudeトークン0・無料。

  設計の背景と全体像 = docs/設計・調査/チャイム設計_Discord即時ウェイク.md
  従来の heartbeat.py(定期TTL満了で起こす)の置き換え。**併用しない**(二重脈の混乱防止)。

使い方:
  python scripts/llm/inbox_waiter.py --name main             # 司令塔=local/discord_inbox.jsonl を見張る
  python scripts/llm/inbox_waiter.py --name research-room     # 部門窓=local/inbox/<name>.jsonl を見張る
  python scripts/llm/inbox_waiter.py --name main --minutes 45 --interval 2
  python scripts/llm/inbox_waiter.py --name main --once       # 1回stat+touchして即終了(点検/再武装用)

  各セッションは「起動時」と「各作業を終えて箱をドレインした直後」に、これを
  run_in_background で再武装する(heartbeatの再武装と同じ習慣。コマンドが変わるだけ)。
  ★再武装は必ず箱をドレイン(mv/処理)した後に行う。空箱で待機に入り、次の新着で鳴る。
    ドレイン前に再武装すると「未処理あり」で即鳴動する=無害だが、まず処理してから再武装するのが正。

判定はレベル駆動: 箱が非空なら鳴る(=未処理メールを絶対に取り残さない)。増分ではなく
  「今そこに未処理があるか」で判断するため、起動時に既に溜まっていても即座に拾う。

終了時の1行(起床ターンで最初に見える):
  WAITER:MESSAGE name=<name> total=<現行数>   … 新着あり=すぐ箱を処理
  WAITER:TTL     name=<name> total=<現行数>   … 満了=静かな定期点検(再武装だけでよい)

INC-091(有限TTL安全機構・絶対に崩さない):
  このループは**あえて有限**(TTL)。セッションが生きていれば作業のたびに再武装する。
  もし本体がフリーズ/暴走してもループはTTL満了で自然終了し、脈(claude_active_<name>.txt)が
  90秒で古くなる → inbox_poller の sweep_stale_dept_boxes() が部門箱をmainへ回収 →
  mainのwaiterが鳴る(自動フェイルオーバー)。
  ※「新着が来るまで無限に待つ」形は偽生存(フリーズを生存に見せる)になるため禁止。
    本waiterは新着到達"または"TTLで必ず終わる=偽生存しない。**条件式に定数の真値を置く無限ループは書かない。**
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

DEFAULT_MINUTES = 45.0     # TTL。長くてよい(フリーズ回復はsweep側が担保・回復速度に効かない)
DEFAULT_INTERVAL = 2.0     # 見張り間隔(秒)。新着→起床のレイテンシ=ポーラー15s + これ


def box_path(name):
    """見張る受信箱のパス。main=司令塔本箱 / それ以外=部門箱。"""
    if name == "main":
        return os.path.join(LOCAL, "discord_inbox.jsonl")
    return os.path.join(LOCAL, "inbox", f"{name}.jsonl")


def active_path(name):
    """脈ファイル(配達先の維持・司令塔稼働の生存信号)。heartbeat.pyと同じ命名。"""
    fn = "claude_active.txt" if name == "main" else f"claude_active_{name}.txt"
    return os.path.join(LOCAL, "llm", fn)


def touch(name):
    p = active_path(name)
    os.makedirs(os.path.dirname(p), exist_ok=True)
    now = datetime.now(timezone.utc).isoformat()
    with open(p, "w", encoding="utf-8") as f:
        f.write(now + "\n")


def count_lines(path):
    """箱の非空行数。無い/読めないは0。行数ベースなので部分ドレインでも壊れない。"""
    try:
        with open(path, "r", encoding="utf-8") as f:
            return sum(1 for line in f if line.strip())
    except OSError:
        return 0


def _safe_float(value, default, minimum):
    try:
        v = float(value)
    except (TypeError, ValueError):
        return default
    return v if v >= minimum else default


def parse_args(argv):
    p = argparse.ArgumentParser(description="受信箱ウェイター(チャイム線・有限TTL)")
    p.add_argument("--name", default="main",
                   help="セッション名。main=司令塔本箱 / 部門はdept名(local/inbox/<name>.jsonl)")
    p.add_argument("--minutes", type=float, default=DEFAULT_MINUTES,
                   help=f"TTL(分)。既定{DEFAULT_MINUTES:g}")
    p.add_argument("--interval", type=float, default=DEFAULT_INTERVAL,
                   help=f"見張り間隔(秒)。既定{DEFAULT_INTERVAL:g}")
    p.add_argument("--once", action="store_true", help="1回stat+touchして即終了(点検/再武装用)")
    p.add_argument("--verbose", action="store_true", help="毎回のstat結果もprintする")
    args = p.parse_args(argv)
    args.minutes = _safe_float(args.minutes, DEFAULT_MINUTES, minimum=0.01)
    args.interval = _safe_float(args.interval, DEFAULT_INTERVAL, minimum=0.5)
    return args


def main(argv=None):
    args = parse_args(sys.argv[1:] if argv is None else argv)
    box = box_path(args.name)

    if args.once:
        touch(args.name)
        n = count_lines(box)
        print(f"WAITER:ONCE name={args.name} total={n}")
        return 0

    max_count = max(1, int(round((args.minutes * 60.0) / args.interval)))
    print(f"inbox_waiter開始[{args.name}]: {args.interval:g}秒間隔・最大{args.minutes:g}分"
          f"({max_count}回) box={box}")

    for _ in range(max_count):
        touch(args.name)                 # 脈=配達先の維持(見張るたびに新鮮化)
        cur = count_lines(box)
        if cur > 0:                      # ★チャイム鳴動: 箱に未処理がある(レベル駆動)
            print(f"WAITER:MESSAGE name={args.name} total={cur}")
            return 0
        if args.verbose:
            print(f"  watch name={args.name} cur={cur}")
        time.sleep(args.interval)

    print(f"WAITER:TTL name={args.name} total={count_lines(box)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
