#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Vともっと推し活ちゃんねるの公開動画指標を取得する。

認証は subs_shorts_daily.build_youtube() の既存 youtube.readonly OAuth を再利用する。
登録変更などの書き込み API は呼ばない。出力はローカル専用 data/ 配下。
"""
from __future__ import annotations

import datetime as dt
import json
import os
import sys
from typing import Any

HERE = os.path.dirname(os.path.abspath(__file__))
ANALYSIS_DIR = os.environ.get(
    "VTOMO_ANALYSIS_DIR",
    r"D:\SougouStartFolder\5SecMovieMaker\scripts\analysis",
)
CHANNEL_ID = "UCGi6xupkArA48grMFovqa5g"
JST = dt.timezone(dt.timedelta(hours=9))


def _duration_to_seconds(value: str) -> int:
    """PT1M2S 形式を秒へ変換する。既存関数を優先し、単体実行にも耐える。"""
    try:
        if ANALYSIS_DIR not in sys.path:
            sys.path.insert(0, ANALYSIS_DIR)
        from subs_shorts_daily import iso_dur_to_sec

        return int(iso_dur_to_sec(value))
    except (ImportError, TypeError, ValueError):
        import re

        match = re.fullmatch(r"PT(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?", value or "")
        if not match:
            return 0
        hours, minutes, seconds = (int(part or 0) for part in match.groups())
        return hours * 3600 + minutes * 60 + seconds


def _to_int(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _thumbnail(snippet: dict[str, Any], video_id: str) -> str:
    thumbs = snippet.get("thumbnails") or {}
    for key in ("maxres", "standard", "high", "medium", "default"):
        url = (thumbs.get(key) or {}).get("url")
        if url:
            return str(url)
    return f"https://i.ytimg.com/vi/{video_id}/hqdefault.jpg"


def fetch(youtube: Any, channel_id: str = CHANNEL_ID) -> dict[str, Any]:
    """channels.list -> playlistItems.list -> videos.list の読み取りだけを行う。"""
    response = youtube.channels().list(
        part="contentDetails,statistics,snippet",
        id=channel_id,
    ).execute()
    items = response.get("items") or []
    if not items:
        raise RuntimeError(f"チャンネルが見つからない: {channel_id}")

    channel = items[0]
    uploads = channel["contentDetails"]["relatedPlaylists"]["uploads"]
    video_ids: list[str] = []
    page_token: str | None = None
    playlist_calls = 0
    while True:
        page = youtube.playlistItems().list(
            part="contentDetails",
            playlistId=uploads,
            maxResults=50,
            pageToken=page_token,
        ).execute()
        playlist_calls += 1
        video_ids.extend(
            row["contentDetails"]["videoId"]
            for row in page.get("items") or []
            if (row.get("contentDetails") or {}).get("videoId")
        )
        page_token = page.get("nextPageToken")
        if not page_token:
            break

    videos: list[dict[str, Any]] = []
    videos_calls = 0
    for start in range(0, len(video_ids), 50):
        page = youtube.videos().list(
            part="contentDetails,statistics,snippet",
            id=",".join(video_ids[start : start + 50]),
        ).execute()
        videos_calls += 1
        for row in page.get("items") or []:
            snippet = row.get("snippet") or {}
            stats = row.get("statistics") or {}
            video_id = str(row.get("id") or "")
            videos.append(
                {
                    "video_id": video_id,
                    "title": snippet.get("title") or "(無題)",
                    "published_at": snippet.get("publishedAt"),
                    "sec": _duration_to_seconds((row.get("contentDetails") or {}).get("duration", "")),
                    "views": _to_int(stats.get("viewCount")) or 0,
                    "likes": _to_int(stats.get("likeCount")),
                    "comments": _to_int(stats.get("commentCount")),
                    "thumb": _thumbnail(snippet, video_id),
                    "url": f"https://www.youtube.com/watch?v={video_id}",
                }
            )
    videos.sort(key=lambda row: row.get("published_at") or "", reverse=True)

    channel_snippet = channel.get("snippet") or {}
    channel_stats = channel.get("statistics") or {}
    return {
        "schema": "vtomo_own_v1",
        "channel": {
            "channel_id": channel_id,
            "title": channel_snippet.get("title") or "Vともっと推し活ちゃんねる",
            "subscribers": _to_int(channel_stats.get("subscriberCount")),
        },
        "api_calls": {
            "channels_list": 1,
            "playlist_items_list": playlist_calls,
            "videos_list": videos_calls,
            "estimated_quota_units": 1 + playlist_calls + videos_calls,
        },
        "videos": videos,
    }


def build_youtube_client() -> Any:
    """通常は既存build_youtubeを使う。検証時だけtokenを保存せずメモリ更新する。"""
    if not os.environ.get("VTOMO_NO_TOKEN_WRITE"):
        from subs_shorts_daily import build_youtube

        return build_youtube()

    # worktree検証用。外部token原本を変更しないための読み取り専用経路。
    scripts_dir = os.path.dirname(ANALYSIS_DIR)
    if scripts_dir not in sys.path:
        sys.path.insert(0, scripts_dir)
    import paths_5ch
    from google.auth.transport.requests import Request as GoogleRequest
    from google.oauth2.credentials import Credentials
    from googleapiclient.discovery import build

    token_path = os.path.join(paths_5ch.subs_dir(), "oauth_token.json")
    scopes = ["https://www.googleapis.com/auth/youtube.readonly"]
    credentials = Credentials.from_authorized_user_file(token_path, scopes)
    if not credentials.valid and credentials.expired and credentials.refresh_token:
        credentials.refresh(GoogleRequest())
    return build("youtube", "v3", credentials=credentials, cache_discovery=False)


def main() -> int:
    if ANALYSIS_DIR not in sys.path:
        sys.path.insert(0, ANALYSIS_DIR)
    now = dt.datetime.now(JST)
    body = fetch(build_youtube_client())
    body["fetched_at_jst"] = now.isoformat(timespec="seconds")

    out_dir = os.environ.get("VTOMO_OUT_DIR") or os.path.join(HERE, "data")
    os.makedirs(out_dir, exist_ok=True)
    output = os.path.join(out_dir, f"own_videos_{now:%Y-%m-%d}.json")
    with open(output, "w", encoding="utf-8") as handle:
        json.dump(body, handle, ensure_ascii=False, indent=2)
        handle.write("\n")
    print(
        "own videos={videos} quota_units={quota} -> {output}".format(
            videos=len(body["videos"]),
            quota=body["api_calls"]["estimated_quota_units"],
            output=output,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
