#!/usr/bin/env python3
"""ローカル画像生成ブリッジ (B route・ComfyUI API)。

既存のComfyUI(AIArtCreater配下・WAI-Illustrious SDXL v17)へ
プロンプトを送り、生成画像を保存して、必要ならDiscordへキャラ名義で貼る。

使い方:
  python scripts/imagegen/generate.py "1girl, smile, ..." [--neg "..."] [--out 出力パス]
  python scripts/imagegen/generate.py "..." --discord "画像生成ルーム" --persona "アメス" --caption "できたわよ"
前提: ComfyUIが起動中(start_comfyui.bat・ポート8188)。
"""
import json
import os
import sys
import time
import urllib.request
import uuid

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.normpath(os.path.join(HERE, "..", ".."))
API = "http://127.0.0.1:8188"
CKPT = "waiIllustriousSDXL_v170.safetensors"
NEG_DEFAULT = "lowres, bad anatomy, bad hands, text, error, missing fingers, extra digit, fewer digits, cropped, worst quality, low quality, jpeg artifacts, signature, watermark, username, blurry"


def workflow(pos, neg, w=832, h=1216, steps=26, cfg=6.0, seed=None):
    seed = seed if seed is not None else int.from_bytes(os.urandom(4), "big")
    return {
        "1": {"class_type": "CheckpointLoaderSimple", "inputs": {"ckpt_name": CKPT}},
        "2": {"class_type": "CLIPTextEncode", "inputs": {"clip": ["1", 1], "text": pos}},
        "3": {"class_type": "CLIPTextEncode", "inputs": {"clip": ["1", 1], "text": neg}},
        "4": {"class_type": "EmptyLatentImage", "inputs": {"width": w, "height": h, "batch_size": 1}},
        "5": {"class_type": "KSampler", "inputs": {
            "model": ["1", 0], "positive": ["2", 0], "negative": ["3", 0], "latent_image": ["4", 0],
            "seed": seed, "steps": steps, "cfg": cfg, "sampler_name": "euler_ancestral",
            "scheduler": "normal", "denoise": 1.0}},
        "6": {"class_type": "VAEDecode", "inputs": {"samples": ["5", 0], "vae": ["1", 2]}},
        "7": {"class_type": "SaveImage", "inputs": {"images": ["6", 0], "filename_prefix": "go5org"}},
    }


def api(path, payload=None):
    req = urllib.request.Request(API + path,
                                 data=json.dumps(payload).encode("utf-8") if payload is not None else None,
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read())


def generate(pos, neg=NEG_DEFAULT, out=None, timeout=600):
    cid = str(uuid.uuid4())
    res = api("/prompt", {"prompt": workflow(pos, neg), "client_id": cid})
    pid = res["prompt_id"]
    print(f"生成開始 prompt_id={pid[:8]}…")
    t0 = time.time()
    while time.time() - t0 < timeout:
        time.sleep(3)
        try:
            hist = api(f"/history/{pid}")
        except Exception:
            continue
        if pid in hist and hist[pid].get("outputs"):
            for node in hist[pid]["outputs"].values():
                for img in node.get("images", []):
                    q = urllib.parse.urlencode({"filename": img["filename"],
                                                "subfolder": img.get("subfolder", ""), "type": img.get("type", "output")})
                    with urllib.request.urlopen(f"{API}/view?{q}", timeout=60) as r:
                        data = r.read()
                    out = out or os.path.join(ROOT, "local", "imagegen", f"{img['filename']}")
                    os.makedirs(os.path.dirname(out), exist_ok=True)
                    with open(out, "wb") as f:
                        f.write(data)
                    print(f"生成完了({time.time()-t0:.0f}秒): {out}")
                    return out
    raise TimeoutError("生成がタイムアウト")


import urllib.parse


def discord_upload(image_path, channel, persona, caption=""):
    """Webhookにmultipartで画像を添付投稿(キャラ名義)。"""
    sys.path.insert(0, os.path.join(ROOT, "scripts", "discord"))
    from persona_send import ensure_webhook  # noqa
    token = open(os.path.join(ROOT, "local", "discord_bot_token.txt"), encoding="utf-8").read().strip()
    chans = json.load(open(os.path.join(ROOT, "local", "discord_channels.json"), encoding="utf-8"))
    ch = next(c for c in chans if c.get("name") == channel)
    hook = ensure_webhook(str(ch["id"]), token)
    avatar = None
    try:
        av = json.load(open(os.path.join(ROOT, "local", "persona_avatars.json"), encoding="utf-8")).get(persona)
        avatar = av[0] if isinstance(av, list) else av
    except Exception:
        pass
    boundary = uuid.uuid4().hex
    payload = {"username": persona, "content": caption[:1900]}
    if avatar:
        payload["avatar_url"] = avatar
    fname = os.path.basename(image_path)
    body = (f"--{boundary}\r\nContent-Disposition: form-data; name=\"payload_json\"\r\n"
            f"Content-Type: application/json\r\n\r\n{json.dumps(payload, ensure_ascii=False)}\r\n"
            f"--{boundary}\r\nContent-Disposition: form-data; name=\"files[0]\"; filename=\"{fname}\"\r\n"
            f"Content-Type: image/png\r\n\r\n").encode("utf-8") + open(image_path, "rb").read() + f"\r\n--{boundary}--\r\n".encode()
    req = urllib.request.Request(hook, data=body,
                                 headers={"Content-Type": f"multipart/form-data; boundary={boundary}",
                                          "User-Agent": "go5-imagegen"})
    with urllib.request.urlopen(req, timeout=60) as r:
        print(f"Discord投稿OK ({r.status}) → {channel} as {persona}")


def main():
    args = sys.argv[1:]
    neg, out, channel, persona, caption = NEG_DEFAULT, None, None, None, ""
    rest = []
    i = 0
    while i < len(args):
        a = args[i]
        if a == "--neg":
            neg = args[i + 1]; i += 2
        elif a == "--out":
            out = args[i + 1]; i += 2
        elif a == "--discord":
            channel = args[i + 1]; i += 2
        elif a == "--persona":
            persona = args[i + 1]; i += 2
        elif a == "--caption":
            caption = args[i + 1]; i += 2
        else:
            rest.append(a); i += 1
    if not rest:
        print("プロンプトを指定してください")
        sys.exit(1)
    path = generate(" ".join(rest), neg, out)
    if channel and persona:
        discord_upload(path, channel, persona, caption)


if __name__ == "__main__":
    main()
