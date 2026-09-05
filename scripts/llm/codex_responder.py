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
import time

try:
    # line_buffering=True 必須(INC-93): 無口な常駐のログが8KBバッファで到達しない事故を防ぐ。
    sys.stdout.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)
except Exception:
    pass

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.normpath(os.path.join(HERE, "..", ".."))
sys.path.insert(0, HERE)

LOCAL = os.environ.get("GO5_LOCAL_DIR") or os.path.join(ROOT, "local")
INBOX = os.path.join(LOCAL, "discord_inbox_codex.jsonl")           # 旧jsonl経路(残置・実質未使用)
PROCESSED = os.path.join(LOCAL, "discord_inbox_codex_processed.jsonl")
FOR_CLAUDE = os.path.join(LOCAL, "discord_inbox.jsonl")            # =司令塔の主受付箱(gemini_responderと同じ)
CHANNELS_FILE = os.path.join(LOCAL, "discord_channels.json")
TOKEN_FILE = os.path.join(LOCAL, "discord_codex_token.txt")
ENABLE_FLAG = os.path.join(LOCAL, "codex_enabled.txt")
LOG = os.path.join(LOCAL, "llm", "codex_responder_log.jsonl")
CODEX_CLI = os.path.join(ROOT, "scripts", "codex", "codex_run.py")

# 表示名は人事が確定=「ネイキッド・スネーク」(2026-09-05・デブライネ経由)。実応答は codex_run.py が
# Codex bot本人として投稿するので、この名前はエスカレ通知の文面にしか使わない(変数名は互換のため据置)。
PERSONA_TENTATIVE = "ネイキッド・スネーク"

# 機微=司令塔直轄(防御的ガード。codex部屋は該当しない想定だが念のため)
SENSITIVE_DEPTS = ("dream-care", "past-room", "hr-room", "health-log")

# Codexは遅い(実測45〜60秒/件)。1巡回の上限を小さくして暴走と長時間ブロックを防ぐ。
QUEUE_CLAIM_CAP = 2
QUEUE_DB = os.path.join(LOCAL, "queue", "inbox.db")
# codex_run.py の worktree保持ログ行を拾う正規表現(重い実装の着地点を引き継ぐため)。
WT_RE = re.compile(r"★worktreeに変更あり=\s*(.+?)(?:\(枝|$)")
# codex_run.py の --timeout(既定600)より少し長く待つ(生成+worktree操作+投稿の余白)。
RUN_TIMEOUT = 720


def log(rec):
    os.makedirs(os.path.dirname(LOG), exist_ok=True)
    with open(LOG, "a", encoding="utf-8") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")


def append_line(path, line):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "a", encoding="utf-8") as f:
        f.write(line.rstrip("\n") + "\n")


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
def notify_room(channel, text):
    """エスカレ受領などの短い通知を Codex bot本人として投稿する(codex_run.dc_sendを借りる)。
    失敗しても握りつぶす(通知は本筋を止めない)。"""
    try:
        sys.path.insert(0, os.path.join(ROOT, "scripts", "codex"))
        import codex_run
        token = open(TOKEN_FILE, encoding="utf-8").read().strip()
        codex_run.dc_send(token, codex_run.resolve_channel(channel), text)
    except Exception as e:
        print(f"  通知失敗(続行): {type(e).__name__}")


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
def codex_answer(channel, content):
    """codex_run.py へ委譲= 専用worktreeで生成/実装し、Codex bot本人として部屋へ投稿。

    戻り値 (ok, worktree_or_empty)。
    - ok=False は生成失敗(投稿は codex_run 側で中止済み)= 呼び側が司令塔へ回す。
    - worktree_or_empty= 変更が残った worktree のパス(あれば)。無ければ空文字。
    """
    try:
        r = subprocess.run(
            [sys.executable, CODEX_CLI, "--ask", content, "--to", channel,
             "--tag", "room", "--timeout", "600"],
            capture_output=True, text=True, encoding="utf-8", errors="replace",
            timeout=RUN_TIMEOUT)
    except subprocess.TimeoutExpired:
        return False, ""
    out = (r.stdout or "") + "\n" + (r.stderr or "")
    m = WT_RE.search(out)
    worktree = m.group(1).strip() if m else ""
    return r.returncode == 0, worktree


def handle(rec, raw_line):
    content = rec.get("content", "")
    channel = rec.get("channel", "")
    if rec.get("dept") in SENSITIVE_DEPTS:
        escalate(channel, raw_line)
        notify_room(channel, "受け取りました。ここは司令塔が直接読む部屋なので、そちらへ回しました。")
        log({"ts": time.strftime("%Y-%m-%dT%H:%M:%S"), "mode": "sensitive_deferred", "channel": channel})
        return
    if not content.strip():
        escalate(channel, raw_line)
        notify_room(channel, "テキスト以外(添付/音声)は扱えないので、司令塔の受付箱へ入れました。")
        log({"ts": time.strftime("%Y-%m-%dT%H:%M:%S"), "mode": "escalated_no_text", "channel": channel})
        return

    # ★Codexは仕事をする側= 作業語で弾かない。部屋の発言はそのまま Codex へ渡す。
    ok, worktree = codex_answer(channel, content)
    if ok:
        append_line(PROCESSED, raw_line)
        if worktree:
            # 重い実装が worktree に着地= 司令塔へ「レビュー/取り込み待ち」として引き継ぐ。
            note = (f"[codex] 部屋 {channel} の依頼で Codex が実装を worktree に残しました(要レビュー/取り込み)。"
                    f" worktree= {worktree} / 依頼= {content[:120]}")
            append_line(FOR_CLAUDE, json.dumps(
                {"content": note, "channel": channel, "dept": "codex",
                 "from": "codex_responder", "worktree": worktree,
                 "ts": time.strftime("%Y-%m-%dT%H:%M:%S")}, ensure_ascii=False))
            print(f"  Codex実装→worktree保持 [{channel}] {worktree}")
        else:
            print(f"  Codex回答 [{channel}] {content[:30]!r}")
        log({"ts": time.strftime("%Y-%m-%dT%H:%M:%S"), "mode": "answered", "channel": channel,
             "q": content[:200], "worktree": worktree})
    else:
        escalate(channel, raw_line,
                 note=f"[codex] 生成失敗のため司令塔へ回送: {content[:120]}")
        notify_room(channel, "うまく処理できなかったので、司令塔の受付箱へ回しました。")
        log({"ts": time.strftime("%Y-%m-%dT%H:%M:%S"), "mode": "escalated_failed", "channel": channel,
             "q": content[:200]})
        print(f"  Codex失敗→Claude行き [{channel}] {content[:30]!r}")


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
                handle(rec, raw_line)
                q.ack(c["id"], result="処理済")
            except Exception as e:
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
            except Exception as e:
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
