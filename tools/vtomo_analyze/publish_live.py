#!/usr/bin/env python3
"""自社動画の再生数・高評価を取り直し、公開Pagesの own_live.json を更新する(定期実行用)。

1回の実行: fetch_own_videos(約3 quota単位) → build_data → 公開用worktreeへコピー → 変化があればcommit+push。
登録ch側の data.js は、元ログ(sources)が変わった時だけ一緒に載せる。
"""
from __future__ import annotations

import datetime as dt
import json
import os
import shutil
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(HERE, "data")
PUB_DIR = os.environ.get("VTOMO_PUB_DIR") or r"D:\SougouStartFolder\_vtomo_pub"
PUB_DATA = os.path.join(PUB_DIR, "tools", "vtomo_analyze", "data")
LOG_PATH = os.path.join(DATA_DIR, "publish_live.log")
LOCK_PATH = os.path.join(DATA_DIR, "publish_live.lock")
JST = dt.timezone(dt.timedelta(hours=9))


def log(message: str) -> None:
    os.makedirs(DATA_DIR, exist_ok=True)
    stamp = dt.datetime.now(JST).strftime("%Y-%m-%d %H:%M:%S")
    with open(LOG_PATH, "a", encoding="utf-8") as handle:
        handle.write(f"{stamp} {message}\n")


def run(args: list[str], cwd: str) -> subprocess.CompletedProcess:
    return subprocess.run(args, cwd=cwd, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=300)


def git(*args: str) -> subprocess.CompletedProcess:
    return run(["git", *args], PUB_DIR)


def _read_json(path: str):
    try:
        with open(path, encoding="utf-8") as handle:
            return json.load(handle)
    except (OSError, ValueError):
        return None


def _data_js_sources(path: str):
    try:
        with open(path, encoding="utf-8") as handle:
            text = handle.read()
        payload = json.loads(text[text.index("=") + 1 : text.rindex(";")])
        sources = payload.get("sources") or {}
        return sources.get("subscription_snapshot"), sources.get("subscription_video_log")
    except (OSError, ValueError):
        return None


def _own_signature(live) -> str:
    videos = ((live or {}).get("own") or {}).get("videos") or []
    return json.dumps(
        [[v.get("video_id"), v.get("views"), v.get("likes"), v.get("comments"), v.get("checkpoints")] for v in videos],
        ensure_ascii=False,
        sort_keys=True,
    )


def publish() -> int:
    for script in ("fetch_own_videos.py", "build_data.py"):
        result = run([sys.executable, script], HERE)
        if result.returncode != 0:
            log(f"NG {script} rc={result.returncode} {result.stderr.strip()[-300:]}")
            return 1

    for attempt in range(2):
        fetched = git("fetch", "-q", "origin", "main")
        reset = git("checkout", "-q", "-f", "--detach", "origin/main")
        if fetched.returncode or reset.returncode:
            log(f"NG git sync {fetched.stderr.strip()} {reset.stderr.strip()}")
            return 1
        os.makedirs(PUB_DATA, exist_ok=True)

        new_live = _read_json(os.path.join(DATA_DIR, "own_live.json"))
        old_live = _read_json(os.path.join(PUB_DATA, "own_live.json"))
        live_changed = _own_signature(new_live) != _own_signature(old_live)
        subs_changed = _data_js_sources(os.path.join(DATA_DIR, "data.js")) != _data_js_sources(os.path.join(PUB_DATA, "data.js"))
        if not live_changed and not subs_changed:
            log("skip 変化なし")
            return 0

        files = []
        if live_changed:
            shutil.copyfile(os.path.join(DATA_DIR, "own_live.json"), os.path.join(PUB_DATA, "own_live.json"))
            files.append("tools/vtomo_analyze/data/own_live.json")
        if subs_changed:
            shutil.copyfile(os.path.join(DATA_DIR, "data.js"), os.path.join(PUB_DATA, "data.js"))
            files.append("tools/vtomo_analyze/data/data.js")
        git("add", "-f", *files)
        stamp = (new_live or {}).get("generated_at_jst", "")[:16]
        message = f"vtomo_analyze: 自社の再生数・高評価を自動更新 ({stamp} JST)"
        if subs_changed:
            message += " +登録ch日次ログ"
        committed = git("commit", "-q", "--no-verify", "-m", message)
        if committed.returncode:
            log(f"NG commit {committed.stdout.strip()} {committed.stderr.strip()}")
            return 1
        pushed = git("push", "-q", "origin", "HEAD:main")
        if pushed.returncode == 0:
            log(f"OK push {' '.join(os.path.basename(f) for f in files)} {stamp}")
            return 0
        log(f"retry push rejected attempt={attempt + 1} {pushed.stderr.strip()[-200:]}")
        time.sleep(5)
    log("NG push 2回とも拒否")
    return 1


def main() -> int:
    os.makedirs(DATA_DIR, exist_ok=True)
    if os.path.exists(LOCK_PATH) and time.time() - os.path.getmtime(LOCK_PATH) < 600:
        log("skip 前回の実行が続いている")
        return 0
    with open(LOCK_PATH, "w", encoding="utf-8") as handle:
        handle.write(str(os.getpid()))
    try:
        return publish()
    except Exception as error:  # 定期実行なので落ちた理由をログへ残す
        log(f"NG {type(error).__name__}: {error}")
        return 1
    finally:
        try:
            os.remove(LOCK_PATH)
        except OSError:
            pass


if __name__ == "__main__":
    raise SystemExit(main())
