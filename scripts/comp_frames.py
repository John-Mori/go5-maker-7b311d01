#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""競合Shorts 代表フレーム取得  (2026-07-29 改修部門α / Chami指示・分析部アーモンドアイ経由)

やること: GASの 競合_動画 から未取得のShortを引き、各1本の 4.5秒付近1枚 を抜き、
  ベホップ(強Gemini)で ①焼き込みのフック文字 ②コマ画像の中身の要約 を起こしてシートへ書き戻す。

方針(Chami条件):
  - 全編DLしない。yt-dlp --download-sections で 4.5秒付近の一瞬だけ取る。
  - 尺が4.5秒未満の動画は末尾フレームに落とす。取得位置 4.5秒 はChami確定。
  - 競合ID/実名は公開repoに出さない(このスクリプトはIDを実行時にGASから引くだけ・保持しない)。
  - ベホップのキー等の秘密は front/repo/ログに出さない。

前提ツール: ffmpeg(導入済) / yt-dlp(未導入なら `python -m pip install -U yt-dlp`)。
使い方:
  python scripts/comp_frames.py --check           # 疎通確認のみ(pending件数を出す・DL/生成しない)
  python scripts/comp_frames.py --limit 5         # 5本処理して書き戻す
  python scripts/comp_frames.py --limit 5 --dry   # DL＋視覚まで走るが書き戻さない(結果を印字)
"""
import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.normpath(os.path.join(HERE, ".."))
sys.path.insert(0, os.path.join(HERE, "behop"))
import behop  # noqa: E402  (ベホップの vision 経路を再利用: inline_data で画像を渡す)

GAS = json.load(open(os.path.join(ROOT, "scripts", "gas_deploy_config.json"), encoding="utf-8"))["execUrl"]
SECTION_START = 4.0       # DLする区間の開始秒(4.5をこの中に含める)
SECTION_END = 5.4         # DLする区間の終了秒
TARGET_OFFSET = 4.5 - SECTION_START   # 区間先頭からの目的フレーム位置(=0.5秒)
SHORT_TAIL_EPS = 0.15     # 短尺動画で末尾フレームを取る時の末尾からの戻し(秒)

VISION_PROMPT = (
    "この画像は縦型ショート動画(9:16)の1コマです。次を日本語で答え、JSONだけを返してください。\n"
    '{"frameText":"画面に焼き込まれている文字(フック/テロップ)をそのまま書き起こす。無ければ空文字",'
    '"panelDesc":"コマ(イラスト/写真)の中身を1〜2文で要約。誰が・何をしている・雰囲気"}\n'
    "余計な説明やコードフェンスは付けず、JSONオブジェクト1つだけを返す。"
)


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


def gas_write(items, tries=3):
    """comp_frame_write で書き戻す。SHARED_SECRET候補を順に試す。"""
    last = {}
    for sec in _secrets():
        payload = {"op": "comp_frame_write", "secret": sec, "items": items}
        for _ in range(tries):
            try:
                req = urllib.request.Request(GAS, data=json.dumps(payload).encode("utf-8"),
                                             headers={"Content-Type": "application/json"})
                with urllib.request.urlopen(req, timeout=90) as r:
                    last = json.loads(r.read())
                break
            except Exception:
                time.sleep(3)
        if last.get("ok"):
            return last
        if last.get("error") and last.get("error") != "bad_secret":
            break
    return last


def have_ytdlp():
    return shutil.which("yt-dlp") is not None or _ytdlp_module()


def _ytdlp_module():
    try:
        import yt_dlp  # noqa: F401
        return True
    except Exception:
        return False


def _run(cmd):
    return subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).returncode == 0


def ytdlp_cmd():
    if shutil.which("yt-dlp"):
        return ["yt-dlp"]
    return [sys.executable, "-m", "yt_dlp"]


def grab_frame(video_id, dur, workdir):
    """4.5秒付近(尺不足なら末尾)の1枚を frame.jpg として書き出す。成功でパス、失敗でNone。"""
    url = f"https://www.youtube.com/watch?v={video_id}"
    seg = os.path.join(workdir, "seg.%(ext)s")
    short = dur and dur > 0 and dur < 4.6
    section = f"*0-{max(dur, 1):.1f}" if short else f"*{SECTION_START}-{SECTION_END}"
    dl = ytdlp_cmd() + [
        "--no-playlist", "--force-keyframes-at-cuts",
        "--download-sections", section,
        "-f", "bestvideo[height<=720]/best[height<=720]/best",
        "-o", seg, url,
    ]
    if not _run(dl):
        return None
    files = [f for f in os.listdir(workdir) if f.startswith("seg.")]
    if not files:
        return None
    segfile = os.path.join(workdir, files[0])
    frame = os.path.join(workdir, "frame.jpg")
    if short:
        ff = ["ffmpeg", "-y", "-sseof", f"-{SHORT_TAIL_EPS}", "-i", segfile,
              "-frames:v", "1", "-q:v", "3", frame]
    else:
        # 出力側シーク=区間先頭からデコードしてフレーム精度で TARGET_OFFSET を取る(PTS再設定に強い)
        ff = ["ffmpeg", "-y", "-i", segfile, "-ss", f"{TARGET_OFFSET}",
              "-frames:v", "1", "-q:v", "3", frame]
    if not _run(ff) or not os.path.exists(frame):
        # 末尾フォールバック(短尺誤判定・区間がPTSずれで空になった時)
        ff2 = ["ffmpeg", "-y", "-sseof", f"-{SHORT_TAIL_EPS}", "-i", segfile,
               "-frames:v", "1", "-q:v", "3", frame]
        if not _run(ff2) or not os.path.exists(frame):
            return None
    return frame


def parse_vision(text):
    """ベホップの返答からJSONを取り出す。コードフェンス/前後の地の文を許容。"""
    if not text:
        return None
    m = re.search(r"\{.*\}", text, re.S)
    if not m:
        return None
    try:
        d = json.loads(m.group(0))
    except Exception:
        return None
    ft = str(d.get("frameText", "") or "").strip()
    pd = str(d.get("panelDesc", "") or "").strip()
    if not ft and not pd:
        return None
    return {"frameText": ft, "panelDesc": pd}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=10)
    ap.add_argument("--check", action="store_true", help="pending件数だけ出す(DL/生成しない)")
    ap.add_argument("--dry", action="store_true", help="DL＋視覚まで走るが書き戻さない")
    args = ap.parse_args()

    pend = gas_get(f"action=comp_frame_pending&limit={args.limit}")
    if not pend.get("ok"):
        print(f"ABORT: comp_frame_pending 応答不正: {pend.get('error') or pend}")
        return 2
    items = pend.get("pending", [])
    print(f"pending: {pend.get('count', len(items))}件")
    if args.check:
        return 0
    if not items:
        return 0

    if not have_ytdlp():
        print("ABORT: yt-dlp が無い。導入: python -m pip install -U yt-dlp")
        return 3
    if not shutil.which("ffmpeg"):
        print("ABORT: ffmpeg が無い。")
        return 3

    key = behop._read(behop.KEY_FILE, "ベホップ用APIキー")
    model, avail = behop.pick_model(key)

    results, ok = [], 0
    for it in items:
        vid = it.get("videoId", "")
        dur = float(it.get("durationSec") or 0)
        if not vid:
            continue
        work = tempfile.mkdtemp(prefix="cf_")
        try:
            frame = grab_frame(vid, dur, work)
            if not frame:
                print(f"  {vid}: フレーム取得失敗(スキップ)")
                continue
            text, used = behop.ask(key, model, VISION_PROMPT, [frame], avail)
            v = parse_vision(text)
            if not v:
                print(f"  {vid}: 視覚結果パース失敗(スキップ) model={used}")
                continue
            results.append({"videoId": vid, "frameText": v["frameText"], "panelDesc": v["panelDesc"]})
            ok += 1
            print(f"  {vid}: frameText={v['frameText'][:24]!r} panelDesc={v['panelDesc'][:32]!r}")
        finally:
            shutil.rmtree(work, ignore_errors=True)
        time.sleep(1.0)

    print(f"視覚化 {ok}/{len(items)} 件")
    if args.dry:
        print("--dry のため書き戻さない")
        return 0
    if not results:
        return 0
    w = gas_write(results)
    if w.get("ok"):
        print(f"書き戻し: {w.get('written', 0)}件")
        return 0
    print(f"書き戻し失敗: {w.get('error') or w}")
    return 4


if __name__ == "__main__":
    sys.exit(main())
