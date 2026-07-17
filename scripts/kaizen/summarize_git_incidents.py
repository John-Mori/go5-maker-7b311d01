#!/usr/bin/env python3
"""git log とインシデント台帳を分析し、修正・失敗の型を要点化する。

改善提案部門(kaizen-analyst)の週次改善便の燃料。
「同じ型の修正が繰り返されていないか」「どの領域が事故りやすいか」を見て、
再発防止・仕組み化の提案につなげる(生ログをLLMに読ませない前処理)。

使い方:
  python scripts/kaizen/summarize_git_incidents.py [日数]   # 既定=14日
出力(stdout・UTF-8): 期間内commit数 / キーワード別commit数 / INC件数 / 最近のINC見出し
"""
import collections
import os
import re
import subprocess
import sys

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.normpath(os.path.join(HERE, "..", ".."))

# commit を分類するキーワード(1件が複数に入ってよい)
TAGS = [
    ("修正・不具合", ["修正", "直し", "直す", "fix", "バグ", "不具合", "是正", "根治", "誤"]),
    ("インシデント", ["INC-", "インシデント", "事故", "再発", "喪失", "停止", "無応答"]),
    ("設計・改善書", ["設計書", "改善書", "改善設計", "ロードマップ"]),
    ("規約・運用", ["規約", "orchestration", "BOOT", "承認", "運用"]),
    ("人格・キャラ", ["人格", "persona", "口調", "キャラ", "アイコン"]),
]


def run(cmd):
    r = subprocess.run(cmd, capture_output=True, text=True, cwd=ROOT, shell=True,
                       encoding="utf-8", errors="replace")
    return r.stdout or ""


def main():
    days = int(sys.argv[1]) if len(sys.argv) > 1 else 14
    log = run(f'git log --since="{days} days ago" --pretty=format:%s')
    lines = [l for l in log.splitlines() if l.strip()]
    print(f"# git/インシデント分析 (直近{days}日) — commit {len(lines)}件\n")

    tag_hits = collections.OrderedDict((name, []) for name, _ in TAGS)
    for l in lines:
        for name, kws in TAGS:
            if any(k in l for k in kws):
                tag_hits[name].append(l)

    print("## 種別ごとのcommit数")
    for name in tag_hits:
        print(f"- {name}: {len(tag_hits[name])}件")

    # インシデント台帳の見出し
    inc_path = os.path.join(ROOT, "インシデント.md")
    if os.path.exists(inc_path):
        text = open(inc_path, encoding="utf-8").read()
        inc_ids = re.findall(r"INC-\d+", text)
        uniq = sorted(set(inc_ids), key=lambda x: int(x.split("-")[1]))
        print(f"\n## インシデント台帳: 記録済み {len(uniq)}件 (最新 {uniq[-1] if uniq else 'なし'})")

    print("\n## 直近の修正・インシデント系commit(最大8件)")
    seen = set()
    for l in tag_hits["修正・不具合"] + tag_hits["インシデント"]:
        if l in seen:
            continue
        seen.add(l)
        print(f"- {l[:100]}")
        if len(seen) >= 8:
            break


if __name__ == "__main__":
    main()
