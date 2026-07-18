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
import datetime as dt
import glob
import io
import os
import re
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.normpath(os.path.join(HERE, "..", ".."))
PERSONAS = os.path.join(ROOT, "docs", "departments", "personas")

BUDGET_MANIFEST = 8_000
BUDGET_DETAIL = 48_000
WARN_RATIO = 0.8  # 予算の8割で「接近」警告(超過してからでは遅い=Chami指示2026-07-18)

# ★常読層(全セッションが起動時に必ず読む共通ファイル)。人格より先にここが効く:
# 1部門のdetailは1セッションに効くだけだが、常読層は全セッション×毎起動に効く。
# 2026-07-18実測: orchestration.md 64.7KB+CLAUDE.md 25.3KB=毎セッション約90KBを積んでいた。
ALWAYS_READ = [
    # (path, budget, 備考)
    ("CLAUDE.md", 32_000, "全セッション自動読込"),
    ("docs/departments/00_common/orchestration.md", 48_000, "全部門の起動時必読"),
    ("引き継ぎ_Vol7.md", 16_000, "新セッション必読(現行巻)"),
    ("docs/departments/00_common/system-brief.md", 16_000, "qwen知識パックの土台"),
]
# インシデント.md は「該当カテゴリをgrepで参照」運用なので常読予算の対象外(情報表示のみ)
GREP_REFERENCED = ["インシデント.md"]


def verdict(size, budget):
    """OK / 接近(80%超) / 超過 の3段階。"""
    if size > budget:
        return "超過"
    if size > budget * WARN_RATIO:
        return "接近"
    return "OK"


def sections_of(path):
    """mdファイルの見出しごとのサイズ内訳(圧縮候補の特定に使う)。"""
    text = io.open(path, encoding="utf-8").read()
    parts = []
    cur_head, cur_start = "(冒頭)", 0
    for m in re.finditer(r"^#{1,3} .*$", text, re.M):
        parts.append((cur_head, m.start() - cur_start))
        cur_head, cur_start = m.group(0)[:60], m.start()
    parts.append((cur_head, len(text) - cur_start))
    return sorted(parts, key=lambda p: -p[1])


def main():
    ap = argparse.ArgumentParser(description="コンテキスト予算監視(常読層+人格・読むだけ)")
    ap.add_argument("--over", action="store_true", help="超過/接近だけ表示")
    ap.add_argument("--sections", default="", help="指定mdの見出し別サイズ内訳(圧縮候補の特定)")
    ap.add_argument("--out-dir", default="", help="<dir>/budget_YYYY-MM-DD.md へ書き出す(週次タスク用)")
    args = ap.parse_args()

    if args.sections:
        p = args.sections if os.path.isabs(args.sections) else os.path.join(ROOT, args.sections)
        print(f"見出し別サイズ(大きい順・圧縮候補の特定用): {args.sections}")
        for head, size in sections_of(p)[:15]:
            print(f"  {size / 1000:7.1f}KB  {head}")
        return 0

    L = []
    n_over = n_warn = 0

    # 1) 常読層(全セッション×毎起動に効く=人格より先)
    L.append(f"# コンテキスト予算表 ({dt.datetime.now():%Y-%m-%d %H:%M})")
    L.append("")
    L.append(f"## 常読層(全セッションが毎回読む・最優先) 接近={int(WARN_RATIO * 100)}%")
    L.append(f"{'ファイル':<52} {'実測':>9} {'予算':>7}  判定")
    for rel, budget, note in ALWAYS_READ:
        p = os.path.join(ROOT, rel)
        size = os.path.getsize(p) if os.path.exists(p) else 0
        v = verdict(size, budget)
        n_over += v == "超過"
        n_warn += v == "接近"
        if (not args.over) or v != "OK":
            L.append(f"{rel:<52} {size / 1000:>7.1f}KB {budget / 1000:>5.0f}KB  {v}"
                     + (f" ← {note}" if v != "OK" else ""))
    for rel in GREP_REFERENCED:
        p = os.path.join(ROOT, rel)
        if os.path.exists(p) and not args.over:
            L.append(f"{rel:<52} {os.path.getsize(p) / 1000:>7.1f}KB {'—':>7}  対象外(grep参照運用)")

    # 2) 人格層
    L.append("")
    L.append(f"## 人格層 (manifest≦{BUDGET_MANIFEST // 1000}KB / detail≦{BUDGET_DETAIL // 1000}KB)")
    L.append(f"{'部門':<20} {'manifest':>10} {'detail':>10}  判定")
    for d in sorted(glob.glob(os.path.join(PERSONAS, "*"))):
        if not os.path.isdir(d):
            continue
        dept = os.path.basename(d)
        man = sum(os.path.getsize(f) for f in glob.glob(os.path.join(d, "*manifest*")))
        det = sum(os.path.getsize(f) for f in glob.glob(os.path.join(d, "*detail*")))
        vm, vd = verdict(man, BUDGET_MANIFEST), verdict(det, BUDGET_DETAIL)
        n_over += (vm == "超過") + (vd == "超過")
        n_warn += (vm == "接近") + (vd == "接近")
        marks = []
        if vm != "OK":
            marks.append(f"manifest{vm}(常読=全発言に効く)")
        if vd != "OK":
            marks.append(f"detail{vd}(圧縮サイクル§3.3へ)")
        if (not args.over) or marks:
            L.append(f"{dept:<20} {man / 1000:>8.1f}KB {det / 1000:>8.1f}KB  {' '.join(marks) or 'OK'}")

    L.append("")
    L.append(f"超過 {n_over}件 / 接近 {n_warn}件。接近=予算の{int(WARN_RATIO * 100)}%超(超過してからでは遅い"
             f"=Chami指示2026-07-18)。圧縮候補の特定は --sections <ファイル>。")
    body = "\n".join(L)
    print(body)
    if args.out_dir:
        out = os.path.join(args.out_dir, f"budget_{dt.date.today():%Y-%m-%d}.md")
        os.makedirs(os.path.dirname(os.path.abspath(out)), exist_ok=True)
        io.open(out, "w", encoding="utf-8").write(body + "\n")
        print(f"\n書き出し: {out}", file=sys.stderr)
        # タスクモード(--out-dir)は常に0を返す。意味つき終了コード(2=超過/1=接近)を
        # スケジュールタスクに漏らすと、接近が出るたび毎週「失敗したタスク」に見え、
        # 本物の故障(python不在等)と区別できなくなる(reregister_tasksの発火検証で実測)。
        # レポートファイルが信号・終了コードは健康状態、と役割を分ける。
        return 0
    return 2 if n_over else (1 if n_warn else 0)


if __name__ == "__main__":
    sys.exit(main())
