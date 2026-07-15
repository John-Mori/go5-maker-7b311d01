#!/usr/bin/env python3
"""ローカルLLM受付係 (Discord一次応答・Claudeセッション不在時の24時間窓口)。

仕組み(2026-07-15 変更・Chami指示「一次受けにローカルを挟むな・全部門で排除」):
  - **部門の依頼(main箱 discord_inbox.jsonl)には一切触れない**。以前はClaude不在時にmain箱を
    ドレインしてqwen応答/for_claude箱へ再エスカレしていたが、それが「依頼が横取りされて司令塔に
    届かない/無視される」原因だった。部門の依頼は司令塔(Claude)専任=main箱のまま待たせる。
  - ローカルqwenが応対するのは**自室 llm-growth(discord_inbox_llm.jsonl)だけ**。
  - 質問系: Ollama(知識パック注入)で即答 → persona_send「ローカルqwen」名義で返信
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
PERSONA = "ローカルqwen"  # 旧名「ローカル受付」(Chami改名2026-07-13)
MODEL = "qwen3:8b"  # RTX 3060 Ti 8GBで実測55秒/回・品質向上のため4b→8bへ格上げ(2026-07-13)
INBOX_LLM = os.path.join(LOCAL, "discord_inbox_llm.jsonl")  # llm-growth部屋専用=Claude稼働中でも本人が応対
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


SENSITIVE_DEPTS = ("dream-care", "past-room", "hr-room", "health-log")  # 夢と回復/過去の共有/人事/健康記録=司令塔直轄・機微。ローカルLLMは応答せず受領印のみ


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
        # llm-growth部屋(自分の部屋)はClaude稼働中でも常時応対
        if os.path.exists(INBOX_LLM) and os.path.getsize(INBOX_LLM) > 0:
            with open(INBOX_LLM, "r", encoding="utf-8") as f:
                llm_lines = [l for l in f.read().splitlines() if l.strip()]
            os.remove(INBOX_LLM)
            for line in llm_lines:
                try:
                    handle(json.loads(line), line)
                except Exception as e:
                    print(f"  処理失敗(llm箱): {type(e).__name__}")
                    append_line(FOR_CLAUDE, line)
        # ★main箱(部門の依頼)には一切触れない=ローカルを一次受付として挟まない
        #   (Chami指示2026-07-15「一次受けにローカルを挟むな・全部門で排除」)。
        #   以前はClaude不在時にmain箱をドレインしてqwen応答/for_claude箱へ再エスカレしていたが、
        #   それが「依頼が横取りされて司令塔に届かない/無視される」原因だった。
        #   部門の依頼は司令塔(Claude)の専任。main箱はそのまま司令塔が処理する。
        #   ローカルqwenは自室 llm-growth(上の INBOX_LLM)だけを応対する。
        if once:
            print("1回分の処理完了(自室llm-growthのみ・main箱は司令塔専任)")
            break
        time.sleep(30)


if __name__ == "__main__":
    main()
