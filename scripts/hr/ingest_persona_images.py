# -*- coding: utf-8 -*-
"""
ingest_persona_images.py  —  取り込みフォルダの画像を正本(persona_avatars.json)へ取り込む(hrツール・C-019)

なぜ要るか(Chami依頼 2026-08-31 msg 1544081974363291729):
  「わざわざ(Discordの)ここに画像添付しなくてもいいように」。
  人格ハブは静的ページで裏側が無いため、ページで足した画像は手元(localStorage)にしか残らず、
  実体のバイト列を人事部門へ渡すのに Discord添付が要っていた。この道具は Discord添付を要らなくする=
  取り込みフォルダにファイルを置くだけで、人事部門(またはChami)が1コマンドで正本へ反映する。

使い方:
  1. local/persona_inbox/<キャラ名>/ に画像を置く(<キャラ名>= persona_avatars.json のキーと一致させる)。
     例: local/persona_inbox/ヴィルシーナ/new1.png
  2. python scripts/hr/ingest_persona_images.py            # 実行(R2へput→台帳へ追記→ハブ再生成)
     python scripts/hr/ingest_persona_images.py --dry-run  # 何が起きるか見るだけ

やること(1枚ごと):
  - sha256 でキー化 → R2(go5-sync-images)へ put(既存の migrate_avatars_to_r2.put_r2 を流用)。
  - 公開URL(BASE+sha256)を HEAD 200 で着地確認(検証は curl。urllib は 403 になる=既知)。
  - persona_avatars.json[キャラ] の配列末尾へ追記(sha256 が既に在れば冪等スキップ)。追記前に .bak。
  - 取り込んだファイルは local/persona_inbox/_done/<キャラ>/ へ退避(削除しない=退避する)。
  - 変更は persona_changelog.py(面=アイコン)へ1行記録。最後に persona_settings_index.py でハブ再生成。

正本には触るがhrの管轄(人格・アイコン)。R2 blob は content-addressed で追記のみ(消せない)。
"""
import hashlib
import importlib.util
import io
import json
import os
import shutil
import subprocess
import sys

ROOT = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
LOCAL = os.path.join(ROOT, "local")
AVATARS = os.path.join(LOCAL, "persona_avatars.json")
INBOX = os.path.join(LOCAL, "persona_inbox")
DONE = os.path.join(INBOX, "_done")
IMG_EXT = (".png", ".jpg", ".jpeg", ".webp", ".gif")


def _load_migrate():
    """既存の R2 put ロジックを流用する(重複実装しない)。"""
    path = os.path.join(ROOT, "scripts", "discord", "migrate_avatars_to_r2.py")
    spec = importlib.util.spec_from_file_location("migrate_avatars_to_r2", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _head_ok(url):
    """R2の公開URLを HEAD で 200 確認(urllib は 403 になるので curl を使う=既知)。"""
    try:
        r = subprocess.run(
            ["curl", "-sI", "-o", os.devnull, "-w", "%{http_code}", url],
            capture_output=True, text=True, timeout=40,
        )
        return (r.stdout or "").strip() == "200"
    except Exception:
        return False


def _changelog(persona, what, by, dry):
    if dry:
        print(f"  [dry] changelog: [{persona}] アイコン {what}")
        return
    subprocess.run(
        [sys.executable, os.path.join(ROOT, "scripts", "hr", "persona_changelog.py"),
         "add", "--char", persona, "--面", "アイコン", "--what", what, "--by", by],
        cwd=ROOT,
    )


def main():
    dry = "--dry-run" in sys.argv

    if not os.path.isdir(INBOX):
        os.makedirs(INBOX, exist_ok=True)
        print(f"取り込みフォルダを作成: {INBOX}")
        print("→ ここに <キャラ名>/画像 を置いて、もう一度実行してください。")
        return 0

    ledger = json.load(io.open(AVATARS, encoding="utf-8"))
    mig = _load_migrate()
    base = mig.BASE

    # 取り込み対象を集める(<キャラ>/ 直下の画像。_done は除外)。
    jobs = []  # (persona, filepath)
    for persona in sorted(os.listdir(INBOX)):
        pdir = os.path.join(INBOX, persona)
        if persona == "_done" or not os.path.isdir(pdir):
            continue
        for fn in sorted(os.listdir(pdir)):
            fp = os.path.join(pdir, fn)
            if os.path.isfile(fp) and fn.lower().endswith(IMG_EXT):
                jobs.append((persona, fp))

    if not jobs:
        print(f"取り込む画像がありません({INBOX}/<キャラ名>/ に画像を置いてください)。")
        return 0

    added, skipped, failed = 0, 0, 0
    changed = False
    unknown = []

    for persona, fp in jobs:
        fn = os.path.basename(fp)
        if persona not in ledger:
            print(f"  ! 未知のキャラ『{persona}』(persona_avatars.json にキー無し)→ 据え置き: {fn}")
            unknown.append(persona)
            failed += 1
            continue
        blob = open(fp, "rb").read()
        key = hashlib.sha256(blob).hexdigest()
        url = base + key
        arr = ledger[persona] if isinstance(ledger[persona], list) else [ledger[persona]]

        if url in arr:
            print(f"  = 既に台帳に有り(冪等スキップ) {persona}: {fn} (id …{key[-6:]})")
            _retreat(fp, persona, dry)
            skipped += 1
            continue

        if dry:
            print(f"  [dry] {persona}: {fn} {len(blob):,}B → R2 put → 台帳追記 (id …{key[-6:]})")
            added += 1
            continue

        if not mig.put_r2(key, fp, mig.ctype_of(fn)):
            print(f"  x R2put失敗 {persona}: {fn} → 据え置き")
            failed += 1
            continue
        if not _head_ok(url):
            print(f"  x HEAD200不成立 {persona}: {fn} → 台帳へは足さず据え置き(putは実行済)")
            failed += 1
            continue

        arr.append(url)
        ledger[persona] = arr
        changed = True
        added += 1
        print(f"  OK {persona}: {fn} → R2put+HEAD200 → 台帳追記 (id …{key[-6:]})")
        _changelog(persona, f"取り込みフォルダから1枚追加 (id …{key[-6:]})", "ククール(hr)", dry)
        _retreat(fp, persona, dry)

    # 追記後の台帳を書き出す(_write_ledger が書き込み前に現物を .bak する)→ハブ再生成。
    if changed and not dry:
        _write_ledger(ledger)
        _regen_hub()

    print(f"\n取り込み {added} / 冪等スキップ {skipped} / 失敗 {failed}")
    if unknown:
        print("未知キャラ(キー名を persona_avatars.json のキーと一致させてください): "
              + ", ".join(sorted(set(unknown))))
    return 0 if failed == 0 else 1


def _retreat(fp, persona, dry):
    """取り込んだ元ファイルは削除せず _done/<キャラ>/ へ退避する。"""
    if dry:
        print(f"  [dry] 退避 → _done/{persona}/{os.path.basename(fp)}")
        return
    dst_dir = os.path.join(DONE, persona)
    os.makedirs(dst_dir, exist_ok=True)
    dst = os.path.join(dst_dir, os.path.basename(fp))
    if os.path.exists(dst):
        stem, ext = os.path.splitext(os.path.basename(fp))
        dst = os.path.join(dst_dir, f"{stem}_{os.path.getmtime(fp):.0f}{ext}")
    shutil.move(fp, dst)


def _write_ledger(ledger):
    # 書き込み前に必ず現物を .bak(戻せるように)。
    if os.path.exists(AVATARS):
        shutil.copyfile(AVATARS, AVATARS + ".bak")
    io.open(AVATARS, "w", encoding="utf-8").write(
        json.dumps(ledger, ensure_ascii=False, indent=2))


def _regen_hub():
    subprocess.run(
        [sys.executable, os.path.join(ROOT, "scripts", "hr", "persona_settings_index.py")],
        cwd=ROOT,
    )


if __name__ == "__main__":
    sys.exit(main())
