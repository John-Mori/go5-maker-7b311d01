#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""vermix_foresight の自己検査(空PASSにしない=test-must-fail)。

わざと「載せ忘れ(orphan)」「載せ残し(stale)」「版混在」を仕込んだ疑似リポを作り、
検出器がそれぞれ拾うことを確かめる。1つでも取りこぼしたら赤。
"""
import os
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import vermix_foresight as vf  # noqa: E402


def write(path, text):
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)


def make_bump(scripts_dir, targets):
    arr = ", ".join(f'"{t}"' for t in targets)
    write(os.path.join(scripts_dir, "bump.mjs"),
          f'import x from "y";\nconst TARGETS = [{arr}]\n  .map(f => f);\nconst RE = /x/;\n')


def main():
    with tempfile.TemporaryDirectory() as root:
        scripts_dir = os.path.join(root, "scripts")
        os.makedirs(scripts_dir)

        # ① parse_targets: bump.mjs の配列を正しく読むか
        make_bump(scripts_dir, ["index.html", "gone.html"])  # gone.html は実在させない=枯れ
        targets = vf.parse_targets(os.path.join(scripts_dir, "bump.mjs"))
        assert targets == ["index.html", "gone.html"], f"TARGETS解釈が違う: {targets}"

        # 直下HTML: index(対象・v=7) / new(孤児・v=7) / noref(?v=無し=無視) / v=違い(混在)
        write(os.path.join(root, "index.html"), '<script src="app.js?v=7"></script>')
        write(os.path.join(root, "new.html"), '<link href="s.css?v=7"><script src="a.js?v=8">')
        write(os.path.join(root, "noref.html"), "<h1>版参照なし</h1>")

        orphans, stale, versions = vf.scan_root(root, targets)
        onames = sorted(o[0] for o in orphans)
        assert onames == ["new.html"], f"孤児の検出が違う: {onames}"          # 載せ忘れを拾う
        assert stale == ["gone.html"], f"枯れの検出が違う: {stale}"           # 載せ残しを拾う
        assert "noref.html" not in versions, "?v=無しは対象に入れてはいけない"
        all_vers = sorted({v for refs in versions.values() for v in refs})
        assert all_vers == [7, 8], f"混在版の集約が違う: {all_vers}"          # 7と8の混在を見る

        # ② 全部が対象内・単一版なら arm は空(誤発火しないこと)
        make_bump(scripts_dir, ["index.html"])
        os.remove(os.path.join(root, "new.html"))
        os.remove(os.path.join(root, "index.html"))
        write(os.path.join(root, "index.html"), '<script src="app.js?v=7"></script>')
        t2 = vf.parse_targets(os.path.join(scripts_dir, "bump.mjs"))
        o2, s2, v2 = vf.scan_root(root, t2)
        assert o2 == [] and s2 == [], f"クリーンで誤発火した: orphans={o2} stale={s2}"

    print("PASS: 孤児(載せ忘れ)/枯れ(載せ残し)/混在 を検出・クリーンで無発火")


if __name__ == "__main__":
    main()
