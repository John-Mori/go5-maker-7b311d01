#!/usr/bin/env python3
"""Chami の Discord 発言ログを分析し、要望・課題・指摘・肯定の傾向を要点化する。

改善提案部門(kaizen-analyst)の能動提案(週次改善便)の燃料。
生ログ数百件を LLM に読ませる前に、Python でカテゴリ別に圧縮して要点だけ渡す
(orchestration.md「Python積極利用方針」・summarize_user_events.py と同じ思想)。

使い方:
  python scripts/kaizen/summarize_chami_chats.py [日数]   # 既定=全期間
入力: local/discord_processed.jsonl, local/discord_inbox_processed.jsonl
出力(stdout・UTF-8): カテゴリ別件数 / 部屋別件数 / 日別件数 / 各カテゴリ代表例
"""
import collections
import json
import os
import sys

try:
    sys.stdout.reconfigure(encoding="utf-8")  # cp932 環境での日本語出力を保証
except Exception:
    pass

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.normpath(os.path.join(HERE, "..", ".."))
SOURCES = [
    os.path.join(ROOT, "local", "discord_processed.jsonl"),
    os.path.join(ROOT, "local", "discord_inbox_processed.jsonl"),
]

# 機微な個人領域の部屋。集計(件数・傾向)には含めてよいが、生の記述は表示・引用・
# 公開docs/D1への書き込みをしない(Chami方針2026-07-18「読んでいい・要約に・健康職歴は書かない」)。
SENSITIVE_DEPTS = ("dream-care", "past-room", "health-log", "future-room")

# カテゴリ = (見出し, [キーワード]). 1発言が複数カテゴリに入ってよい。
CATEGORIES = [
    ("要望(こうしたい)", ["してほしい", "して欲しい", "したい", "できないか", "欲しい",
                      "あったら", "作って", "追加", "実装して", "つくって", "できる?", "できるか"]),
    ("課題(困りごと)", ["困る", "できてない", "できていない", "ズレ", "ずれ", "バグ", "ミス",
                    "事故", "放置", "遅い", "見えない", "分からない", "わからない", "面倒",
                    "無駄", "むだ", "壊れ", "止まっ", "落ち"]),
    ("指摘(規約・様式)", ["半角", "括弧", "Discord", "ディスコード", "報告", "貼らせ", "名乗",
                     "刻んだ", "口調", "人格", "呼び方", "呼称", "徹底"]),
    ("肯定(喜び・承認)", ["いいね", "それいい", "助かる", "ありがとう", "最高", "嬉しい",
                     "うれしい", "おまかせ", "任せる", "まかせる", "go", "ゴー", "承認"]),
]


def load_rows(days):
    rows = []
    cutoff = None
    if days:
        import datetime
        cutoff = (datetime.datetime.utcnow() - datetime.timedelta(days=days)).isoformat()
    for path in SOURCES:
        if not os.path.exists(path):
            continue
        for line in open(path, encoding="utf-8"):
            line = line.strip()
            if not line:
                continue
            try:
                d = json.loads(line)
            except Exception:
                continue
            author = (d.get("author") or "").lower()
            if "chami" not in author:
                continue
            ts = d.get("ts") or ""
            if cutoff and ts < cutoff:
                continue
            rows.append({
                "ts": ts,
                "dept": d.get("dept") or "?",
                "content": (d.get("content") or "").replace("\n", " "),
                # 機微部屋は集計に含めてよいが、生の記述は代表例に出さない(健康・職歴等)
                "sensitive": (d.get("dept") or "") in SENSITIVE_DEPTS,
            })
    return rows


def main():
    days = int(sys.argv[1]) if len(sys.argv) > 1 else 0
    rows = load_rows(days)
    scope = f"直近{days}日" if days else "全期間"
    print(f"# Chami発言分析 ({scope}) — 総{len(rows)}件\n")

    by_dept = collections.Counter(r["dept"] for r in rows)
    by_day = collections.Counter((r["ts"] or "")[:10] for r in rows)
    cat_hits = collections.OrderedDict((name, []) for name, _ in CATEGORIES)

    for r in rows:
        c = r["content"]
        for name, kws in CATEGORIES:
            if any(k in c for k in kws):
                cat_hits[name].append(r)

    print("## カテゴリ別件数")
    for name in cat_hits:
        print(f"- {name}: {len(cat_hits[name])}件")

    print("\n## 部屋別件数(Top12)")
    for dept, n in by_dept.most_common(12):
        print(f"- {dept}: {n}")

    print("\n## 日別件数")
    for day in sorted(by_day):
        print(f"- {day}: {by_day[day]}")

    print("\n## 各カテゴリの代表例(最大4件・新しい順・機微部屋は生表示せず件数のみ)")
    for name in cat_hits:
        print(f"\n### {name}")
        shown = 0
        for r in sorted(cat_hits[name], key=lambda x: x["ts"], reverse=True):
            if shown >= 4:
                break
            if r["sensitive"]:
                continue  # 健康・職歴・夢などの生記述は表示・引用しない(Chami方針2026-07-18)
            print(f"- [{(r['ts'] or '')[:16]} {r['dept']}] {r['content'][:90]}")
            shown += 1


if __name__ == "__main__":
    main()
