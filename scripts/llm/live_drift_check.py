#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""live_drift_check.py — ローカル作業ツリーが LIVE(origin/main)から遅れていないか見る。

なぜ在るか(2026-09-02 SE日次レビュー / Type-C 再発防止):
  同じ日に、同じ「画像の大きさ適正化」依頼へ研究室が食い違う返しをした——
  片方は LIVE(origin/main=v967・grid化済)を見て「もう直ってる/古いキャッシュ」と返し、
  片方はローカル作業ツリー(v937・旧flex版)を見て "新しい修正" を積んだ(9874f87)。
  ローカル main が origin/main より 13 遅れ・フロントが旧版のままだったのが真因。
  遅れたローカルを実物と誤認すると (a)「もう直ってる」の誤報告 (b) push すれば LIVE を巻き戻す
  退行、の両方が起きる。だから "直った/もうLIVEに入ってる" と言う前・フロントを触る前に
  必ず 実物(LIVE)との差 をこの目で1回見る。

やること(読むだけ・破壊しない):
  - ローカル作業ツリーの ?v=(scripts/bump.mjs --check)
  - LIVE の ?v=(git show origin/main:index.html)
  - main vs origin/main の ahead/behind
  - フロント主要ファイルが LIVE と一致しているか

戻り値: 0=同期(遅れなし) / 2=LIVEに遅れあり(誤報告・退行push の危険) / 1=検査不能
"""
import re
import subprocess
import sys

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

FRONT_FILES = ["index.html", "app.js", "style.css", "js/candidates.js"]


def run(cmd):
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")
        return p.returncode, (p.stdout or ""), (p.stderr or "")
    except Exception as e:
        return 1, "", str(e)


def v_of(text):
    m = re.search(r"app\.js\?v=(\d+)", text or "")
    return int(m.group(1)) if m else None


def main():
    # LIVE を取り込む(失敗しても続行=オフラインでも local 側は見える)
    run(["git", "fetch", "origin", "main", "-q"])

    _, chk, _ = run(["node", "scripts/bump.mjs", "--check"])
    local_v = None
    m = re.search(r"[Vv]=(\d+)", chk)
    if m:
        local_v = int(m.group(1))

    _, live_html, _ = run(["git", "show", "origin/main:index.html"])
    live_v = v_of(live_html)

    ahead = behind = None
    rc, lr, _ = run(["git", "rev-list", "--left-right", "--count", "main...origin/main"])
    if rc == 0:
        parts = lr.split()
        if len(parts) == 2:
            ahead, behind = int(parts[0]), int(parts[1])

    # フロントが LIVE と一致しているか
    front_diff = []
    for f in FRONT_FILES:
        rc, out, _ = run(["git", "diff", "--quiet", "origin/main", "--", f])
        # --quiet: rc0=同一 / rc1=差分あり
        if rc == 1:
            front_diff.append(f)

    print("== live_drift_check ==")
    print(f"  local ?v = {local_v}   live(origin/main) ?v = {live_v}")
    if ahead is not None:
        print(f"  local main: {ahead} ahead / {behind} behind  origin/main")
    if front_diff:
        print(f"  フロントが LIVE と相違: {', '.join(front_diff)}")

    behind_ver = (local_v is not None and live_v is not None and local_v < live_v)
    behind_git = (behind is not None and behind > 0)

    if behind_ver or behind_git:
        print()
        print("  [!!] ローカルは LIVE より遅れている。")
        print("       → 『もう直ってる/LIVEに入ってる』と断定する前に、必ず origin/main の実物で確認する。")
        print("       → このツリーからフロントを push しない(LIVE を巻き戻す退行になる)。")
        print("       → 反映するなら detached worktree で origin/main から cherry-pick して HEAD:main へ。")
        return 2

    print("  OK: ローカルは LIVE に遅れていない。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
