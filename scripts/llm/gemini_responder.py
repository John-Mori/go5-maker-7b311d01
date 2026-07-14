#!/usr/bin/env python3
"""Gemini受付係 (Discord専用部屋の一次応答・local_responder.pyのGemini版)。

仕組み:
  - local/discord_inbox_gemini.jsonl を30秒ごとに監視(受信振り分けはinbox_poller.pyが担当・dept=="gemini")
  - 自分専用の部屋なので、qwenのllm-growth部屋と同じく**Claude稼働中でも常時応答**する(claude_active待機なし)
  - 質問系: Gemini(ask_gemini.ask・知識パック注入)で即答 → persona_send「Gemini受付」名義で返信
  - 作業依頼系(修正/実装/デプロイ等)や知識外: local/discord_inbox_for_claude.jsonl へ回し、その旨を返信
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
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
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
FOR_CLAUDE = os.path.join(LOCAL, "discord_inbox_for_claude.jsonl")
LOG = os.path.join(LOCAL, "llm", "gemini_responder_log.jsonl")
PERSONA = "Gemini受付"
# local_responder.pyのWORK_WORDSをそのまま流用(作業依頼語の判定基準を揃える)
WORK_WORDS = ("直して", "修正", "実装", "追加して", "デプロイ", "変えて", "作って", "調べて", "特定して",
              "バグ", "エラー", "壊れ", "対応して", "やって", "反映", "消して", "削除")
SENSITIVE_DEPTS = ("dream-care", "past-room", "hr-room")  # 通常はgemini部屋に該当しないが防御的にガード


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
        append_line(FOR_CLAUDE, raw_line)
        append_line(PROCESSED, raw_line)
        send(channel, "これは司令塔(Claude)の仕事として受付箱に入れておくね。次のセッションで対応されるよ。")
        log({"ts": time.strftime("%Y-%m-%dT%H:%M:%S"), "mode": "escalated", "channel": channel,
             "q": content[:200]})
        print(f"  Claude行き [{channel}] {content[:30]!r}")


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
    print("Gemini受付 起動 (30秒間隔, 自分の部屋なのでClaude稼働中でも常時応答)")
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
                append_line(FOR_CLAUDE, line)
        if once:
            print("1回分の処理完了")
            break
        time.sleep(30)


if __name__ == "__main__":
    main()
