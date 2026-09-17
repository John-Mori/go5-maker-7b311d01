#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Codex(GPT-5.4)受付係 (Discord専用部屋の一次応答・gemini_responder.pyのCodex版)。

なぜ在るか(Chami設計・配線依頼=ケヴィン 2026-09-05):
  「システム設計・重い実装は Codex の方が強い」ので、Codex専用部屋の発言を掴んで
  scripts/codex/codex_run.py へ渡し、Codexに実装/改修まで走らせる。
  形は べホップ(Gemini)と同じ= 部屋 → 発言 → 実行 → 返信。手本= gemini_responder.py。

★Geminiとの決定的な違い= Codexは「仕事をする側」:
  ホイミン(Gemini)は作業依頼(WORK_WORDS)を司令塔へ回すが、Codexは**重い実装こそが役目**。
  だから作業語で弾かない。部屋の発言はそのまま codex_run.py --ask --to --tag room へ渡す。
  codex_run.py が 専用worktreeを切り(INC-99対策)・所有権を宣言し・Codex bot本人として投稿する。

★休眠の自己ゲート(codex_active・「設定ファイル1行で刺さる」形):
  次の3つが全部そろうまで**完全に眠る**(キューに一切触れない=回帰ゼロ):
    (1) local/discord_channels.json に dept=='codex' の部屋が登録済み(=Chamiが部屋を作った)
    (2) local/codex_enabled.txt が存在(=起動許可フラグ)
    (3) local/discord_codex_token.txt が存在(=口=Codex botのトークン設置済み)
  ★人格名・口調は人事部門(hr-room)の職責= ここでは仮の表示のみ。確定は人事が決める。

★重い実装の着地(worktreeの引き継ぎ):
  codex_run.py は変更があった worktree を**残す**(共有ツリーへは自動反映しない)。
  responder はその worktree パスを検出し、主受付箱(司令塔)へ「レビュー/取り込み待ち」として
  引き継ぐ= 実装が worktree で迷子にならないようにする。

使い方: python scripts/llm/codex_responder.py [--once]
"""
import json
import os
import re
import subprocess
import sys
import threading
import time

try:
    # line_buffering=True 必須(INC-93): 無口な常駐のログが8KBバッファで到達しない事故を防ぐ。
    sys.stdout.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)
except Exception:
    pass

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.normpath(os.path.join(HERE, "..", ".."))
sys.path.insert(0, HERE)
from tokenless_router import scripted_reply  # noqa: E402

LOCAL = os.environ.get("GO5_LOCAL_DIR") or os.path.join(ROOT, "local")
INBOX = os.path.join(LOCAL, "discord_inbox_codex.jsonl")           # 旧jsonl経路(残置・実質未使用)
PROCESSED = os.path.join(LOCAL, "discord_inbox_codex_processed.jsonl")
FOR_CLAUDE = os.path.join(LOCAL, "discord_inbox.jsonl")            # =司令塔の主受付箱(gemini_responderと同じ)
CHANNELS_FILE = os.path.join(LOCAL, "discord_channels.json")
TOKEN_FILE = os.path.join(LOCAL, "discord_codex_token.txt")
ENABLE_FLAG = os.path.join(LOCAL, "codex_enabled.txt")
LOG = os.path.join(LOCAL, "llm", "codex_responder_log.jsonl")
CODEX_CLI = os.path.join(ROOT, "scripts", "codex", "codex_run.py")
REACT = os.path.join(ROOT, "scripts", "discord", "react.py")       # 進捗印(既読/着手/即答)

# 表示名は人事が確定=「ネイキッド・スネーク」(2026-09-05・デブライネ経由)。実応答は codex_run.py が
# Codex bot本人として投稿するので、この名前はエスカレ通知の文面にしか使わない(変数名は互換のため据置)。
PERSONA_TENTATIVE = "ネイキッド・スネーク"

# 機微=司令塔直轄(防御的ガード。codex部屋は該当しない想定だが念のため)
SENSITIVE_DEPTS = ("dream-care", "past-room", "hr-room", "health-log")

# ★2026-09-16 止血(研究室HQ・Chami直接指示)= **Chami本人の@ボス名指しは上のガードで弾かない。**
#   壊れていた実物= 👤人事部門-補強•キャラ設定(hr-room)で 11:47:35 と 11:48:38 に
#   sensitive_deferred が2連続(codex_responder_log.jsonl)。2通目はChami本人の
#   「＠ボス 引き継がず、ここで考えてくれ」(msg 1549612874945663090)で、
#   **回すなという指示そのものを回し返していた**。
#   なぜ弾いてよいか= ここへ来る便は discord_gateway.route_codex_summon を通った
#   **@ボス名指しだけ**(is_codex_mentioned)。共通規律§3.8「Chamiが相手を名指しした時は
#   階梯を経由せず直送してよい」/§3.7「Chamiの直接指示はどの裁定より上」。
#   他人(AI)が機微部屋でボスを名指した時は従来どおり司令塔へ回す=防御の意図は残す。
#   ★値の正本は `scripts/_common/chami_identity.py` **1本だけ**
#     (2026-09-16 イージス研究室が一本化。それ以前は3箇所に写しが散っていた)。
#     ★ここに写しを作り直すな。ユーザ名かIDが変わった日、直し忘れた写しが**黙って**誤判定する。
#     ★try/except で包むな= 読めない時は起動時に落ちる方がよい(無音の無効化を作らない)。
sys.path.insert(0, os.path.join(ROOT, "scripts", "_common"))
from chami_identity import from_chami  # noqa: E402

# Codexは遅い(実測45〜60秒/件)。1巡回の上限を小さくして暴走と長時間ブロックを防ぐ。
QUEUE_CLAIM_CAP = 2
QUEUE_DB = os.path.join(LOCAL, "queue", "inbox.db")
# codex_run.py の worktree保持ログ行を拾う正規表現(重い実装の着地点を引き継ぐため)。
WT_RE = re.compile(r"★worktreeに変更あり=\s*(.+?)(?:\(枝|$)")
# codex_run.py が print する失敗文『(生成失敗: … [not supported] rc=…)』から理由バケツを拾う。
REASON_RE = re.compile(r"生成失敗[:：].*?\[([^\]]+)\]")
# 橋(Codex回線)が落ちている系の理由= Chamiの依頼が悪いのではなく橋の不通。codex_run.py L294の版数切れバケツと同義。
BRIDGE_DOWN_REASONS = ("not supported", "invalid_request", "unauthorized",
                       "401", "429", "Error loading config")


def _env_int(name, default, minimum=1, maximum=86400):
    try:
        value = int(os.environ.get(name, default))
    except (TypeError, ValueError):
        value = int(default)
    return max(minimum, min(maximum, value))


# 重い実装は実測600秒を越えた。内側の生成上限と外側の待機上限を分け、終了処理の余白を持つ。
CODEX_EXEC_TIMEOUT = _env_int("CODEX_EXEC_TIMEOUT_SEC", 1800, minimum=60, maximum=7200)
RUN_TIMEOUT = CODEX_EXEC_TIMEOUT + 180
LEASE_EXTEND_INTERVAL = _env_int("CODEX_LEASE_HEARTBEAT_SEC", 240, minimum=10, maximum=600)
LEASE_EXTEND_SEC = max(900, min(7200, CODEX_EXEC_TIMEOUT + 300))
SEND_RETRY_SEC = _env_int("CODEX_SEND_RETRY_SEC", 60, minimum=10, maximum=3600)
MAX_SEND_ATTEMPTS = _env_int("CODEX_SEND_MAX_ATTEMPTS", 3, minimum=1, maximum=10)


def log(rec):
    os.makedirs(os.path.dirname(LOG), exist_ok=True)
    with open(LOG, "a", encoding="utf-8") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")


def append_line(path, line):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "a", encoding="utf-8") as f:
        f.write(line.rstrip("\n") + "\n")


def origin_dept_for(rec):
    """@ボス召喚元の部門を返す。

    queueのdeptはCodex受付用に 'codex' へ付け替えるため、元部門は
    codex_origin_dept に退避して読む。古い行はchannel台帳から復元する。
    """
    if not isinstance(rec, dict):
        return ""
    for key in ("codex_origin_dept", "origin_dept"):
        v = str(rec.get(key) or "").strip()
        if v and v != "codex":
            return v
    v = str(rec.get("dept") or "").strip()
    if v and v != "codex":
        return v
    ch = str(rec.get("channel") or "").strip()
    if not ch:
        return ""
    try:
        chans = json.load(open(CHANNELS_FILE, encoding="utf-8"))
        for c in chans:
            if ch in (str(c.get("id", "")), str(c.get("name", ""))):
                d = str(c.get("dept") or "").strip()
                if d and d != "codex":
                    return d
    except Exception:
        pass
    return ""


# ---------------------------------------------------------------------------
# 休眠の自己ゲート
# ---------------------------------------------------------------------------
def codex_room_registered():
    """dept=='codex' の専用部屋が在るか。※現運用の起床判定には使わない(下記 codex_active 参照)。
    残置理由= 将来Codex専用部屋を新設した時の分岐に流用できるため(Chamiの手で部屋を作る時)。"""
    try:
        chans = json.load(open(CHANNELS_FILE, encoding="utf-8"))
        return any(c.get("dept") == "codex" for c in chans)
    except Exception:
        return False


def codex_active():
    """起床判定= Chamiが手で置く2ファイル(活性フラグ+トークン)が両方在ること。
    専用部屋(dept=='codex')は要求しない= Chami①の設計「既存の~15部屋へ @ボス で召喚」を採るため。
    召喚は gateway(discord_gateway.py)が @ボス 発言の dept を codex に付け替えて実現する。
    専用部屋の新設はChamiの手なので、それを起床の必須条件にすると設計と矛盾する(2026-09-05 platform-se)。"""
    return (os.path.exists(ENABLE_FLAG)
            and os.path.exists(TOKEN_FILE))


# ---------------------------------------------------------------------------
# 口(部屋への通知)= Codex bot本人として。codex_run の送信部を再利用(二重管理しない)。
# ---------------------------------------------------------------------------
def reply_target(rec):
    """返信先は不変のchannel_idを優先し、旧レコードだけ表示名へフォールバックする。"""
    channel_id = str(rec.get("channel_id") or "").strip()
    if channel_id.isdigit():
        return channel_id
    return str(rec.get("channel") or "").strip()


def channel_label(rec):
    return str(rec.get("channel") or rec.get("channel_id") or "").strip()


def notify_room(channel, text):
    """エスカレ受領などの短い通知を Codex bot本人として投稿する(codex_run.dc_sendを借りる)。
    失敗しても握りつぶす(通知は本筋を止めない)。"""
    try:
        sys.path.insert(0, os.path.join(ROOT, "scripts", "codex"))
        import codex_run
        token = open(TOKEN_FILE, encoding="utf-8").read().strip()
        channel_id = str(channel) if str(channel).isdigit() else codex_run.resolve_channel(channel)
        return bool(codex_run.dc_send(token, channel_id, text))
    except (Exception, SystemExit) as e:
        print(f"  通知失敗(続行): {type(e).__name__}")
        return False


def mark(channel, msg_id, kind):
    """進捗印(既読/着手/即答)を Claude同様に押す(2026-09-05 Chami依頼:
    「Claud同様に既読と着手のスタンプに意味を把握して適応できるように」)。

    なぜ responder で押すか= Codexは対話セッションではなく **サブプロセス経路**なので、
    Claude側の progress_mark.py(UserPromptSubmit=既読 / PostToolUse=着手 / Stop=即答 の hook)が
    そもそも鳴らない。そこで handle() の節目に手で押して同じ4状態信号を Chami の画面へ出す。
      既読 … 掴んで読んだ直後(返答/実装はこれから)
      着手 … codex_run.py で重い実装を始める直前(本格的な作業の開始)
      即答 … 司令塔へ回すなど その場の返信で完結した時(「読んだだけ」との曖昧さ解消)
    処理中の当の1通(msg_id/channel は rec が持つ)を狙って押すので react_mark の dept走査は要らない。
    べき等(react.py の PUT /@me は同じ印の二度押しが no-op)・fail-open(印は本筋を絶対に止めない)。

    ★2026-09-06(イージス研究室)= 押し方を scripts/lib/mark_press.py へ一本化した。
      ここと codex_run.mark_sent に同じ subprocess 呼び出しの**写しが2本**あり、
      どちらも returncode を捨てていた(ORG-11+無言)。押し方も記録も正本は1本。"""
    if not (channel and msg_id):
        return
    try:
        # ★--codex= 受け手がCodex(@ネイキッド・スネーク)。react.py が §A.1 に従い
        #   送信/既読/着手だけを uptsukiyomi/‼️/🐍 へ差し替える(他印は共通)。
        #   ここは Codex専用の responder なので常に --codex を渡す(Chami指示 2026-09-05)。
        sys.path.insert(0, os.path.join(ROOT, "scripts", "lib"))
        from mark_press import press
        press(channel, msg_id, kind, codex=True, caller="codex_responder.mark")
    except Exception:
        pass


def _extend_lease_once(qid, queue_db=QUEUE_DB, lease_sec=LEASE_EXTEND_SEC):
    """別SQLite接続でリースを延長する。ワーカー本体の接続を別threadへ渡さない。"""
    if not qid:
        return False
    try:
        sys.path.insert(0, os.path.join(ROOT, "scripts", "queue"))
        from leasequeue import LeaseQueue
        queue = LeaseQueue(queue_db)
        try:
            return bool(queue.extend(qid, lease_sec=lease_sec))
        finally:
            queue.close()
    except Exception as e:
        print(f"  lease延長失敗(続行): {type(e).__name__}")
        return False


def _start_lease_extender(qid, stop_event, queue_db=QUEUE_DB):
    """長いCodex処理中だけリースを定期延長する。"""
    if not qid:
        return None
    _extend_lease_once(qid, queue_db=queue_db)

    def loop():
        while not stop_event.wait(LEASE_EXTEND_INTERVAL):
            _extend_lease_once(qid, queue_db=queue_db)

    thread = threading.Thread(target=loop, name=f"codex-lease-{qid}", daemon=True)
    thread.start()
    return thread


def heavy_request(rec):
    """実装・設計系か、ある程度長い依頼なら開始通知を文字でも返す。"""
    content = str(rec.get("content") or "").strip()
    if len(content) >= 40:
        return True
    return any(word in content for word in
               ("設計", "修正", "実装", "作って", "直して", "調査", "回収", "テスト"))


# ---------------------------------------------------------------------------
# Codexの利用枠切れ(usage_limit)を覚えておく= HQ-0254(2026-09-10 aegis-gl)
# ---------------------------------------------------------------------------
# なぜ在るか: 枠が尽きている間も来た依頼を全部 codex_run.py へ渡すと、依頼のたびに
#   (1) 専用worktreeを切って捨てる (2) 同じ理由の便を司令塔の受付箱へ積み増す
#   が延々続く。実物= local/llm/codex_fail_raw.jsonl の 2026-09-10T02:40:33 / 02:41:40。
#   Codexの原文が返した回復予定は 2026-09-16 05:23= 放っておくと1週間これが続く。
# ★fail-open= 状態ファイルが読めない/壊れている/古い時は「保持しない」側へ倒す。
#   最悪の事故は「枠は戻っているのに、この砂袋のせいでCodexが一切動かない」ことだ。
# ★保持中でも一定間隔で1回だけ本物を試す= 枠が早く戻った時に自力で復帰する
#   (Chamiが枠を買った直後に、こちらの都合で止まったままにしない)。
# ★枠の追加購入そのものはChamiの領域(HQ-0254 ③)。ここは待つ・伝える・一度だけ上げる。
USAGE_LIMIT_STATE = os.path.join(LOCAL, "llm", "codex_usage_limit.json")
FAIL_RAW = os.path.join(LOCAL, "llm", "codex_fail_raw.jsonl")   # codex_run.py の書く生ログ(読むだけ)
USAGE_LIMIT_PROBE_SEC = _env_int("CODEX_USAGE_LIMIT_PROBE_SEC", 1800, minimum=60, maximum=86400)
# `… or try again at Sep 16th, 2026 5:23 AM.` から回復予定を拾う(取れなくても保持は成立する)。
USAGE_LIMIT_RESET_RE = re.compile(
    r"try again at\s+([A-Za-z]{3,9})\.?\s+(\d{1,2})(?:st|nd|rd|th)?,\s*(\d{4})\s+"
    r"(\d{1,2}):(\d{2})\s*([AP]M)", re.I)
_MONTHS = {m: i + 1 for i, m in enumerate(
    ("jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"))}


def _parse_reset_at(text):
    """Codexの原文から回復予定時刻を拾って epoch 秒で返す。読めなければ 0。

    ★タイムゾーンは原文に書かれていない= ローカル時刻として読む。数時間ずれても
      「保持を続けるか」の判定には使わない(そちらは下の再試行間隔が持つ)ので害はない。
      使うのは (a) 部屋へ書く予定時刻の表示 (b) 予定を過ぎたら保持を捨てる の2つだけ。
    """
    m = USAGE_LIMIT_RESET_RE.search(str(text or ""))
    if not m:
        return 0
    mon = _MONTHS.get(m.group(1)[:3].lower())
    if not mon:
        return 0
    hour = int(m.group(4)) % 12
    if m.group(6).upper() == "PM":
        hour += 12
    try:
        return time.mktime((int(m.group(3)), mon, int(m.group(2)), hour, int(m.group(5)),
                            0, 0, 1, -1))
    except (ValueError, OverflowError):
        return 0


def _latest_usage_limit_raw():
    """codex_run.py が残した直近の枠切れ原文を拾う(表示と回復予定のため。読めなければ空)。"""
    try:
        with open(FAIL_RAW, encoding="utf-8", errors="replace") as f:
            lines = f.readlines()[-50:]
    except OSError:
        return ""
    for line in reversed(lines):
        try:
            rec = json.loads(line)
        except Exception:
            continue
        if rec.get("reason") == "usage_limit":
            return str(rec.get("session_error") or rec.get("stderr_tail") or "")
    return ""


def _read_usage_limit_state():
    """保持状態を読む。無い/壊れている=保持なし(fail-open)。"""
    try:
        with open(USAGE_LIMIT_STATE, encoding="utf-8") as f:
            state = json.load(f)
        return state if isinstance(state, dict) else None
    except (OSError, ValueError):
        return None


def _write_usage_limit_state(state):
    try:
        os.makedirs(os.path.dirname(USAGE_LIMIT_STATE), exist_ok=True)
        with open(USAGE_LIMIT_STATE, "w", encoding="utf-8") as f:
            json.dump(state, f, ensure_ascii=False)
        return True
    except OSError:
        return False


def note_usage_limit():
    """枠切れを踏んだ= 保持を立てる(既にあれば回数だけ増やす)。戻り値=状態。

    ★『司令塔へ上げたか』(escalated)は初回だけ True にする= 受付箱へ同じ上申を積み増さない。
    """
    now = time.time()
    raw = _latest_usage_limit_raw()
    state = _read_usage_limit_state() or {}
    if not state.get("since"):
        state["since"] = time.strftime("%Y-%m-%dT%H:%M:%S")
        state["escalated"] = False
        state["last_probe"] = now
    state["hits"] = int(state.get("hits") or 0) + 1
    state["source_ts"] = time.strftime("%Y-%m-%dT%H:%M:%S")
    if raw:
        state["raw"] = raw[:400]
        reset_at = _parse_reset_at(raw)
        if reset_at:
            state["until_epoch"] = reset_at
            state["until"] = time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(reset_at))
    _write_usage_limit_state(state)
    return state


def clear_usage_limit(why=""):
    """枠が戻った(またはChamiが手で外した)= 保持を捨てる。"""
    if not os.path.exists(USAGE_LIMIT_STATE):
        return False
    try:
        os.remove(USAGE_LIMIT_STATE)
    except OSError:
        return False
    log({"ts": time.strftime("%Y-%m-%dT%H:%M:%S"), "mode": "usage_limit_cleared", "why": why})
    print(f"  Codex利用枠の保持を解除 ({why})")
    return True


def usage_limit_hold():
    """今この便でCodexを起動してよいか。戻り値 (hold, state)。

    hold=True なら codex_run.py を起動しない= worktreeも作らない。
    ★保持していても USAGE_LIMIT_PROBE_SEC ごとに1回は本物を試す(=Falseを返す)。
      その1回が通れば handle() 側が clear_usage_limit() で保持を捨てる。
    """
    state = _read_usage_limit_state()
    if not state:
        return False, None
    now = time.time()
    until = state.get("until_epoch") or 0
    if until and now >= float(until):
        # 回復予定を過ぎた= 保持の根拠が切れた。素直に試す。
        clear_usage_limit("回復予定時刻を過ぎた")
        return False, None
    last_probe = float(state.get("last_probe") or 0)
    if now - last_probe >= USAGE_LIMIT_PROBE_SEC:
        state["last_probe"] = now
        _write_usage_limit_state(state)
        return False, state
    return True, state


def usage_limit_text(state):
    """部屋へ返す文面。★『依頼の中身が悪いのではない』を必ず先に言う。"""
    until = (state or {}).get("until")
    when = f"Codexが返した回復予定は {until} です。" if until else \
        "回復予定はCodexの原文にしか無く、今回は読み取れませんでした。"
    return ("Codex(Astra)側の**利用枠が上限**に達したままなので、実行していません。"
            "依頼の中身の問題でも、私が読めていないのでもありません。"
            f"{when}"
            "枠が戻るまでは同じ依頼を投げても同じところで止まるので、"
            "無駄な作業場所を作らずに止めました。依頼は司令塔の受付箱へ渡してあります。"
            "枠の追加購入か回復待ちかの判断はChamiの領域なので、こちらでは決めません。")


def escalate(channel, raw_line, note=""):
    """作業をこなせなかった/失敗した発言を司令塔の主受付箱へ回す。"""
    append_line(FOR_CLAUDE, raw_line)
    append_line(PROCESSED, raw_line)
    if note:
        # 引き継ぎメモ(worktreeパス等)を1行、主受付箱へ別途残す。
        append_line(FOR_CLAUDE, json.dumps(
            {"content": note, "channel": channel, "dept": "codex",
             "from": "codex_responder", "ts": time.strftime("%Y-%m-%dT%H:%M:%S")},
            ensure_ascii=False))


# ---------------------------------------------------------------------------
# 中核= Codexに投げる
# ---------------------------------------------------------------------------
def codex_answer(channel, content, msg_id="", origin_dept=""):
    """codex_run.py へ委譲= 専用worktreeで生成/実装し、Codex bot本人として部屋へ投稿。

    戻り値 (ok, worktree_or_empty, reason)。
    - ok=False は生成失敗(投稿は codex_run 側で中止済み)= 呼び側が司令塔へ回す。
    - worktree_or_empty= 変更が残った worktree のパス(あれば)。無ければ空文字。
    - reason= 失敗理由バケツ(codex_run の失敗文から抽出。"not supported" 等 / timeout / 空=不明)。
      これで呼び側が「橋の不通」と「依頼の中身の問題」を見分けて文面を変える(ケヴィン発注(b))。
    msg_id= 元便のmsg_id。--reply-to として渡し、codex_run側でdc_send実成功時だけ
      送信(uptsukiyomi)を押させる(2026-09-05配線②=従来ここが空撃ちだった)。
    """
    argv = [sys.executable, CODEX_CLI, "--ask", content, "--to", channel,
            "--tag", "room", "--timeout", str(CODEX_EXEC_TIMEOUT)]
    if origin_dept:
        argv += ["--origin-dept", str(origin_dept)]
    if msg_id:
        argv += ["--reply-to", str(msg_id), "--request-id", str(msg_id)]
    try:
        r = subprocess.run(
            argv,
            capture_output=True, text=True, encoding="utf-8", errors="replace",
            timeout=RUN_TIMEOUT)
    except subprocess.TimeoutExpired:
        return False, "", "timeout"
    out = (r.stdout or "") + "\n" + (r.stderr or "")
    m = WT_RE.search(out)
    worktree = m.group(1).strip() if m else ""
    rm = REASON_RE.search(out)
    reason = rm.group(1).strip() if rm else ""
    if r.returncode == 8 or "SEND_FAILED saved_result=" in out:
        reason = "send_failed"
    elif r.returncode == 9:
        reason = "outbox_failed"
    elif r.returncode == 5 and "応答しなかった" in out:
        reason = "timeout"
    return r.returncode == 0, worktree, reason


def handle(rec, raw_line, lease_id=None, deliveries=1):
    content = str(rec.get("content") or "")
    channel = reply_target(rec)
    label = channel_label(rec)
    msg_id = str(rec.get("msg_id") or "")
    try:
        delivery_count = max(1, int(deliveries or 1))
    except (TypeError, ValueError):
        delivery_count = 1

    origin_dept = origin_dept_for(rec)
    mark(channel, msg_id, "既読")           # 掴んで読んだ=まず既読
    if origin_dept in SENSITIVE_DEPTS and not from_chami(rec):
        mark(channel, msg_id, "即答")
        escalate(channel, raw_line)
        # ★2026-09-16 撤去(Chami直接指示・イージス研究室)= ここに在った
        #   「受け取りました。ここは司令塔が直接読む部屋なので、そちらへ回しました。」を出さない。
        #   Chami原文=「これやめろって」(msg 1549628255173353625 / 12:49:26 JST / hr-room)。
        #   ★中身の無い一次ackは**沈黙より悪い**(共通規律§2)。Codex自身の心得
        #     `scripts/codex/codex_briefing.py:193`=「『司令塔へ回しました』だけの返事を出すな」を、
        #     responder 側が破っていた= 機械が自分の掟を破る形になっていた。
        #   ★恒久 DEF-otacon-radio-df36094b69(炎上/C-038・C-040)の第2の口。
        #     第1の口(重い依頼の「受け取った。処理を開始する。」)は撤去済= test_codex_no_ack.py。
        #   ★沈黙にはしていない= 上の escalate() が生の便を司令塔の主受付箱
        #     (local/discord_inbox.jsonl)へ入れ、既読/即答の印は部屋へ残る。
        #     回送の防御(他人のAI便は Codex を起こさない)は HQ の意図どおり触っていない。
        log({"ts": time.strftime("%Y-%m-%dT%H:%M:%S"), "mode": "sensitive_deferred",
             "channel": label, "channel_id": channel})
        return "sensitive_deferred"
    if not content.strip():
        mark(channel, msg_id, "即答")
        escalate(channel, raw_line)
        notify_room(channel, "テキスト以外(添付/音声)は扱えないので、司令塔の受付箱へ入れました。")
        log({"ts": time.strftime("%Y-%m-%dT%H:%M:%S"), "mode": "escalated_no_text",
             "channel": label, "channel_id": channel})
        return "escalated_no_text"

    # 「元気?」「了解」「使い方」など、意味を考えなくてよい短い全文一致だけは
    # Pythonの固定文で返す。少しでも依頼本文が足されていれば scripted_reply() は
    # None を返し、従来どおり下のCodex実行へ流れる。
    scripted = scripted_reply(content, "codex")
    if scripted:
        mark(channel, msg_id, "即答")
        sent = notify_room(channel, scripted["text"])
        if sent:
            append_line(PROCESSED, raw_line)
            mode = "tokenless_answered"
        elif delivery_count < MAX_SEND_ATTEMPTS:
            mode = "retry_tokenless"
        else:
            # AIへフォールバックすると、Discord送信障害のたびに無意味な生成費用が出る。
            # 固定文の送信失敗は固定文のまま上限回数だけ再試行し、最後はログへ残す。
            append_line(PROCESSED, raw_line)
            mode = "tokenless_send_failed"
        log({"ts": time.strftime("%Y-%m-%dT%H:%M:%S"), "mode": mode,
             "intent": scripted["intent"], "channel": label, "channel_id": channel,
             "deliveries": delivery_count})
        return mode

    # ★HQ-0254= Codexの利用枠が尽きている間は codex_run.py を**起動しない**。
    #   起動しない=専用worktreeも切られない。依頼そのものは消さず、1便につき1行だけ
    #   司令塔の受付箱へ渡す(同じ上申の積み増しは escalated フラグで1回に抑える)。
    hold, ul_state = usage_limit_hold()
    if hold:
        mark(channel, msg_id, "即答")
        note = ""
        if not (ul_state or {}).get("escalated"):
            note = ("[codex] Codexの利用枠切れで保持中(枠を買うか待つかの判断はChami・HQ-0254)。"
                    f"回復予定={(ul_state or {}).get('until') or '不明'}"
                    f" / 初回検出={(ul_state or {}).get('since') or '不明'}")
            ul_state["escalated"] = True
            _write_usage_limit_state(ul_state)
        escalate(channel, raw_line, note=note)
        notify_room(channel, usage_limit_text(ul_state))
        log({"ts": time.strftime("%Y-%m-%dT%H:%M:%S"), "mode": "held_usage_limit",
             "channel": label, "channel_id": channel, "q": content[:200],
             "until": (ul_state or {}).get("until", ""),
             "hits": (ul_state or {}).get("hits", 0)})
        print(f"  Codex枠切れ保持→起動せず [{label}] {content[:30]!r}")
        return "held_usage_limit"

    # Codexは仕事をする側。開始通知を先に返し、ブロッキング実行中は別接続でリースを延ばす。
    mark(channel, msg_id, "着手")
    stop_lease = threading.Event()
    lease_thread = _start_lease_extender(lease_id, stop_lease)
    try:
        # ★中身の無い一次ackテキストは出さない(炎上/恒久 DEF-otacon-radio-df36094b69・C-040)。
        #   Chami原文「このやり取りいらない」→「効いてません」。直上 :540 の mark(…,"着手") で
        #   進捗印👀が既に付く=「今やってる」はChamiに伝わるので、定型テキストは重複だった。
        #   再発防止の検査= scripts/llm/test_codex_no_ack.py(must-fail・C-053)。
        ok, worktree, reason = codex_answer(channel, content, msg_id, origin_dept)
    finally:
        stop_lease.set()
        if lease_thread:
            lease_thread.join(timeout=2)

    if ok:
        # 枠切れの保持中でも一定間隔で1回だけ本物を試している(usage_limit_hold)。
        # その1回が通った=枠は戻っている。ここで保持を捨てないと自力で復帰できない。
        clear_usage_limit("Codexが応答を返した")
        append_line(PROCESSED, raw_line)
        if worktree:
            note = (f"[codex] 部屋 {label} の依頼で実装をworktreeに保存(要レビュー/取り込み)。"
                    f" worktree={worktree} / 依頼={content[:120]}")
            append_line(FOR_CLAUDE, json.dumps(
                {"content": note, "channel": label, "channel_id": channel, "dept": "codex",
                 "from": "codex_responder", "worktree": worktree,
                 "ts": time.strftime("%Y-%m-%dT%H:%M:%S")}, ensure_ascii=False))
            print(f"  Codex実装→worktree保持 [{label}] {worktree}")
        else:
            print(f"  Codex回答 [{label}] {content[:30]!r}")
        log({"ts": time.strftime("%Y-%m-%dT%H:%M:%S"), "mode": "answered",
             "channel": label, "channel_id": channel, "q": content[:200], "worktree": worktree})
        return "answered"

    if reason == "send_failed":
        # 生成済み全文はcodex_outboxにある。同じ便を再生成せず、キュー再配達で送信だけ再試行する。
        if delivery_count < MAX_SEND_ATTEMPTS:
            if delivery_count == 1:
                note = (f"[codex] 生成済み・Discord送信だけ失敗。request_id={msg_id} は"
                        "local/llm/codex_outboxに保存済みで、再配達時は再生成しない。")
                append_line(FOR_CLAUDE, json.dumps(
                    {"content": note, "channel": label, "channel_id": channel, "dept": "codex",
                     "from": "codex_responder", "ts": time.strftime("%Y-%m-%dT%H:%M:%S")},
                    ensure_ascii=False))
            log({"ts": time.strftime("%Y-%m-%dT%H:%M:%S"), "mode": "send_retry_saved",
                 "channel": label, "channel_id": channel, "deliveries": delivery_count,
                 "request_id": msg_id})
            return "retry_saved"
        escalate(channel, raw_line,
                 note=(f"[codex] 生成結果は保存済みだがDiscord送信が{delivery_count}回失敗。"
                       f"request_id={msg_id} は --resend-outbox {msg_id} で再送可能。"))
        log({"ts": time.strftime("%Y-%m-%dT%H:%M:%S"), "mode": "send_failed_saved",
             "channel": label, "channel_id": channel, "request_id": msg_id})
        return "send_failed_saved"

    worktree_note = f" / worktree={worktree}" if worktree else ""
    bridge_down = any(key in reason for key in BRIDGE_DOWN_REASONS)
    if reason == "timeout":
        mode = "escalated_timeout"
        note_kind = "処理時間上限"
        notify_text = (f"処理が{CODEX_EXEC_TIMEOUT // 60}分の上限に達しました。依頼は消していません。"
                       + ("作業途中のworktreeを残し、司令塔へ回しました。" if worktree else
                          "司令塔へ回しました。"))
    elif reason == "usage_policy":
        # ★2026-09-06 研究室HQ 仮当て= 実物(14:11の便)は橋が生きたまま、最終メッセージだけが
        #   OpenAI側の方針フィルタに弾かれていた。ここを「橋不通」に混ぜるとChamiへ誤報になる。
        mode = "escalated_usage_policy"
        note_kind = "方針フィルタで最終応答が止まった"
        notify_text = ("橋は繋がっていますが、返す最終メッセージがOpenAI側の方針フィルタで止められました。"
                       "作業自体は進んでいることがあります。作業場所を残して司令塔へ回しました。")
    elif reason == "usage_limit":
        # ★2026-09-10 研究室HQ 止血= Codexアカウントの利用枠切れ(codex_run.classify_failure と対)。
        #   橋は生きている・依頼の中身も悪くない。枠が尽きているだけなので、
        #   「うまく処理できなかった」の一般文に混ぜず、**何が起きたかと次の一手**まで書く。
        mode = "escalated_usage_limit"
        note_kind = "Codexの利用枠切れ"
        # ★HQ-0254(aegis-gl 2026-09-10)= ここで保持を立てる。次の便からは上の事前ゲートが
        #   codex_run.py の起動そのものを止める(worktreeを切らない)。
        ul_state = note_usage_limit()
        notify_text = ("Codex(Astra)側の**利用枠が上限**に達していて、実行できませんでした。"
                       "依頼の中身の問題でも、私が読めていないのでもありません。"
                       + (f"Codexが返した回復予定は {ul_state.get('until')} です。"
                          if ul_state.get("until") else
                          "回復予定はCodexの返した原文に入っています。")
                       + "枠が戻るまでは同じ依頼を投げても同じところで止まるので、"
                       "以後の依頼は実行せずに司令塔の受付箱へ渡します。"
                       "枠の追加購入か回復待ちかの判断はChamiの領域なので、こちらでは決めません。")
    elif bridge_down:
        mode = "escalated_bridge_down"
        note_kind = "橋(Codex回線)不通"
        notify_text = ("今『橋』(Codexへの回線)が落ちていて、応答を取り出せませんでした。"
                       "依頼の中身の問題ではありません。司令塔へ復旧を上げました。")
    elif reason == "outbox_failed":
        mode = "escalated_outbox_failed"
        note_kind = "生成結果の保存失敗"
        notify_text = "生成は完了しましたが、結果を安全に保存できなかったため投稿を止め、司令塔へ回しました。"
    else:
        mode = "escalated_failed"
        note_kind = "生成失敗"
        notify_text = "うまく処理できなかったので、依頼と作業場所を司令塔の受付箱へ回しました。"
    escalate(channel, raw_line,
             note=f"[codex] {note_kind} [{reason or '不明'}]{worktree_note}: {content[:120]}")
    notify_room(channel, notify_text)
    log({"ts": time.strftime("%Y-%m-%dT%H:%M:%S"), "mode": mode,
         "channel": label, "channel_id": channel, "reason": reason,
         "q": content[:200], "worktree": worktree})
    print(f"  Codex失敗→Claude行き [{label}] reason={reason!r} {content[:30]!r}")
    return mode


# ---------------------------------------------------------------------------
# 旧jsonl経路(残置・実質未使用)
# ---------------------------------------------------------------------------
def take_inbox():
    if not (os.path.exists(INBOX) and os.path.getsize(INBOX) > 0):
        return []
    archive = INBOX + ".pick"
    try:
        os.rename(INBOX, archive)
    except FileNotFoundError:
        return []
    with open(archive, "r", encoding="utf-8") as f:
        lines = [l for l in f.read().splitlines() if l.strip()]
    os.remove(archive)
    return lines


# ---------------------------------------------------------------------------
# 主経路= LeaseQueue から dept='codex' のみ
# ---------------------------------------------------------------------------
def drain_queue():
    """LeaseQueue から dept='codex' を claim→処理→ack(gemini_responder.drain_queueと同型)。"""
    if not os.path.exists(QUEUE_DB):
        return 0
    try:
        sys.path.insert(0, os.path.join(ROOT, "scripts", "queue"))
        from leasequeue import LeaseQueue
        q = LeaseQueue(QUEUE_DB)
    except Exception as e:
        print(f"  queue接続失敗(続行): {type(e).__name__}")
        return 0
    done = 0
    try:
        processed = set()
        try:
            for pl in open(PROCESSED, encoding="utf-8", errors="replace"):
                try:
                    m = json.loads(pl).get("msg_id")
                    if m:
                        processed.add(str(m))
                except Exception:
                    continue
        except OSError:
            pass
        while done < QUEUE_CLAIM_CAP:
            c = q.claim(dept="codex", who="codex_responder")
            if c is None:
                break
            rec = c["body"] if isinstance(c["body"], dict) else {}
            mid = str(rec.get("msg_id", c.get("msg_id") or ""))
            if mid and mid in processed:
                q.ack(c["id"], result="skip(処理済)")
                done += 1
                continue
            raw_line = json.dumps(rec, ensure_ascii=False)
            try:
                result = handle(rec, raw_line, lease_id=c["id"], deliveries=c.get("deliveries", 1))
                if result in ("retry_saved", "retry_tokenless"):
                    q.nack(c["id"], retry_after=time.time() + SEND_RETRY_SEC)
                else:
                    q.ack(c["id"], result=result or "処理済")
            except (Exception, SystemExit) as e:
                print(f"  queue処理失敗: {type(e).__name__}")
                append_line(FOR_CLAUDE, raw_line)  # =main箱。喪失させない
                q.ack(c["id"], result=f"failed:{type(e).__name__}")
            done += 1
    finally:
        q.close()
    return done


def main():
    once = "--once" in sys.argv
    print("Codex受付 起動 (dept='codex' 専用・3条件がそろうまで休眠)")
    was_active = None
    while True:
        active = codex_active()
        if active != was_active:
            # 状態が変わった時だけログ(毎30秒のスパムを避ける)。
            print("Codex受付= " + ("稼働(部屋+フラグ+トークン そろった)" if active else
                  "休眠(discord_channels.json の dept='codex' / codex_enabled.txt / "
                  "discord_codex_token.txt のいずれか未設置)"))
            was_active = active
        if not active:
            if once:
                break
            time.sleep(30)
            continue
        for line in take_inbox():
            try:
                handle(json.loads(line), line)
            except (Exception, SystemExit) as e:
                print(f"  処理失敗: {type(e).__name__}")
                append_line(FOR_CLAUDE, line)
        try:
            n = drain_queue()
            if n:
                print(f"  queue経路 {n}件処理")
        except Exception as e:
            print(f"  queueドレイン失敗(続行): {type(e).__name__}")
        if once:
            print("1回分の処理完了")
            break
        time.sleep(30)


if __name__ == "__main__":
    main()
