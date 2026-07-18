#!/usr/bin/env python3
"""人物コンテキストの予算監視(コンテキスト永続化設計書§3.2)。読むだけ・何も変更しない。

解く問題: 各人物のコンテキストが肥大するとセッションが劣化する(人格の声の退行・
INC-97等は、重いコンテキストを積んだ長いセッションの後半で起きている)。
恒久策は3層規律(常読=manifest/詳細=detail/経験=注入しない)+この予算監視。

予算(設計書§3.1):
  manifest(常読層)   8KB/部門   … 起動時・発言前に毎回読む層。ここが重いと全セッションが重い
  detail(詳細層)    48KB/部門   … 必要時のみ読む層。超過したら圧縮サイクル(§3.3)へ
超過は「即バグ」ではない。**圧縮サイクルを回すべき部門の一覧**として出す。

使い方:
  python scripts/maintenance/context_budget.py           # 全部門の予算表
  python scripts/maintenance/context_budget.py --over    # 超過だけ
"""
import argparse
import glob
import os
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.normpath(os.path.join(HERE, "..", ".."))
PERSONAS = os.path.join(ROOT, "docs", "departments", "personas")

BUDGET_MANIFEST = 8_000
BUDGET_DETAIL = 48_000


def main():
    ap = argparse.ArgumentParser(description="人物コンテキスト予算監視(読むだけ)")
    ap.add_argument("--over", action="store_true", help="超過だけ表示")
    args = ap.parse_args()

    rows = []
    for d in sorted(glob.glob(os.path.join(PERSONAS, "*"))):
        if not os.path.isdir(d):
            continue
        dept = os.path.basename(d)
        man = sum(os.path.getsize(f) for f in glob.glob(os.path.join(d, "*manifest*")))
        det = sum(os.path.getsize(f) for f in glob.glob(os.path.join(d, "*detail*")))
        other = sum(os.path.getsize(f) for f in glob.glob(os.path.join(d, "*"))
                    if os.path.isfile(f) and "manifest" not in f and "detail" not in f)
        over_m = man > BUDGET_MANIFEST
        over_d = det > BUDGET_DETAIL
        rows.append((dept, man, det, other, over_m, over_d))

    over_rows = [r for r in rows if r[4] or r[5]]
    show = over_rows if args.over else rows

    print(f"人物コンテキスト予算表 (manifest≦{BUDGET_MANIFEST // 1000}KB / detail≦{BUDGET_DETAIL // 1000}KB)")
    print(f"{'部門':<20} {'manifest':>10} {'detail':>10} {'その他':>8}  判定")
    for dept, man, det, other, om, od in show:
        marks = []
        if om:
            marks.append("★manifest超過(常読層が重い=全発言に効く。最優先で圧縮)")
        if od:
            marks.append("detail超過(圧縮サイクル§3.3へ)")
        mark = " ".join(marks) if marks else "OK"
        print(f"{dept:<20} {man / 1000:>8.1f}KB {det / 1000:>8.1f}KB {other / 1000:>6.1f}KB  {mark}")

    n_over = len(over_rows)
    print(f"\n超過 {n_over}/{len(rows)} 部門。超過は即バグではない。圧縮サイクル(detailの過去経緯を"
          f" local/persona_context/<dept>_history.md へ移す)を回す目安。")
    return 2 if n_over else 0


if __name__ == "__main__":
    sys.exit(main())
