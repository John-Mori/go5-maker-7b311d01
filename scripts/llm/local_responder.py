#!/usr/bin/env python3
"""ローカルLLM受付係 (Discord一次応答・Claudeセッション不在時の24時間窓口)。

仕組み:
  - local/discord_inbox.jsonl を30秒ごとに監視(受信はinbox_poller.pyが担当)
  - Claudeセッション稼働中(local/llm/claude_active.txt が90秒以内に更新)は何もしない=自動バトンタッチ
  - 質問系: Ollama(知識パック注入)で即答 → persona_send「ローカル受付」名義で返信
  - 作業依頼系(修正/実装/デプロイ等)や知識外: local/discord_inbox_for_claude.jsonl へ回し、その旨を返信
  - 処理済みは local/discord_inbox_processed.jsonl へ移動。応答ログは local/llm/responder_log.jsonl
使い方: python scripts/llm/local_responder.py [--once]
常駐: scripts/llm/start_local_responder.bat
"""
import json
import os
import subprocess
import sys
import time

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.normpath(os.path.join(HERE, "..", ".."))
sys.path.insert(0, HERE)
from ask_local import ask  # noqa: E402

LOCAL = os.path.join(ROOT, "local")
INBOX = os.path.join(LOCAL, "discord_inbox.jsonl")
PROCESSED = os.path.join(LOCAL, "discord_inbox_processed.jsonl")
FOR_CLAUDE = os.path.join(LOCAL, "discord_inbox_for_claude.jsonl")
CLAUDE_ACTIVE = os.path.join(LOCAL, "llm", "claude_active.txt")
LOG = os.path.join(LOCAL, "llm", "responder_log.jsonl")
PERSONA = "ローカル受付"
MODEL = "qwen3:4b"
WORK_WORDS = ("直して", "修正", "実装", "追加して", "デプロイ", "変えて", "作って", "調べて", "特定して",
              "バグ", "エラー", "壊れ", "対応して", "やって", "反映", "消して", "削除")


def claude_is_active():
    try:
        return (time.time() - os.path.getmtime(CLAUDE_ACTIVE)) < 90
    except Exception:
        return False


def send(channel, text):
    r = subprocess.run([sys.executable, os.path.join(ROOT, "scripts", "discord", "persona_send.py"),
                        "--channel", channel, "--persona", PERSONA, text],
                       capture_output=True, text=True, encoding="utf-8", errors="replace")
    return r.returncode == 0


def log(rec):
    os.makedirs(os.path.dirname(LOG), exist_ok=True)
    with open(LOG, "a", encoding="utf-8") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")


def append_line(path, line):
    with open(path, "a", encoding="utf-8") as f:
        f.write(line.rstrip("\n") + "\n")


AUDIO_EXT = (".ogg", ".m4a", ".mp3", ".wav", ".webm")


def fetch_and_transcribe(url):
    """Discordの音声添付をダウンロードして文字起こし(失敗時は空文字)。"""
    import urllib.request
    tmp = os.path.join(ROOT, "local", "llm", "voice_tmp.bin")
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (go5-responder)"})
        with urllib.request.urlopen(req, timeout=60) as r, open(tmp, "wb") as f:
            f.write(r.read())
        from transcribe import transcribe
        return transcribe(tmp)
    except Exception as e:
        print(f"  文字起こし失敗: {type(e).__name__}")
        return ""


SENSITIVE_DEPTS = ("dream-care", "past-room", "hr-room")  # 夢と回復/過去の共有/人事=司令塔直轄。ローカルLLMは応答せず受領印のみ


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
        voice = next((a for a in (rec.get("attachments") or [])
                      if any(x in a.lower() for x in AUDIO_EXT)), "")
        if voice:
            content = fetch_and_transcribe(voice)
            if not content:
                append_line(FOR_CLAUDE, raw_line)
                append_line(PROCESSED, raw_line)
                send(channel, "ボイスメモを受け取ったけど聞き起こせなかったから、司令塔の受付箱に入れておくね。")
                log({"ts": time.strftime("%Y-%m-%dT%H:%M:%S"), "mode": "escalated_voice_fail", "channel": channel})
                return
            rec = dict(rec, content=content, voice=True)
            raw_line = json.dumps(rec, ensure_ascii=False)
    is_work = any(w in content for w in WORK_WORDS)
    answer = ""
    if not is_work:
        try:
            answer = ask(content, MODEL)
        except Exception as e:
            print(f"  LLM失敗: {type(e).__name__} → Claude行き")
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
        append_line(FOR_CLAUDE, raw_line)
        append_line(PROCESSED, raw_line)
        send(channel, "これは司令塔(Claude)の仕事として受付箱に入れておくね。次のセッションで対応されるよ。")
        log({"ts": time.strftime("%Y-%m-%dT%H:%M:%S"), "mode": "escalated", "channel": channel,
             "q": content[:200]})
        print(f"  Claude行き [{channel}] {content[:30]!r}")


def main():
    once = "--once" in sys.argv
    print(f"ローカル受付 起動 (model={MODEL}, 30秒間隔, Claude稼働中は待機)")
    while True:
        if claude_is_active():
            if once:
                print("Claudeセッション稼働中のため待機のみで終了")
                break
            time.sleep(30)
            continue
        if os.path.exists(INBOX) and os.path.getsize(INBOX) > 0:
            with open(INBOX, "r", encoding="utf-8") as f:
                lines = [l for l in f.read().splitlines() if l.strip()]
            # 先に受付箱を空にする(処理中の新着はpollerが追記→次周期で拾う)
            os.remove(INBOX)
            for line in lines:
                try:
                    handle(json.loads(line), line)
                except Exception as e:
                    print(f"  処理失敗: {type(e).__name__}")
                    append_line(FOR_CLAUDE, line)
        if once:
            print("1回分の処理完了")
            break
        time.sleep(30)


if __name__ == "__main__":
    main()
