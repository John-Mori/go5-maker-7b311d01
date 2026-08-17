#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""指定videoIdを狙い撃ちで視覚化する(comp_frame_pendingの順序に依らず、名指しのchを取る)。
comp_frames.py の grab_frame/ask_pro(2キー束ね)/gas_write をそのまま流用。
使い方: python scripts/comp/target_frames.py VID1 VID2 ...  [--dry]
実名・videoIdは公開repo禁止(このスクリプトは引数で受けハードコードしない)。
"""
import argparse, os, shutil, sys, tempfile, time
HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPTS = os.path.normpath(os.path.join(HERE, ".."))
sys.path.insert(0, SCRIPTS)
import comp_frames as cf  # noqa: E402
sys.path.insert(0, os.path.join(SCRIPTS, "behop"))
import behop  # noqa: E402
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("vids", nargs="+")
    ap.add_argument("--dry", action="store_true")
    ap.add_argument("--dur", type=float, default=5.0, help="尺の既定(Shortsは~5s。<4.6で末尾フォールバック)")
    args = ap.parse_args()

    key = behop._read(behop.KEY_FILE, "ベホップ用APIキー")
    keys = [("ベホップ", key)]
    try:
        homin = open(os.path.join(cf.ROOT, "local", "gemini_api_key.txt"), encoding="utf-8").read().strip()
        if homin and homin != key:
            keys.append(("ホイミン", homin))
    except OSError:
        pass

    results, kidx = [], 0
    for vid in args.vids:
        work = tempfile.mkdtemp(prefix="tf_")
        try:
            frame = cf.grab_frame(vid, args.dur, work)
            if not frame:
                print(f"  {vid}: フレーム取得失敗(スキップ)")
                continue
            text, status = None, None
            while kidx < len(keys):
                text, status = behop.ask_pro(keys[kidx][1], cf.VISION_PROMPT, [frame], cf.BASE_MODEL,
                                             tag="target_frames", who=behop.bundle_of(keys[kidx][0]))
                if status == "quota":
                    print(f"  {vid}: {keys[kidx][0]}枠尽き(429)→次キー")
                    kidx += 1
                    continue
                break
            if kidx >= len(keys):
                print(f"  {vid}: 全キー429。打ち切り。")
                break
            if status != "ok":
                print(f"  {vid}: 視覚失敗({status})")
                continue
            v = cf.parse_vision(text)
            if not v:
                print(f"  {vid}: パース失敗")
                continue
            results.append({"videoId": vid, "frameText": v["frameText"], "panelDesc": v["panelDesc"]})
            print(f"  {vid}: frameText={v['frameText'][:36]!r}\n        panelDesc={v['panelDesc'][:44]!r}")
        finally:
            shutil.rmtree(work, ignore_errors=True)
        time.sleep(1.0)

    print(f"視覚化 {len(results)}/{len(args.vids)} 件")
    if args.dry or not results:
        return 0
    w = cf.gas_write(results)
    print(f"書き戻し: {w.get('written', 0)}件" if w.get("ok") else f"書き戻し失敗: {w.get('error') or w}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
