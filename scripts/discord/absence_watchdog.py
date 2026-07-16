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
    # line_buffering=True が必須(INC-93): ファイル向けstdoutは約8KBのブロックバッファになり、
    # 無口な常駐は到達せず、Stop-Process -Forceで未書き出し分が破棄される=ログが残らない。
    # (このwatchdogだけログが生きていたのは、お喋りで8KBを埋め続けていたからに過ぎない)
    sys.stdout.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)
except Exception:
    pass

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.normpath(os.path.join(HERE, "..", ".."))
LOCAL = os.environ.get("GO5_LOCAL_DIR") or os.path.join(ROOT, "local")
INBOX_FILE = os.path.join(LOCAL, "discord_inbox.jsonl")
FOR_CLAUDE_FILE = os.path.join(LOCAL, "discord_inbox_for_claude.jsonl")
CLAUDE_ACTIVE = os.path.join(LOCAL, "llm", "claude_active.txt")
POLLER_ACTIVE = os.path.join(LOCAL, "llm", "poller_active.txt")  # inbox_pollerの死活脈(巡回毎に更新)
STATE_FILE = os.path.join(LOCAL, "discord_watchdog_state.json")
BOT_SEND = os.path.join(ROOT, "scripts", "discord", "bot_send.py")
PERSONA_SEND = os.path.join(ROOT, "scripts", "discord", "persona_send.py")
MACHINE_PERSONA = "メタルギアMk.II"  # 機械的アナウンスの担当(Chami指定2026-07-14・report-notifyの配送役)
SESSION_LABEL_FILE = os.path.join(LOCAL, "llm", "session_label.txt")


def session_label():
    """司令塔セッションのChami命名の表示名(通知に明示・Chami指定2026-07-14)。未設定なら既定。"""
    try:
        s = open(SESSION_LABEL_FILE, encoding="utf-8").read().strip()
        return s or "(名称未設定の司令塔セッション)"
    except OSError:
        return "(名称未設定の司令塔セッション)"

STALE_MIN = 15                 # これ以上未処理なら「司令塔不在の可能性」
# ポーラー脈がこれ以上古い/無い=停止の可能性。
# 2026-07-16: 120秒だと誤検知が頻発した(実測の発報は121〜166秒=閾値のわずかな超過ばかり)。
# 原因はch数の増加(27ch)で1巡回のAPI往復が伸び、脈の更新間隔が120秒を超えるようになったため。
# ポーラーは生きているのに鳴る=狼少年になり、本当の停止を見落とす。実態に合わせ5分へ。
POLLER_STALE_SEC = 300
POLLER_ALERT_COOLDOWN_SEC = 30 * 60  # ポーラー停止アラートは30分に1回まで
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
            data.setdefault("last_poller_alert", 0)
            return data
        except Exception:
            pass
    return {"announced": [], "sent_ts": [], "last_summary": 0, "last_poller_alert": 0}


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
    # 機械的アナウンスはメタルギアMk.II名義(persona_send)で送る(Chami指定2026-07-14)
    args = [sys.executable, PERSONA_SEND]
    args += (["--dept", channel] if by_dept else ["--channel", channel])
    args += ["--persona", MACHINE_PERSONA, body]
    r = subprocess.run(args, capture_output=True, text=True, encoding="utf-8", errors="replace")
    return r.returncode == 0


def poller_age_sec():
    """inbox_pollerの死活脈の古さ(秒)。ファイルが無ければNone(=一度も動いていない/停止)。"""
    if not os.path.exists(POLLER_ACTIVE):
        return None
    return time.time() - os.path.getmtime(POLLER_ACTIVE)


def check_poller_health(state, dry_run):
    """ポーラー停止を単独で検知して通知する(受付箱の滞留とは独立)。

    ポーラーが死ぬと新着が一切配達されず、受付箱は空のまま=滞留検知は永久に発火しない。
    そのためチャイム全体の単一障害点として、ここで死活脈の鮮度を直接見る。
    30分に1回までincidentへ通知(暴走ガード)。State(last_poller_alert)を更新する。
    """
    age = poller_age_sec()
    if age is not None and age < POLLER_STALE_SEC:
        return  # 正常
    now_epoch = time.time()
    if now_epoch - state.get("last_poller_alert", 0) < POLLER_ALERT_COOLDOWN_SEC:
        return  # クールダウン中
    when = "脈ファイルなし(未起動/停止)" if age is None else f"最終更新{int(age)}秒前"
    msg = (
        f"⚠inbox_poller 停止の可能性(自動監視): Discord受信ポーラーの死活脈が{when}。"
        "ポーラーが止まると新着が一切受付箱へ届かず、Discordの呼びかけに誰も気づけません。"
        "司令塔は `scripts\\discord\\start_discord_inbox.bat` で再起動を(二重起動に注意=既存cmd窓を閉じてから)。"
    )
    if bot_send(SUMMARY_DEPT, msg, dry_run, by_dept=True):
        state["last_poller_alert"] = now_epoch


def run_once(dry_run=False):
    if not os.path.isdir(LOCAL):
        print(f"local/ ディレクトリが見つかりません({LOCAL})。監視対象なしのため正常終了します。")
        return
    state = load_state()
    check_poller_health(state, dry_run)  # ポーラー死活は受付箱の滞留と独立に監視(単一障害点)
    save_state(state)
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
    # ★2026-07-15 Chami指示「Mk.IIがやかましい・トークンの無駄」で個別通知は無効化。
    #   (b)復旧chへの1時間毎サマリのみ残す(不在の把握には十分で、各chへの連投を止める)。
    ANNOUNCE_PER_MESSAGE = False
    stale_sorted = sorted(stale, key=lambda t: -t[1])
    sent_this_cycle = 0
    for rec, age_min in (stale_sorted if ANNOUNCE_PER_MESSAGE else []):
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
        label = session_label()
        summary = (
            f"⚠受付箱の滞留を検知(自動監視): 司令塔セッション「{label}」宛ての受付箱に"
            f"{n_stale}件が{STALE_MIN}分以上未処理(最古{int(oldest_min)}分)・{hb_text}・司令塔待ち{for_claude_n}件。"
            "※これは『受付箱を読む司令塔が15分不在』の検知であり、コンテキスト残量とは無関係です。"
            "該当セッションが稼働中なら受付箱を確認、終了済みなら新セッションへ引き継ぎを。"
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
