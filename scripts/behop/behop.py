#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""behop — ベホップ (強Gemini) の頭脳と口。 (2026-07-19 QA配線・Chami Go)

構成 (Chami設計2026-07-18):
  頭脳 = Geminiの強モデル。キー=local/gemini_api_key_behop.txt (森光技研Logosの事業用・正規利用)
  口   = 専用Discord bot。トークン=local/discord_behop_token.txt (非公開bot・最小権限・Intents OFF)
  役割 = 重い下書き・長文整形・要約・画像読み。**判断・コード・数字・データ編集は渡さない** (縄張り規約)
  ホイミン (弱・私用キー・共有bot) とは束を分ける: 資格情報を跨いで使い回さない。

使い方:
  python scripts/behop/behop.py --ping                          # キーとbotの生存確認 (投稿しない)
  python scripts/behop/behop.py --ask "質問"                    # 生成して印字のみ
  python scripts/behop/behop.py --ask-file p.txt --to <ch名|ID> # 生成してベホップとして投稿
  python scripts/behop/behop.py --ask "..." --image a.png --to <ch>   # 画像つき
  --model <name> で強モデルの明示指定も可 (既定は優先リスト→実在照会で自動選択)
"""
import base64
import json
import os
import sys
import time
import urllib.parse
import urllib.request

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.normpath(os.path.join(HERE, "..", ".."))
LOCAL = os.environ.get("GO5_LOCAL_DIR") or os.path.join(ROOT, "local")

KEY_FILE = os.path.join(LOCAL, "gemini_api_key_behop.txt")       # Chami設置名が正 (2026-07-18 23:25)
TOKEN_FILE = os.path.join(LOCAL, "discord_behop_token.txt")
CHANNELS_FILE = os.path.join(LOCAL, "discord_channels.json")
GEM_API = "https://generativelanguage.googleapis.com/v1beta"
DC_API = "https://discord.com/api/v10"

# 強モデルの優先順。実在は起動時にListModelsで照会し、無ければ次へ (モデル名の変遷に強くする)。
PREFERRED = ("gemini-3-pro-latest", "gemini-3-pro", "gemini-2.5-pro", "gemini-pro-latest")

MIME = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
        ".webp": "image/webp", ".gif": "image/gif"}


def _read(path, what):
    try:
        return open(path, encoding="utf-8").read().strip()
    except OSError:
        print(f"ABORT: {what}が未設置 ({path})")
        sys.exit(2)


def list_models(key):
    req = urllib.request.Request(f"{GEM_API}/models?key={key}&pageSize=200",
                                 headers={"User-Agent": "go5-behop/1.0"})
    with urllib.request.urlopen(req, timeout=20) as r:
        data = json.loads(r.read().decode("utf-8"))
    out = []
    for m in data.get("models", []):
        if "generateContent" in m.get("supportedGenerationMethods", []):
            out.append(m.get("name", "").split("/")[-1])
    return out


def pick_model(key, override=None):
    avail = list_models(key)
    if override:
        if override in avail:
            return override, avail
        print(f"ABORT: 指定モデル {override} はこのキーで使えません")
        sys.exit(3)
    for p in PREFERRED:
        if p in avail:
            return p, avail
    pros = [m for m in avail if "pro" in m and "preview" not in m] or [m for m in avail if "pro" in m]
    if pros:
        return sorted(pros)[-1], avail
    flashes = [m for m in avail if "flash" in m]
    if flashes:
        print(f"注意: proモデルが見つからずflashへフォールバック")
        return sorted(flashes)[-1], avail
    print("ABORT: 使えるモデルがありません")
    sys.exit(3)


def _gen_once(key, model, payload):
    req = urllib.request.Request(
        f"{GEM_API}/models/{model}:generateContent?key={key}",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json", "User-Agent": "go5-behop/1.0"})
    with urllib.request.urlopen(req, timeout=120) as r:
        data = json.loads(r.read().decode("utf-8"))
    return "".join(pt.get("text", "") for pt in data["candidates"][0]["content"]["parts"])


def ask(key, model, prompt, image_paths=(), avail=()):
    """生成。429 (割当超過)/404は下位モデルへ自動降格して粘る (無料枠のproは割当が極小のため)。
    トレースバックで落とさない=部品として使う側 (セッション/将来のresponder) を巻き込まない。"""
    parts = [{"text": prompt}]
    for p in image_paths:
        ext = os.path.splitext(p)[1].lower()
        with open(p, "rb") as f:
            parts.append({"inline_data": {"mime_type": MIME.get(ext, "image/png"),
                                          "data": base64.b64encode(f.read()).decode("ascii")}})
    payload = {"contents": [{"parts": parts}]}
    ladder = [model] + [m for m in ("gemini-2.5-pro", "gemini-flash-latest", "gemini-2.5-flash",
                                    "gemini-flash-lite-latest")
                        if m != model and (not avail or m in avail)]
    last_err = "?"
    for m in ladder:
        try:
            text = _gen_once(key, m, payload)
            if m != model:
                print(f"(注: {model}が割当超過等のため {m} へ降格して生成)")
            return text, m
        except urllib.error.HTTPError as e:
            last_err = f"HTTP {e.code}"
            if e.code in (429, 404, 400):
                time.sleep(1.5)
                continue
            break
        except (KeyError, IndexError):
            last_err = "応答形式が想定外"
            continue
        except Exception as e:
            last_err = type(e).__name__
            break
    return f"(生成失敗: {last_err}。時間を置くか--modelで明示指定を)", None


def resolve_channel(token, target):
    if str(target).isdigit():
        return str(target)
    chans = json.load(open(CHANNELS_FILE, encoding="utf-8"))
    ch = next((c for c in chans if c.get("name") == target or c.get("dept") == target), None)
    if not ch:
        print(f"ABORT: チャンネル未登録: {target}")
        sys.exit(4)
    return str(ch["id"])


def dc_send(token, channel_id, text):
    """ベホップ (bot本人) として投稿。2000字制限は段落優先で分割。"""
    chunks, cur = [], ""
    for ln in text.splitlines(keepends=True):
        if len(cur) + len(ln) > 1900:
            chunks.append(cur)
            cur = ""
        cur += ln
    if cur.strip():
        chunks.append(cur)
    for i, c in enumerate(chunks or [text]):
        req = urllib.request.Request(
            f"{DC_API}/channels/{channel_id}/messages",
            data=json.dumps({"content": c}).encode("utf-8"),
            headers={"Authorization": f"Bot {token}", "Content-Type": "application/json",
                     "User-Agent": "go5-behop/1.0"})
        try:
            with urllib.request.urlopen(req, timeout=20) as r:
                mid = json.loads(r.read().decode("utf-8")).get("id", "")
            print(f"投稿OK (ベホップ) msg={mid}" + (f" [{i+1}通目]" if i else ""))
        except urllib.error.HTTPError as e:
            if e.code == 403:
                print(f"投稿失敗: HTTP 403 = ベホップbotがこのチャンネルに入室できていない。"
                      f"Discordでそのチャンネルの設定→権限→メンバー/ロールを追加→Behop_Gemini を追加")
            else:
                print(f"投稿失敗: HTTP {e.code}")
            return False
        time.sleep(0.4)
    return True


def main():
    args = sys.argv[1:]
    prompt = model = to = ask_file = None
    images = []
    ping = "--ping" in args
    i = 0
    while i < len(args):
        a = args[i]
        if a == "--ask" and i + 1 < len(args):
            prompt = args[i + 1]; i += 2
        elif a == "--ask-file" and i + 1 < len(args):
            ask_file = args[i + 1]; i += 2
        elif a == "--image" and i + 1 < len(args):
            images.append(args[i + 1]); i += 2
        elif a == "--to" and i + 1 < len(args):
            to = args[i + 1]; i += 2
        elif a == "--model" and i + 1 < len(args):
            model = args[i + 1]; i += 2
        else:
            i += 1
    key = _read(KEY_FILE, "ベホップ用APIキー")
    if ping:
        m, avail = pick_model(key, model)
        print(f"キーOK: 使用可能モデル{len(avail)}種 / 強モデル選択={m}")
        token = _read(TOKEN_FILE, "ベホップbotトークン")
        req = urllib.request.Request(f"{DC_API}/users/@me",
                                     headers={"Authorization": f"Bot {token}",
                                              "User-Agent": "go5-behop/1.0"})
        with urllib.request.urlopen(req, timeout=15) as r:
            me = json.loads(r.read().decode("utf-8"))
        print(f"botOK: {me.get('username')}#{me.get('discriminator')} (id={me.get('id')})")
        return 0
    if ask_file:
        prompt = open(ask_file, encoding="utf-8").read().strip()
    if not prompt:
        print("使い方: behop.py --ping | --ask <文|--ask-file p> [--image p]... [--to <ch名|ID>] [--model m]")
        return 1
    m, avail = pick_model(key, model)
    text, used = ask(key, m, prompt, images, avail)
    print(f"--- ベホップ ({used or '失敗'}) ---")
    print(text)
    if to and used:
        token = _read(TOKEN_FILE, "ベホップbotトークン")
        dc_send(token, resolve_channel(token, to), text)
    elif to:
        print("生成失敗のため投稿は中止 (失敗文をDiscordへ流さない)")
        return 5
    return 0


if __name__ == "__main__":
    sys.exit(main())
