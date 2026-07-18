#!/usr/bin/env python3
"""ホイミン(Gemini)受付係 (Discord専用部屋の一次応答・local_responder.pyのGemini版)。

仕組み:
  - local/discord_inbox_gemini.jsonl を30秒ごとに監視(受信振り分けはinbox_poller.pyが担当・dept=="gemini")
  - 自分専用の部屋なので、qwenのllm-growth部屋と同じく**Claude稼働中でも常時応答**する(claude_active待機なし)
  - 質問系: Gemini(ask_gemini.ask・知識パック注入)で即答 → persona_send「ホイミン(Gemini)」名義で返信
  - 作業依頼系(修正/実装/デプロイ等)や知識外: **司令塔の主受付箱 local/discord_inbox.jsonl** へ回す
    (専用for_claude箱は司令塔が開始時しか読まず滞留・喪失していた=2026-07-15恒久修正)。
    司令塔不在(claude_active.txt>90秒)なら「受け取った・復帰後対応」を返信/稼働中は黙ってエスカレ
  - APIキー未設定(local/gemini_api_key.txt / 環境変数GEMINI_API_KEY)の間は**受付箱を消費せず**待機(キー設定後に自動開始)
  - 受付箱は処理前に mv で先に退避してから全行処理(INC-76対策・読了後の追記巻き込みを防ぐ)
  - 処理済みは local/discord_inbox_processed.jsonl へ移動。応答ログは local/llm/gemini_responder_log.jsonl
使い方: python scripts/llm/gemini_responder.py [--once]
常駐: scripts/llm/start_gemini_responder.bat
"""
import json
import os
import subprocess
import sys
import time

try:
    # line_buffering=True が必須(INC-93): ファイル向けstdoutは約8KBのブロックバッファになり、
    # 無口な常駐は到達せず、Stop-Process -Forceで未書き出し分が破棄される=ログが残らない。
    sys.stdout.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)
except Exception:
    pass

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.normpath(os.path.join(HERE, "..", ".."))
sys.path.insert(0, HERE)
from ask_gemini import ask, read_key  # noqa: E402

# テスト: 環境変数 GO5_LOCAL_DIR があれば local/ の代わりにそれを使う(全パス)。
# 注意: ask_gemini.read_key() 自体はこの変数を見ない(常にリポジトリ本体のlocal/を見る=元コードのまま変更なし)。
LOCAL = os.environ.get("GO5_LOCAL_DIR") or os.path.join(ROOT, "local")
INBOX = os.path.join(LOCAL, "discord_inbox_gemini.jsonl")
PROCESSED = os.path.join(LOCAL, "discord_inbox_processed.jsonl")
# エスカレーション先=司令塔の主受付箱(discord_inbox.jsonl)。専用for_claude箱は司令塔がセッション
# 開始時にしか読まず、開始前に届いた分が喪失していた(2026-07-14に3件滞留)。main箱なら司令塔が
# 毎セッション必ず処理し、Gemini自身はmain箱を読まない(=読むのはgemini箱のみ)ので取り込みループも無い。
# (local_responterはClaude不在時にmain箱をドレインするが、dept=="gemini"行は保全する側のガード有り)
FOR_CLAUDE = os.path.join(LOCAL, "discord_inbox.jsonl")
CLAUDE_ACTIVE = os.path.join(LOCAL, "llm", "claude_active.txt")
LOG = os.path.join(LOCAL, "llm", "gemini_responder_log.jsonl")
PERSONA = "ホイミン(Gemini)"  # 表示名=persona_avatars.json のアバター引き先(Chami改名2026-07-15・旧「Gemini受付」)
# local_responder.pyのWORK_WORDSをそのまま流用(作業依頼語の判定基準を揃える)
WORK_WORDS = ("直して", "修正", "実装", "追加して", "デプロイ", "変えて", "作って", "調べて", "特定して",
              "バグ", "エラー", "壊れ", "対応して", "やって", "反映", "消して", "削除")
SENSITIVE_DEPTS = ("dream-care", "past-room", "hr-room", "health-log")  # 機微=司令塔直轄。通常はgemini部屋に該当しないが防御的にガード


def send(channel, text):
    r = subprocess.run([sys.executable, os.path.join(ROOT, "scripts", "discord", "persona_send.py"),
                        "--channel", channel, "--persona", PERSONA, text],
                       capture_output=True, text=True, encoding="utf-8", errors="replace")
    return r.returncode == 0


def claude_absent():
    """司令塔(Claude)が不在か。判定は共有ヘルパ presence.lab_alive へ一本化(全responder同一基準)。

    旧・claude_active.txt 90秒単独ゲートは、mainが長い作業中(耳=waiter脈が一時途切れ・
    toolフック脈は新鮮)でも不在と誤判定し、ホイミンが受領文を暴発させた(2026-07-18 INC)。
    presence.lab_alive は readiness(耳) OR liveness(toolフック脈)+HARD_CAP の2信号で判定する。"""
    from presence import lab_alive  # sys.path に HERE を追加済(冒頭)
    return not lab_alive()


# 司令塔不在時にエスカレーションした際の受領返信(稼働中は黙ってエスカレ=逐一アナウンス不要)。
ABSENT_ACK = ("🤖 司令塔(Claude)が今は応答できない状態なんだけど、メッセージはちゃんと受け取ったよ。"
              "復帰したら必ず対応するから、少し待っててね。")


def escalate(channel, raw_line, announce_when_active=False):
    """作業依頼・知識外を司令塔の主受付箱へ回す。不在時のみ受領を返信する。"""
    append_line(FOR_CLAUDE, raw_line)
    append_line(PROCESSED, raw_line)
    if claude_absent():
        send(channel, ABSENT_ACK)
    elif announce_when_active:
        send(channel, "これは司令塔(Claude)が対応するね。")


def log(rec):
    os.makedirs(os.path.dirname(LOG), exist_ok=True)
    with open(LOG, "a", encoding="utf-8") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")


def append_line(path, line):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "a", encoding="utf-8") as f:
        f.write(line.rstrip("\n") + "\n")


def handle(rec, raw_line):
    content = rec.get("content", "")
    channel = rec.get("channel", "")
    if rec.get("dept") in SENSITIVE_DEPTS:
        append_line(FOR_CLAUDE, raw_line)
        append_line(PROCESSED, raw_line)
        send(channel, "受け取ったよ。ここは司令塔(アメスたち)が直接読む部屋だから、次に起きた時に必ず応えるね。")
        log({"ts": time.strftime("%Y-%m-%dT%H:%M:%S"), "mode": "sensitive_deferred", "channel": channel})
        return
    if not content.strip():
        # 音声添付等の文字起こしは非対応(Geminiはテキスト受付のみ)→司令塔へ
        append_line(FOR_CLAUDE, raw_line)
        append_line(PROCESSED, raw_line)
        send(channel, "テキスト以外(添付/音声)は聞き起こせないから、司令塔の受付箱に入れておくね。")
        log({"ts": time.strftime("%Y-%m-%dT%H:%M:%S"), "mode": "escalated_no_text", "channel": channel})
        return
    is_work = any(w in content for w in WORK_WORDS)
    answer = ""
    if not is_work:
        try:
            answer = ask(content)
        except Exception as e:
            print(f"  Gemini呼び出し失敗: {type(e).__name__} → Claude行き")
            answer = ""
        if answer and ("わからないので司令塔" in answer or "ESCALATE" in answer):
            answer = ""
    if answer:
        ok = send(channel, answer)
        log({"ts": time.strftime("%Y-%m-%dT%H:%M:%S"), "mode": "answered", "channel": channel,
             "q": content[:200], "a": answer[:300], "sent": ok})
        append_line(PROCESSED, raw_line)
        print(f"  即答 [{channel}] {content[:30]!r}")
    else:
        absent = claude_absent()
        escalate(channel, raw_line)  # main箱へ。不在時のみ受領を返信・稼働中は黙ってエスカレ
        log({"ts": time.strftime("%Y-%m-%dT%H:%M:%S"), "mode": "escalated", "channel": channel,
             "q": content[:200], "claude_absent": absent})
        print(f"  Claude行き [{channel}] {content[:30]!r} (claude_absent={absent})")


def take_inbox():
    """受付箱をmvで先に退避してから全行を返す(INC-76対策・読了後の追記巻き込みを防ぐ)。"""
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


def main():
    once = "--once" in sys.argv
    print("ホイミン(Gemini)受付 起動 (30秒間隔, 自分の部屋なのでClaude稼働中でも常時応答)")
    while True:
        if not read_key():
            print("GeminiのAPIキー未設定(local/gemini_api_key.txt)。キー設定後に自動で受付開始します")
            if once:
                break
            time.sleep(30)
            continue
        for line in take_inbox():
            try:
                handle(json.loads(line), line)
            except Exception as e:
                print(f"  処理失敗: {type(e).__name__}")
                append_line(FOR_CLAUDE, line)  # =main箱。喪失させない
        if once:
            print("1回分の処理完了")
            break
        time.sleep(30)


if __name__ == "__main__":
    main()
