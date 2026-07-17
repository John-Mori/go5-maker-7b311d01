#!/usr/bin/env python3
"""画像前処理 (VLMへ渡す前の正規化・T-1 / 改善設計書_ローカルLLM画像認識強化_2026-07-17 §4.1)。

役割:
  Discord添付URL(またはローカルパス)→ ダウンロード → RGB化 → 長辺リサイズ → base64(PNG/JPEG)。
  Ollamaは Qwen系の min_pixels/max_pixels を露出しないため、**送る前に画像自体を縮める**のが
  等価の解像度制御になる(改善設計書§2.4)。高解像度をそのまま投げるとOllamaでは
  劣化/クラッシュの報告があるため、既定で長辺1280pxへ丸める。

使い方(CLI・単体検証用):
  python scripts/llm/image_prep.py <URL または パス>        # 情報だけ表示
  python scripts/llm/image_prep.py <URL> --out tmp.png      # 正規化後の画像を保存して目視確認

  from image_prep import prepare_image, is_image_url
  b64, meta = prepare_image(url)   # b64: Ollamaのmessages[].images に入れる文字列

方針(改善設計書 §5 やらないこと と整合):
  - 機微部門の画像はそもそも呼ばない(呼び出し側=local_responder のSENSITIVE_DEPTS判定が先)。
  - 画像は保存しない(メモリ内で完結)。--out は人が検証する時だけの明示オプション。
"""
import base64
import io
import os
import sys
import urllib.request

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)
except Exception:
    pass

IMAGE_EXT = (".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp", ".heic", ".heif", ".jfif")
MAX_EDGE = 1280          # 長辺の上限px(§2.4: Ollama運用でのmin/max_pixels代替)
MAX_BYTES = 20 * 1024 * 1024   # DL上限20MB(Discord添付の実質上限を超える分は捨てる)
MAX_PIXELS = 40_000_000  # 画素数の上限(解凍爆弾対策)。バイト数だけでは守れない=
                         # 高圧縮PNGは数百KBでも数億画素に展開しRAMを食い潰す(常駐が死ぬ)
DL_TIMEOUT = 30          # DL上限(実測: 画像1枚のDLは1秒未満。30秒×2枚でも30秒ループが吸収できる)


def is_image_url(url):
    """添付URLが画像か(クエリ文字列付きのDiscord CDN URLにも対応)。"""
    if not url:
        return False
    path = str(url).split("?", 1)[0].lower()
    return path.endswith(IMAGE_EXT)


def _fetch(url):
    """URLならDL、ローカルパスならread。戻り値=bytes。"""
    if os.path.exists(url):
        with open(url, "rb") as f:
            return f.read(MAX_BYTES + 1)
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (go5-image-prep)"})
    with urllib.request.urlopen(req, timeout=DL_TIMEOUT) as r:
        return r.read(MAX_BYTES + 1)


def prepare_image(url, max_edge=MAX_EDGE):
    """画像を正規化して (base64文字列, メタ情報dict) を返す。

    失敗は例外を投げず (None, {"error": ...}) を返す=呼び出し側(常駐)を絶対に落とさない。
    メタ情報: {"w","h","orig_w","orig_h","fmt","bytes"}
    """
    # ★importもtryの内側に置く(2026-07-17レビュー指摘・実測で確認)。
    #   遅延importをtryの外に書くと、Pillowが欠けた日にImportErrorがこの関数を貫通し、
    #   「例外を投げない」という上位(ask_vision/local_responder)との契約を破る=常駐が黙る。
    try:
        from PIL import Image, ImageOps
    except Exception as e:
        return None, {"error": f"pillow_missing:{type(e).__name__}"}

    try:
        raw = _fetch(url)
    except Exception as e:
        return None, {"error": f"download_failed:{type(e).__name__}"}
    if len(raw) > MAX_BYTES:
        return None, {"error": "too_large"}

    try:
        im = Image.open(io.BytesIO(raw))
        if (im.size[0] * im.size[1]) > MAX_PIXELS:   # ★load()の前に弾く(展開させない)
            return None, {"error": "too_many_pixels"}
        im.load()                      # 遅延読み込みをここで確定させる(壊れた画像はここで落ちる)
        # ★EXIF Orientationを適用してから縮小する。スマホ写真は「横向きで保存+回転指示」が
        #   普通で、これを捨てるとVLMには寝た画像が渡る(文字が90度倒れて読めない)。
        #   exif_transposeはEXIFが無い画像ではそのまま返る=無害。
        im = ImageOps.exif_transpose(im) or im
        orig_w, orig_h = im.size
        # アニメGIF/WebPは1フレーム目のみ。透過は白背景に合成(VLMは透過を黒と誤読しがち)
        if im.mode in ("RGBA", "LA", "P"):
            im = im.convert("RGBA")
            bg = Image.new("RGB", im.size, (255, 255, 255))
            bg.paste(im, mask=im.split()[-1])
            im = bg
        else:
            im = im.convert("RGB")
        long_edge = max(im.size)
        if long_edge > max_edge:       # 拡大はしない(縮小のみ=情報を増やさない)
            scale = max_edge / float(long_edge)
            im = im.resize((max(1, int(im.width * scale)), max(1, int(im.height * scale))),
                           Image.LANCZOS)
        buf = io.BytesIO()
        im.save(buf, format="PNG", optimize=True)   # PNG=文字の輪郭を潰さない(OCR用途)
        data = buf.getvalue()
        return base64.b64encode(data).decode("ascii"), {
            "w": im.width, "h": im.height, "orig_w": orig_w, "orig_h": orig_h,
            "fmt": "PNG", "bytes": len(data),
        }
    except Exception as e:
        return None, {"error": f"decode_failed:{type(e).__name__}"}


def images_of(rec, limit=2):
    """受信レコードの attachments から画像URLだけを最大limit件返す。

    limit=2 の根拠: 8GB VRAMでは画像1枚ごとに視覚トークンとKVが積み上がるため
    (改善設計書§2.4 few-shot項)。llmcord(参照実装)の既定5枚は12GB+級の想定。
    """
    return [a for a in (rec.get("attachments") or []) if is_image_url(a)][:limit]


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    if not args:
        print(__doc__)
        return 1
    url = args[0]
    b64, meta = prepare_image(url)
    if not b64:
        print(f"NG: {meta.get('error')}")
        return 1
    print(f"OK: {meta['orig_w']}x{meta['orig_h']} → {meta['w']}x{meta['h']} "
          f"{meta['fmt']} {meta['bytes']}bytes base64={len(b64)}文字")
    if "--out" in sys.argv:
        out = sys.argv[sys.argv.index("--out") + 1]
        with open(out, "wb") as f:
            f.write(base64.b64decode(b64))
        print(f"保存: {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
