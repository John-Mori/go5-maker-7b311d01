"""アイコン/立ち絵をR2へ上げ、台帳のURLをR2の恒久URLへ差し替える。

なぜ要るか:
  Discord CDNのURLは数日で署名が切れ、アイコンが表示されなくなる(既知の穴)。
  そのたびに refresh_avatars.py で貼り直していた。R2は期限が無く、キーが中身の
  sha256 なので推測もできない。公開repoに画像を置く(=著作物の再配布)より安全。
  → 一度R2へ移せば「アイコンが切れた」は根絶できる(Chami承認 2026-07-16)。

使い方:
  python scripts/discord/migrate_avatars_to_r2.py --dry-run   # 何が起きるか見るだけ
  python scripts/discord/migrate_avatars_to_r2.py             # 実行

やること:
  1. persona_avatars.json の各URLをローカルの原寸ファイル(persona_sprites/)と突き合わせる。
     ローカルに無いものはDiscord CDNから落とす(切れる前に確保する意味も兼ねる)。
  2. sha256 でキー化して R2(go5-sync-images) へ put。
  3. 台帳のURLを https://go5-sync.<subdomain>.workers.dev/img/<sha256> へ差し替える。
  4. 差し替え前の台帳は .bak として残す(戻せるように)。
"""
import argparse
import hashlib
import io
import json
import os
import subprocess
import sys
import urllib.request

ROOT = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
LOCAL = os.path.join(ROOT, "local")
AVATARS = os.path.join(LOCAL, "persona_avatars.json")
SPRITES = os.path.join(LOCAL, "persona_sprites")
BUCKET = "go5-sync-images"
BASE = "https://go5-sync.trustsignalbot.workers.dev/img/"


def fetch(url: str) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": "go5-org (personal)"})
    with urllib.request.urlopen(req, timeout=40) as r:
        return r.read()


def put_r2(key: str, path: str, ctype: str) -> bool:
    r = subprocess.run(
        ["npx", "wrangler", "r2", "object", "put", f"{BUCKET}/{key}",
         "--file", path, "--content-type", ctype, "--remote"],
        capture_output=True, text=True, encoding="utf-8", errors="replace", cwd=ROOT, shell=True,
    )
    return "Upload complete" in ((r.stdout or "") + (r.stderr or ""))


def ctype_of(name: str) -> str:
    n = name.lower()
    if n.endswith(".png"):
        return "image/png"
    if n.endswith(".webp"):
        return "image/webp"
    if n.endswith(".gif"):
        return "image/gif"
    return "image/jpeg"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    d = json.load(io.open(AVATARS, encoding="utf-8"))
    cache = os.path.join(SPRITES, "_r2cache")
    os.makedirs(cache, exist_ok=True)

    done, skip, fail = 0, 0, 0
    out = {}
    for name, val in d.items():
        urls = val if isinstance(val, list) else [val]
        newurls = []
        for u in urls:
            if not isinstance(u, str) or not u.startswith("http"):
                newurls.append(u)
                continue
            if u.startswith(BASE):  # 既にR2
                newurls.append(u)
                skip += 1
                continue
            try:
                blob = fetch(u)
            except Exception as e:
                print(f"  DL失敗 {name}: {str(e)[:60]} → URL据え置き")
                newurls.append(u)
                fail += 1
                continue
            key = hashlib.sha256(blob).hexdigest()
            ext = ".png" if u.lower().find(".png") >= 0 else (".webp" if ".webp" in u.lower() else ".jpg")
            tmp = os.path.join(cache, key + ext)
            if not os.path.exists(tmp):
                open(tmp, "wb").write(blob)
            if args.dry_run:
                print(f"  [dry] {name}: {len(blob):,}B → {BASE}{key[:12]}…")
                newurls.append(BASE + key)
                done += 1
                continue
            if put_r2(key, tmp, ctype_of(ext)):
                print(f"  OK {name}: {len(blob):,}B → R2")
                newurls.append(BASE + key)
                done += 1
            else:
                print(f"  R2失敗 {name} → URL据え置き")
                newurls.append(u)
                fail += 1
        out[name] = newurls if isinstance(val, list) else newurls[0]

    if not args.dry_run:
        io.open(AVATARS + ".bak", "w", encoding="utf-8").write(json.dumps(d, ensure_ascii=False, indent=1))
        io.open(AVATARS, "w", encoding="utf-8").write(json.dumps(out, ensure_ascii=False, indent=1))
    print(f"\n移行 {done} / 既にR2 {skip} / 失敗 {fail}")
    return 0 if fail == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
