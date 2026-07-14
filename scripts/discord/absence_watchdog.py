#!/usr/bin/env python3
"""司令塔不在watchdog (Phase DB・受付箱の「未処理滞留」を検知して自動アナウンス)。

背景:
  Discordの返信は「司令塔(Claude Codeセッション)が受付箱を読む」ことで初めて発生する
  設計(自動botではない)。セッションフリーズ等で誰にも読まれないと無反応になる。
  本スクリプトは local/discord_inbox.jsonl の未処理滞留そのものを検知し、
  (a) 滞留メッセージの発生元chへ受領お知らせ、(b) 復旧用ch(dept=="incident")へサマリ、を自動送信する。

監視は読み取り専用(受付箱ファイルは消費・削除・書き換えしない。所有者は
inbox_poller.py / local_responder.py / 司令塔)。heartbeat(local/llm/claude_active.txt)
の生死は判定に使わない=heartbeatが偽陽性で生きたままフリーズしているケースも拾うため、
受付箱の滞留時間だけで判定する。

使い方: python scripts/discord/absence_watchdog.py [--once] [--dry-run]
常駐起動: scripts/discord/start_absence_watchdog.bat (60秒間隔)
テスト: 環境変数 GO5_LOCAL_DIR があれば local/ の代わりにそれを使う(全パス)
"""
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
LOCAL = os.environ.get("GO5_LOCAL_DIR") or os.path.join(ROOT, "local")
INBOX_FILE = os.path.join(LOCAL, "discord_inbox.jsonl")
FOR_CLAUDE_FILE = os.path.join(LOCAL, "discord_inbox_for_claude.jsonl")
CLAUDE_ACTIVE = os.path.join(LOCAL, "llm", "claude_active.txt")
STATE_FILE = os.path.join(LOCAL, "discord_watchdog_state.json")
BOT_SEND = os.path.join(ROOT, "scripts", "discord", "bot_send.py")

STALE_MIN = 15                 # これ以上未処理なら「司令塔不在の可能性」
POLL_SEC = 60                  # 常駐時の巡回間隔
MAX_ANNOUNCE_PER_CYCLE = 3     # (a)の1周期あたり上限(暴走ガード)
MAX_ANNOUNCE_PER_HOUR = 6      # (a)の直近1時間あたり上限
SUMMARY_COOLDOWN_SEC = 60 * 60  # (b)は60分に1回まで
ANNOUNCED_KEEP = 500           # announced履歴の保持件数

ANNOUNCE_TEXT = "司令塔が不在です。このメッセージは受付済み・復帰後に対応します(自動お知らせ)"
# 不在サマリの通知先=復旧用チャンネル(dept=="incident"・「システム事故対・復旧部門」)。
# 未登録の間はbot_sendが失敗し次周期で再試行(取りこぼしなし)。総合受付でなくここへ集約(Chami指定2026-07-14)。
SUMMARY_DEPT = "incident"


def load_state():
    if os.path.exists(STATE_FILE):
        try:
            with open(STATE_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
            data.setdefault("announced", [])
            data.setdefault("sent_ts", [])
            data.setdefault("last_summary", 0)
            return data
        except Exception:
            pass
    return {"announced": [], "sent_ts": [], "last_summary": 0}


def save_state(state):
    os.makedirs(os.path.dirname(STATE_FILE), exist_ok=True)
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=1)


def parse_ts(ts_raw):
    """Discord ISOタイムスタンプをUTCのdatetimeへ。解析失敗はNone(呼び出し側でスキップ)。"""
    if not ts_raw:
        return None
    try:
        ts = datetime.fromisoformat(str(ts_raw).replace("Z", "+00:00"))
    except Exception:
        return None
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=timezone.utc)
    return ts.astimezone(timezone.utc)


def read_inbox_rows():
    """受付箱を読み取り専用でパース。ファイル自体には一切書き込まない。

    無い場合はNone、解析できた(rec, ts)のリスト(壊れた行/ts解析失敗行はスキップ)。
    """
    if not os.path.exists(INBOX_FILE):
        return None
    rows = []
    with open(INBOX_FILE, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except Exception:
                continue
            ts = parse_ts(rec.get("ts", ""))
            if ts is None:
                continue
            rows.append((rec, ts))
    return rows


def heartbeat_age_min():
    """heartbeatファイルの鮮度(分)。無ければNone。"""
    if not os.path.exists(CLAUDE_ACTIVE):
        return None
    age_sec = time.time() - os.path.getmtime(CLAUDE_ACTIVE)
    return age_sec / 60.0


def for_claude_count():
    """次セッション待ち件数(情報表示のみ・滞留判定はしない)。"""
    if not os.path.exists(FOR_CLAUDE_FILE):
        return 0
    n = 0
    with open(FOR_CLAUDE_FILE, "r", encoding="utf-8") as f:
        for line in f:
            if line.strip():
                n += 1
    return n


def bot_send(channel, body, dry_run, by_dept=False):
    if dry_run:
        target = f"--dept {channel}" if by_dept else channel
        print(f"[dry-run] bot_send -> {target}: {body}")
        return True
    args = [sys.executable, BOT_SEND]
    if by_dept:
        args += ["--dept", channel]
    else:
        args += [channel]
    args += [body]
    r = subprocess.run(args, capture_output=True, text=True, encoding="utf-8", errors="replace")
    return r.returncode == 0


def run_once(dry_run=False):
    if not os.path.isdir(LOCAL):
        print(f"local/ ディレクトリが見つかりません({LOCAL})。監視対象なしのため正常終了します。")
        return
    rows = read_inbox_rows()
    if rows is None:
        print(f"受付箱ファイルが見つかりません({INBOX_FILE})。正常終了します。")
        return

    now = datetime.now(timezone.utc)
    stale = []
    for rec, ts in rows:
        age_min = (now - ts).total_seconds() / 60.0
        if age_min >= STALE_MIN:
            stale.append((rec, age_min))

    if not stale:
        print(f"滞留なし(受付箱{len(rows)}行・{STALE_MIN}分以上滞留0件)。")
        return

    hb_age = heartbeat_age_min()
    for_claude_n = for_claude_count()
    n_stale = len(stale)
    oldest_min = max(age for _, age in stale)

    state = load_state()
    announced = state.get("announced", [])
    now_epoch = time.time()
    sent_ts = [t for t in state.get("sent_ts", []) if now_epoch - t < 3600]  # 直近1時間だけ保持

    # (a) 未アナウンスの滞留行へ個別返信(暴走ガード込み・古い順)
    stale_sorted = sorted(stale, key=lambda t: -t[1])
    sent_this_cycle = 0
    for rec, age_min in stale_sorted:
        if sent_this_cycle >= MAX_ANNOUNCE_PER_CYCLE:
            break
        if len(sent_ts) >= MAX_ANNOUNCE_PER_HOUR:
            break
        msg_id = rec.get("msg_id")
        channel = rec.get("channel")
        if not msg_id or not channel or msg_id in announced:
            continue  # id/ch不明、または既に生涯1回済み=送らない(超過分は次周期へ)
        ok = bot_send(channel, ANNOUNCE_TEXT, dry_run)
        if ok:
            announced.append(msg_id)
            sent_ts.append(now_epoch)
            sent_this_cycle += 1

    state["announced"] = announced[-ANNOUNCED_KEEP:]
    state["sent_ts"] = sent_ts

    # (b) 総合受付へサマリ(60分に1回まで)
    last_summary = state.get("last_summary", 0)
    if now_epoch - last_summary >= SUMMARY_COOLDOWN_SEC:
        hb_text = "heartbeat未検出" if hb_age is None else f"heartbeat最終更新{int(hb_age)}分前"
        summary = (
            f"⚠司令塔不在の可能性: 受付箱{n_stale}件が{STALE_MIN}分以上未処理"
            f"(最古{int(oldest_min)}分)・{hb_text}・司令塔待ち{for_claude_n}件。"
            "PCでClaude Codeを開くか受付箱を確認してください(自動監視)"
        )
        ok = bot_send(SUMMARY_DEPT, summary, dry_run, by_dept=True)
        if ok:
            state["last_summary"] = now_epoch

    save_state(state)


def main():
    argv = sys.argv[1:]
    once = "--once" in argv
    dry_run = "--dry-run" in argv
    if once:
        run_once(dry_run)
        return
    print(f"司令塔不在watchdog 起動 ({POLL_SEC}秒間隔{'・dry-run' if dry_run else ''})")
    while True:
        try:
            run_once(dry_run)
        except Exception as e:
            print(f"watchdog処理失敗: {type(e).__name__}")
        time.sleep(POLL_SEC)


if __name__ == "__main__":
    main()
