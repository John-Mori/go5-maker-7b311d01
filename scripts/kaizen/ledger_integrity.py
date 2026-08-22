#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""台帳(JSONL)壊れ行検査(改善提案部門・自室ツール / C-019)。

Chami依頼(2026-08-22 msg1540622217=「任せる」で②を承認)=
  Claudeが目で見つけていた台帳の破損を、Pythonで毎回自動検出する。

背景= 2026-08-19に change_log.jsonl L1051 が**二重エンコードで壊れ**、tally が
読めなくなった(手で発見→隔離)。BOM混入で dept=system-engineer の実記録1件が
どの読み手からも永久に見えなかった事故(commit 1b4aa38)もある。
PowerShell の Out-File/`>` は既定でBOM付きUTF-8を書く=**また起きる**。
→ 「壊れたら黙って消える」を、毎回バイト単位で機械検出する常設の目。

検出(バイト単位=undecodableも捕える)=
  ①undecodable = UTF-8として復号できないバイト列(=二重エンコード/文字化けの生バイト)
  ②invalid-json = 復号はできるが json.loads で落ちる行
  ③bom = 行頭にBOM(﻿)。除去すれば読めるが、素の json.loads は落ちる=潜在事故

★これは検査のみ。**直さない**(修復は .bak を取って人が慎重にやる=C-003)。
  隔離の実務手順= docs/departments/kaizen-analyst/ 側(L1051隔離の記録参照)。

使い方:
  python scripts/kaizen/ledger_integrity.py                 # local/llm/*.jsonl 全部
  python scripts/kaizen/ledger_integrity.py path1 path2 ...  # 対象を明示
  python scripts/kaizen/ledger_integrity.py --warn-only      # 壊れ有りでも exit 0
終了コード= 壊れ(undecodable/invalid-json)が1件でもあれば 1(BOMのみは警告=0)。
  → 追記の前・毎朝の門番に噛ませられる(--warn-only で監視専用にも)。
"""
import argparse
import glob
import json
import os
import sys

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
BOM = b"\xef\xbb\xbf"


def scan(path):
    """1ファイルをバイトで読み、(good, issues) を返す。issues=(行番号, 種別, 詳細)。"""
    issues = []
    good = 0
    with open(path, "rb") as f:
        raw = f.read()
    if not raw:
        return 0, issues
    for i, bline in enumerate(raw.split(b"\n"), 1):
        b = bline.strip(b"\r")
        if not b.strip():
            continue
        had_bom = b.startswith(BOM)
        if had_bom:
            b = b[len(BOM):]
        try:
            s = b.decode("utf-8")
        except UnicodeDecodeError as e:
            # 復号不能=二重エンコード/文字化けの生バイト。何バイト目で落ちたかを出す。
            issues.append((i, "undecodable",
                           f"byte {e.start} 0x{b[e.start]:02x} が不正(len={len(b)})"))
            continue
        s = s.strip()
        if not s:
            continue
        try:
            json.loads(s)
        except json.JSONDecodeError as e:
            issues.append((i, "invalid-json", str(e)))
            continue
        if had_bom:
            # 復号後は読めるが、素の loads は BOM で落ちる=潜在事故
            issues.append((i, "bom", "行頭にBOM(﻿)。除去すれば読めるが素のloadsは落ちる"))
        good += 1
    return good, issues


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("paths", nargs="*", help="省略時= local/llm/*.jsonl")
    ap.add_argument("--warn-only", action="store_true")
    a = ap.parse_args()

    targets = a.paths or sorted(glob.glob(os.path.join(ROOT, "local", "llm", "*.jsonl")))
    print(f"# 台帳壊れ行検査({len(targets)}ファイル)")
    total_bad = 0   # undecodable + invalid-json(=真の壊れ)
    total_bom = 0
    dirty_files = []
    for p in targets:
        good, issues = scan(p)
        if not issues:
            continue
        hard = [x for x in issues if x[1] != "bom"]
        bom = [x for x in issues if x[1] == "bom"]
        total_bad += len(hard)
        total_bom += len(bom)
        dirty_files.append(os.path.relpath(p, ROOT))
        print(f"\n## {os.path.relpath(p, ROOT)}(正常{good}行 / 要手当て{len(hard)} / BOM{len(bom)})")
        for ln, kind, detail in issues[:20]:
            print(f"- L{ln} [{kind}] {detail}")
        if len(issues) > 20:
            print(f"- …他 {len(issues) - 20} 件")

    print(f"\n---\n壊れ(undecodable/invalid-json)= **{total_bad}件** / BOM= {total_bom}件"
          f" / 汚れファイル {len(dirty_files)}")
    if total_bad == 0 and total_bom == 0:
        print("全台帳クリーン。")
    if total_bad and not a.warn_only:
        sys.exit(1)


if __name__ == "__main__":
    main()
