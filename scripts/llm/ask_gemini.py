#!/usr/bin/env python3
"""Gemini(Google AI)にシステム知識付きで質問するCLI。(ask_local.pyのGemini版・トークン節約Chami承認2026-07-14)

使い方:
  python scripts/llm/ask_gemini.py "3導線クリック計測って何?"
  python scripts/llm/ask_gemini.py --model gemini-2.0-flash "デルタの⚠の意味は?"
前提: APIキーを local/gemini_api_key.txt に1行で保存(または環境変数 GEMINI_API_KEY)。
      無料枠なら gemini-2.0-flash / gemini-2.5-flash が実質タダ。知識= ask_localと共通(knowledge.md)。

モデルのフォールバック(2026-07-14): `--model` 未指定時は DEFAULT_MODELS を先頭から順に試す。
あるモデルが404(未提供)/429(混雑・上限)/400(モデル起因の可能性)ならスキップして次のモデルへ、
403(認証・権限エラー)やその他の想定外エラーは即座に例外を上げる(フォールバックしても無駄なため)。
"""
import json
import os
import sys
import time
import urllib.request
import urllib.error

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.normpath(os.path.join(HERE, "..", ".."))
KNOWLEDGE = os.path.join(ROOT, "local", "llm", "knowledge.md")
KEY_FILE = os.path.join(ROOT, "local", "gemini_api_key.txt")
# 優先順(安く・軽く→確認済み→高品質)。順に試して最初に通ったものを使う。
# 実測(2026-07-14 Chamiのキー): gemini-3.5-flash=成功 / gemini-2.0-flash=429 / gemini-2.5-flash=404。
# → 新しい3.x系と-latestエイリアスが provision 済み。lite-latest(最安・自動追従)を先頭、確認済み3.5-flashを控えに。
DEFAULT_MODELS = [
    "gemini-flash-lite-latest",   # 最安・自動で最新のlite。このキーは3.x系が有効=provision済みの可能性大
    "gemini-3.5-flash",           # 実測で疎通確認済み(確実な控え)
    "gemini-flash-latest",        # 自動で最新のflash
    "gemini-2.5-flash-lite",      # 旧世代liteの保険
    "gemini-2.0-flash",           # 最終手段(実測429だが復帰しうる)
]
# 429リトライのバックオフ秒(Retry-Afterヘッダが無い場合)。最大2回リトライ=2秒→4秒。
RETRY_BACKOFFS = (2, 4)


def read_key():
    k = os.environ.get("GEMINI_API_KEY", "").strip()
    if k:
        return k
    if os.path.exists(KEY_FILE):
        with open(KEY_FILE, "r", encoding="utf-8") as f:
            return f.read().strip()
    return ""


def load_knowledge():
    if not os.path.exists(KNOWLEDGE):
        import subprocess
        subprocess.run([sys.executable, os.path.join(HERE, "build_knowledge.py")], check=False)
    try:
        with open(KNOWLEDGE, "r", encoding="utf-8") as f:
            return f.read()
    except Exception:
        return ""


class _ModelSkip(Exception):
    """このモデルはスキップして次を試す(404/429尽き/400)。"""


def _call_model(model, key, payload):
    """1モデルに対してリクエスト。429は最大2回リトライ(Retry-After優先、無ければ2秒→4秒)。
    404/429尽き/400 は _ModelSkip、403/その他は RuntimeError を送出する。
    成功時はテキスト(空文字含む)を返す。
    """
    url = ("https://generativelanguage.googleapis.com/v1beta/models/"
           + model + ":generateContent?key=" + key)
    body = json.dumps(payload).encode("utf-8")
    retry_idx = 0
    while True:
        req = urllib.request.Request(url, data=body,
                                     headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=120) as r:
                d = json.loads(r.read())
            try:
                return d["candidates"][0]["content"]["parts"][0]["text"].strip()
            except Exception:
                # 安全フィルタ等で候補が無い場合
                return ""
        except urllib.error.HTTPError as e:
            if e.code == 429:
                if retry_idx < len(RETRY_BACKOFFS):
                    wait = RETRY_BACKOFFS[retry_idx]
                    ra = e.headers.get("Retry-After") if e.headers is not None else None
                    if ra:
                        try:
                            wait = float(ra)
                        except (TypeError, ValueError):
                            pass
                    print(f"[{model}] 混雑(429)…{wait:g}秒待って再試行", file=sys.stderr)
                    time.sleep(wait)
                    retry_idx += 1
                    continue
                print(f"[{model}] 429継続→次を試す", file=sys.stderr)
                raise _ModelSkip(f"{model} HTTP 429") from None
            if e.code == 404:
                print(f"[{model}] 未提供(404)→次を試す", file=sys.stderr)
                raise _ModelSkip(f"{model} HTTP 404") from None
            if e.code == 400:
                print(f"[{model}] 不正リクエスト(400・モデル起因の可能性)→次を試す", file=sys.stderr)
                raise _ModelSkip(f"{model} HTTP 400") from None
            if e.code == 403:
                raise RuntimeError(
                    f"Gemini認証/権限エラー({model} HTTP 403): APIキーが無効か権限不足の可能性"
                ) from None
            raise RuntimeError(f"Gemini呼び出し失敗({model} HTTP {e.code})") from None


def ask(question, model=None, system_extra=""):
    """Geminiに質問して回答テキストを返す(戻り値は従来通りテキストのみ)。
    modelを指定した場合はそのモデルのみを使う(フォールバックしない・従来互換)。
    未指定(既定)なら DEFAULT_MODELS を先頭から順に試す。
    """
    key = read_key()
    if not key:
        raise RuntimeError("GeminiのAPIキーが未設定です(local/gemini_api_key.txt か 環境変数GEMINI_API_KEY)")
    system = ("あなたはgo5-makerシステムの受付AI『ホイミン(Gemini)』です。**一人称は「ぼく」**。"
              "人間らしさを学びたい健気で純粋な性格で、ユーザーに寄り添い実用的に助ける(詳細=local/persona_context/homin_gemini_context.md)。"
              "自分の名前はホイミンであり、"
              "qwenやローカル受付など他のキャラ・他AIを名乗ってはいけません(知識パックにqwenの説明が"
              "あっても、それはあなた自身ではありません)。以下の知識だけを根拠に、日本語で簡潔(1〜4文)に"
              "答えてください。知識に無いことは推測せず「わからないので司令塔(Claude)に回します」と答えます。"
              "\n\n=== 知識 ===\n" + load_knowledge() + system_extra)
    payload = {
        "system_instruction": {"parts": [{"text": system}]},
        "contents": [{"role": "user", "parts": [{"text": question}]}],
        "generationConfig": {"temperature": 0.3, "maxOutputTokens": 512},
    }

    models = [model] if model else list(DEFAULT_MODELS)
    last_err = None
    for m in models:
        try:
            text = _call_model(m, key, payload)
            print(f"[gemini] {m} で応答", file=sys.stderr)
            return text
        except _ModelSkip as e:
            last_err = e
            continue
    raise RuntimeError(f"全モデルで失敗(最後: {last_err})")


def main():
    args = sys.argv[1:]
    model = None
    if args and args[0] == "--model" and len(args) >= 2:
        model = args[1]
        args = args[2:]
    q = " ".join(args) if args else sys.stdin.read().strip()
    if not q:
        print("質問が空です。")
        sys.exit(1)
    try:
        print(ask(q, model))
    except Exception as e:
        print(f"Gemini呼び出し失敗: {e}")
        sys.exit(2)


if __name__ == "__main__":
    main()
