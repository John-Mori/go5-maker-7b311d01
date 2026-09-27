#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""既存の日次ログと自社チェックポイントをローカル閲覧用 data.js にまとめる。"""
from __future__ import annotations

import datetime as dt
import glob
import json
import os
import re
import sys
from typing import Any, Iterable

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPTS_DIR = os.environ.get("VTOMO_SCRIPTS_DIR", r"D:\SougouStartFolder\5SecMovieMaker\scripts")
CONSULT_INTEL_DIR = os.environ.get(
    "VTOMO_CONSULT_INTEL_DIR",
    r"D:\SougouStartFolder\5SecMovieMaker\local\consult_intel",
)
CHECKPOINTS_PATH = os.environ.get(
    "VTOMO_CHECKPOINTS_PATH",
    r"E:\5chShortMovie\リサーチ\自社48h\own_48h.jsonl",
)
CHECKPOINT_HOURS = (1, 2, 3, 6, 12, 24, 48, 72)
JST = dt.timezone(dt.timedelta(hours=9))


def _read_json(path: str) -> Any:
    with open(path, encoding="utf-8") as handle:
        return json.load(handle)


def _read_jsonl(path: str) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    if not path or not os.path.isfile(path):
        return rows
    with open(path, encoding="utf-8") as handle:
        for line_no, line in enumerate(handle, 1):
            line = line.strip()
            if not line:
                continue
            try:
                value = json.loads(line)
            except json.JSONDecodeError as exc:
                raise RuntimeError(f"JSONL不正: {path}:{line_no}: {exc}") from exc
            if isinstance(value, dict):
                rows.append(value)
    return rows


def _latest(pattern: str) -> str:
    paths = glob.glob(pattern)
    if not paths:
        raise FileNotFoundError(f"入力が見つからない: {pattern}")
    return max(paths, key=lambda path: (os.path.basename(path), os.path.getmtime(path)))


def _to_int(value: Any, default: int = 0) -> int:
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return default


def _to_float(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _load_subs_dir() -> str:
    override = os.environ.get("VTOMO_SUBS_DIR")
    if override:
        return override
    if SCRIPTS_DIR not in sys.path:
        sys.path.insert(0, SCRIPTS_DIR)
    import paths_5ch

    return paths_5ch.subs_dir()


def _checkpoint_map(rows: Iterable[dict[str, Any]]) -> dict[str, dict[int, dict[str, Any]]]:
    merged: dict[str, dict[int, dict[str, Any]]] = {}
    for row in rows:
        video_id = str(row.get("video_id") or "")
        hour = _to_int(row.get("checkpoint_h"), -1)
        if not video_id or hour not in CHECKPOINT_HOURS:
            continue
        age_h = _to_float(row.get("age_h"))
        drift_min = round((age_h - hour) * 60, 1) if age_h is not None else None
        delayed = bool(row.get("delayed"))
        if drift_min is not None and abs(drift_min) > 3:
            delayed = True
        value = {
            "checkpoint_h": hour,
            "views": _to_int(row.get("views")),
            "likes": None if row.get("likes") is None else _to_int(row.get("likes")),
            "age_h": age_h,
            "drift_min": drift_min,
            "delayed": delayed,
            "fetched_jst": row.get("fetched_jst"),
        }
        current = merged.setdefault(video_id, {}).get(hour)
        if current is None or str(value.get("fetched_jst") or "") >= str(current.get("fetched_jst") or ""):
            merged[video_id][hour] = value
    return merged


def _own_payload(out_dir: str, checkpoint_rows: list[dict[str, Any]]) -> tuple[dict[str, Any], str]:
    own_path = _latest(os.path.join(out_dir, "own_videos_*.json"))
    own = _read_json(own_path)
    checkpoints = _checkpoint_map(checkpoint_rows)
    videos = []
    for source in own.get("videos") or []:
        row = dict(source)
        video_id = str(row.get("video_id") or "")
        row["url"] = row.get("url") or f"https://www.youtube.com/watch?v={video_id}"
        row["thumb"] = row.get("thumb") or f"https://i.ytimg.com/vi/{video_id}/hqdefault.jpg"
        row["checkpoints"] = [checkpoints.get(video_id, {}).get(hour) for hour in CHECKPOINT_HOURS]
        videos.append(row)
    return {
        "channel": own.get("channel") or {},
        "fetched_at_jst": own.get("fetched_at_jst"),
        "api_calls": own.get("api_calls") or {},
        "videos": videos,
    }, own_path


def _subscription_payload(snapshot_path: str, log_path: str) -> dict[str, Any]:
    snapshot = _read_json(snapshot_path)
    channels = snapshot.get("channels") or []
    by_id = {
        str(row.get("channel_id") or ""): {
            "channel_id": str(row.get("channel_id") or ""),
            "title": row.get("title") or row.get("handle") or "(名称不明)",
            "handle": row.get("handle"),
        }
        for row in channels
        if row.get("channel_id")
    }

    # ログが同一動画を複数行含む場合は、ts が新しい行だけを表示する。
    video_by_id: dict[str, dict[str, Any]] = {}
    matched_rows = 0
    for source in _read_jsonl(log_path):
        channel_id = str(source.get("channel_id") or "")
        if channel_id not in by_id:
            continue
        matched_rows += 1
        video_id = str(source.get("video_id") or "")
        if not video_id:
            continue
        seconds = _to_float(source.get("sec"))
        row = {
            "channel_id": channel_id,
            "channel": source.get("channel") or by_id[channel_id]["title"],
            "video_id": video_id,
            "title": source.get("title") or "(無題)",
            "sec": seconds,
            "views": _to_int(source.get("views")),
            "published": source.get("published"),
            "is_short": seconds is not None and seconds <= 60,
            "thumb": f"https://i.ytimg.com/vi/{video_id}/hqdefault.jpg",
            "url": f"https://www.youtube.com/watch?v={video_id}",
            "ts": source.get("ts"),
        }
        previous = video_by_id.get(video_id)
        if previous is None or str(row.get("ts") or "") >= str(previous.get("ts") or ""):
            video_by_id[video_id] = row

    videos = sorted(
        video_by_id.values(),
        key=lambda row: (row.get("published") or "", row.get("views") or 0),
        reverse=True,
    )
    return {
        "account": snapshot.get("account") or "@yoizakura_t",
        "snapshot_fetched_at": snapshot.get("fetched_at"),
        "channels": sorted(by_id.values(), key=lambda row: row["title"]),
        "videos": videos,
        "matched_log_rows": matched_rows,
    }


def build() -> tuple[dict[str, Any], str]:
    out_dir = os.environ.get("VTOMO_OUT_DIR") or os.path.join(HERE, "data")
    os.makedirs(out_dir, exist_ok=True)
    subs_dir = _load_subs_dir()
    snapshot_path = _latest(os.path.join(subs_dir, "subs_yoizakura_t_????-??-??.json"))
    log_path = _latest(os.path.join(CONSULT_INTEL_DIR, "subs_shorts_????-??-??.jsonl"))
    checkpoint_rows = _read_jsonl(CHECKPOINTS_PATH)
    own, own_path = _own_payload(out_dir, checkpoint_rows)
    subscriptions = _subscription_payload(snapshot_path, log_path)
    now = dt.datetime.now(JST)
    payload = {
        "schema": "vtomo_analyze_v1",
        "generated_at_jst": now.isoformat(timespec="seconds"),
        "checkpoint_hours": list(CHECKPOINT_HOURS),
        "own": own,
        "subscriptions": subscriptions,
        "sources": {
            "own": os.path.basename(own_path),
            "subscription_snapshot": os.path.basename(snapshot_path),
            "subscription_video_log": os.path.basename(log_path),
            "checkpoints": os.path.basename(CHECKPOINTS_PATH),
        },
        "counts": {
            "own_videos": len(own["videos"]),
            "subscription_channels": len(subscriptions["channels"]),
            "subscription_videos": len(subscriptions["videos"]),
        },
    }
    latest_path = os.path.join(out_dir, "latest.json")
    data_path = os.path.join(out_dir, "data.js")
    with open(latest_path, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2)
        handle.write("\n")
    with open(data_path, "w", encoding="utf-8") as handle:
        handle.write("window.VTOMO_DATA = ")
        json.dump(payload, handle, ensure_ascii=False, separators=(",", ":"))
        handle.write(";\n")
    # 自社分だけの小さい版。公開ページが数分おきに読み直し、再生数・高評価を差し替える。
    live_path = os.path.join(out_dir, "own_live.json")
    with open(live_path, "w", encoding="utf-8") as handle:
        json.dump(
            {"schema": "vtomo_own_live_v1", "generated_at_jst": payload["generated_at_jst"], "own": own},
            handle,
            ensure_ascii=False,
            separators=(",", ":"),
        )
        handle.write("\n")
    return payload, data_path


def main() -> int:
    payload, output = build()
    counts = payload["counts"]
    print(
        "built own={own_videos} channels={subscription_channels} "
        "subscription_videos={subscription_videos} -> {output}".format(output=output, **counts)
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
