#!/usr/bin/env python3
"""ローカル img2img / 高画質化ブリッジ (ComfyUI API)。

generate.py は txt2img 専用で、手元の絵を「作り直す・大きくする・背景を描き足す」ことができない。
このファイルはその穴を埋める。2パス(hires fix)構成:

  LoadImage → ImageScale(基準辺へ) → VAEEncode → KSampler(denoise=d1)
            → LatentUpscale(×scale) → KSampler(denoise=d2) → VAEDecode → SaveImage

使い方:
  python scripts/imagegen/img2img.py --ref 入力.png --out 出力.png "positive prompt" \
      [--neg "..."] [--base 1024] [--scale 1.5] [--denoise 0.5] [--denoise2 0.35] \
      [--ckpt novaAnimeXL_ilV140.safetensors] [--steps 34] [--cfg 5.5] [--seed 12345]

前提: ComfyUI が起動中(ポート8188)。
  起動= D:\\総合スタートファイル\\AIArtCreater\\ComfyUI\\venv\\Scripts\\python.exe main.py
"""
import argparse
import json
import os
import sys
import time
import urllib.parse
import urllib.request
import uuid

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.normpath(os.path.join(HERE, "..", ".."))
API = "http://127.0.0.1:8188"
CKPT_DEFAULT = "novaAnimeXL_ilV140.safetensors"
NEG_DEFAULT = ("lowres, bad anatomy, bad hands, text, error, missing fingers, extra digit, "
               "fewer digits, cropped, worst quality, low quality, jpeg artifacts, "
               "signature, watermark, username, blurry")


def fit(w, h, base, mult=64):
    """長辺を base に合わせ、縦横とも mult の倍数へ丸める(SDXLのlatentは8/64刻みが安全)。"""
    r = base / float(max(w, h))
    nw = max(mult, int(round(w * r / mult)) * mult)
    nh = max(mult, int(round(h * r / mult)) * mult)
    return nw, nh


def upload(path):
    with open(path, "rb") as f:
        data = f.read()
    b = "----go5img2img" + uuid.uuid4().hex[:8]
    body = (f"--{b}\r\nContent-Disposition: form-data; name=\"image\"; filename=\"{os.path.basename(path)}\"\r\n"
            "Content-Type: image/png\r\n\r\n").encode() + data + f"\r\n--{b}--\r\n".encode()
    req = urllib.request.Request(f"{API}/upload/image", data=body,
                                 headers={"Content-Type": f"multipart/form-data; boundary={b}"})
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.loads(r.read())["name"]


def workflow(refname, pos, neg, w, h, scale, ckpt, steps, cfg, seed, d1, d2):
    w2, h2 = int(w * scale) // 8 * 8, int(h * scale) // 8 * 8
    return {
        "1": {"class_type": "CheckpointLoaderSimple", "inputs": {"ckpt_name": ckpt}},
        "2": {"class_type": "CLIPTextEncode", "inputs": {"clip": ["1", 1], "text": pos}},
        "3": {"class_type": "CLIPTextEncode", "inputs": {"clip": ["1", 1], "text": neg}},
        "8": {"class_type": "LoadImage", "inputs": {"image": refname, "upload": "image"}},
        "9": {"class_type": "ImageScale", "inputs": {"image": ["8", 0], "width": w, "height": h,
                                                    "upscale_method": "lanczos", "crop": "disabled"}},
        "10": {"class_type": "VAEEncode", "inputs": {"pixels": ["9", 0], "vae": ["1", 2]}},
        "11": {"class_type": "KSampler", "inputs": {
            "model": ["1", 0], "positive": ["2", 0], "negative": ["3", 0], "latent_image": ["10", 0],
            "seed": seed, "steps": steps, "cfg": cfg, "sampler_name": "euler_ancestral",
            "scheduler": "normal", "denoise": d1}},
        "12": {"class_type": "LatentUpscale", "inputs": {"samples": ["11", 0], "width": w2, "height": h2,
                                                        "upscale_method": "bislerp", "crop": "disabled"}},
        "13": {"class_type": "KSampler", "inputs": {
            "model": ["1", 0], "positive": ["2", 0], "negative": ["3", 0], "latent_image": ["12", 0],
            "seed": seed + 1, "steps": steps, "cfg": cfg, "sampler_name": "euler_ancestral",
            "scheduler": "normal", "denoise": d2}},
        "6": {"class_type": "VAEDecode", "inputs": {"samples": ["13", 0], "vae": ["1", 2]}},
        "7": {"class_type": "SaveImage", "inputs": {"images": ["6", 0], "filename_prefix": "go5i2i"}},
    }


def run(wf, out, timeout=900):
    cid = str(uuid.uuid4())
    req = urllib.request.Request(f"{API}/prompt",
                                 data=json.dumps({"prompt": wf, "client_id": cid}).encode("utf-8"),
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=60) as r:
        pid = json.loads(r.read())["prompt_id"]
    print(f"生成開始 prompt_id={pid[:8]}…", flush=True)
    t0 = time.time()
    while time.time() - t0 < timeout:
        time.sleep(4)
        try:
            with urllib.request.urlopen(f"{API}/history/{pid}", timeout=30) as r:
                hist = json.loads(r.read())
        except Exception:
            continue
        if pid not in hist:
            continue
        st = hist[pid].get("status", {})
        if st.get("status_str") == "error":
            raise RuntimeError(json.dumps(st, ensure_ascii=False)[:2000])
        if not st.get("completed"):
            continue
        for node in hist[pid]["outputs"].values():
            for img in node.get("images", []):
                q = urllib.parse.urlencode({"filename": img["filename"],
                                            "subfolder": img.get("subfolder", ""),
                                            "type": img.get("type", "output")})
                with urllib.request.urlopen(f"{API}/view?{q}", timeout=120) as r:
                    data = r.read()
                os.makedirs(os.path.dirname(os.path.abspath(out)), exist_ok=True)
                with open(out, "wb") as f:
                    f.write(data)
                print(f"生成完了({time.time()-t0:.0f}秒): {out}", flush=True)
                return out
    raise TimeoutError("生成がタイムアウト")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("prompt", nargs="+")
    ap.add_argument("--ref", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--neg", default=NEG_DEFAULT)
    ap.add_argument("--base", type=int, default=1024)
    ap.add_argument("--scale", type=float, default=1.5)
    ap.add_argument("--denoise", type=float, default=0.50)
    ap.add_argument("--denoise2", type=float, default=0.35)
    ap.add_argument("--ckpt", default=CKPT_DEFAULT)
    ap.add_argument("--steps", type=int, default=34)
    ap.add_argument("--cfg", type=float, default=5.5)
    ap.add_argument("--seed", type=int, default=None)
    a = ap.parse_args()

    if not os.path.exists(a.ref):
        sys.exit(f"入力が無い: {a.ref}")
    try:
        from PIL import Image
        with Image.open(a.ref) as im:
            sw, sh = im.size
    except Exception:
        sw = sh = a.base
    w, h = fit(sw, sh, a.base)
    seed = a.seed if a.seed is not None else int.from_bytes(os.urandom(4), "big")
    print(f"入力 {sw}x{sh} → 1パス {w}x{h} → 2パス {int(w*a.scale)//8*8}x{int(h*a.scale)//8*8} / seed={seed}")
    refname = upload(a.ref)
    wf = workflow(refname, " ".join(a.prompt), a.neg, w, h, a.scale,
                  a.ckpt, a.steps, a.cfg, seed, a.denoise, a.denoise2)
    run(wf, a.out)


if __name__ == "__main__":
    main()
