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
import re
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
# ★2026-08-13 イージス研究室: 受信の死活を「退役済みのinbox_poller」から
#   **現行の受信= discord_gateway** の脈へ張り替えた。
#   実測(incidentの直近400件・08-06 10:42〜08-13 16:22)= そのうち **341件(85%)** が
#   「⚠inbox_poller 停止の可能性」の同一文だった。inbox_poller は 2026-07-20 に退役済み
#   (deadman_check.py の EXPECTED から外れている)で、脈ファイル local/llm/poller_active.txt は
#   **2026-07-19 14:55 で更新が止まっている**= 以後25日間、30分ごとに鳴り続けていた。
#   狼少年の実害= 8/13 の🔥digest消失で本物の警報がこの山に埋まり「完全サイレント」と誤診された。
#   ★規律§3「常に誤発火する安全網は無視される」の実例。閾値ではなく**見る先**が間違っていた。
GATEWAY_PULSE = os.path.join(LOCAL, "queue", "_gateway_pulse.txt")  # discord_gatewayの死活脈(イベントループが回る度に更新)
STATE_FILE = os.path.join(LOCAL, "discord_watchdog_state.json")
# ★部門名の日本語化(2026-07-27 Chami原文=「用語が難しい、結論が見えないかな。
#   たとえば部門は日本語表記にして欲しいな。hqは研究室HQでsystems engineerは改修部門 みたいに」)。
#   変換の正本は scripts/_common/dept_names.py の1本だけ(ORG-11)。
#   ★警報が出なくなるのが最悪なので、読めなければ変換だけ諦める(fail-safe)。
sys.path.insert(0, os.path.join(ROOT, "scripts", "_common"))
try:
    from dept_names import dept_ja
except Exception:                                      # noqa: BLE001
    def dept_ja(slug, with_slug=False):
        return slug or ""
try:
    from session_presence import window_age as _window_age
except Exception:                                      # noqa: BLE001
    # ★fail-safe: 判定できない時は None(=判定不能)。**死んだ扱いにしない。**
    def _window_age(dept, now=None):
        return None

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
# ★2026-08-13: 対象を discord_gateway の脈へ張り替え。gatewayは _touch_pulse() を
#   高頻度(実測24秒前)で叩くので、5分の鮮度で十分に「詰まり」を捉えられる。
POLLER_STALE_SEC = 300
POLLER_ALERT_COOLDOWN_SEC = 30 * 60  # 状態遷移で鳴らすので実質バックストップ(連投の最終防波堤)

# --- ★司令塔のliveness脈の死活 (2026-08-13 イージス研究室・裁定C-044⑤) ---
# なぜ: presence.lab_alive() の2信号目 lab_tool_pulse.txt が **2026-07-20 19:22 で止まり、
#   23.9日間 誰も気づかなかった**。打ち手(hook pulse_touch.py)のコードは1行も壊れていない。
#   「自分が司令塔か」を判定する条件(手で名乗る札)が部屋の作り替えで切れただけで機能が消えた。
#   実害= 判定が readiness 1本へ退行し、司令塔が長いターンを処理している最中に
#   代打が出る条件(INC-94)が復活。さらに revive_lab.ps1 が「死亡」と読んで生きた窓を掃除した。
# ★C-044⑤=「条件付きで打つ脈は、その条件が切れた時に気づく手を同時に置く」の実装がここ。
#   鳴らす条件は **2つ揃った時だけ**= ①脈が24時間以上古い ②なのに司令塔の耳は動いている。
#   ②を要求する理由= 司令塔が単に閉じている夜間に鳴らしても行動が変わらない(狼少年になる)。
LAB_TOOL_PULSE = os.path.join(LOCAL, "llm", "lab_tool_pulse.txt")
LAB_PULSE_STALE_SEC = 24 * 3600      # これ以上古い=打ち手の条件が切れている
LAB_TRAFFIC_SEC = 30 * 60            # 司令塔の耳(readiness)がこの新しさなら「便は流れている」
LAB_PULSE_ALERT_COOLDOWN_SEC = 6 * 3600

# --- P2 死んだ窓の検知 (2026-07-18 応答性改善書P2・Chami承認「全て承認」) ---
# 部門窓の死をちゃみが手動発見する状態(hr-context実例)を根絶する。
# 「最近まで生きていた脈が途絶えた」窓だけを検知する(開いたことの無い部屋は対象外=
# 25部屋の常設を強要しない)。閾値20分の理由: INC-94により処理中ターンでは脈が
# 数分〜十数分死ぬのが正常動作のため、それより短いと働いている窓を誤検知する。
WINDOW_STALE_SEC = 20 * 60        # 脈がこれ以上古い=窓が死んだ疑い
WINDOW_RECENT_SEC = 12 * 3600     # これ以内に生きていた窓だけ対象(古い骸は通知しない)
WINDOW_ALERT_COOLDOWN_SEC = 6 * 3600  # 同じ窓への再通知は6時間に1回まで
WINDOW_SKIP_DEPTS = ("router", "llm-growth", "gemini")  # 窓を持たない部屋
POLL_SEC = 60                  # 常駐時の巡回間隔

# --- ⏳対応中(生存)通知 (2026-07-18 Chami直要望「前の分を対応中だから生きてるけど時間が欲しい、を
#     報告通知部屋から通知して」・learning経由msg 1527889534187208784) ---
# 進捗印3段(📮送信/✅既読/👀着手)の先=「着手後の長作業中、生存と凍結の区別が付かない」穴の4段目。
# 判定は既存ファイルのみ: local/_work/<dept>.jsonl が BUSY_NOTIFY_MIN_SEC 以上残っている
# =「案件を退避して処理中」。かつ脈が WINDOW_STALE_SEC 以内=「生存」(死んだ窓はP2が別途警報
# するので、ここでは「生きてるのに時間がかかっている」だけを拾う)。
# 絞り(洪水防止・learning琴葉案をChamiへ提示済): (a)5分超の作業のみ (b)同一作業(workファイルの
# mtime単位)につき1通のみ+部門毎45分クールダウン。名義はオタコン(Chami指定)。
BUSY_NOTIFY_MIN_SEC = 5 * 60
BUSY_NOTIFY_COOLDOWN_SEC = 45 * 60
BUSY_NOTIFY_DEPT = "report-notify"          # 報告通知部屋(1525703461965004900)
BUSY_NOTIFY_PERSONA = "オタコン"
BUSY_KEEP = 200                             # 通知済みキーの保持数

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
            data.setdefault("poller_down", False)  # 受信停止の状態遷移(2026-08-13)
            return data
        except Exception:
            pass
    return {"announced": [], "sent_ts": [], "last_summary": 0, "last_poller_alert": 0,
            "poller_down": False}


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
    """受信(discord_gateway)の死活脈の古さ(秒)。ファイルが無ければNone(=未起動/停止)。"""
    if not os.path.exists(GATEWAY_PULSE):
        return None
    return time.time() - os.path.getmtime(GATEWAY_PULSE)


def check_poller_health(state, dry_run):
    """受信の停止を単独で検知して通知する(受付箱の滞留とは独立)。

    受信が死ぬと新着が一切配達されず、受付箱は空のまま=滞留検知は永久に発火しない。
    そのためチャイム全体の単一障害点として、ここで死活脈の鮮度を直接見る。

    ★2026-08-13 イージス研究室: 2つ直した。
      ① 見る先= 退役済み inbox_poller → 現行の discord_gateway(GATEWAY_PULSE)。
      ② 鳴らし方= 「異常な間ずっと30分毎」→ **状態遷移で1回だけ**(check_prompt_bloat /
         check_roster と同じレール)。復旧したら ✅ を1回出して状態を戻す。
         クールダウンは連投の最終防波堤として残す。
      ★これが無いと「ずっと鳴っている警報」になり、誰も読まなくなって本物が埋まる(規律§3)。
    """
    age = poller_age_sec()
    now_epoch = time.time()
    down = (age is None) or (age >= POLLER_STALE_SEC)
    was_down = bool(state.get("poller_down"))
    if not down:
        if was_down:
            # 復旧= 1回だけ知らせて状態を戻す(黙って直ると「まだ壊れている」と思われ続ける)
            if bot_send(SUMMARY_DEPT,
                        "✅受信(discord_gateway)は復旧しました — 死活脈が"
                        f"{int(age)}秒前まで戻っています(自動監視)。", dry_run, by_dept=True):
                state["poller_down"] = False
        else:
            state["poller_down"] = False
        return
    if was_down:
        return  # 既に報告済みの継続中の停止では鳴らさない(狼少年にしない)
    if now_epoch - state.get("last_poller_alert", 0) < POLLER_ALERT_COOLDOWN_SEC:
        return  # クールダウン中(バックストップ)
    when = "脈ファイルなし(未起動/停止)" if age is None else f"最終更新{int(age)}秒前"
    msg = (
        f"⚠受信(discord_gateway)停止の可能性(自動監視): Discord受信の死活脈が{when}。"
        "受信が止まると新着が一切キューへ届かず、Discordの呼びかけに誰も気づけません。"
        "確認= `powershell scripts\\_daemons\\status.ps1`(番人=daemon_keeperが常時立て直す対象です)。"
    )
    if bot_send(SUMMARY_DEPT, msg, dry_run, by_dept=True):
        state["last_poller_alert"] = now_epoch
        state["poller_down"] = True


def _age_or_none(path):
    if not os.path.exists(path):
        return None
    return time.time() - os.path.getmtime(path)


def check_lab_pulse(state, dry_run):
    """司令塔のliveness脈が死んだまま放置されるのを検知する(裁定C-044⑤)。

    鳴らす条件= 脈が24時間以上古い **かつ** 司令塔の耳(readiness)は動いている。
    ★片方だけでは鳴らさない: 司令塔が閉じているだけの夜間に鳴らしても行動が変わらず、
      「常に鳴っている警報」= 誰も読まない警報を自分で作ることになる(規律§3)。
    状態遷移で1回だけ鳴らし、戻ったら✅を1回出す(check_poller_health と同じレール)。
    """
    live = _age_or_none(LAB_TOOL_PULSE)
    ready = _age_or_none(CLAUDE_ACTIVE)
    traffic = (ready is not None) and (ready < LAB_TRAFFIC_SEC)
    stale = (live is None) or (live >= LAB_PULSE_STALE_SEC)
    down = bool(traffic and stale)
    was_down = bool(state.get("lab_pulse_down"))
    now_epoch = time.time()
    if not down:
        if was_down and not stale:
            # 復旧= 脈が戻った時だけ✅(司令塔が閉じて traffic が消えただけの時は黙る)
            if bot_send(SUMMARY_DEPT,
                        "✅司令塔のliveness脈は復旧しました — lab_tool_pulse.txt が"
                        f"{int(live)}秒前まで戻っています(自動監視・C-044⑤)。", dry_run, by_dept=True):
                state["lab_pulse_down"] = False
        elif not stale:
            state["lab_pulse_down"] = False
        return
    if was_down:
        return
    if now_epoch - state.get("last_lab_pulse_alert", 0) < LAB_PULSE_ALERT_COOLDOWN_SEC:
        return
    when = "脈ファイルなし" if live is None else f"最終更新{live / 3600.0:.1f}時間前"
    msg = (
        f"⚠司令塔のliveness脈が止まっています(自動監視・C-044⑤): lab_tool_pulse.txt が{when}。"
        f"耳(readiness)は{int(ready)}秒前まで動いているので、司令塔は居ます。"
        "この脈が死ぬと生存判定が readiness 1本へ退行し、長い作業の最中に代打が出ます"
        "(INC-94の再来)。打ち手= hook `scripts/hooks/pulse_touch.py`、"
        "身元= `local/llm/lab_owner_pid.txt`(耳の武装時に書かれる)。"
    )
    if bot_send(SUMMARY_DEPT, msg, dry_run, by_dept=True):
        state["last_lab_pulse_alert"] = now_epoch
        state["lab_pulse_down"] = True


# --- ★リンク死活監視 (2026-07-20 da.gd障害インシデント対応・緊急Chami指示) ---
#   実害: da.gdグローバル障害(522)で公開64本中53本のYT概要欄リンク(表示用da.gd)が全滅。
#   発見がChamiのiPad手動アクセス=監視の穴。ここで収益導線の外部依存を定期監視し、
#   down/復旧の状態遷移でincidentへ1通ずつ通知する(狼少年にしない)。
LINK_HEALTH_GATE_SEC = 30 * 60   # 30分毎(外部サービスへ礼儀的な頻度)
LINK_TARGETS = [
    # (名前, URL, タイムアウト秒) — 収益導線の全ホップ
    # ★2026-07-21: da.gd を監視から外した(Chami裁定「復旧待ちはやめる。治ったらラッキー」)。
    #   サービス本体が停止しており復旧の見込みを誰も制御できない=鳴らし続けても行動が変わらない
    #   =ORG-09と同じ「読まれない警報」を自分で作ることになる。調査書=
    #   docs/設計・調査/調査_da.gd障害はBANか障害か_2026-07-21.md
    #   代わりに**現行の収益導線である自前ドメイン2本**を監視対象にした(ここが死ぬと実害が出る)。
    ("5mgl.com(acc1 月詠み・現行短縮)", "https://5mgl.com/", 10),
    ("yoz2.com(acc2 宵桜艶帖・現行短縮)", "https://yoz2.com/", 10),
    ("r2(自前計測短縮worker)", "https://r2.trustsignalbot.workers.dev/", 10),
]


def _http_alive(url, timeout):
    """HTTP応答が返れば生存(404も生存=サーバは生きている)。5xx/timeout/接続不能=死。"""
    import urllib.request
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "go5-linkhealth/1.0"})
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status < 500
    except Exception as e:
        code = getattr(e, "code", None)   # HTTPError(4xx)は生存扱い
        return code is not None and code < 500


def check_link_health(state, dry_run):
    now_epoch = time.time()
    if now_epoch - state.get("last_link_health", 0) < LINK_HEALTH_GATE_SEC:
        return
    state["last_link_health"] = now_epoch
    st = state.setdefault("link_health", {})
    for name, url, to in LINK_TARGETS:
        alive = _http_alive(url, to)
        prev = st.get(name, "up")
        cur = "up" if alive else "down"
        if cur != prev:
            if cur == "down":
                msg = (f"🔗⚠ **{name} がダウン**({url} 応答なし/5xx)。"
                       "YT概要欄の表示用リンクがda.gd依存の場合、その導線は今止まっています。"
                       "計測用r2リンクは独立(こちらもこの監視の対象)。復旧したら再度通知します。")
            else:
                msg = f"🔗✅ **{name} 復旧** — リンク導線は再び機能しています。"
            bot_send(SUMMARY_DEPT, msg, dry_run, by_dept=True)
        st[name] = cur


# --- ★CI失敗の可視化 (2026-07-21 Chami「cl失敗はまかせる」= 宛先は研究室HQが決める) ---
#
# 背景(ORG-09): GitHub Actionsの失敗通知は**メールにしか出ていなかった**。
#   2026-07-20は同じ検査が6回落ちて6通届いたが、誰も読まず運用は変わらなかった。
#   Chamiが不審に思って持ち込むまで表に出ていない。**鳴っていたが届いていなかった**。
#
# ★宛先を system-engineer(バックエンドα)にした理由:
#   ①**生きた消費者が居る唯一の候補**(dept_daemon稼働中)。report-notify は自動出力の部屋で、
#     そこへ流すと「メールの代わりに読まれない部屋へ置く」だけ=同じ穴を掘り直すことになる。
#   ②フロント/CI/デプロイはこの部門の職責そのもの(直せる主体の手元へ出す)。
#   ③デーモンが受けるので、範囲外なら本人の判断でHQへ上げてくる(3階梯=RULES §6.4)。
CI_DEPT = "system-engineer"
CI_GATE_SEC = 15 * 60            # 15分毎(GitHub APIへ礼儀的な頻度)
CI_REPO = "John-Mori/go5-maker-7b311d01"

# --- ★通知の間引き (2026-08-11 Chami msg 1536743924939628695) ---
#   Chami原文=「CLがおちてます通知が多すぎる。特に改修α。で、特に問題ないことしかない。無駄な通知要らない」
#
#   実測(2026-08-11 23:2x JST・gh run list --limit 40):
#     Frontend deploy smoke (恒久-3) = failure 17 / success 2、pages build and deployment = success 21。
#     落ちている理由は**全部同じ1件**= `check_schedule_ver.mjs` の verstamp 焼き直し漏れ
#     (本物の版ずれ=中身が変わったのに ?v= 据え置き、は 0件)。
#
#   何が悪かったか: 旧実装は **run_id(=pushごと)** で新着を判定していた。赤が続いている間は
#     pushのたびに新しいrun_idが生まれるので、**同じ1つの故障で何通も鳴る**。
#     共通規律§3「常に誤発火する安全網は無視される」の典型で、実際Chamiに無視されるどころか邪魔になった。
#
#   直し方: 単位を run_id から **検査(ワークフロー)ごとの状態遷移** へ変える。
#     緑→赤の**1回だけ**鳴らす。赤のまま続く間は黙る。緑に戻ったら状態を静かに戻すだけ(復旧通知も出さない
#     =通知を増やさないのが今回の目的だから)。★導入時に既に赤いものは鳴らさない(初回は現状を黙って記録)。
CI_JUDGED = ("success", "failure", "timed_out")   # cancelled/skipped等は判定に使わない(赤にも緑にもしない)


def _gh_latest_per_workflow(limit=40):
    """gh CLIで直近runを取り、**検査(ワークフロー)ごとの最新の結論**を返す。

    ghが無い/未認証なら**黙って空**(fail-open)=監視のために本体を止めない。
    """
    try:
        p = subprocess.run(
            ["gh", "run", "list", "--repo", CI_REPO, "--limit", str(limit),
             "--json", "databaseId,name,displayTitle,url,createdAt,conclusion,status"],
            capture_output=True, timeout=45, text=True, encoding="utf-8", errors="replace")
        if p.returncode != 0:
            return {}
        runs = json.loads(p.stdout or "[]")
    except Exception:
        return {}
    latest = {}
    for r in runs:                       # ghは新しい順。各名前で最初に出たものが最新
        if r.get("status") != "completed" or r.get("conclusion") not in CI_JUDGED:
            continue                     # 実行中・中止は判定しない
        name = r.get("name") or ""
        if name and name not in latest:
            latest[name] = r
    return latest


def check_ci_health(state, dry_run):
    now_epoch = time.time()
    if now_epoch - state.get("last_ci_check", 0) < CI_GATE_SEC:
        return
    state["last_ci_check"] = now_epoch
    latest = _gh_latest_per_workflow()
    if not latest:
        return
    cur = {n: ("red" if r.get("conclusion") != "success" else "green")
           for n, r in latest.items()}
    prev = state.get("ci_status")
    if prev is None:                     # ★移行(初回)= 今の姿を黙って覚えるだけ。既知の赤で鳴らさない
        state["ci_status"] = cur
        return
    fresh = [latest[n] for n, v in cur.items() if v == "red" and prev.get(n) != "red"]
    state["ci_status"] = cur
    if not fresh:
        return
    lines = []
    for r in fresh[:3]:
        # ★URLは <> で囲む= Discordの自動埋め込み(GitHubのリポジトリカード)を出さない。
        #   Chami指示 2026-08-11(msg 1536582235602296957)「この機能必要っていうのは良いとして、
        #   埋め込みは表示しないようにして」= 1件の通知にカードが2枚積まれて画面を潰していた。
        #   リンク自体は残る(タップで飛べる)。
        lines.append(f"・**{r.get('name','')}** — {str(r.get('displayTitle',''))[:70]}\n  <{r.get('url','')}>")
    more = f"\n(他 {len(fresh) - 3} 件)" if len(fresh) > 3 else ""
    msg = ("🚨 **CIが落ちています**(GitHub Actions)\n" + "\n".join(lines) + more +
           "\n\n★`?v=` は必ず `node scripts/bump.mjs` で**一括**バンプすること"
           "(個別に手で上げるとスモークが即赤になる=ORG-09)。"
           "\n★この通知は**緑→赤に変わった時の1回だけ**です(赤のまま続く間は鳴りません)。"
           "つまり出た時は『新しく落ちた』。直したら緑に戻してください。"
           "\n原因が分からない/範囲外なら研究室HQへ上げてください。")
    bot_send(CI_DEPT, msg, dry_run, by_dept=True)


# --- ★チャイム線の死活 (2026-07-21 ORG-14: Chami「10分応答なし」「塞いだ→塞いでません」) ---
#
# 何が起きたか: ORG-12でsweepを止め「便が消えない」ようにしたが、**誰も起こしに来ない**穴が
#   残っていた。総括本部4室は専任デーモンを持たないので、消費者は対話セッションだけ。
#   そのセッションを起こす唯一の線が inbox_waiter(チャイム)で、これは**新着で1回鳴って終了する**
#   使い捨て(終了がハーネスへの通知=起床の合図)。つまり毎ターン**再武装が必須**。
#   研究室HQが再武装を忘れ、Chamiの便(msg 178)は pending・deliveries=0 のまま10分放置された。
#
# ★構造的な制約(正直に書く): チャイムを再武装できるのは**セッション自身のターン中だけ**。
#   hookや常駐から起動しても、ハーネスが追跡しないプロセスの終了はセッションを起こせない。
#   =この穴は「機構で完全自動化」できない。**だから最低限、落ちていることをChamiに見せる**。
#   沈黙は良いが(ORG-02)、**理由の分からない沈黙は良くない**。
SESSION_OWNED_DEPTS_WD = ("hq", "aegis-gl", "research-room", "keiei-kikaku")
CHIME_STALE_SEC = 5 * 60          # 5分待たされたら知らせる(15分のwatchdogでは遅い)
CHIME_COOLDOWN_SEC = 20 * 60      # 同じ部屋への再通知は20分に1回(鳴りっぱなし防止)


def _waiter_armed(name):
    """【★死んだセンサー・2026-07-27に用途を降格】その部屋のチャイムが武装中か。

    ★実装は1文字も変えていない。**残す**理由= 鳩(inbox_waiter)が復活したら再び有効な信号
      になるから。だが**今は必ずFalseを返す**(lockファイルは実測0件)ので、これ単独を
      ガードに使ってはいけない。判定の正本は下の `_receiver_alive()`。

    検死(Chami原文=「これ対応中なんだからいらんでしょこの通知」msg 1531001024427327542):
      この関数が見る `local/llm/waiter_<部屋>.lock` は **inbox_waiter(鳩)** が生きている間だけ
      更新されるファイル。鳩は **2026-07-19に退役** し、lockは1つも存在しない(実測: 0件)。
      = ガードが常にFalse → 「便が5分残れば必ず鳴る」。実際 2026-07-27 02:49 / 03:11 に
      「チャイム線が落ちています」「デーモン側も止まっている疑い」が鳴ったが、その時間帯
      HQの対話セッションは 02:50/02:56/03:03/03:04 とDiscordへ返信し続けていた=**誤報**。

    ★同じ形の穴がこの日だけで3つ見つかった(全部HQが実測):
      「鳩:★停止疑い」(poller_active.txt を見ていた) /
      「印が付かない」(inbox_waiter信号を探していた・progress_mark.py) /
      この警報(waiter_*.lock を見ていた)。
      **退役した機械のセンサーだけが残り、空を見て鳴っていた。**
      → 教訓: 信号を出す主体を退役させる時は、**その信号を読んでいる側を全部数える**。
    """
    p = os.path.join(LOCAL, "llm", f"waiter_{name}.lock")
    try:
        return (time.time() - os.path.getmtime(p)) < 120
    except OSError:
        return False


# --- ★生きている信号で「受け手が居るか」を判定する (2026-07-27・_waiter_armedの代替) ---
#
# 3つのどれか1つでも真なら「受け手は生きている」= 鳴らさない。
#   ① その部屋へ直近に返信/処理が出ている … 一番強い証拠(答えが出ているなら警報は不要)
#   ② 対話セッションが在席している        … 在席の刻み(下の SESSION_PRESENCE_SEC 参照)
#   ③ 留守番デーモンが生きている **かつ** 直近に処理を出している
#
# ★判定不能(信号が1つも取れない)なら鳴らす側へ倒す(沈黙が最悪=規律§3)。
#   ただし**常時鳴るなら、それは死んだ警報**(ORG-42)なので、生きている信号だけを使う。
SESSION_PRESENCE_SEC = 10 * 60    # 在席ファイルがこれ以内=対話セッションが居る
# ★session_rooms.PRESENCE_TTL(150秒)より広く取る理由:
#   あちらは「デーモンが箱を譲るか」の判定で、譲りすぎない=可用性のため短くて正しい。
#   こちらは「受け手が居るか」の判定。1本のBashが5分回るターンでは刻みが数分空くので、
#   150秒だと**働いている最中に誤報**する(これが直そうとしている事故そのもの)。
#   窓を閉じれば10分で枯れる=自然に警報が戻るので「常時黙る」にはならない。
ANSWER_PROOF_SEC = 15 * 60        # 返信/処理の実績がこれ以内なら受け手は生きている
# ★15分は既存の STALE_MIN(=このwatchdogが「司令塔不在の可能性」と呼ぶ閾値)と同じ値に揃えた。
#   新しい物差しを増やさない(ORG-11)。
DAEMON_PROOF_SEC = 15 * 60        # ③でデーモンに要求する「実際に処理を出した」実績の鮮度
REQUEST_LOG_WD = os.path.join(LOCAL, "llm", "request_log.jsonl")
REQUEST_LOG_TAIL = 256 * 1024     # 末尾だけ読む(全部読むと60秒巡回が重くなる)
# session_relay._record が書く state のうち「答えが出た」を意味するもの。
# answered_by_session = 対話セッションが窓で答えた分(2026-07-27 mirror_to_discord.py が書く)。
ANSWER_STATES = ("completed", "replied", "replied_unverified", "answered_by_session", "recovered")


def _request_log_tail():
    """request_log.jsonl の末尾だけを読んで dict のリストにする。壊れた行は捨てる(fail-open)。"""
    try:
        size = os.path.getsize(REQUEST_LOG_WD)
        with open(REQUEST_LOG_WD, "rb") as f:
            if size > REQUEST_LOG_TAIL:
                f.seek(size - REQUEST_LOG_TAIL)
                f.readline()                    # 途中で切れた1行目は捨てる
            raw = f.read().decode("utf-8", "replace")
    except OSError:
        return []
    out = []
    for line in raw.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            rec = json.loads(line)
        except ValueError:
            continue
        if isinstance(rec, dict):
            out.append(rec)
    return out


def _log_ts_age(rec, now_epoch):
    """1行の ts からの経過秒。_record は**ローカル時刻**で書くのでローカルとして解釈する。"""
    try:
        t = time.mktime(time.strptime(str(rec.get("ts", ""))[:19], "%Y-%m-%dT%H:%M:%S"))
    except (ValueError, OverflowError):
        return None
    return now_epoch - t


def _last_answer_age(dept):
    """その部屋で最後に「答えが出た」ことの経過秒。証拠が無ければ None。

    2つの独立した台帳を見て新しい方を採る:
      (a) queue の done行(acked_at)   … 便が処理済みになった実測
      (b) request_log.jsonl の遷移行  … completed/replied/answered_by_session 等
    """
    ages = []
    now_epoch = time.time()
    if os.path.exists(QUEUE_DB_WD):
        try:
            import sqlite3
            con = sqlite3.connect(f"file:{QUEUE_DB_WD}?mode=ro", uri=True, timeout=2)
            try:
                con.execute("PRAGMA busy_timeout=1000")
                row = con.execute(
                    "select max(acked_at) from queue where dept=? and status='done'",
                    (dept,)).fetchone()
            finally:
                con.close()
            if row and row[0]:
                ages.append(now_epoch - float(row[0]))
        except Exception:
            pass
    for rec in _request_log_tail():
        if rec.get("dept") != dept or rec.get("state") not in ANSWER_STATES:
            continue
        a = _log_ts_age(rec, now_epoch)
        if a is not None:
            ages.append(a)
    return min(ages) if ages else None


def _daemon_work_age(dept):
    """その部屋の**留守番デーモン**が最後に便を掴んだ/処理した経過秒。証拠が無ければ None。

    ★portが開いているだけでは「生きている」と言えない(INC-107= プロセスとTCPは生存、
      処理ループだけ停止)。実際に仕事を出していることまで要求する。
    """
    now_epoch = time.time()
    tag = f"dept_daemon:{dept}"
    ages = []
    for rec in _request_log_tail():
        if rec.get("dept") != dept:
            continue
        if not str(rec.get("evidence", "")).startswith(tag):
            continue
        a = _log_ts_age(rec, now_epoch)
        if a is not None:
            ages.append(a)
    return min(ages) if ages else None


def _session_present(dept):
    """対話セッションが在席しているか(★2026-07-27に実測して正本を確かめた信号)。

    ★正本は `local/llm/interactive_presence_<部屋>.txt`。
      hook(progress_mark.py / mirror_to_discord.py)が `session_rooms.touch_presence()` で刻む。
    ★**`claude_active_<部屋>.txt` ではない**(実測 2026-07-27 03:18):
        interactive_presence_hq.txt …  0.1分前(HQは作業中=正しい)
        claude_active_hq.txt        … 48.4分前
      `claude_active_<部屋>.txt` を書くのは **留守番デーモンの touch_pulse()** で、しかも
      `dept_daemon.run()` の `else:` 側=**在席で譲っていない時だけ**呼ばれる。
      つまり対話セッションが働いている間は**書き手が意図的に黙る**ファイルで、
      「セッションが生きているか」の信号としては構造的に使えない
      (もう1人の書き手だった inbox_waiter は2026-07-19に退役済み)。
    ★置き場の正本は session_rooms.presence_path() から引く(パスを2箇所に書かない=ORG-11)。
      鮮度の閾値だけはこちらの都合(SESSION_PRESENCE_SEC)で持つ。
    """
    p = None
    try:
        sys.path.insert(0, os.path.join(ROOT, "scripts", "llm"))
        import session_rooms
        p = session_rooms.presence_path(dept)
    except Exception:
        p = os.path.join(LOCAL, "llm", f"interactive_presence_{dept}.txt")
    try:
        return (time.time() - os.path.getmtime(p)) < SESSION_PRESENCE_SEC
    except OSError:
        return False


def _receiver_alive(dept):
    """その部屋の受け手が生きているか。(bool, 理由) を返す。理由はログに出して後から追える形。

    ★偽陽性(受け手が居ないのに居ると言う)より、偽陰性(居るのに鳴る)の方が今は害が大きい。
      理由= 誤報は**警報全体を無視させる**(狼少年)。本当の不在は他の警報
      (check_orphan_pending=15分/未配送・check_dead_windows・DLQ監視)でも拾える。
    """
    ans = _last_answer_age(dept)
    if ans is not None and ans < ANSWER_PROOF_SEC:
        return (True, f"直近{int(ans // 60)}分前に返信/処理の実績あり")
    if _session_present(dept):
        return (True, "対話セッションが在席(interactive_presence)")
    if _daemon_alive(dept):
        work = _daemon_work_age(dept)
        if work is not None and work < DAEMON_PROOF_SEC:
            return (True, f"留守番デーモンが生存かつ{int(work // 60)}分前に処理あり")
    return (False, "生きている信号なし(返信実績・在席・デーモン処理のいずれも無し)")


def _daemon_alive(dept):
    """その部屋に留守番デーモンが生きているか。判定不能はFalse(=居ない側)へ倒す。

    居ないのに「居る」と案内する方が有害(Chamiが待ってしまう)ため、迷ったら居ない扱いにする。
    """
    try:
        import socket
        sys.path.insert(0, os.path.join(ROOT, "scripts", "llm"))
        from dept_daemon import DEPT_CONF
        port = (DEPT_CONF.get(dept) or {}).get("port")
        if not port:
            return False
        with socket.create_connection(("127.0.0.1", int(port)), timeout=0.3):
            return True
    except Exception:
        return False


def _pending_age(dept):
    """その deptで最も古い pending便の経過秒。無ければ0。読み取り専用・fail-open。"""
    if not os.path.exists(QUEUE_DB_WD):
        return 0
    try:
        import sqlite3
        con = sqlite3.connect(f"file:{QUEUE_DB_WD}?mode=ro", uri=True, timeout=2)
        try:
            row = con.execute(
                "select min(enqueued_at) from queue where dept=? and status='pending'",
                (dept,)).fetchone()
        finally:
            con.close()
        return max(0, time.time() - row[0]) if row and row[0] else 0
    except Exception:
        return 0


def check_chime_health(state, dry_run):
    """便が待っているのにチャイムが落ちている部屋を、その部屋自身へ知らせる。

    ★通知先を incident ではなく**その部屋**にするのが要点。Chamiが待っているのはそこで、
      incidentへ出しても読まれない(ORG-09=読まれない警報を自分で作る、の再発になる)。
    """
    st = state.setdefault("chime_alert", {})
    now_epoch = time.time()
    for dept in SESSION_OWNED_DEPTS_WD:
        age = _pending_age(dept)
        if age < CHIME_STALE_SEC:
            continue
        if _waiter_armed(dept):
            continue                # 旧信号(鳩)。今は必ずFalse=実質無効。復活したら効く
        # ★2026-07-27: ここが「常に鳴る」の真因だった。旧ガードは _waiter_armed だけで、
        #   その信号は退役済み=常にFalse → 便が5分残れば必ず鳴っていた。
        #   生きている信号で判定し直す(_receiver_alive の docstring 参照)。
        # ★2026-07-27(2度目の是正) Chami=「これちゃんと研究室動いているならいらないアラートだよね?」
        #   1度目の是正でも鳴った。理由= `_receiver_alive` の在席判定が**10分の時間窓**で、
        #   セッションが長考中・サブエージェント待ちの間は hook が動かず脈が止まるため。
        #   → **窓のプロセスが生きているか**という実体で先に見る(時間ではない)。
        #   ★さらに今日から、この4室は**デーモンが答えない設計**になった(1部屋1所有者)。
        #     便が数十分 pending なのは**窓が答えている最中という正常な姿**であって異常ではない。
        try:
            sys.path.insert(0, os.path.join(ROOT, "scripts", "_common"))
            from session_presence import window_present
            present, pwhy = window_present(dept)
        except Exception:
            present, pwhy = (False, "")
        if present:
            print(f"[chime] {dept}: 便が{int(age // 60)}分滞留しているが窓が在る — {pwhy}")
            continue
        alive, why = _receiver_alive(dept)
        if alive:
            # 警報は出さないが、判断の跡はログに残す(黙って握り潰すと次の調査で困る)。
            print(f"[chime] {dept}: 便が{int(age // 60)}分滞留しているが受け手は生存 — {why}")
            continue
        if now_epoch - st.get(dept, 0) < CHIME_COOLDOWN_SEC:
            continue
        st[dept] = now_epoch
        # ★部屋名を必ず本文に入れる(2026-07-21 ORG-28)。
        #   旧文は「**この部屋の**チャイム線が…」だった。Chamiがこの警告を別の部屋へ**転送**した瞬間、
        #   どの部屋の話か分からなくなり、hqのデーモン(アメス)が「この部屋=hqにデーモンが居ない」と
        #   誤読した(実際はアメス自身がhqのデーモン)。**転送されても意味が保たれる文にする**。
        #   今日の他の事故と同型= 文脈は転送で失われる前提で書く。
        # ★デーモンの有無で文面を変える(同 ORG-28)。留守番デーモンを置いた部屋に対して
        #   「セッションを開かないと拾えません」と出すのは**事実と違う**。
        #   デーモンが居るのに便が5分溜まっているなら、それは**デーモンも止まっている**という
        #   より重い異常で、案内すべき対処が正反対になる。
        # ★部屋名は日本語+スラッグ(2026-07-27)。転送されても意味が保たれる形はORG-28で確定済み。
        #   スラッグを残すのは、この警報の対処(status.ps1・DEPT_CONF)で実際に要るため。
        room = dept_ja(dept, with_slug=True)
        if _daemon_alive(dept):
            # ★2026-07-27 文面を事実に合わせた。この4室は**デーモンが答えない設計**へ変わったので
            #   「デーモンも止まっている疑い」は**嘘になる**(黙っているのが正常な姿)。
            #   ここに来た時点で分かっているのは「窓が無い」「relayも答えていない」の2つだけだ。
            tail = (f"★{room} は**あなたの窓が答える部屋**です(留守番デーモンは答えません)。\n"
                    "窓が見つからず、代わりのセッションも答えていません。\n"
                    "→ その部屋のClaude Codeセッションを開くか、艦隊を確認: "
                    "`scripts\\_daemons\\status.ps1`")
        else:
            tail = (f"★{room} は対話セッション本人が担当する部屋で、留守番デーモンが居ません。\n"
                    "**その部屋のClaude Codeセッションを開かないと拾えません**。")
        bot_send(dept, (
            f"⚠ **{room} のチャイム線が落ちています**(約{int(age // 60)}分前の依頼が未受信)。\n"
            "依頼は消えていません。queueに保持されていて、担当が起きれば必ず読まれます。\n"
            f"{tail}\n"
            "(この文を別の部屋へ転送する場合は、上の部屋名がどこを指すかご注意ください)"),
            dry_run, by_dept=True)


# --- ★取りこぼし便の定期回収 (2026-07-25 gatewayにcatch-upが無い穴・HQ発注2026-07-26) ---
#
# 何が起きたか: scripts/queue/discord_gateway.py は **Discord Gateway(WebSocket)の push受信**
#   しか持たず、catch-up / last_seen / backfill に相当する仕組みが1つも無い。
#   gatewayが受信していない間にChamiが書いた便は、gatewayが復帰しても永久に取り込まれない。
#   queueに行が生まれないので未配送監視(check_orphan_pending)にもDLQにも引っかからない
#   =完全な沈黙になる。2026-07-25に実際に2件が失われていたのを検出し手で回収した。
#
# ★なぜ「gateway起動時に1回」ではなく「定期実行」なのか(この設計の理由):
#   gatewayが**再起動する**ケースだけなら起動時catch-upで足りる。しかし
#   **プロセスは生きているのに受信だけが止まる**ケースがある(INC-107: プロセスとTCPは
#   生存していたが処理ループ停止)。ゾンビは再起動しないので起動時catch-upは永久に走らない。
#   定期実行なら「再起動した」も「生きたまま黙った」も**両方**拾える。
#
# ★回収ロジックをここへ写さない(ORG-11: 同じ判定を2箇所に持たない)。
#   取りこぼしの判定の正本は relay_health.collect_missing()、回収の正本は relay_repair.py。
#   watchdogは「定期的に叩く起動係」に徹する。窓72時間・最大20件も relay_repair の既定のまま。
RELAY_REPAIR_PY = os.path.normpath(
    os.path.join(ROOT, "..", "00_AI-HQ", "scripts", "relay_repair.py"))
RELAY_REPAIR_GATE_SEC = 15 * 60    # 15分に1回だけ(毎巡回=60秒毎に叩くとDiscord APIの無駄打ち)
RELAY_REPAIR_TIMEOUT_SEC = 180     # ★止まったサブプロセスでwatchdogの巡回を詰まらせない


def _relay_repair_recovered(out):
    """relay_repair の出力から「実際にqueueへ入れ直した件数」を読む。

    正本は最終行の `結果: 回収 N件 / ...`。この行が無い(=取りこぼし0件で早期return等)
    ときは0件。★自前で行を数え直さない: relay_repair 自身が出した結論の数字だけを信じる。
    """
    m = re.search(r"結果: 回収 (\d+)件", out or "")
    return int(m.group(1)) if m else 0


def check_relay_repair(state, dry_run, now_epoch=None):
    """gatewayの取りこぼしを15分に1回 subprocess で回収する(理由は上のブロックコメント)。

    ★0件なら何も出さない。1件以上のときだけwatchdogログへ1行。
      **Discordへは通知しない**(ORG-03/42: 鳴らし過ぎない)。回収された便そのものが
      該当部屋へ流れて処理されるので、そこで自然にChamiの目に入る。通知を重ねると
      同じ事を2回鳴らすことになる。
    ★どんな失敗でもwatchdogを止めない(例外は握り潰してログ1行)。watchdogが死ぬのが最悪。
    """
    now_epoch = time.time() if now_epoch is None else now_epoch
    if now_epoch - state.get("last_relay_repair", 0) < RELAY_REPAIR_GATE_SEC:
        return
    # ★先に時刻を進める。失敗しても60秒毎に叩き直さない(外部APIを殴り続けない)。
    state["last_relay_repair"] = now_epoch
    if dry_run:
        print(f"[dry-run] relay_repair --repair は実行しない({RELAY_REPAIR_PY})")
        return
    try:
        r = subprocess.run(
            [sys.executable, RELAY_REPAIR_PY, "--repair"],
            capture_output=True, timeout=RELAY_REPAIR_TIMEOUT_SEC,
            text=True, encoding="utf-8", errors="replace")
        if r.returncode != 0:
            tail = (r.stderr or r.stdout or "").strip().splitlines()
            print(f"取りこぼし回収に失敗(rc={r.returncode}): "
                  f"{tail[-1] if tail else '(出力なし)'}")
            return
        n = _relay_repair_recovered(r.stdout)
        if n > 0:
            print(f"★取りこぼし{n}件を回収した(gateway停止中の便)")
    except Exception as e:
        # タイムアウト(TimeoutExpired)・実行不能・その他すべてここで止める。
        print(f"取りこぼし回収の起動に失敗: {type(e).__name__}")


# --- ★O1 DLQ監視 (改善書P0-5: 5回配送失敗→dead に隔離された毒メッセージを誰も見ていない) ---
QUEUE_DB_WD = os.path.join(LOCAL, "queue", "inbox.db")
DEAD_ALERT_COOLDOWN_SEC = 60 * 60  # デッドレター通知は1時間に1回まで(暴走ガード)


def queue_db_path():
    """DLQ系の警報が読むキューDBの在りか。**差し替え点**(2026-08-14 イージス研究室)。

    ★これは検査のための継ぎ目だ。理由= 滞留(stale)の警報は「滞留が0件だと発火しない」ため、
      本番DBをそのまま読む形では**入力を作れず**、検査がソースの文字列一致へ落ちていた
      (共通規律§3= それは検査ではなく保険。本番の初発火が実質の初検証になる)。
      → 読む先を1関数に切り出し、検査側が**滞留が在る状態の偽DB**を渡して
        判定・本文・宛先を**実行で**通せるようにする(HQ裁定 2026-08-14・2部門で連続2回の指摘)。
    ★本番の挙動は変わらない(既定は従来どおり local/queue/inbox.db)。
    """
    return QUEUE_DB_WD


def dead_letter_summary():
    """DLQ(status='dead')の総数・dept内訳・**最大id**。読み取り専用・fail-open(DB不在/ロックで0)。

    ★max_id を足した(2026-08-13 一ノ瀬怜)= check_dead_letters が「件数の増分」で鳴る形だと、
      古いdeadが1件手当て/purgeされた同じ周期に新しいdeadが1件落ちると **total が増えず**
      (net-zero)警報が黙る穴があった。dead行のidは単調増加=**過去の最大idより大きいdead**が
      現れたら「新しい隔離が起きた」と確実に言える(件数の増減に一切左右されない)。
    """
    db = queue_db_path()
    if not os.path.exists(db):
        return 0, {}, 0
    try:
        import sqlite3
        con = sqlite3.connect(f"file:{db}?mode=ro", uri=True, timeout=2)
        try:
            con.execute("PRAGMA busy_timeout=1000")
            rows = con.execute(
                "SELECT dept, COUNT(*), MAX(id) FROM queue WHERE status='dead' GROUP BY dept"
            ).fetchall()
        finally:
            con.close()
        total = sum(r[1] for r in rows)
        by = {(r[0] or "?"): r[1] for r in rows}
        max_id = max((r[2] or 0) for r in rows) if rows else 0
        return total, by, max_id
    except Exception:
        return 0, {}, 0


# --- ★2026-07-20 未配送pending監視 (INC-110: 消費者不在のdept宛が無警報で永久に沈む) ---
# 背景: data-org宛の依頼が25分間pendingのまま誰にも拾われなかった。チャンネル台帳には在ったが
#   dept_daemon.py の DEPT_CONF に未登録=消費者プロセスが存在しなかった。
#   既存の警報は「_work/へ退避済みの滞留」と「DLQ(dead)」しか見ない。一度もリースされない行
#   (status='pending' かつ deliveries=0)はどちらにも該当せず、全ての目を素通りする穴だった。
ORPHAN_PENDING_MIN_SEC = 15 * 60      # これ以上誰にも掴まれなければ異常
ORPHAN_ALERT_COOLDOWN_SEC = 60 * 60


def orphan_pending_summary():
    """一度も配送されていないpending行のdept内訳と最古の滞留秒数。読み取り専用・fail-open。"""
    db = queue_db_path()
    if not os.path.exists(db):
        return {}
    try:
        import sqlite3
        con = sqlite3.connect(f"file:{db}?mode=ro", uri=True, timeout=2)
        try:
            con.execute("PRAGMA busy_timeout=1000")
            rows = con.execute(
                "SELECT dept, COUNT(*), MIN(enqueued_at) FROM queue "
                "WHERE status='pending' AND deliveries=0 GROUP BY dept").fetchall()
        finally:
            con.close()
    except Exception:
        return {}
    now_epoch = time.time()
    out = {}
    for dept, cnt, oldest in rows:
        try:
            age = now_epoch - float(oldest)
        except (TypeError, ValueError):
            continue
        if age >= ORPHAN_PENDING_MIN_SEC:
            out[dept or "?"] = (cnt, int(age // 60))
    return out


def check_orphan_pending(state, dry_run):
    """宛先部門に消費者が居ないまま沈んだ依頼を検知する。
    deliveries=0=一度もリースされていない=デーモン未登録/全滅の疑い。"""
    orphans = orphan_pending_summary()
    if not orphans:
        return
    now_epoch = time.time()
    if now_epoch - state.get("last_orphan_alert", 0) < ORPHAN_ALERT_COOLDOWN_SEC:
        return
    # ★日本語名(スラッグ)の形。ここは直す手順に**スラッグそのものが要る**(DEPT_CONFを引く)ため
    #   両方出す。Chamiが読むだけの行は日本語だけにしてある(2026-07-27)。
    detail = "、".join(f"{dept_ja(d, with_slug=True)}={n}件/最古{m}分"
                       for d, (n, m) in orphans.items())
    msg = (f"🕳 **未配送のまま滞留**: {detail}。"
           "一度も配送されていない(deliveries=0)=宛先部門に**消費者プロセスが存在しない**疑いです。"
           "確認: dept_daemon.py の DEPT_CONF に該当deptが登録されているか / "
           "`powershell scripts\\_daemons\\status.ps1` でdept_daemon数が期待値か。"
           "チャンネルだけ作ってDEPT_CONF登録を忘れると、依頼はここに永久に沈みます(INC-110)。")
    if bot_send(SUMMARY_DEPT, msg, dry_run, by_dept=True):
        state["last_orphan_alert"] = now_epoch


def dead_ids():
    """dead 行の **id の集合**。読み取り専用・fail-open(DB不在/ロックで空集合)。

    ★2026-08-14 イージス研究室(HQ発注 msg 1537539162083823732)。
      なぜ「集合」が要るか= 高水位(last_dead_max_id)1本では**順序の穴**が塞げない。
      id は**投函順**に振られるが、dead に落ちるのは**5回配送に失敗した後**だ。
      = 先に入った便が後から入った便より**遅れて死ぬ**と、その id は基準より小さく、
        `max_id <= last_id` で**永久に黙る**(基準は purge 対策で下げない設計のため)。
      「告知済みの id を持つ」形にすれば、基準を下げずに順序の穴も塞げる。
    """
    db = queue_db_path()
    if not os.path.exists(db):
        return set()
    try:
        import sqlite3
        con = sqlite3.connect(f"file:{db}?mode=ro", uri=True, timeout=2)
        try:
            con.execute("PRAGMA busy_timeout=1000")
            rows = con.execute("SELECT id FROM queue WHERE status='dead'").fetchall()
        finally:
            con.close()
        return {int(r[0]) for r in rows if r[0] is not None}
    except Exception:
        return set()


def check_dead_letters(state, dry_run):
    """毒メッセージ(max_deliveries超過でdead隔離)が黙って消えるのを防ぐ=**遷移時**の速報(60s周期)。

    ★2026-08-13 一ノ瀬怜 2点直した(HQ便 1537339495504936980「この辺の通知大丈夫?」の依頼2):
      (1) 判定を件数ではなく**最大idの前進**にした。旧= total<=last で即return=古いdead1件が
          手当て/purgeされた同周期に新規dead1件が落ちると net-zero で黙る穴があった。dead行の
          idは単調増加なので「前回見た最大idより大きいdeadが在る」ことだけを見れば、件数の
          増減に一切左右されずに**新しい隔離**を必ず捕まえる。
      (2) 宛先に **hq を足した**。旧= incident部屋だけ=**動ける人(研究室HQ)が読まない場所**へ
          しか出ておらず、実測(2026-08-13)で速報は 08:32 に鳴っていたのにHQは「完全サイレント」と
          判断しsqliteを直接見に行った。滞留警報(check_stale_dead)は同日hqを足したが、こちらの
          **速報(60s)**が hq に届いていなかった=遷移時に気づける経路が塞がっていた核心。
    """
    total, by, max_id = dead_letter_summary()
    # ★last_dead_count は weekly_metrics.py が現在のdead件数として読む=毎周期同期させておく
    #   (判定には使わない。判定は下の「告知済みidの集合」のみ)。
    state["last_dead_count"] = total
    if total == 0:
        return
    ids = dead_ids()
    if not ids:
        return                       # 集合が引けない(DBロック等)=fail-open で黙る
    # ★★2026-08-14 判定を「最大idの前進」から**「告知済みidの集合」**へ替えた(順序の穴・上の dead_ids)。
    #   ★集合は**現に dead な行だけ**を毎回書き戻す= 際限なく太らない(purge済みの id は自然に落ちる)。
    if "dead_announced_ids" in state:
        known = {int(x) for x in (state.get("dead_announced_ids") or [])}
    elif "last_dead_max_id" in state:
        # 移行(1回だけ)= 旧い高水位を**集合へ翻訳する**。基準以下の現dead行は「告知済み」とみなす。
        #   ★以後 last_dead_max_id は判定に使わない(互換のため書き続けるだけ)。
        known = {i for i in ids if i <= int(state.get("last_dead_max_id") or 0)}
        # ★★翻訳した結果を**その場で凍結する**。ここを毎周回やり直すと
        #   「基準より小さい id は常に告知済み」= **順序の穴がそのまま残る**(直す意味が消える)。
        state["dead_announced_ids"] = sorted(known)
    else:
        # ★新コードの初回=既存deadを**黙って取り込む**(告知しない)。
        #   デプロイ時点で既に隔離済みの行は「新しい隔離」ではないため。
        state["dead_announced_ids"] = sorted(ids)
        state["last_dead_max_id"] = max_id
        return
    fresh = sorted(i for i in ids if i not in known)
    if not fresh:
        return                       # 新しい隔離は無い(★件数にも id の大小にも左右されない)
    now_epoch = time.time()
    if now_epoch - state.get("last_dead_alert", 0) < DEAD_ALERT_COOLDOWN_SEC:
        return
    detail = "、".join(f"{dept_ja(d, with_slug=True)}={n}" for d, n in by.items()) or "(内訳不明)"
    newly = "・".join(str(i) for i in fresh[:10]) + ("…" if len(fresh) > 10 else "")
    msg = (f"⚠デッドレターが新たに発生(現在計{total}件・新規id {newly}): {detail}。"
           "5回配送しても処理できずキューに隔離されたメッセージです。"
           "毒メッセージ(壊れた本文/対応不能な依頼)か、宛先部門の長期不在・配送処理の例外が原因。"
           "中身を見る: `python scripts/queue/dlq_tool.py --list`。"
           "手当てしたら印を付ける: "
           "`python scripts/queue/dlq_tool.py --ack <id> --by \"<誰>\" --note \"<どう片付けたか>\"`。")
    # ★2026-08-14 宛先を **incident + hq の2室に固定**(HQ裁定 DISPATCH-aegis-gl-1786644517490。
    #   出典= Chami msg 1537520749349310605「これ送られる部屋が多すぎて邪魔かな」)。
    #   直前の実発火(02:37:45)は by が5部門= incident+hq+5部門の**7室**へ同一の長文が出ていた。
    #   当該部門へ1件ずつ出す仕事は 9325c04 の on_dead フック(dept_daemon の _dead_letter_notice)が
    #   持っている= 同じ事実を「集計の長文で全室へ」と「個別に当該室へ」で二重に配っていた。
    #   ★内訳(detail)は本文に残る=どの部門で詰まっているかは2室で読める。判定・頻度・本文は変えない。
    targets = [SUMMARY_DEPT, "hq"]
    sent = False
    for dept in targets:
        if bot_send(dept, msg, dry_run, by_dept=True):
            sent = True
    if sent:
        state["last_dead_alert"] = now_epoch
        # ★告知できた時だけ更新する(送信に失敗した便は次の周回で必ずもう一度拾う)。
        state["dead_announced_ids"] = sorted(ids)
        state["last_dead_max_id"] = max(max_id, int(state.get("last_dead_max_id") or 0))


# --- ★★2026-08-12 dead が「増えない限り二度と鳴らない」穴を塞ぐ(イージス研究室/KPI A1) ---
# 実測(2026-08-12 02:45): status='dead' が3件、**2026-07-30 05:03〜05:11 から13日間**残っていた。
#   中身は3件ともChami本人の便で、うち1件は「この部屋、応答できる?」(イージス研究室宛)。
#   誰にも掴まれず、誰にも警報されないまま沈黙した= まさに A1 無警報滞留。
# 真因は上の check_dead_letters の形にある= **増分でしか鳴らない**(total<=last で即return)。
#   一度鳴った(あるいは基準が追いついた)時点でその滞留は永久に見えなくなる。
#   ★「鳴った」と「片付いた」は別物なのに、片方の記録で両方を代表させていた。
# → 増分とは別に**滞留の年齢**を見る。手当ての印が付くまで1日1回だけ言い続ける。
STALE_DEAD_MIN_SEC = 6 * 60 * 60        # dead になって6時間、まだ手当ての印が無ければ滞留
STALE_DEAD_COOLDOWN_SEC = 24 * 60 * 60  # 1日1回まで(毎周期鳴らすと無視される安全網になる)


def stale_dead_summary():
    """手当ての印が無いまま残っている dead 行。読み取り専用・fail-open(DB不在/ロックで空)。

    手当て済みの印= result 列が空でない(scripts/queue/dlq_tool.py --ack が書く)。
    ★status は 'dead' のまま動かさない= 既存の件数・台帳の意味を変えないため。
    戻り値: (件数, {dept: 件数}, 最古の滞留秒数, Chami発の件数)
    """
    db = queue_db_path()
    if not os.path.exists(db):
        return 0, {}, 0, 0
    try:
        import sqlite3
        con = sqlite3.connect(f"file:{db}?mode=ro", uri=True, timeout=2)
        try:
            con.execute("PRAGMA busy_timeout=1000")
            rows = con.execute(
                "SELECT dept, enqueued_at, body FROM queue "
                "WHERE status='dead' AND (result IS NULL OR result='')").fetchall()
        finally:
            con.close()
    except Exception:
        return 0, {}, 0, 0
    now_epoch = time.time()
    by, oldest, from_chami = {}, 0, 0
    for dept, enq, body in rows:
        try:
            age = now_epoch - float(enq)
        except (TypeError, ValueError):
            continue
        if age < STALE_DEAD_MIN_SEC:
            continue
        by[dept or "?"] = by.get(dept or "?", 0) + 1
        oldest = max(oldest, age)
        # ★Chami本人の便かどうかは重大度が違う(返事を待っている人間が居る)。
        #   本文はDiscordの生JSON。author名を素朴に見るだけ=判定不能なら鳴らす側へ倒す。
        if body and '"author": "chami' in str(body):
            from_chami += 1
    return sum(by.values()), by, int(oldest), from_chami


def check_stale_dead(state, dry_run):
    """dead に落ちたまま手当てされていない便を、片付くまで1日1回だけ言い続ける。"""
    total, by, oldest_sec, from_chami = stale_dead_summary()
    if not total:
        return
    now_epoch = time.time()
    if now_epoch - state.get("last_stale_dead_alert", 0) < STALE_DEAD_COOLDOWN_SEC:
        return
    detail = "、".join(f"{dept_ja(d, with_slug=True)}={n}件" for d, n in by.items())
    head = "🕳 **配送に失敗したまま放置されている便**"
    if from_chami:
        head = f"🔥 **Chamiの便が{from_chami}件、配送に失敗したまま放置されています**"
    msg = (f"{head}: 計{total}件({detail})、最古は**{int(oldest_sec // 3600)}時間前**。"
           "5回配送しても処理できずキューへ隔離された行が、手当ての印が付かないまま残っています。"
           "★この警報はデッドレターの**増分**ではなく**滞留**を見ています"
           "(増分監視は一度鳴ると二度と鳴らないため、13日間見えなかった実例がある)。"
           "中身を見る: `python scripts/queue/dlq_tool.py --list`。"
           "手当てしたら印を付ける(これで鳴り止む): "
           "`python scripts/queue/dlq_tool.py --ack <id> --by \"<誰>\" --note \"<どう片付けたか>\"`。")
    # ★2026-08-13 宛先を足した(イージス研究室・HQ便 1537344368124366889 の依頼3への回答)。
    #   実測= 2026-08-13 の 🔥digest 消失で、増分警報 08:32・滞留警報 15:25 の**2本とも鳴っていた**。
    #   それでも研究室HQは「完全サイレント」と判断し、sqliteを直接見て真因へ辿り着いた。
    #   = 穴は「鳴らない」ではなく「**鳴っている場所を、動ける人が読んでいない**」(共通規律§4)。
    #   → 3本目の警報を作らず、既存の1本の**宛先**を足す。1日1回の上限は変えない=増音しない。
    #   ★不明な宛先(dept='router' 等)は bot_send が False を返すだけ=fail-open・他の宛先は届く。
    # ★2026-08-14 **当該部門への横展開だけを外す**(HQ裁定 DISPATCH-aegis-gl-1786644517490)。
    #   2026-08-13 に hq を足したのは正しい(動ける人が読む場所へ出す)=そこは残す。
    #   デッドレターの手当てはHQ/基盤の仕事で、ackも dlq_tool.py で一括だ=各部門は自室の1件で動かない。
    #   増音の巻き戻しであって警報の弱体化ではない(滞留の判定・1日1回の上限・本文はそのまま)。
    targets = [SUMMARY_DEPT, "hq"]
    sent = False
    for dept in targets:
        if bot_send(dept, msg, dry_run, by_dept=True):
            sent = True
    if sent:
        state["last_stale_dead_alert"] = now_epoch


def check_dead_windows(state, dry_run):
    """最近まで生きていた部門窓の脈が途絶えたら、incident chへまとめて1通で可視化する(P2)。

    窓が死ぬと部屋宛ての新着はsweep経由でmainへ迂回し研究室の直列になる(応答性悪化の主因)。
    従来これをちゃみが手動で発見していた(hr-context実例 2026-07-18)。ここで自動化する。
    自動開窓はしない(無人でのセッション起動=費用発生のため通知に留める。在宅時の
    開窓は研究室へ「<dept>の窓を起こして」で足りる)。
    """
    import glob as _glob
    now_epoch = time.time()
    alerts = state.setdefault("window_alerts", {})
    dead = []
    for p in _glob.glob(os.path.join(LOCAL, "llm", "claude_active_*.txt")):
        dept = os.path.basename(p)[len("claude_active_"):-len(".txt")]
        if not dept or dept in WINDOW_SKIP_DEPTS:
            continue
        # ★2026-07-27 脈の取り方を差し替えた。旧実装は claude_active_<部屋>.txt の mtime だけを見ており、
        #   **対話セッションが在席している間はこのファイルが更新されない**ため
        #   「働いている窓」を「死んだ窓」と判定していた(研究室HQが46分前と出た実測)。
        #   → 2つの脈(デーモン側 claude_active / セッション側 interactive_presence)の
        #     **新しい方**を採る。正本= scripts/_common/session_presence.py(判定は1本だけ=ORG-11)。
        age = _window_age(dept, now=now_epoch)
        if age is None:
            continue
        if WINDOW_STALE_SEC <= age < WINDOW_RECENT_SEC:
            if now_epoch - alerts.get(dept, 0) >= WINDOW_ALERT_COOLDOWN_SEC:
                dead.append((dept, int(age // 60)))
    if not dead:
        return
    # ★Chamiが読んで動くだけの行なので日本語名だけ(スラッグは足さない=情報を増やさない)
    parts = "・".join(f"{dept_ja(d)}(脈{m}分前)" for d, m in dead)
    msg = (
        f"⚠部門窓の停止を検知(自動監視): {parts}。"
        "この部屋宛ての新着はmain箱へ迂回し、研究室の直列キュー(遅い)になります。"
        "蘇生する場合は該当セッションを再開するか、研究室へ「<部門>の窓を起こして」を。"
    )
    if bot_send(SUMMARY_DEPT, msg, dry_run, by_dept=True):
        for d, _ in dead:
            alerts[d] = now_epoch


def check_busy_notices(state, dry_run):
    """⏳対応中(生存)通知: 「作業ファイルが残っている+脈が生きている」部門を報告部屋へ1通で可視化。

    生存はwaiter/hookの脈(claude_active*.txt)、作業中は退避ファイル(_work/<dept>.jsonl)の存在で
    機械判定する=各部門セッションの改修ゼロ。凍結(脈切れ)はP2 check_dead_windowsの担当なので
    ここでは通知しない(「生きてるのに遅い」と「死んでる」を混ぜない)。
    """
    import glob as _glob
    work_dir = os.path.join(LOCAL, "_work")
    if not os.path.isdir(work_dir):
        return
    now_epoch = time.time()
    sent_keys = state.setdefault("busy_notified", [])
    last_by_dept = state.setdefault("busy_last_sent", {})
    for p in sorted(_glob.glob(os.path.join(work_dir, "*.jsonl"))):
        dept = os.path.basename(p)[:-len(".jsonl")]
        try:
            mtime = os.path.getmtime(p)
            size = os.path.getsize(p)
        except OSError:
            continue
        if size == 0:
            continue
        work_age = now_epoch - mtime
        if work_age < BUSY_NOTIFY_MIN_SEC:
            continue
        # 生存判定: mainは無印脈+hook脈(lab_tool_pulse)の新しい方、部門は claude_active_<dept>.txt
        pulses = ([CLAUDE_ACTIVE, os.path.join(LOCAL, "llm", "lab_tool_pulse.txt")]
                  if dept == "main" else
                  [os.path.join(LOCAL, "llm", f"claude_active_{dept}.txt")])
        ages = []
        for pf in pulses:
            try:
                ages.append(now_epoch - os.path.getmtime(pf))
            except OSError:
                pass
        if not ages or min(ages) >= WINDOW_STALE_SEC:
            continue  # 脈なし/脈切れ=凍結疑いはP2の担当。ここでは「生存」だけ扱う
        key = f"{dept}:{int(mtime)}"
        if key in sent_keys:
            continue  # 同一作業につき1通のみ
        if now_epoch - last_by_dept.get(dept, 0) < BUSY_NOTIFY_COOLDOWN_SEC:
            continue  # 部門毎クールダウン
        try:
            n_items = sum(1 for l in open(p, encoding="utf-8", errors="replace") if l.strip())
        except OSError:
            n_items = 0
        # ★日本語名は既に「〜部門/〜の部屋」まで含む(正本=display_ja)ので「部門」を足さない。
        #   旧実装は f"{dept}部門" で「system-engineer部門」と出ていた(2026-07-27 Chami指摘)。
        label = "研究室" if dept == "main" else dept_ja(dept)
        msg = (
            f"⏳{label}は前の案件を対応中だよ(処理中{n_items}件・着手から{int(work_age // 60)}分・生存確認済み)。"
            "順番に片付けているから、少し時間をもらえると助かる。完了したら本人から報告が行くよ。"
        )
        if dry_run:
            print(f"[dry-run] busy-notice -> {BUSY_NOTIFY_DEPT}: {msg}")
            ok = True
        else:
            r = subprocess.run(
                [sys.executable, PERSONA_SEND, "--dept", BUSY_NOTIFY_DEPT,
                 "--persona", BUSY_NOTIFY_PERSONA, msg],
                capture_output=True, text=True, encoding="utf-8", errors="replace")
            ok = r.returncode == 0
        if ok:
            sent_keys.append(key)
            last_by_dept[dept] = now_epoch
    state["busy_notified"] = sent_keys[-BUSY_KEEP:]


def run_once(dry_run=False):
    if not os.path.isdir(LOCAL):
        print(f"local/ ディレクトリが見つかりません({LOCAL})。監視対象なしのため正常終了します。")
        return
    state = load_state()
    check_poller_health(state, dry_run)  # ポーラー死活は受付箱の滞留と独立に監視(単一障害点)
    check_lab_pulse(state, dry_run)      # ★C-044⑤: 司令塔のliveness脈が黙って死ぬのを検知
    check_dead_windows(state, dry_run)   # P2: 死んだ部門窓の可視化(応答性改善書2026-07-18)
    check_busy_notices(state, dry_run)   # ⏳対応中(生存)通知: Chami直要望2026-07-18・4段目の進捗信号
    check_dead_letters(state, dry_run)   # ★O1(P0-5): DLQ(毒メッセージ)が黙って消えるのを検知
    check_stale_dead(state, dry_run)     # ★2026-08-12: 増分でしか鳴らない穴(13日間の無警報滞留)を塞ぐ
    check_orphan_pending(state, dry_run)  # ★INC-110: 消費者不在のdept宛が無警報で沈む穴を塞ぐ
    check_link_health(state, dry_run)    # ★2026-07-20: 収益導線(自前ドメイン/r2)の死活監視
    check_ci_health(state, dry_run)      # ★2026-07-21: CI失敗をDiscordへ(ORG-09=メールは読まれない)
    check_chime_health(state, dry_run)   # ★2026-07-21: チャイム線が落ちた部屋を可視化(ORG-14)
    check_relay_repair(state, dry_run)   # ★2026-07-26: gatewayの取りこぼしを15分毎に回収(catch-up欠落)
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
    # ★例外: 機微部屋だけは滞留を黙らせない(dream-care設計書 P0-2・Chami承認2026-07-17)。
    #   理由: 悪夢の夜に書き込んで無反応だと「無視された」に見える。全体方針(個別通知OFF)は
    #   維持したまま、この3部屋の滞留に限り「届いている・必ず読まれる」という**事実**だけを返す。
    #   慰めではなく可用性の下限の担保。生涯1回は既存のannounced台帳がそのまま保証する。
    SENSITIVE_DEPTS = ("dream-care", "past-room", "health-log")
    SENSITIVE_TEXT = ("(自動通知)今は応対できるセッションが居ない。"
                      "内容は受付箱に届いていて、次に起きた研究室が必ず読む。")
    stale_sorted = sorted(stale, key=lambda t: -t[1])
    sent_this_cycle = 0
    targets = stale_sorted if ANNOUNCE_PER_MESSAGE else [
        (rec, age) for rec, age in stale_sorted if rec.get("dept") in SENSITIVE_DEPTS
    ]
    for rec, age_min in targets:
        if sent_this_cycle >= MAX_ANNOUNCE_PER_CYCLE:
            break
        if len(sent_ts) >= MAX_ANNOUNCE_PER_HOUR:
            break
        msg_id = rec.get("msg_id")
        channel = rec.get("channel")
        if not msg_id or not channel or msg_id in announced:
            continue  # id/ch不明、または既に生涯1回済み=送らない(超過分は次周期へ)
        # 機微部屋には専用の事実通知(慰めない・急かさない・内容に一切触れない)。他は従来文。
        text = SENSITIVE_TEXT if rec.get("dept") in SENSITIVE_DEPTS else ANNOUNCE_TEXT
        ok = bot_send(channel, text, dry_run)
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
