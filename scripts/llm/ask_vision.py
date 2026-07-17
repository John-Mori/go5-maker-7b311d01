#!/usr/bin/env python3
"""ローカルVLMに画像を見せる (V0シャドー配線 / 改善設計書_ローカルLLM画像認識強化_2026-07-17)。

役割:
  画像URL(またはパス)→ image_prep で正規化 → Ollama /api/chat の images へ base64 で渡す →
  日本語の説明+読み取れた文字を返す。ask_local.py の画像版だが、**知識パックは注入しない**
  (V0の目的は「画像に何が写っているか」の下読みで、システム知識の推論ではないため。
   知識と混ぜるとVLMが画像に無いことを語り出す=幻覚の温床になる)。

使い方(CLI・単体検証用):
  python scripts/llm/ask_vision.py assets/promo/tsukuyomi-discount-base.png
  python scripts/llm/ask_vision.py <URL> --model qwen3.5:9b --prompt "文字だけ書き出して"

  from ask_vision import describe_images
  res = describe_images([url1, url2])   # {"draft","model","sec","n","error"}

設計上の約束(改善設計書§2.4・§5):
  - temperature 0(下読みは再現性優先。自己検証の2回聞きはV3で導入)
  - プロンプトは短く・出力言語だけ日本語で明示(§2.4「プロンプト言語」)
  - 例外は投げない=常駐(local_responder)を絶対に落とさない。失敗は error 文字列で返す
  - 8GB VRAM: qwen3:8b(5.2GB)と本モデルは同居できずOllamaが自動スワップする。
    V0はそのスワップ待ち(数秒〜十数秒)を許容する。根治はV1のqwen3.5一本化(§3)
"""
import json
import os
import sys
import time
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from image_prep import prepare_image  # noqa: E402

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)
except Exception:
    pass

VISION_MODEL = "gemma3:4b"   # V0=導入済みモデル(追加pullゼロ)。V1でqwen3.5へ差し替え予定(要Chami承認)
DEFAULT_PROMPT = ("画像に何が写っているかを1〜3文で説明し、続けて画像内の文字を読める範囲で正確に書き出してください。"
                  "推測で補わず、読めない文字は書かないでください。出力は日本語。")
# ★90秒(2026-07-17レビューで300→90へ短縮)。実測は4秒前後で、300秒はモデルスワップを
#   見込んでも過大。30秒周期の常駐が1通で長時間ブロックすると、その間に再起動が挟まった時に
#   ドレイン中の行を失う窓が広がる(=下読みという「おまけ」のために配達という本業を危険に晒す)。
TIMEOUT = 90
NUM_PREDICT = 512            # 下読みの長さ上限。暴走生成でタイムアウトするのを防ぐ


def describe_images(urls, prompt=DEFAULT_PROMPT, model=VISION_MODEL, max_edge=1280):
    """画像URL(list)をVLMに見せて下読みテキストを得る。例外は投げない。

    戻り値: {"draft": str, "model": str, "sec": float, "n": int, "error": str|None,
             "sizes": [{"w","h",...}]}
    """
    t0 = time.time()
    b64s, sizes, skipped = [], [], []
    for i, u in enumerate(urls):
        try:
            b64, meta = prepare_image(u, max_edge=max_edge)
        except Exception as e:      # ★二重防御: prepare_imageは投げない設計だが、契約に依存しない
            b64, meta = None, {"error": f"prep_failed:{type(e).__name__}"}
        if not b64:
            # ★1枚が壊れていても他の画像は捨てない(2026-07-17レビュー指摘)。
            #   全滅させると「2枚目がDL失敗しただけで1枚目の下読みも消える」=情報を無駄に捨てる。
            skipped.append({"i": i, "error": meta.get("error")})
            continue
        b64s.append(b64)
        sizes.append(meta)
    if not b64s:
        err = skipped[0]["error"] if skipped else "no_image"
        return {"draft": "", "model": model, "sec": round(time.time() - t0, 1),
                "n": 0, "error": err, "sizes": [], "skipped": skipped}

    payload = {"model": model, "stream": False, "think": False,
               "messages": [{"role": "user", "content": prompt, "images": b64s}],
               "options": {"temperature": 0, "num_ctx": 8192, "num_predict": NUM_PREDICT}}
    try:
        req = urllib.request.Request("http://localhost:11434/api/chat",
                                     data=json.dumps(payload).encode("utf-8"),
                                     headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
            d = json.loads(r.read())
        msg = (d.get("message") or {}).get("content", "") or ""
        if "</think>" in msg:              # 将来qwen3.5等のthinkingブロック対策(ask_localと同じ作法)
            msg = msg.split("</think>", 1)[1]
        return {"draft": msg.strip(), "model": model, "sec": round(time.time() - t0, 1),
                "n": len(b64s), "error": None, "sizes": sizes, "skipped": skipped}
    except Exception as e:
        return {"draft": "", "model": model, "sec": round(time.time() - t0, 1),
                "n": len(b64s), "error": f"{type(e).__name__}", "sizes": sizes, "skipped": skipped}


def main():
    args, model, prompt = [], VISION_MODEL, DEFAULT_PROMPT
    argv = sys.argv[1:]
    i = 0
    while i < len(argv):
        a = argv[i]
        if a in ("--model", "--prompt"):
            if i + 1 >= len(argv):        # 値なし=画像URLとして誤解釈しない(明示エラー)
                print(f"NG: {a} には値が必要です")
                return 1
            if a == "--model":
                model = argv[i + 1]
            else:
                prompt = argv[i + 1]
            i += 2
        else:
            args.append(a); i += 1
    if not args:
        print(__doc__)
        return 1
    res = describe_images(args, prompt=prompt, model=model)
    if res["error"]:
        print(f"NG: {res['error']} ({res['sec']}秒)")
        return 1
    sz = res["sizes"][0]
    print(f"[{res['model']} / {res['n']}枚 / {sz['orig_w']}x{sz['orig_h']}→{sz['w']}x{sz['h']} / {res['sec']}秒]")
    print(res["draft"])
    return 0


if __name__ == "__main__":
    sys.exit(main())
