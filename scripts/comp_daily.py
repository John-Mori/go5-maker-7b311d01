#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""競合_日次スナップの PC側収集  (2026-09-04 改修部門α / 方向2・モドリッチ依頼 REQ-research-room-de08ad55fc)

なぜ在るか(総量設計):
  競合_日次は 2026-08-18 から17日間凍結した。真因は競合側ではなく本体=snapshotStats(5分毎)
  +refreshClicks(毎時)が GASプロジェクト全体の UrlFetchApp 日次枠(2万)を夜通し食い尽くし、
  04:00 の competitor ジョブ(自身は約30fetchと軽い)が ytVideosStats_ の全fetchで枯渇例外
  →snapped=0 になること=「競合ジョブ単独では回復不可」。診断/回帰ガードを足しても凍結は解けない。
  → 映像側の取得(view/like/comment・新着discovery)を丸ごとPC(yt-dlp・APIキー不要・PC自身の回線)へ
     移し、GASは台帳/日次の読み書きだけ持つ。GAS urlfetch枠を1回も使わない=本体の枯渇と無関係に動く。
     comp_frames.py(代表フレーム収集)の PC→GAS 足回りと同じ形。

やること:
  1. GAS action=comp_daily_pending で「追跡窓内の既存windowVids」と「watchチャンネル(uploads)」を引く。
  2. yt-dlp でwatchチャンネルの新着(flat playlist)を拾い、windowVidsと合わせて対象集合を作る。
  3. yt-dlp -J(--skip-download)で各動画の view_count/like_count/comment_count/upload_date/duration を取る。
  4. GAS op=comp_daily_write で 競合_日次 へ append(＋窓内新着を台帳へupsert・競合_日次ステータスへpc行)。

方針(既存規律を踏襲):
  - 競合ID/実名は公開repoに出さない=このスクリプトはIDを実行時にGASから引くだけ・保持しない・ログにも出さない。
  - GAS urlfetch枠は使わない(=読み書きは全てSpreadsheetApp側の口)。YouTube Data APIキーは不要(yt-dlp)。

前提: yt-dlp(未導入なら python -m pip install -U yt-dlp)。ffmpegは不要(メタデータのみ)。
使い方:
  python scripts/comp_daily.py --check        # 疎通のみ(windowVids/watch件数を出す・yt-dlpを動かさない)
  python scripts/comp_daily.py                # 収集して書き戻す(discovery＋snapshot)
  python scripts/comp_daily.py --no-discover  # 新着discoveryをやらず既存windowVidsだけ
  python scripts/comp_daily.py --dry          # 取得まで走るが書き戻さない(結果を印字)
"""
import argparse
import datetime as dt
import json
import os
import re
import shutil
import subprocess
import sys
import time
import urllib.request

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.normpath(os.path.join(HERE, ".."))
GAS = json.load(open(os.path.join(ROOT, "scripts", "gas_deploy_config.json"), encoding="utf-8"))["execUrl"]

DISCOVER_PER_CHANNEL = 20    # 1チャンネルあたり flat playlist で見に行く直近本数
MAX_FETCH = 120              # 1回のランで yt-dlp -J を叩く動画数の上限(過負荷/レート避け)
YTID_RE = re.compile(r"^[A-Za-z0-9_-]{11}$")
PULSE = os.path.join(ROOT, "local", "_work", "comp_daily_pulse.md")   # 毎回書く脈(静かな死をproducers側が検知できる)


def _secrets():
    """GAS doPost の SHARED_SECRET 候補(順に試す)。値は印字しない。"""
    out = []
    try:
        cfg = json.load(open(os.path.join(ROOT, "scripts", "scrape_config.json"), encoding="utf-8"))
        for k in ("sharedSecret", "adminSecret"):
            if cfg.get(k):
                out.append(cfg[k])
    except Exception:
        pass
    out.append("daremogamewoubawareteikukimihakanpekidekyukyokunoidol")  # GASのソフト鍵フォールバック
    return out


def gas_get(query, tries=3):
    for _ in range(tries):
        try:
            with urllib.request.urlopen(f"{GAS}?{query}&callback=x", timeout=90) as r:
                raw = r.read().decode("utf-8", "replace").strip()
            return json.loads(re.sub(r"^x\(|\)$", "", raw))
        except Exception:
            time.sleep(3)
    return {}


def gas_write(body, tries=3):
    """op=comp_daily_write で書き戻す。SHARED_SECRET候補を順に試す。"""
    last = {}
    for sec in _secrets():
        payload = dict(body)
        payload["op"] = "comp_daily_write"
        payload["secret"] = sec
        for _ in range(tries):
            try:
                req = urllib.request.Request(GAS, data=json.dumps(payload).encode("utf-8"),
                                             headers={"Content-Type": "application/json"})
                with urllib.request.urlopen(req, timeout=120) as r:
                    last = json.loads(r.read())
                break
            except Exception:
                time.sleep(3)
        if last.get("ok"):
            return last
        if last.get("error") and last.get("error") != "bad_secret":
            break
    return last


def ytdlp_cmd():
    if shutil.which("yt-dlp"):
        return ["yt-dlp"]
    return [sys.executable, "-m", "yt_dlp"]


def have_ytdlp():
    if shutil.which("yt-dlp"):
        return True
    try:
        import yt_dlp  # noqa: F401
        return True
    except Exception:
        return False


def _yt_json(args, timeout=90):
    """yt-dlp を JSON 出力で叩き、stdout をパースして返す(失敗は None)。stderrは握る。"""
    try:
        r = subprocess.run(ytdlp_cmd() + args, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                           timeout=timeout)
    except Exception:
        return None
    if r.returncode != 0 or not r.stdout:
        return None
    try:
        return json.loads(r.stdout.decode("utf-8", "replace"))
    except Exception:
        return None


def discover(uploads, channel_id, per=DISCOVER_PER_CHANNEL):
    """uploadsプレイリストの直近動画IDを flat playlist で拾う。[{id, channel_id}] を返す。"""
    if not uploads:
        return []
    url = f"https://www.youtube.com/playlist?list={uploads}"
    d = _yt_json(["-J", "--flat-playlist", "--playlist-end", str(per), "--no-warnings", url], timeout=120)
    out = []
    if not d:
        return out
    for e in (d.get("entries") or []):
        vid = str(e.get("id") or "").strip()
        if YTID_RE.match(vid):
            out.append({"id": vid, "channel_id": channel_id})
    return out


def fetch_stats(video_id):
    """1動画のメタ+統計を yt-dlp -J(DLしない)で取る。取れた辞書 or None。"""
    url = f"https://www.youtube.com/watch?v={video_id}"
    d = _yt_json(["-J", "--skip-download", "--no-playlist", "--no-warnings", url], timeout=90)
    if not d:
        return None
    up = str(d.get("upload_date") or "")           # YYYYMMDD
    published = f"{up[0:4]}-{up[4:6]}-{up[6:8]}" if len(up) == 8 else ""
    return {
        "video_id": video_id,
        "channel_id": str(d.get("channel_id") or ""),
        "title": d.get("title") or "",
        "views": d.get("view_count"),
        "likes": d.get("like_count"),
        "comments": d.get("comment_count"),
        "durationSec": int(d.get("duration") or 0),
        "publishedAt": published,
    }


def write_pulse(note):
    os.makedirs(os.path.dirname(PULSE), exist_ok=True)
    with open(PULSE, "w", encoding="utf-8") as f:
        f.write("# 競合_日次 PC収集(comp_daily)の脈(毎回上書き)\n\n"
                "最終走行: %s\n%s\n" % (dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S"), note))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true", help="疎通のみ(windowVids/watch件数を出す・yt-dlp不使用)")
    ap.add_argument("--dry", action="store_true", help="取得まで走るが書き戻さない")
    ap.add_argument("--no-discover", dest="discover", action="store_false", default=True,
                    help="新着discoveryをやらず既存windowVidsだけをスナップ")
    ap.add_argument("--max", type=int, default=MAX_FETCH, help="yt-dlp -J を叩く動画数の上限")
    ap.add_argument("--per-channel", type=int, default=DISCOVER_PER_CHANNEL, help="1chあたりdiscovery本数")
    args = ap.parse_args()

    t0 = time.time()
    pend = gas_get("action=comp_daily_pending")
    if not pend.get("ok"):
        note = f"comp_daily_pending 応答不正: {pend.get('error') or pend}"
        print(f"ABORT: {note}")
        write_pulse(f"状態: fail(疎通)\n{note}")
        return 2
    channels = pend.get("channels", [])
    window = pend.get("windowVids", [])
    print(f"windowVids: {len(window)}件 / watchチャンネル: {len(channels)}件 / 追跡窓: {pend.get('windowDays')}日")

    if args.check:
        write_pulse(f"状態: ok(--check)\nwindowVids={len(window)} / watch={len(channels)}")
        return 0

    if not have_ytdlp():
        note = "yt-dlp が無い(python -m pip install -U yt-dlp)"
        print(f"ABORT: {note}")
        write_pulse(f"状態: fail(前提)\n{note}")
        return 3

    # 対象集合= 既存windowVids ∪ discovery新着。channel_id を引けるよう対応表を作る。
    ch_of = {}
    targets = []      # video_id の順序付き集合(重複排除)
    seen = set()
    for w in window:
        vid = str(w.get("videoId") or "").strip()
        if YTID_RE.match(vid) and vid not in seen:
            seen.add(vid); targets.append(vid); ch_of[vid] = str(w.get("channelId") or "")

    known_before = set(seen)   # 既存台帳(=新着判定の基準)
    if args.discover:
        for c in channels:
            found = discover(c.get("uploads", ""), c.get("channelId", ""), args.per_channel)
            for e in found:
                vid = e["id"]
                if vid not in seen:
                    seen.add(vid); targets.append(vid); ch_of[vid] = e["channel_id"]
        print(f"discovery後の対象: {len(targets)}件(うち新着候補 {len(targets) - len(known_before)}件)")

    if len(targets) > args.max:
        print(f"対象 {len(targets)}件 > 上限 {args.max}件 → 先頭{args.max}件に絞る(残りは翌日)")
        targets = targets[:args.max]

    cutoff = dt.date.today() - dt.timedelta(days=int(pend.get("windowDays") or 30))
    daily, new_videos = [], []
    got = 0
    for vid in targets:
        s = fetch_stats(vid)
        if not s:
            continue
        got += 1
        cid = s["channel_id"] or ch_of.get(vid, "")
        daily.append({"videoId": vid, "channelId": cid,
                      "views": s["views"], "likes": s["likes"], "comments": s["comments"]})
        # 既存台帳に無く、公開が追跡窓内の動画だけを新着として台帳へ渡す(窓外は日次だけ・台帳に足さない)。
        if vid not in known_before and s["publishedAt"]:
            try:
                if dt.date.fromisoformat(s["publishedAt"]) >= cutoff:
                    new_videos.append({"video_id": vid, "channel_id": cid, "title": s["title"],
                                       "publishedAt": s["publishedAt"], "durationSec": s["durationSec"]})
            except ValueError:
                pass
        time.sleep(0.3)

    elapsed = int((time.time() - t0) * 1000)
    print(f"取得: {got}/{len(targets)}件 / 日次行 {len(daily)} / 新着候補 {len(new_videos)}")

    if args.dry:
        print("--dry のため書き戻さない")
        for d in daily[:5]:
            print(f"  {d['videoId']}: views={d['views']} likes={d['likes']} comments={d['comments']}")
        write_pulse(f"状態: ok(--dry)\n日次{len(daily)} / 新着{len(new_videos)} / 取得{got}/{len(targets)}")
        return 0

    body = {"daily": daily, "videos": new_videos,
            "attempted": len(targets), "channels": len(channels), "elapsedMs": elapsed}
    w = gas_write(body)
    if w.get("ok"):
        print(f"書き戻し: 競合_日次 {w.get('written', 0)}行 / 台帳新規 {w.get('newVideos', 0)} / {w.get('date')}")
        write_pulse(f"状態: ok\n競合_日次へ {w.get('written', 0)}行 append({w.get('date')}) / "
                    f"台帳新規 {w.get('newVideos', 0)} / 取得 {got}/{len(targets)}")
        return 0
    note = f"書き戻し失敗: {w.get('error') or w}"
    print(note)
    write_pulse(f"状態: fail(書き戻し)\n{note}")
    return 4


if __name__ == "__main__":
    sys.exit(main())
