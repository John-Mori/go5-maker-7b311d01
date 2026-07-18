#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""窓が要る部屋 × persona_manifest.yml の突合 (QA回帰・A-7)。
回帰の意味論: known_gaps.json (既知の欠落ベースライン) に**無い**新規欠落だけをFAILにする。
既知の欠落が埋まったら「進捗」として報告し、ベースラインの手動更新を促す (勝手に書き換えない)。
初出根拠: 2026-07-16 に15部屋のmanifest欠落を発見 (「キャラの言動の設定が生きてない」の正体)。
"""
import json
import os
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.normpath(os.path.join(HERE, "..", "..", "..", ".."))
NOWIN = {"router", "llm-growth", "gemini"}  # 窓が不要な部屋 (inbox_poller.py の対象外指定と同期)
BASELINE = os.path.join(HERE, "known_gaps.json")


def main():
    reg = os.path.join(ROOT, "local", "discord_channels.json")
    chs = json.load(open(reg, encoding="utf-8"))
    depts = sorted({str(c.get("dept", "")) for c in chs} - NOWIN)
    missing = [d for d in depts
               if not os.path.exists(os.path.join(ROOT, "docs", "departments", "personas", d, "persona_manifest.yml"))]
    try:
        baseline = set(json.load(open(BASELINE, encoding="utf-8")))
    except Exception:
        baseline = set()
    new_missing = sorted(set(missing) - baseline)
    healed = sorted(baseline - set(missing))
    if new_missing:
        print(f"FAIL: check_manifest_coverage 新規のmanifest欠落 {len(new_missing)}件 (回帰)")
        for d in new_missing:
            print("  -", d)
        return 1
    msg = f"PASS: check_manifest_coverage (窓要{len(depts)}dept・既知欠落{len(missing)}件・新規欠落なし)"
    if healed:
        msg += f" / 進捗: {len(healed)}件が解消 {healed} -> known_gaps.json の手動更新を推奨"
    print(msg)
    return 0


if __name__ == "__main__":
    sys.exit(main())
