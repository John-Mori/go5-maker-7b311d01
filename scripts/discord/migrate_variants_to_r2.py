"""表情差分の台帳(persona_avatar_variants.json)をR2の恒久URLへ移す。

なぜ別スクリプトか(改善書v1 SPR-2):
  persona_avatars.json は 2026-07-16 にR2へ移行済みだが、**変種台帳だけが両方の機構から漏れていた**。
  refresh_avatars.py(48h前倒し再署名)も migrate_avatars_to_r2.py も対象が persona_avatars.json 固定のため、
  variants の12URLは誰にも面倒を見られず **全て失効済み**(ex=デコードで2026-07-14切れを確認)。
  = アメス/デブライネ/アロンソ/ヴィルシーナの表情差分が現在すべて表示できない。

なぜ既存の migrate_avatars_to_r2.py を使えないか:
  あれは「台帳のURLからDLしてR2へ上げ直す」設計。**URLが既に死んでいるのでDLできない**。
  幸い原本は local/persona_visuals/ にローカル保全されている(Chami提供・2026-07-14)ので、
  **URLではなくローカル原本からR2へ上げる**。Discord APIのrefresh-urlsは不要。

安全性: R2へは新規オブジェクトのputのみ(キー=中身のsha256)。削除・上書きはしない。
        台帳は書き換え前に .bak を残す。

使い方:
  python scripts/discord/migrate_variants_to_r2.py --dry-run   # 対応と差分を見るだけ
  python scripts/discord/migrate_variants_to_r2.py             # 実行
"""
import argparse
import hashlib
import io
import json
import os
import shutil
import subprocess
import sys

ROOT = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
LOCAL = os.path.join(ROOT, "local")
LEDGER = os.path.join(LOCAL, "persona_avatar_variants.json")
VISUALS = os.path.join(LOCAL, "persona_visuals")
BUCKET = "go5-sync-images"
BASE = "https://go5-sync.trustsignalbot.workers.dev/img/"

# (キャラ, ラベル) → local/persona_visuals/ の原本。
# 出典=各persona_manifest.ymlのavatar欄(正本)。例: research-room/persona_manifest.yml の
#   「喜び…はames_happy / 考え中・落ち込み…はames_think / 微笑み…はames_3 / 長考…はames_talklong」
# 全12件で台帳URLの拡張子とローカル原本の拡張子が一致することを確認済み(対応の裏付け)。
SRC = {
    ("ヴィルシーナ", "標準"): "verxina_std.jpg",
    ("ヴィルシーナ", "愛(嬉しい時・愛を届ける時)"): "verxina_love.png",
    ("デブライネ", "標準"): "de-bruyne.webp",
    ("デブライネ", "考え中・検討中"): "de-bruyne_think.jpg",
    ("シャビ・アロンソ", "標準"): "xabi-alonso.webp",
    ("シャビ・アロンソ", "喜び(プロジェクト順調)"): "xabi-alonso_happy.jpg",
    ("シャビ・アロンソ", "怒り・強い指示(不調時)"): "xabi-alonso_angry.webp",
    ("アメス", "標準"): "ames.png",
    ("アメス", "微笑み(ちょっと嬉しい・ほっこり)"): "ames_3.png",
    ("アメス", "長考(話が長い時)"): "ames_talklong.png",
    ("アメス", "喜び(とても嬉しい・好調)"): "ames_happy.png",
    ("アメス", "考え中・落ち込み(思考中・ネガティブ)"): "ames_think.png",
}


def ctype_of(name):
    n = name.lower()
    if n.endswith(".png"):
        return "image/png"
    if n.endswith(".webp"):
        return "image/webp"
    if n.endswith(".gif"):
        return "image/gif"
    return "image/jpeg"


def put_r2(key, path, ctype):
    r = subprocess.run(
        ["npx", "wrangler", "r2", "object", "put", f"{BUCKET}/{key}",
         "--file", path, "--content-type", ctype, "--remote"],
        capture_output=True, text=True, encoding="utf-8", errors="replace", cwd=ROOT, shell=True,
    )
    out = (r.stdout or "") + (r.stderr or "")
    return "Upload complete" in out, out.strip()[-160:]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    led = json.load(io.open(LEDGER, encoding="utf-8"))
    out = {}
    done = skip = fail = 0
    for name, variants in led.items():
        out[name] = {}
        for label, url in variants.items():
            if isinstance(url, str) and url.startswith(BASE):
                out[name][label] = url
                skip += 1
                print(f"  既にR2: {name}/{label}")
                continue
            fn = SRC.get((name, label))
            if not fn:
                out[name][label] = url
                fail += 1
                print(f"  ✗ 原本の対応が未登録: {name}/{label} → URL据え置き(失効のまま)")
                continue
            src = os.path.join(VISUALS, fn)
            if not os.path.exists(src):
                out[name][label] = url
                fail += 1
                print(f"  ✗ 原本が無い: {name}/{label} → {fn}")
                continue
            blob = open(src, "rb").read()
            key = hashlib.sha256(blob).hexdigest()
            if args.dry_run:
                out[name][label] = BASE + key
                done += 1
                print(f"  [dry] {name}/{label}: {fn} {len(blob):,}B → {BASE}{key[:12]}…")
                continue
            okd, msg = put_r2(key, src, ctype_of(fn))
            if okd:
                out[name][label] = BASE + key
                done += 1
                print(f"  OK {name}/{label}: {fn} {len(blob):,}B → R2")
            else:
                out[name][label] = url
                fail += 1
                print(f"  ✗ R2失敗 {name}/{label}: {msg}")

    if not args.dry_run and done:
        shutil.copyfile(LEDGER, LEDGER + ".bak")
        io.open(LEDGER, "w", encoding="utf-8").write(json.dumps(out, ensure_ascii=False, indent=1))
        print(f"\n台帳を更新(戻す時は {os.path.basename(LEDGER)}.bak)")
    print(f"\n移行 {done} / 既にR2 {skip} / 失敗 {fail}")
    return 0 if fail == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
