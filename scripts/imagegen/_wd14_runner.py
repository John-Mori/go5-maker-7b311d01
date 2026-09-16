#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""WD14タガーを**向こうのvenvの中で**走らせる小さな走者(1回1プロセス・標準出力はJSON1行)。

なぜ別プロセスなのか:
  当室(5SecMovieMaker)のPythonには onnxruntime も numpy も入っていない。
  ★裁定(研究室HQ 2026-09-16)=「新規導入はするな」。だから**入れない**。
  タガーの実体と重み一式は `D:\\local-ai\\tools\\wd14\\` に**既に在る**(実測:
  model/model.onnx 378,536,310 bytes・model_manifest.json= SmilingWolf/wd-vit-tagger-v3)ので、
  あちらの `.venv\\Scripts\\python.exe` にこのファイルを渡して走らせる。

★`D:\\local-ai\\` は読み取り専用(同裁定)。このファイルは 5SecMovieMaker 側に置き、
  あちらからは `sys.path` に足して **import するだけ**= 1バイトも書かない。
  (`tag_liked_records.py` は module直下が定数定義だけで、実行は `if __name__ == "__main__"`
   の中に閉じている= import しても向こうの台帳には触らない。実物を読んで確認済み。)

★CPUだけで回す(向こうの `WD14Tagger` が providers=["CPUExecutionProvider"] を指定している)。
  = 画像生成(ComfyUI)のVRAMと喧嘩しない。

使い方: <向こうのpython> _wd14_runner.py --general 0.35 --character 0.85 <画像パス>...
出力  : {"ok": true, "items": [{"path": ..., "general": [...], "character": [...],
                               "rating": "...", "scores": {...}}]}
"""
import argparse
import json
import sys

TOOL_DIR = r"D:\local-ai\tools\wd14"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("paths", nargs="+")
    ap.add_argument("--general", type=float, default=0.35)
    ap.add_argument("--character", type=float, default=0.85)
    a = ap.parse_args()

    if TOOL_DIR not in sys.path:
        sys.path.insert(0, TOOL_DIR)
    from tag_liked_records import WD14Tagger      # 読むだけ(上のコメント参照)

    tagger = WD14Tagger()
    probs = tagger.infer(a.paths)
    items = []
    for path, row in zip(a.paths, probs):
        got = tagger.split_prediction(row, a.general, a.character)
        items.append({
            "path": path,
            "general": got.get("general") or [],
            "character": got.get("character") or [],
            "rating": (got.get("rating") or [""])[0] if got.get("rating") else "",
            "scores": got.get("scores") or {},
        })
    sys.stdout.write(json.dumps({"ok": True, "items": items}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
