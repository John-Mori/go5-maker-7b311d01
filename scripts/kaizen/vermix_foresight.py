#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""版ずれ先読み(改善提案部門・自室ツール / C-019)。

Chami依頼(2026-08-22 msg1540735867=「いいよ」で③を承認)=
  「スキル化に加えて、よりPythonでできる事を」。Claudeが目で拾っていた
  版ずれの兆しを、デプロイ前にPythonで先に鳴らす。

★bump.mjs の守備範囲の"外側"を見る道具(bump.mjs と役割を分ける=重複させない)。
  bump.mjs は TARGETS 配列(index.html + 分割4ページ)の中でしか ?v= を見ない=
  **TARGETS へ載せ忘れた新ルートHTMLは、bump も --check も素通りする**。
  そのままだと CIスモーク(配信版の全一致検査)が20分後に赤で気付く
  (bump.mjs L22-23 が自認する既知の穴)。→ **その載せ忘れを、デプロイ前に拾う**。

見るもの(読み取りのみ・直さない)=
  ①孤児(orphan)= リポジトリ直下(GitHub Pagesのルート)に ?v= を持つHTMLが在るのに
    bump.mjs の TARGETS に無い=バンプの対象外で古いJSが配られ続ける候補。**これが本命**。
  ②枯れ(stale)= TARGETS に載っているのに実ファイルが無い(=綴り違い/退役の載せ残し)。
  ③混在(mix)= 全参照が同一Nか(bump.mjs も見るが、孤児を含めた"全ルート"で見るのがこちら)。

範囲の線引き= **リポジトリ直下のHTMLだけ**(Pagesのルートが配信対象)。
  schedule/ は別サブシステム(.verstamp.json / check_schedule_ver.mjs が別途管理)= 対象外。
  node_modules/ local/ 産業廃棄物/ guide_HTML/ gas/ は配信面でない= 対象外。

終了コード= 孤児 or 枯れ が1件でもあれば 1(混在のみは警告=0。混在の是正入口は bump.mjs)。
  → デプロイ前の門番に噛ませられる(--warn-only で監視専用にも)。

使い方:
  python scripts/kaizen/vermix_foresight.py            # 直下HTMLを検査
  python scripts/kaizen/vermix_foresight.py --warn-only
  python scripts/kaizen/vermix_foresight.py --root <dir>  # 検査対象の根(既定=repo直下)
"""
import argparse
import glob
import os
import re
import sys

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
VER_RE = re.compile(r"\?v=(\d+)")


def parse_targets(bump_path):
    """bump.mjs から TARGETS 配列のファイル名を読む(バンプ対象=正本)。

    ここを自前の別リストに持たない(=二重管理は必ずずれる)。bump.mjs を1つの真実にする。
    """
    with open(bump_path, "r", encoding="utf-8") as f:
        src = f.read()
    m = re.search(r"const\s+TARGETS\s*=\s*\[([^\]]*)\]", src)
    if not m:
        return None
    return [s for s in re.findall(r'"([^"]+\.html)"', m.group(1))]


def ver_refs(path):
    """1ファイルの ?v= 参照の版数リスト。読めなければ空。"""
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            return [int(x) for x in VER_RE.findall(f.read())]
    except OSError:
        return []


def scan_root(root, targets):
    """root直下のHTMLを見て (orphans, stale, versions, covered_present) を返す。

    orphans = [(ファイル名, 参照数, 版集合)]  … ?v=在り かつ TARGETS外
    stale   = [ファイル名]                    … TARGETS在り かつ 実ファイル無し
    versions= {ファイル名: [版数,...]}         … ?v=を持つ全ファイル(混在判定用)
    """
    tset = set(targets)
    versions = {}
    orphans = []
    for path in sorted(glob.glob(os.path.join(root, "*.html"))):
        name = os.path.basename(path)
        refs = ver_refs(path)
        if not refs:
            continue
        versions[name] = refs
        if name not in tset:
            orphans.append((name, len(refs), sorted(set(refs))))
    stale = [t for t in targets if not os.path.exists(os.path.join(root, t))]
    return orphans, stale, versions


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", default=ROOT, help="検査対象の根(既定=repo直下)")
    ap.add_argument("--warn-only", action="store_true")
    a = ap.parse_args()

    bump = os.path.join(a.root, "scripts", "bump.mjs")
    if not os.path.exists(bump):
        bump = os.path.join(ROOT, "scripts", "bump.mjs")  # --root がrepo外でも正本は拾う
    targets = parse_targets(bump)
    if targets is None:
        print(f"⚠ bump.mjs の TARGETS を読めない: {bump}(書式が変わった可能性)。検査できない。")
        sys.exit(2)

    orphans, stale, versions = scan_root(a.root, targets)
    all_vers = sorted({v for refs in versions.values() for v in refs})

    print(f"# 版ずれ先読み(bump対象 {len(targets)}ページ / 直下の?v=保持HTML {len(versions)}ファイル)")
    print(f"  bump.mjs TARGETS= {', '.join(targets)}")

    if orphans:
        print(f"\n## ⚠ 孤児(バンプ対象外の?v=保持HTML)= {len(orphans)}件 ★載せ忘れ候補")
        for name, n, vs in orphans:
            print(f"- `{name}`(?v= {n}箇所 / 版 {vs})")
        print("  → scripts/bump.mjs の TARGETS 配列へ追記が要る(でないとCIスモークが版混在でfail)。")
    else:
        print("\n## 孤児= 0件(直下の?v=保持HTMLは全て bump 対象内)")

    if stale:
        print(f"\n## ⚠ 枯れ(TARGETSに在るが実ファイル無し)= {len(stale)}件")
        for t in stale:
            print(f"- `{t}`(綴り違い/退役の載せ残し?)")

    print(f"\n## 版の一致= {'混在なし v=' + str(all_vers[0]) if len(all_vers) == 1 else '混在あり: ' + ', '.join(map(str, all_vers))}")
    if len(all_vers) > 1:
        print("  → 是正入口は bump.mjs(`node scripts/bump.mjs --to <N>` で全参照を揃える)。")

    hard = len(orphans) + len(stale)
    print(f"\n---\n孤児 {len(orphans)} / 枯れ {len(stale)} / 版 {len(all_vers)}種")
    if hard and not a.warn_only:
        sys.exit(1)


if __name__ == "__main__":
    main()
