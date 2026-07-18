#!/usr/bin/env python3
"""改修履歴の月次ビュー生成(コンテキスト永続化設計書§4)。

正本は git のコミット文(このプロジェクトは経緯・理由・検証まで書く文化が確立済)。
本スクリプトはそれを「人が読める月次ビュー」`local/history/改修履歴_YYYY-MM.md` に再生成する。
**新しい台帳は作らない**——ビューは何度でも作り直せる使い捨て(正本はgitのまま)。

将来: Notion APIキー取得後、このビューを notion-sdk-py で Notion DBへ一方向push する
(このスクリプトは変更不要。pushスクリプトがこの出力を読む)。

使い方:
  python scripts/maintenance/build_changelog.py              # 今月
  python scripts/maintenance/build_changelog.py --month 2026-07
  python scripts/maintenance/build_changelog.py --all        # 履歴にある全月
"""
import argparse
import datetime as dt
import io
import os
import re
import subprocess
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.normpath(os.path.join(HERE, "..", ".."))
OUT_DIR = os.path.join(ROOT, "local", "history")

# 種別の推定(コミット文の先頭語から。過検出は許容=ビューの見出し分けのためだけ)
KINDS = [
    (re.compile(r"^INC-\d+|インシデント"), "🚨 インシデント対応"),
    (re.compile(r"恒久解|恒久-|恒久対策"), "🛡 恒久対策"),
    (re.compile(r"設計書|調査"), "📐 設計・調査"),
    (re.compile(r"規約|orchestration|BOOT"), "📜 規約・運用"),
    (re.compile(r"^P\d-\d|バックアップ|アーカイブ"), "💾 データ保全"),
    (re.compile(r"v=\d+|\?v=|GAS|Worker|デプロイ"), "🚀 アプリ・デプロイ"),
]


def git_log(month):
    """month='YYYY-MM' のコミットを取得。(hash, iso-date, subject, body先頭)のリスト。"""
    since = f"{month}-01"
    y, m = int(month[:4]), int(month[5:7])
    until = f"{y + (m == 12):04d}-{(m % 12) + 1:02d}-01"
    fmt = "%h%x1f%ad%x1f%s%x1f%b%x1e"
    out = subprocess.run(
        ["git", "log", f"--since={since}", f"--until={until}", "--date=format:%Y-%m-%d %H:%M",
         f"--pretty=format:{fmt}"],
        cwd=ROOT, capture_output=True, text=True, encoding="utf-8", errors="replace").stdout
    rows = []
    for chunk in out.split("\x1e"):
        parts = chunk.strip("\n").split("\x1f")
        if len(parts) < 3 or not parts[0].strip():
            continue
        h, date, subject = parts[0].strip(), parts[1], parts[2]
        body = parts[3].strip() if len(parts) > 3 else ""
        rows.append((h, date, subject, body))
    return rows


def kind_of(subject):
    for pat, label in KINDS:
        if pat.search(subject):
            return label
    return "🔧 その他の改修"


def build_month(month):
    rows = git_log(month)
    if not rows:
        return None
    by_kind = {}
    for h, date, subject, body in rows:
        by_kind.setdefault(kind_of(subject), []).append((h, date, subject, body))

    L = [f"# 改修履歴 {month}(gitから自動生成・正本はgit log)", ""]
    L.append(f"コミット {len(rows)}件。詳細は `git show <hash>`。失敗の教訓は `インシデント.md` が正本。")
    L.append("")
    order = [label for _, label in KINDS] + ["🔧 その他の改修"]
    for label in order:
        items = by_kind.get(label)
        if not items:
            continue
        L.append(f"## {label} ({len(items)}件)")
        for h, date, subject, body in items:
            # 件名の先頭120字+本文の1行目(あれば)だけ。全文はgitが持っている。
            L.append(f"- `{h}` {date} — {subject[:120]}")
            first = (body.splitlines() or [""])[0].strip()
            if first and first != subject:
                L.append(f"    - {first[:110]}")
        L.append("")
    return "\n".join(L)


def all_months():
    out = subprocess.run(
        ["git", "log", "--date=format:%Y-%m", "--pretty=format:%ad"],
        cwd=ROOT, capture_output=True, text=True, encoding="utf-8", errors="replace").stdout
    return sorted(set(out.splitlines()))


def main():
    ap = argparse.ArgumentParser(description="改修履歴の月次ビュー生成(git正本・使い捨てビュー)")
    ap.add_argument("--month", default=dt.date.today().strftime("%Y-%m"))
    ap.add_argument("--all", action="store_true")
    args = ap.parse_args()

    months = all_months() if getattr(args, "all") else [args.month]
    os.makedirs(OUT_DIR, exist_ok=True)
    made = 0
    for month in months:
        body = build_month(month)
        if body is None:
            print(f"{month}: コミットなし・スキップ")
            continue
        path = os.path.join(OUT_DIR, f"改修履歴_{month}.md")
        io.open(path, "w", encoding="utf-8").write(body + "\n")
        made += 1
        print(f"生成: {os.path.relpath(path, ROOT)} ({len(body)}文字)")
    return 0 if made else 1


if __name__ == "__main__":
    sys.exit(main())
