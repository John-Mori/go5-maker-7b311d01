#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""人格の窓(名義とアイコン)が生きているかの突合 (QA回帰・A-7)。
初出根拠: 2026-07-16 に15部屋のmanifest欠落を発見 (「キャラの言動の設定が生きてない」の正体)。

★2026-08-18 (イージス研究室) 測る単位を **部屋 → 人格** へ変えた。
  旧仕様は「dept ごとに personas/<dept>/persona_manifest.yml が在るか」を見ていた。
  実測でその前提が崩れている:
    ① persona_send は manifest を **glob で全フォルダ横断**して読む
       (persona_send.py:141 / :222)。部屋ごとのフォルダは要件ではない。
    ② 既存の人格を借りるだけの横断部屋(軍議=三笘薫・アーモンドアイ・モドリッチ…/
       ククール-なかま会話/1分shorts)は、自前フォルダを持たなくても名義もアイコンも出る。
       旧仕様はこの3部屋を「欠落」としてFAILさせていたが、**画面は壊れていない**。
  → 見るのは「その部屋が名乗りうる人格が、実際に解決できるか」。2段に分ける:
    **FAIL(実画面が壊れる)**= persona_avatars.json にキーが無い人格。
      persona_send.resolve_persona がそのまま素通しし、デフォルトアイコン+生綴りで投稿される
      (persona_send.py:264 が stderr へ大声で警告する状態そのもの)。
    **既知の欠け(ベースライン)**= 顔は出るが manifest の `name:` に項が無い人格。
      口調・名義の正本(dept_daemon.py:1448 が「正本」と指す先)が無い状態。
      新しく増えた分だけFAILにする=旧仕様の回帰の意味論をそのまま引き継ぐ。
  ★旧・部屋単位のベースライン known_gaps.json は**この検査からは読まれなくなった**。
    消さずに残す(C-003=退避。2026-07-16〜08-18 の部屋単位時代の記録そのもの)。
    QA部門の引き継ぎ書 local/llm/handoff_qa-reviewer.md が正本として指しているので、
    ★あちらの記述の更新はQA部門の持ち場(この検査から勝手に書き換えない)。
"""
import json
import os
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.normpath(os.path.join(HERE, "..", "..", "..", ".."))
# 2026-07-18 移転: persona正本は 00_AI-HQ/departments/hr/personas/ へ(ORG-44対策)
HQ_ROOT = os.path.normpath(os.path.join(ROOT, "..", "00_AI-HQ"))
PERSONA_DIR = os.path.join(HQ_ROOT, "departments", "hr", "personas")
BASELINE = os.path.join(HERE, "known_gaps_personas.json")


def _load_baseline():
    try:
        return set(json.load(open(BASELINE, encoding="utf-8")))
    except Exception:
        return set()


def main():
    sys.path.insert(0, os.path.join(ROOT, "scripts", "llm"))
    sys.path.insert(0, os.path.join(ROOT, "scripts", "discord"))
    import dept_daemon as D
    import persona_send as P

    # manifest に `name:` の項がある人格(=口調・名義の正本が在る)
    import glob
    names = set()
    for base in (PERSONA_DIR, os.path.join(ROOT, "docs", "departments", "personas")):
        for p in glob.glob(os.path.join(base, "**", "persona_manifest.yml"), recursive=True):
            for line in open(p, encoding="utf-8", errors="replace"):
                s = line.strip()
                if s.startswith("name:") and "display_name:" not in s:
                    names.add(s.split(":", 1)[1].strip())
    avatars = set()
    if os.path.exists(P.AVATARS_FILE):
        avatars = set(json.load(open(P.AVATARS_FILE, encoding="utf-8")).keys())

    broken, gaps, total = [], [], 0
    for dept, conf in sorted(D.DEPT_CONF.items()):
        cands = [conf.get("persona")] + [x.get("persona") for x in (conf.get("personas") or [])]
        for nm in sorted({c for c in cands if c}):
            total += 1
            canon = P.resolve_persona(nm)
            if canon not in avatars:
                broken.append(f"{canon} ({dept})")
            elif canon not in names:
                gaps.append(canon)

    baseline = _load_baseline()
    new_gaps = sorted(set(gaps) - baseline)
    healed = sorted(baseline - set(gaps))
    if broken or new_gaps:
        print(f"FAIL: check_manifest_coverage (人格{total}件を突合)")
        for b in sorted(set(broken)):
            print(f"  - ★顔も名義も無い: {b} = デフォルトアイコン+生綴りで投稿される(人事部門)")
        for g in new_gaps:
            print(f"  - 新規のmanifest欠け: {g} (顔は出るが口調・名義の正本が無い)")
        return 1
    msg = (f"PASS: check_manifest_coverage (人格{total}件・顔の欠け0件"
           f"・既知のmanifest欠け{len(set(gaps))}件)")
    if healed:
        msg += f" / 進捗: {len(healed)}件が解消 {healed} -> {os.path.basename(BASELINE)} の手動更新を推奨"
    print(msg)
    return 0


if __name__ == "__main__":
    sys.exit(main())
