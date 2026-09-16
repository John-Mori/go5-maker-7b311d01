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

#: 1回の注文で描く枚数。★2026-09-16 Chami直令 msg 1549785270683967662=
#  「画像生成する際は4枚生成するようにしてよ。」= 1回で複数案を並べて選ぶため。
#  ★★実測してから入れた(C-058=デスクトップの取り分を潰さない)。2026-09-16 23:2x・
#    RTX 5070 Ti(16,303MiB)・Illustrious-XL-v2.0・832x1216・steps 26 で
#    **4枚・27.1秒・VRAMピーク 14,118MiB**(残り約2.2GB)。1枚のときのピークと秒数は
#    同じ計測器 local/_work/measure_batch4.py で並べて測ってある。
#  ★ここは**画像生成する全室に効く**(素モデル室 imagegen / LoRA室 fusoh_v0・fusoh_v2・
#    itsumono は全部この1本を subprocess で呼ぶ)= 部屋ごとに書かない(二重管理を作らない)。
#  ★環境変数 IMAGEGEN_BATCH で上書きできる= VRAMの細い機械へ移った時に
#    コードを書き換えずに落とせるようにしてある。
BATCH_DEFAULT = int(os.environ.get("IMAGEGEN_BATCH") or 4)
NEG_DEFAULT = "lowres, bad anatomy, bad hands, text, error, missing fingers, extra digit, fewer digits, cropped, worst quality, low quality, jpeg artifacts, signature, watermark, username, blurry"


def workflow(pos, neg, w=832, h=1216, steps=26, cfg=6.0, seed=None,
             lora=None, lora_strength=0.8, batch=1):
    """ComfyUIのAPIグラフを組む。

    ★2026-09-14 研究室HQ: `lora` を足した(Chami直令 msg 1548842898773123105=
      「それぞれのLoRAで画像生成するためのルーム」)。**LoRA別の部屋は、この口が無いと成立しない。**
      lora=None の時のグラフは**以前と1ノードも変わらない**(既存の画像生成ルーム・
      local_chain.py の呼び出しは1文字も挙動が変わらない)。
    ★2026-09-16 ローカル研究室(カスミ): `batch` を足した(Chami直令 msg 1549786299408457892=
      「画像生成する際は4枚生成するように」)。EmptyLatentImage の batch_size に流す=
      1回のワークフローで batch 枚を同時に描く。batch=1 の既定はグラフを従来と変えない。
    """
    seed = seed if seed is not None else int.from_bytes(os.urandom(4), "big")
    g = {
        "1": {"class_type": "CheckpointLoaderSimple", "inputs": {"ckpt_name": CKPT}},
        "2": {"class_type": "CLIPTextEncode", "inputs": {"clip": ["1", 1], "text": pos}},
        "3": {"class_type": "CLIPTextEncode", "inputs": {"clip": ["1", 1], "text": neg}},
        "4": {"class_type": "EmptyLatentImage", "inputs": {"width": w, "height": h, "batch_size": batch}},
        "5": {"class_type": "KSampler", "inputs": {
            "model": ["1", 0], "positive": ["2", 0], "negative": ["3", 0], "latent_image": ["4", 0],
            "seed": seed, "steps": steps, "cfg": cfg, "sampler_name": "euler_ancestral",
            "scheduler": "normal", "denoise": 1.0}},
        "6": {"class_type": "VAEDecode", "inputs": {"samples": ["5", 0], "vae": ["1", 2]}},
        "7": {"class_type": "SaveImage", "inputs": {"images": ["6", 0], "filename_prefix": "go5org"}},
    }
    if lora:
        # LoraLoader は model と clip の両方を差し替える。★clip 側を繋ぎ忘れると
        # 「LoRAを読んだのに効き目が薄い」という分かりにくい壊れ方になる。
        g["8"] = {"class_type": "LoraLoader", "inputs": {
            "model": ["1", 0], "clip": ["1", 1], "lora_name": lora,
            "strength_model": lora_strength, "strength_clip": lora_strength}}
        g["2"]["inputs"]["clip"] = ["8", 1]
        g["3"]["inputs"]["clip"] = ["8", 1]
        g["5"]["inputs"]["model"] = ["8", 0]
    return g


def api(path, payload=None):
    req = urllib.request.Request(API + path,
                                 data=json.dumps(payload).encode("utf-8") if payload is not None else None,
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read())


def generate(pos, neg=NEG_DEFAULT, out=None, timeout=600, lora=None, lora_strength=0.8, batch=4):
    """描いた画像の保存先パスを**リストで**返す(batch>1 の時は複数枚)。

    ★2026-09-16(カスミ): 戻り値を単一パス→リストへ変えた= Chami直令の4枚化に伴う。
      本番の呼び出しは local_chain.py が subprocess で main() を叩く経路(戻り値は使わない)、
      直接 import して generate() の戻り値を使う口は無いことを確認済み(grep)。
    """
    cid = str(uuid.uuid4())
    res = api("/prompt", {"prompt": workflow(pos, neg, lora=lora, lora_strength=lora_strength, batch=batch),
                          "client_id": cid})
    pid = res["prompt_id"]
    print(f"生成開始 prompt_id={pid[:8]}…(batch={batch})")
    t0 = time.time()
    while time.time() - t0 < timeout:
        time.sleep(3)
        try:
            hist = api(f"/history/{pid}")
        except Exception:
            continue
        if pid in hist and hist[pid].get("outputs"):
            saved = []
            for node in hist[pid]["outputs"].values():
                for img in node.get("images", []):
                    q = urllib.parse.urlencode({"filename": img["filename"],
                                                "subfolder": img.get("subfolder", ""), "type": img.get("type", "output")})
                    with urllib.request.urlopen(f"{API}/view?{q}", timeout=60) as r:
                        data = r.read()
                    # ★batch>1 の時に out を使い回すと4枚が同じパスへ上書きされる=
                    #   1枚目は out(指定時)、2枚目以降は連番、無指定は ComfyUI 側のファイル名で保存。
                    if out and not saved:
                        dest = out
                    elif out:
                        base, ext = os.path.splitext(out)
                        dest = f"{base}_{len(saved) + 1}{ext}"
                    else:
                        dest = os.path.join(ROOT, "local", "imagegen", f"{img['filename']}")
                    os.makedirs(os.path.dirname(dest), exist_ok=True)
                    with open(dest, "wb") as f:
                        f.write(data)
                    saved.append(dest)
            if saved:
                global LAST_DRAW_SEC
                LAST_DRAW_SEC = time.time() - t0
                print(f"生成完了({LAST_DRAW_SEC:.0f}秒・{len(saved)}枚): {', '.join(saved)}")
                return saved
    raise TimeoutError("生成がタイムアウト")


import urllib.parse


# ★2026-09-16 イージス研究室: 描画にかかった秒数を残す(Chami原文=「かかった時間も
#   教えてもらえるようにして」msg 1549777099580121232・回送 DISPATCH-aegis-gl-1789566427422)。
#   ★2026-09-16 カスミ: 4枚化に伴い generate() の戻り値は単一パス→リストへ変えた
#   (import して戻り値を使う口は無いことを grep で確認済み・本番は subprocess 経路)。
LAST_DRAW_SEC = None


def elapsed_note(draw_sec, tag_sec=None):
    """投稿本文へ添える所要時間の1行を作る(空文字なら何も足さない)。

    ★測れていない段は書かない(推測で埋めない)= tag_sec が無ければ内訳を出さない。
    ★素のunicode絵文字を置かない(共通規律§5の表記)。
    """
    if draw_sec is None:
        return ""
    if tag_sec:
        return "所要 %.0f秒(タグ変換 %.0f秒 / 描画 %.0f秒)" % (tag_sec + draw_sec, tag_sec, draw_sec)
    return "所要 %.0f秒(描画)" % draw_sec


def discord_upload(image_path, channel, persona, caption="", note="", extra_images=None):
    """Webhookにmultipartで画像を添付投稿(キャラ名義)。

    ★2026-09-16(カスミ): extra_images を足した= 4枚化に伴い、1投稿へ files[0..N] を並べる
      (投稿を4本に散らさず1本にまとめる)。extra_images=None の従来呼びは1枚のまま。
    """
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
    # ★炎上表記ゲート(正本= scripts/discord/enjoh.py)。ここも画像便のキャプションがDiscordへ出る口
    #   = 合流点の1つ。片方だけに置いた実装は必ず割れる(REQ-kaizen-analyst-90ebe8bfc8)。
    try:
        from enjoh import enjoh_backstop            # sys.path は上の insert 済み
        caption = enjoh_backstop(caption, tag="imagegen")
    except Exception:
        pass                                        # fail-open= 投稿は殺さない
    # ★所要時間はゲートを通したキャプションの**後ろ**へ足す。1900字で切るのはキャプション側
    #   だけにする= 長い依頼文の時に時間表示だけが消えると「載っていない」と読まれる。
    if note:
        head = caption[:1900 - len(note) - 1]
        content = (head + "\n" + note) if head else note
    else:
        content = caption[:1900]
    payload = {"username": persona, "content": content}
    if avatar:
        payload["avatar_url"] = avatar
    parts = [(f"--{boundary}\r\nContent-Disposition: form-data; name=\"payload_json\"\r\n"
              f"Content-Type: application/json\r\n\r\n{json.dumps(payload, ensure_ascii=False)}\r\n").encode("utf-8")]
    for idx, ip in enumerate([image_path] + list(extra_images or [])):
        fname = os.path.basename(ip)
        parts.append((f"--{boundary}\r\nContent-Disposition: form-data; name=\"files[{idx}]\"; "
                      f"filename=\"{fname}\"\r\nContent-Type: image/png\r\n\r\n").encode("utf-8"))
        parts.append(open(ip, "rb").read())
        parts.append(b"\r\n")
    parts.append(f"--{boundary}--\r\n".encode())
    body = b"".join(parts)
    req = urllib.request.Request(hook, data=body,
                                 headers={"Content-Type": f"multipart/form-data; boundary={boundary}",
                                          "User-Agent": "go5-imagegen"})
    with urllib.request.urlopen(req, timeout=60) as r:
        print(f"Discord投稿OK ({r.status}) → {channel} as {persona}")


def main():
    args = sys.argv[1:]
    neg, out, channel, persona, caption, ckpt = NEG_DEFAULT, None, None, None, "", None
    lora, lora_strength = None, 0.8
    tag_sec = None
    batch = 4  # ★Chami直令(msg 1549786299408457892)= 画像生成は既定で4枚。--batch で上書き可。
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
        elif a == "--ckpt":
            ckpt = args[i + 1]; i += 2
        elif a == "--lora":
            lora = args[i + 1]; i += 2
        elif a == "--lora-strength":
            lora_strength = float(args[i + 1]); i += 2
        elif a == "--tag-seconds":
            # 日本語→英語タグ変換にかかった秒数(local_chain.py が測って渡す)。
            # 付けない従来の呼び方は内訳が出ないだけで、描画の秒数は出る。
            tag_sec = float(args[i + 1]); i += 2
        elif a == "--batch":
            batch = int(args[i + 1]); i += 2
        else:
            rest.append(a); i += 1
    if not rest:
        print("プロンプトを指定してください")
        sys.exit(1)
    global CKPT
    if ckpt:
        CKPT = ckpt
    paths = generate(" ".join(rest), neg, out, lora=lora, lora_strength=lora_strength, batch=batch)
    if channel and persona:
        discord_upload(paths[0], channel, persona, caption,
                       note=elapsed_note(LAST_DRAW_SEC, tag_sec), extra_images=paths[1:])


if __name__ == "__main__":
    main()
