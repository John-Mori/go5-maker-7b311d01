#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""ingest_video.py — 動画取り込みパイプライン(改修α / ルカ・モドリッチ指示・型分解の下ごしらえ)。

なぜ在るか:
  OgiiytcUnzE の型分解(local/video_ingest/OgiiytcUnzE/analysis.md)は
  ①字幕取得 ②Whisper文字起こし(字幕が無い時) ③フレーム抽出+目視 の3段で作られていたが、
  その手順は使い捨てコマンドの積み重ねで、再利用できるスクリプトとして残っていなかった
  (2026-09-02 実測・scripts配下を探索したが該当スクリプトなし)。
  VRbdT3PH2ds+競合5chの型分解で同じ手順を繰り返すため、ここで再利用可能な形にする。

やること(自動化するのはここまで・分析本体は人力/目視):
  1. yt-dlp でメタ情報(タイトル/尺/チャンネル/再生数)を実測して記録
  2. 字幕(日本語自動字幕 json3)を試す→無ければ faster_whisper で音声から文字起こし
  3. 動画DL＋音声抽出(mp3)
  4. ffmpeg で一定間隔のフレームを抜く(既定4秒間隔)
  5. transcript.json(OgiiytcUnzE と同スキーマ)＋frames/＋analysis.mdの空枠を出力

このスクリプトは「型分解の結論」を書かない(構造4段/演出パターン等の解釈は人力)。
出力先: local/video_ingest/<video_id>/
"""
import argparse
import json
import os
import re
import shutil
import subprocess
import sys
from datetime import datetime, timezone, timedelta

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
OUT_ROOT = os.path.join(ROOT, "local", "video_ingest")
JST = timezone(timedelta(hours=9))

FRAME_INTERVAL_SEC = 4.0  # OgiiytcUnzE実績(28秒→7枚≒4秒間隔)に合わせた既定値


def run(cmd, **kw):
    print("  $ " + " ".join(cmd))
    return subprocess.run(cmd, check=True, capture_output=True, text=True, encoding="utf-8", errors="replace", **kw)


def yt_dlp_json(url):
    r = subprocess.run(
        ["yt-dlp", "--skip-download", "--print", "%(id)s\t%(title)s\t%(duration)s\t%(channel)s\t%(view_count)s", url],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
    )
    line = [l for l in r.stdout.splitlines() if "\t" in l]
    if not line:
        raise SystemExit(f"yt-dlp メタ取得失敗: {r.stderr[-500:]}")
    vid, title, duration, channel, views = line[-1].split("\t")
    return {
        "video_id": vid,
        "title": title,
        "duration": float(duration) if duration not in ("NA", "") else None,
        "channel": channel,
        "view_count": int(views) if views not in ("NA", "") else None,
    }


def try_captions(url, out_dir, lang="ja"):
    """自動字幕(json3)を取得できればセグメント配列を返す。無ければ None。"""
    base = os.path.join(out_dir, "_cap")
    cmd = ["yt-dlp", "--write-auto-sub", "--sub-lang", lang, "--sub-format", "json3",
           "--skip-download", "-o", base + ".%(ext)s", url]
    try:
        run(cmd)
    except subprocess.CalledProcessError:
        return None
    cap_path = base + f".{lang}.json3"
    if not os.path.exists(cap_path):
        return None
    with open(cap_path, encoding="utf-8") as f:
        raw = json.load(f)
    os.remove(cap_path)
    return parse_json3_events(raw)


def parse_json3_events(raw):
    """yt-dlp の json3字幕(dict)→ [{start,end,text}] 。空イベント/改行だけの行は除く。"""
    segments = []
    for ev in raw.get("events", []):
        segs = ev.get("segs")
        if not segs:
            continue
        text = "".join(s.get("utf8", "") for s in segs).replace("\n", "").strip()
        if not text:
            continue
        start = ev["tStartMs"] / 1000.0
        end = start + ev.get("dDurationMs", 0) / 1000.0
        segments.append({"start": round(start, 2), "end": round(end, 2), "text": text})
    return segments or None


def whisper_transcribe(audio_path, lang="ja"):
    from faster_whisper import WhisperModel
    model = WhisperModel("small", device="cpu", compute_type="int8")
    segs, _info = model.transcribe(audio_path, language=lang)
    return [{"start": round(s.start, 2), "end": round(s.end, 2), "text": s.text.strip()} for s in segs]


def download_media(url, out_dir):
    video_path = os.path.join(out_dir, "video.mp4")
    audio_path = os.path.join(out_dir, "audio.mp3")
    run(["yt-dlp", "-f", "mp4/best", "-o", video_path, url])
    run(["ffmpeg", "-y", "-i", video_path, "-vn", "-acodec", "libmp3lame", audio_path])
    return video_path, audio_path


def extract_frames(video_path, out_dir, duration, interval=FRAME_INTERVAL_SEC):
    frames_dir = os.path.join(out_dir, "frames")
    os.makedirs(frames_dir, exist_ok=True)
    fps = 1.0 / interval
    run(["ffmpeg", "-y", "-i", video_path, "-vf", f"fps={fps}",
         os.path.join(frames_dir, "f_%03d.png")])
    return sorted(os.listdir(frames_dir))


def write_analysis_stub(out_dir, meta, method):
    path = os.path.join(out_dir, "analysis.md")
    if os.path.exists(path):
        return
    lines = [
        f"# 型分解メモ: {meta['video_id']}",
        "",
        f"- タイトル: {meta['title']}",
        f"- チャンネル: {meta['channel']}",
        f"- 尺(実測): {meta['duration']}秒" if meta["duration"] else "- 尺(実測): 取得失敗(要確認)",
        f"- 再生数(実測・取得時点): {meta['view_count']}" if meta["view_count"] is not None else "- 再生数: 取得失敗",
        f"- 文字起こし方式: {method}",
        f"- 取り込み日時: {datetime.now(JST).isoformat(timespec='seconds')}",
        "",
        "## タイムライン(timestamp | セリフ | 画面内容)",
        "- (frames/ と transcript.json を目視で突き合わせて埋める・自動生成しない)",
        "",
        "## 構造パターン(人力で埋める)",
        "- (起承転結/間の取り方/画像の出し方など。数字は実測分のみ記載)",
    ]
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    print(f"[stub] {path}")


def ingest(video_id, keep_video=True):
    url = f"https://www.youtube.com/watch?v={video_id}"
    out_dir = os.path.join(OUT_ROOT, video_id)
    os.makedirs(out_dir, exist_ok=True)

    print(f"[1/4] メタ情報取得: {video_id}")
    meta = yt_dlp_json(url)

    print("[2/4] 文字起こし(①字幕→②Whisperの順)")
    segments = try_captions(url, out_dir)
    method = "captions(auto-ja)"
    video_path, audio_path = download_media(url, out_dir)
    if segments is None:
        print("  字幕なし。Whisperにフォールバック")
        segments = whisper_transcribe(audio_path)
        method = "whisper(small)"

    transcript = {
        "video_id": video_id,
        "language": "ja",
        "duration": meta["duration"],
        "method": method,
        "segments": segments,
    }
    with open(os.path.join(out_dir, "transcript.json"), "w", encoding="utf-8") as f:
        json.dump(transcript, f, ensure_ascii=False, indent=2)

    print("[3/4] フレーム抽出")
    frames = extract_frames(video_path, out_dir, meta["duration"])
    print(f"  {len(frames)}枚")

    if not keep_video:
        os.remove(video_path)

    print("[4/4] analysis.md 空枠")
    write_analysis_stub(out_dir, meta, method)

    print(f"完了: {out_dir}")
    return out_dir


def main():
    ap = argparse.ArgumentParser(description="動画取り込みパイプライン(字幕/Whisper→フレーム抽出)")
    ap.add_argument("video_id", help="YouTube動画ID")
    ap.add_argument("--no-keep-video", action="store_true", help="video.mp4を残さない(フレーム抽出後に削除)")
    args = ap.parse_args()
    ingest(args.video_id, keep_video=not args.no_keep_video)


if __name__ == "__main__":
    main()
