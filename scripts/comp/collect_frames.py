#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""競合Shorts 代表フレーム収集バッチ (収集足回りのみ・vision解析なし)
分析部門②がvideoIdキーで拾える形で
  local/_work/comp_frames/<videoId>.jpg (4.5秒目 or フォールバック)
  local/_work/comp_frames/meta.jsonl    (1videoId=1行)
を生成する。

使い方:
  python scripts/comp/collect_frames.py [--limit N] [--force] [--days 30] [--top 50]

  --limit N  : 処理するvideoIdの最大件数 (デフォルト: 全件)
  --force    : 既存jpgがあっても再DL・再抽出する
  --days N   : comp_titlesのdaysパラメータ (デフォルト: 30)
  --top N    : comp_titlesのtopパラメータ (デフォルト: 50)

動作:
  1. GAS comp_titles から videoId 一覧を取得
  2. 各videoIdについて:
     a. local/_work/comp_frames/<videoId>.jpg が既存 → スキップ (--forceで強制再取得)
     b. yt-dlp で最小画質DL (全編)
     c. ffprobe で尺取得
     d. ffmpeg で4.5秒目(尺<4.6秒なら末尾フォールバック)を1枚jpg抽出
     e. meta.jsonl へ追記
  3. DL失敗・抽出失敗のvideoIdはerrorメタ行を残してスキップ (全体を止めない)

meta.jsonl の形式:
  {"videoId":"...", "durationSec":5.041, "width":480, "height":854, "bytes":32768,
   "dlAt":"2026-07-30T12:34:56+09:00", "src":"comp_titles", "fallback":false}
  失敗行:
  {"videoId":"...", "error":"dl_failed", "dlAt":"...", "src":"comp_titles"}
"""
import argparse
import datetime
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.request

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.normpath(os.path.join(HERE, "..", ".."))

FRAMES_DIR = os.path.join(ROOT, "local", "_work", "comp_frames")
META_FILE = os.path.join(FRAMES_DIR, "meta.jsonl")

# 4.5秒目がChami指定位置。尺がこれ未満の場合はfallbackする閾値。
TARGET_SEC = 4.5
SHORT_THRESHOLD = 4.6   # 秒。これ未満なら末尾フォールバック
TAIL_EPS = 0.1           # 末尾フォールバック時の末尾からの戻し(秒)


def _exec_url():
    cfg_path = os.path.join(ROOT, "scripts", "gas_deploy_config.json")
    with open(cfg_path, encoding="utf-8") as f:
        return json.load(f)["execUrl"]


def fetch_comp_titles(exec_url, days, top):
    """GAS comp_titles から titles配列を返す。失敗時は空リスト。"""
    url = f"{exec_url}?action=comp_titles&days={days}&top={top}"
    try:
        with urllib.request.urlopen(url, timeout=60) as r:
            raw = r.read()
        try:
            text = raw.decode("utf-8")
        except UnicodeDecodeError:
            text = raw.decode("latin-1")
        data = json.loads(text)
        if not data.get("ok"):
            print(f"[WARN] comp_titles returned ok=false: {data.get('error') or data}")
            return []
        return data.get("titles", [])
    except Exception as e:
        print(f"[ERROR] comp_titles 取得失敗: {e}")
        return []


def load_existing_meta():
    """meta.jsonl を読み、videoId をキーとした辞書を返す。"""
    result = {}
    if not os.path.exists(META_FILE):
        return result
    with open(META_FILE, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
                vid = row.get("videoId")
                if vid:
                    result[vid] = row
            except Exception:
                pass
    return result


def save_meta(row, existing_meta):
    """meta.jsonl へ upsert する (videoId が既存ならその行を上書き・新規なら追記)。
    全行を再書き込みして整合性を保つ。existing_meta を最新の辞書に更新する。
    """
    vid = row["videoId"]
    existing_meta[vid] = row
    with open(META_FILE, "w", encoding="utf-8") as f:
        for r in existing_meta.values():
            f.write(json.dumps(r, ensure_ascii=False) + "\n")


def now_jst_iso():
    """現在時刻をJST ISOで返す。"""
    jst = datetime.timezone(datetime.timedelta(hours=9))
    return datetime.datetime.now(jst).isoformat(timespec="seconds")


def _run_capture(cmd):
    """コマンドを実行して (returncode, stdout, stderr) を返す。"""
    r = subprocess.run(cmd, capture_output=True)
    return r.returncode, r.stdout.decode("utf-8", "replace"), r.stderr.decode("utf-8", "replace")


def _run_silent(cmd):
    """コマンドをサイレントで実行して returncode を返す。"""
    r = subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return r.returncode


def ytdlp_cmd():
    """yt-dlp コマンドのベース。"""
    if shutil.which("yt-dlp"):
        return ["yt-dlp"]
    return [sys.executable, "-m", "yt_dlp"]


def ffprobe_info(filepath):
    """ffprobe で (duration, width, height) をまとめて返す。取得できない値は None。"""
    cmd = [
        "ffprobe", "-v", "quiet",
        "-print_format", "json",
        "-show_format",
        "-show_streams",
        filepath
    ]
    rc, out, _ = _run_capture(cmd)
    if rc != 0:
        return None, None, None
    try:
        d = json.loads(out)
        dur = None
        w, h = None, None
        for s in d.get("streams", []):
            if not dur and s.get("duration"):
                dur = float(s["duration"])
            if s.get("codec_type") == "video":
                w = s.get("width")
                h = s.get("height")
        # format側 duration フォールバック
        if not dur:
            fmt_dur = d.get("format", {}).get("duration")
            if fmt_dur:
                dur = float(fmt_dur)
        return dur, w, h
    except Exception:
        pass
    return None, None, None


def download_video(video_id, outpath):
    """yt-dlp で最小画質DL。outpath は拡張子なしのテンプレ。
    実際のファイルパスを返す。失敗時は None。"""
    url = f"https://www.youtube.com/watch?v={video_id}"
    # outpath は "xxx/vid" の形。yt-dlp が拡張子を付けてくれる。
    outdir = os.path.dirname(outpath)
    basename = os.path.basename(outpath)
    template = os.path.join(outdir, basename + ".%(ext)s")
    cmd = ytdlp_cmd() + [
        "--no-playlist",
        "-f", "bv*[height<=480]+ba/b[height<=480]/b",
        "-o", template,
        url,
    ]
    rc = _run_silent(cmd)
    if rc != 0:
        return None
    # DLされたファイルを探す
    for f in os.listdir(outdir):
        if f.startswith(basename + "."):
            return os.path.join(outdir, f)
    return None


def extract_frame(vidpath, target_sec, dur, outjpg):
    """ffmpeg で1フレームjpg抽出。
    尺が target_sec 未満なら末尾フォールバック。
    成功で (True, fallback_used)、失敗で (False, False)。
    """
    fallback = dur is not None and dur < SHORT_THRESHOLD

    def _extract(ss_flag, ss_val):
        if ss_flag == "sseof":
            cmd = ["ffmpeg", "-y", "-sseof", f"-{ss_val}", "-i", vidpath,
                   "-frames:v", "1", "-q:v", "2", outjpg]
        else:
            cmd = ["ffmpeg", "-y", "-ss", str(ss_val), "-i", vidpath,
                   "-frames:v", "1", "-q:v", "2", outjpg]
        return _run_silent(cmd) == 0 and os.path.exists(outjpg)

    if fallback:
        # 尺が足りない場合: 末尾 TAIL_EPS 秒前
        ok = _extract("sseof", TAIL_EPS)
        if not ok:
            # さらに先頭フォールバック
            ok = _extract("ss", 0)
        return ok, True
    else:
        # 通常ケース: TARGET_SEC を直接シーク
        ok = _extract("ss", target_sec)
        if not ok:
            # 末尾フォールバック
            ok = _extract("sseof", TAIL_EPS)
            return ok, True
        return ok, False


def process_video(video_id, frames_dir, force):
    """1本のvideoIdを処理する。
    Returns: dict (meta行の内容。error キーがあれば失敗)
    """
    jpg_dst = os.path.join(frames_dir, f"{video_id}.jpg")
    dl_at = now_jst_iso()

    # 冪等チェック
    if os.path.exists(jpg_dst) and not force:
        size = os.path.getsize(jpg_dst)
        print(f"  {video_id}: 既存({size}B) → スキップ")
        return None  # スキップ=何も書かない

    workdir = tempfile.mkdtemp(prefix="cf_")
    try:
        vid_base = os.path.join(workdir, "vid")
        vidpath = download_video(video_id, vid_base)
        if not vidpath:
            print(f"  {video_id}: DL失敗")
            return {"videoId": video_id, "error": "dl_failed",
                    "dlAt": dl_at, "src": "comp_titles"}

        dur, w, h = ffprobe_info(vidpath)

        frame_tmp = os.path.join(workdir, "frame.jpg")
        ok, fallback = extract_frame(vidpath, TARGET_SEC, dur, frame_tmp)
        if not ok:
            print(f"  {video_id}: フレーム抽出失敗 (dur={dur})")
            return {"videoId": video_id, "error": "extract_failed",
                    "durationSec": dur, "dlAt": dl_at, "src": "comp_titles"}

        # 成果物を所定の場所へコピー
        shutil.copy2(frame_tmp, jpg_dst)
        size = os.path.getsize(jpg_dst)
        dur_str = f"{dur:.2f}s" if dur is not None else "unknown"
        print(f"  {video_id}: OK {size}B dur={dur_str} fallback={fallback}")
        return {
            "videoId": video_id,
            "durationSec": round(dur, 3) if dur is not None else None,
            "width": w,
            "height": h,
            "bytes": size,
            "dlAt": dl_at,
            "src": "comp_titles",
            "fallback": fallback,
        }
    finally:
        shutil.rmtree(workdir, ignore_errors=True)


def main():
    ap = argparse.ArgumentParser(description="競合Shorts 代表フレーム収集バッチ")
    ap.add_argument("--limit", type=int, default=None, help="処理するvideoId最大件数")
    ap.add_argument("--force", action="store_true", help="既存jpgがあっても再取得")
    ap.add_argument("--days", type=int, default=30, help="comp_titlesのdaysパラメータ")
    ap.add_argument("--top", type=int, default=50, help="comp_titlesのtopパラメータ")
    args = ap.parse_args()

    # 出力先ディレクトリ作成
    os.makedirs(FRAMES_DIR, exist_ok=True)

    # ツール確認
    missing = []
    if not (shutil.which("yt-dlp") or True):  # yt-dlp はモジュール経由も可
        missing.append("yt-dlp")
    if not shutil.which("ffmpeg"):
        missing.append("ffmpeg")
    if not shutil.which("ffprobe"):
        missing.append("ffprobe")
    if missing:
        print(f"[ERROR] 必要ツールが見つかりません: {', '.join(missing)}")
        sys.exit(1)

    # exec URL 取得
    try:
        exec_url = _exec_url()
    except Exception as e:
        print(f"[ERROR] gas_deploy_config.json 読み込み失敗: {e}")
        sys.exit(1)

    # comp_titles から videoId 一覧取得
    print(f"[INFO] comp_titles を取得中 (days={args.days} top={args.top}) ...")
    titles = fetch_comp_titles(exec_url, args.days, args.top)
    if not titles:
        print("[WARN] comp_titles が空または到達不能。処理を終了します。")
        sys.exit(0)

    video_ids = [t["videoId"] for t in titles if t.get("videoId")]
    print(f"[INFO] 取得件数: {len(titles)} 件 / videoId あり: {len(video_ids)} 件")

    if args.limit is not None:
        video_ids = video_ids[:args.limit]
        print(f"[INFO] --limit {args.limit} 適用後: {len(video_ids)} 件")

    # 既存metaを読み込み (冪等判定用)
    existing_meta = load_existing_meta()

    # 処理
    skipped, ok_count, err_count = 0, 0, 0
    for vid in video_ids:
        # meta.jsonl に既存のエラー行があっても --force なければスキップしない
        # (エラーは再試行したい場合が多い。既存jpgがある場合のみスキップ)
        row = process_video(vid, FRAMES_DIR, args.force)
        if row is None:
            skipped += 1
        elif row.get("error"):
            save_meta(row, existing_meta)
            err_count += 1
        else:
            save_meta(row, existing_meta)
            ok_count += 1
        time.sleep(0.5)  # サーバー負荷軽減

    print(f"\n[DONE] 成功: {ok_count} / エラー: {err_count} / スキップ: {skipped} / 対象: {len(video_ids)}")
    print(f"[INFO] フレーム置き場: {FRAMES_DIR}")
    print(f"[INFO] メタファイル:   {META_FILE}")


if __name__ == "__main__":
    main()
