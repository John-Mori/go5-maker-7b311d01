#!/usr/bin/env python3
"""表記ルールの機械チェック (記載ミスの"根治"・Chami指摘2026-07-15「ちょくちょく記載ミスがある」)。

Chami制定の表記ルール(orchestration.md「表記の絶対ルール」)のうち、機械で判定できる2つを検査する:
  1. 全角括弧 （ ） の混入(ルール=括弧は必ず半角 () )
  2. 補足括弧の句点位置ミス「本文(補足)。」(ルール=「本文。(補足)」= 。はカッコの前)
     → 半角 ")。" と全角 "）。" のパターンを検出

使い方:
  python scripts/check_notation.py                 # 既定=docs/departments/**.md を検査
  python scripts/check_notation.py path1 path2 ...  # 指定ファイル/ディレクトリを検査
  python scripts/check_notation.py --all-md         # リポジトリ全体の .md を検査
違反があれば終了コード1(pre-commitフック化して自動で弾ける)。

注: コードブロック内(``` で囲まれた範囲)とURL/コマンド例は誤検出しやすいので、
    ```フェンス内はスキップする。日本語の文書本文のミスを拾うのが目的。
"""
import os
import re
import sys

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.normpath(os.path.join(HERE, ".."))

FULLWIDTH = re.compile(r"[（）]")
# 句点位置ミス「本文(補足)。」: ルールの狙いは「長い補足の後に。だけ残る違和感」なので、
#   短い挿入(例「(並列可)。」)は対象外。**中身が10文字以上の補足**が「)。」で終わる場合だけ違反とする。
#   半角ピリオド ")." は英文の可能性が高いので対象外(全角句点 。 のみ)。
KUTEN_AFTER_PAREN = re.compile(r"[(（][^)）]{10,}[)）]。")
# 誤検出除去: `コード` と 「引用」 の中はルール説明/例示なので検査対象から外す
#   (例: orchestration.md の「本文(補足)。」は禁止 という規則説明文を違反扱いしないため)。
CODE_SPAN = re.compile(r"`[^`]*`")
QUOTE_SPAN = re.compile(r"「[^」]*」")


def _strip_examples(ln):
    """`code`と「引用」を空白で潰す(桁位置は維持しないが検出可否のため)。"""
    ln = CODE_SPAN.sub(lambda m: " " * len(m.group(0)), ln)
    ln = QUOTE_SPAN.sub(lambda m: " " * len(m.group(0)), ln)
    return ln


def iter_files(paths):
    for p in paths:
        if os.path.isdir(p):
            for dp, _, fns in os.walk(p):
                for fn in fns:
                    if fn.endswith(".md"):
                        yield os.path.join(dp, fn)
        elif os.path.isfile(p):
            yield p


def check_file(path, strict=False):
    hits = []
    in_fence = False
    try:
        lines = open(path, encoding="utf-8").read().splitlines()
    except (OSError, UnicodeDecodeError):
        return hits
    for i, ln in enumerate(lines, 1):
        if ln.lstrip().startswith("```"):
            in_fence = not in_fence
            continue
        if in_fence:
            continue
        scan = _strip_examples(ln)
        for m in FULLWIDTH.finditer(scan):
            hits.append((i, m.start() + 1, "全角括弧", ln.strip()[:80]))
        if strict:
            # 句点位置は「長い補足」の主観判定を含むため既定では出さない(誤検出が多い)。
            # --strict の時だけ補助的に出す(ブロックはしない運用推奨)。
            for m in KUTEN_AFTER_PAREN.finditer(scan):
                hits.append((i, m.start() + 1, "句点位置(本文(補足)。→本文。(補足))", ln.strip()[:80]))
    return hits


def main():
    strict = "--strict" in sys.argv
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    if "--all-md" in sys.argv:
        targets = [ROOT]
    elif args:
        targets = args
    else:
        targets = [os.path.join(ROOT, "docs", "departments")]
    total = 0
    seen_files = set()
    for f in iter_files(targets):
        if f in seen_files:
            continue
        seen_files.add(f)
        hits = check_file(f, strict)
        if hits:
            rel = os.path.relpath(f, ROOT)
            for (line, col, kind, snip) in hits:
                print(f"{rel}:{line}:{col}  [{kind}]  {snip}")
                total += 1
    if total:
        tail = "(全角括弧は半角へ" + ("" if not strict else " / 「本文(補足)。」は「本文。(補足)」へ") + ")"
        print(f"\n表記違反 {total} 件。{tail}")
        return 1
    print("表記OK: 違反なし。" + ("" if strict else "(全角括弧チェック。句点位置も見るなら --strict)"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
