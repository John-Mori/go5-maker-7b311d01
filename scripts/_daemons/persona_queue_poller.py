# -*- coding: utf-8 -*-
"""
persona_queue_poller.py — 人格ハブが上げたアイコンを、正本(persona_avatars.json)へ自動で流し込む。

なぜ要るか(2026-09-01 Chami「いる」/ 人事部門ククールからの上申):
  人格ハブのページで画像を1枚選ぶだけでアイコンが増える形にしたい(Discord添付もフォルダ操作もナシ)。
  画像バイトの口は**既に在った**= sync-worker の `PUT /api/img/<sha256>`(X-Sync-Token必須)。
  足りなかったのは「そのkeyが誰のアイコンか」をPCへ伝える道だけで、R2のオブジェクト一覧は
  wrangler に無い(`r2 object` は get/put/delete のみ・実測 2026-09-01)ためポーラーが新着を発見できない。
  → sync-worker へ `POST /api/persona/enqueue` を足し、R2 の固定キー `persona/queue.jsonl` へ
    **追記だけ**する形にした。この道具はそれを wrangler(=アカウント資格)で読む。

  ★SYNC_TOKEN を PC へ置かない(teian と同じ向き)= 書きは Worker・読みは wrangler。

やること(1周):
  1. `persona/queue.jsonl` を R2 から取る(無ければ何もせず終わり=fail-open)。
  2. カーソル(local/persona_queue_cursor.json)より後の行 + 前回積み残し(pending)を対象にする。
  3. 台帳に既に同じURLが在る行は済み扱い。未知の人格名は pending へ残す(捨てない・止めない)。
  4. 残りは R2 から実体を取り、local/persona_inbox/<人格>/<key先頭12>.<拡張子> へ置く。
  5. 既存の `scripts/hr/ingest_persona_images.py` を1回呼ぶ(=sha256→R2 put→HEAD200→台帳追記→
     changelog→ハブ再生成。ここは作り直さない。既に効いている型へ合流する)。
  6. カーソルは**必ず前へ進める**。積み残しは pending に持つので、進めても行は消えない。

使い方: python scripts/_daemons/persona_queue_poller.py [--dry-run] [--verbose]
  戻り値 0=正常(何もしなかった場合も0) / 1=取り込みで失敗が出た。
"""
import io
import json
import os
import shutil
import subprocess
import sys
import time

ROOT = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
LOCAL = os.path.join(ROOT, "local")
AVATARS = os.path.join(LOCAL, "persona_avatars.json")
INBOX = os.path.join(LOCAL, "persona_inbox")
SOURCES = os.path.join(LOCAL, "persona_avatar_sources")
CURSOR = os.path.join(LOCAL, "persona_queue_cursor.json")
LOG = os.path.join(LOCAL, "llm", "persona_queue_poller.jsonl")
BUCKET = "go5-sync-images"
QUEUE_KEY = "persona/queue.jsonl"
BASE = "https://go5-sync.trustsignalbot.workers.dev/img/"
EXT = {"image/png": ".png", "image/jpeg": ".jpg", "image/webp": ".webp", "image/gif": ".gif"}
MAX_PER_RUN = 20  # 1周で扱う上限(暴走時に台帳を一気に膨らませない)


def _log(event, **kw):
    rec = {"ts": time.strftime("%Y-%m-%dT%H:%M:%S"), "event": event}
    rec.update(kw)
    try:
        os.makedirs(os.path.dirname(LOG), exist_ok=True)
        with io.open(LOG, "a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    except Exception:
        pass


def r2_get(key, dest):
    """R2 のオブジェクトを1つ取る。取れたら True。★取れないのは正常でもありうる(fail-open)。"""
    r = subprocess.run(
        ["npx", "wrangler", "r2", "object", "get", "%s/%s" % (BUCKET, key),
         "--file", dest, "--remote"],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
        cwd=ROOT, shell=True, timeout=180,
    )
    return os.path.isfile(dest) and os.path.getsize(dest) > 0


def load_cursor():
    try:
        d = json.load(io.open(CURSOR, encoding="utf-8"))
        return int(d.get("line") or 0), list(d.get("pending") or [])
    except Exception:
        return 0, []


def save_cursor(line, pending, dry):
    if dry:
        return
    if os.path.exists(CURSOR):
        try:
            io.open(CURSOR + ".bak", "w", encoding="utf-8").write(
                io.open(CURSOR, encoding="utf-8").read())
        except Exception:
            pass
    io.open(CURSOR, "w", encoding="utf-8").write(json.dumps(
        {"line": line, "pending": pending, "ts": time.strftime("%Y-%m-%dT%H:%M:%S")},
        ensure_ascii=False, indent=2))


def archive_source(persona, rec, dry):
    """元画像と編集レシピをPC側にも残す。R2が正、ここは再編集・監査用の復旧可能な保管庫。"""
    source_key = str(rec.get("sourceKey") or rec.get("key") or "").strip()
    output_key = str(rec.get("key") or "").strip()
    source_ct = str(rec.get("sourceCt") or rec.get("ct") or "")
    if not source_key:
        return False
    ext = EXT.get(source_ct, ".bin")
    dst_dir = os.path.join(SOURCES, persona)
    source_path = os.path.join(dst_dir, source_key + ext)
    meta_path = os.path.join(dst_dir, output_key + ".json")
    if dry:
        print("  [dry] 元画像保管 %s …%s" % (persona, source_key[-6:]))
        return True
    os.makedirs(dst_dir, exist_ok=True)
    if not os.path.isfile(source_path) and not r2_get(source_key, source_path):
        _log("source_get_failed", persona=persona, key=output_key, sourceKey=source_key)
        return False
    meta = {
        "persona": persona,
        "key": output_key,
        "sourceKey": source_key,
        "sourceCt": source_ct,
        "edit": rec.get("edit"),
        "at": rec.get("at"),
    }
    if os.path.exists(meta_path):
        shutil.copyfile(meta_path, meta_path + ".bak")
    with io.open(meta_path, "w", encoding="utf-8") as f:
        f.write(json.dumps(meta, ensure_ascii=False, indent=2))
    return True


def main():
    dry = "--dry-run" in sys.argv
    verbose = "--verbose" in sys.argv or dry

    tmp = os.path.join(LOCAL, "_work", "persona_queue.jsonl")
    os.makedirs(os.path.dirname(tmp), exist_ok=True)
    if os.path.exists(tmp):
        os.remove(tmp)
    if not r2_get(QUEUE_KEY, tmp):
        if verbose:
            print("申告キューがまだ無い(何もしない)")
        return 0

    lines = [l for l in io.open(tmp, encoding="utf-8").read().split("\n") if l.strip()]
    start, pending = load_cursor()
    fresh = []
    for raw in lines[start:]:
        try:
            fresh.append(json.loads(raw))
        except Exception:
            _log("bad_line", raw=raw[:200])  # 壊れた行は飛ばすが**記録は残す**
    jobs = pending + fresh
    new_line = len(lines)

    if not jobs:
        if verbose:
            print("新しい申告なし(行 %d まで処理済み)" % new_line)
        save_cursor(new_line, [], dry)
        return 0

    ledger = json.load(io.open(AVATARS, encoding="utf-8"))
    still, placed = [], 0

    for rec in jobs[:MAX_PER_RUN]:
        persona = str(rec.get("persona") or "").strip()
        key = str(rec.get("key") or "").strip()
        if not persona or not key:
            _log("bad_record", rec=rec)
            continue
        arr = ledger.get(persona)
        arr = arr if isinstance(arr, list) else ([arr] if arr else [])
        if BASE + key in arr:
            if not archive_source(persona, rec, dry):
                still.append(rec)
                continue
            if verbose:
                print("  = 台帳に既に在る(済み) %s …%s" % (persona, key[-6:]))
            continue
        if persona not in ledger:
            # ★未知の人格は捨てない・止めない= pending に残して次周も試す。
            #   人事部門が persona_avatars.json にキーを足した時点で自然に流れる。
            print("  ! 未知の人格『%s』→ 保留(次周も試す) …%s" % (persona, key[-6:]))
            still.append(rec)
            continue
        dst_dir = os.path.join(INBOX, persona)
        dst = os.path.join(dst_dir, key[:12] + EXT.get(str(rec.get("ct") or ""), ".png"))
        if dry:
            print("  [dry] %s ← R2 …%s → %s" % (persona, key[-6:], dst))
            archive_source(persona, rec, dry=True)
            placed += 1
            continue
        os.makedirs(dst_dir, exist_ok=True)
        if not r2_get(key, dst):
            print("  x R2から実体を取れない …%s → 保留" % key[-6:])
            still.append(rec)
            continue
        if not archive_source(persona, rec, dry=False):
            print("  x 元画像を保管できない …%s → 保留" % str(rec.get("sourceKey") or key)[-6:])
            still.append(rec)
            continue
        placed += 1
        _log("placed", persona=persona, key=key)
        print("  OK %s ← R2 …%s → 投函口へ" % (persona, key[-6:]))

    save_cursor(new_line, still, dry)

    if dry or placed == 0:
        print("\n置いた %d / 保留 %d(取り込みは未実行)" % (placed, len(still)))
        return 0

    # 既存の取り込みへ合流する(ここは作り直さない)。
    r = subprocess.run(
        [sys.executable, os.path.join(ROOT, "scripts", "hr", "ingest_persona_images.py")],
        cwd=ROOT,
    )
    _log("ingest", placed=placed, rc=r.returncode, pending=len(still))
    print("\n置いた %d / 保留 %d / 取り込み rc=%d" % (placed, len(still), r.returncode))
    return 0 if r.returncode == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
