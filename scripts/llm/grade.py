#!/usr/bin/env python3
"""ローカルLLMの応答を採点して教訓台帳(lessons.jsonl)へ記録する(L2)。

採点基準は既決(改善設計書_ローカルllm成長進捗セッション §5.2):
  good     = 正確 + 人格逸脱なし
  bad      = 事実誤り・憶測・なりすまし・できない約束
  escalate = 「わからない」と正しく回した(=良い挙動。加点する)

**この道具は採点基準を決めない。** 基準の設計は研究室(Chami裁定2026-07-15)、
集計・報告はllm-growth、採点の実施はllm-qa/学習室の担当。ここは記録の受け皿だけ。

使い方:
  # 未採点を古い順に見る
  python scripts/llm/grade.py --queue
  python scripts/llm/grade.py --queue --limit 5 --actor qwen

  # 採点する(indexは --queue の番号)
  python scripts/llm/grade.py --index 3 --verdict good
  python scripts/llm/grade.py --index 3 --verdict bad \
      --correction "正しい答え" --why "なぜ間違えたか"

bad は correction と why が必須(無いと教訓にならない=知識パックへ焼けない)。
"""
import argparse
import datetime as dt
import io
import json
import os
import sys

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.normpath(os.path.join(HERE, "..", ".."))
LOGS = {
    "qwen": os.path.join(ROOT, "local", "llm", "responder_log.jsonl"),
    "gemini": os.path.join(ROOT, "local", "llm", "gemini_responder_log.jsonl"),
}
LESSONS = os.path.join(ROOT, "local", "llm", "lessons.jsonl")
VERDICTS = ("good", "bad", "escalate")

# 機微部屋のq/aは原文を扱わない(R4)。採点自体を諦めるのではなく、
# 台帳へは類型だけを残せるよう、原文の持ち出しを既定で止める。
SENSITIVE_HINTS = ("夢", "過去", "健康", "人事", "現在と未来", "recovery")


def read_jsonl(path):
    if not os.path.exists(path):
        return []
    rows = []
    with io.open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                rows.append(json.loads(line))
            except Exception:
                continue
    return rows


def key_of(row):
    """応答の同一性キー。responder_logにidが無いので ts+質問頭で代用する。"""
    return f"{row.get('ts','')}|{(row.get('q') or '')[:40]}"


def is_sensitive(row):
    ch = row.get("channel") or ""
    return row.get("mode") == "sensitive_deferred" or any(h in ch for h in SENSITIVE_HINTS)


def pending(actor=None):
    graded = {l.get("source_key") for l in read_jsonl(LESSONS)}
    out = []
    for name, path in LOGS.items():
        if actor and actor != name:
            continue
        for r in read_jsonl(path):
            if not (r.get("a") or "").strip():
                continue  # 応答していない行は採点対象外
            if key_of(r) in graded:
                continue
            r["_actor"] = name
            out.append(r)
    out.sort(key=lambda r: r.get("ts") or "")
    return out


def cmd_queue(args):
    rows = pending(args.actor)
    if not rows:
        print("未採点なし。")
        return 0
    print(f"未採点 {len(rows)}件(古い順・先頭{min(args.limit, len(rows))}件)\n")
    for i, r in enumerate(rows[: args.limit]):
        sens = " [機微=原文は台帳へ残さない]" if is_sensitive(r) else ""
        print(f"[{i}] {r.get('ts','')[:19]} {r['_actor']} mode={r.get('mode')} ch={r.get('channel','')}{sens}")
        print(f"    Q: {(r.get('q') or '')[:110]}")
        print(f"    A: {(r.get('a') or '')[:110]}\n")
    print("採点: python scripts/llm/grade.py --index <番号> --verdict good|bad|escalate "
          "[--correction ... --why ...]")
    return 0


def cmd_grade(args):
    rows = pending(args.actor)
    if args.index < 0 or args.index >= len(rows):
        print(f"index {args.index} は範囲外(未採点は {len(rows)}件)", file=sys.stderr)
        return 1
    r = rows[args.index]
    if args.verdict == "bad" and not (args.correction and args.why):
        print("bad には --correction と --why が要る(無いと教訓にならず知識パックへ焼けない)", file=sys.stderr)
        return 1

    sens = is_sensitive(r)
    row = {
        "ts": dt.datetime.now(dt.timezone.utc).isoformat(),
        "actor": r["_actor"],
        "mode": r.get("mode"),
        "channel": r.get("channel"),
        "q": "" if sens else (r.get("q") or ""),
        "a": "" if sens else (r.get("a") or ""),
        "verdict": args.verdict,
        "correction": args.correction or "",
        "why": args.why or "",
        "source_key": key_of(r),
        "source_ts": r.get("ts"),
        "sensitive": sens,
        "grader": args.grader,
    }
    os.makedirs(os.path.dirname(LESSONS), exist_ok=True)
    with io.open(LESSONS, "a", encoding="utf-8") as f:
        f.write(json.dumps(row, ensure_ascii=False) + "\n")
    note = "(機微のため原文は記録せず類型のみ)" if sens else ""
    print(f"採点を記録: {args.verdict} / {r.get('ts','')[:19]} {r['_actor']} {note}")
    print("知識パックへの反映: python scripts/llm/build_knowledge.py")
    return 0


def main():
    ap = argparse.ArgumentParser(description="ローカルLLM応答の採点(L2・基準は§5.2の既決)")
    ap.add_argument("--queue", action="store_true", help="未採点を古い順に表示")
    ap.add_argument("--limit", type=int, default=10)
    ap.add_argument("--actor", choices=("qwen", "gemini"), default=None)
    ap.add_argument("--index", type=int, default=None, help="--queueの番号")
    ap.add_argument("--verdict", choices=VERDICTS)
    ap.add_argument("--correction", default="")
    ap.add_argument("--why", default="")
    ap.add_argument("--grader", default="llm-qa")
    args = ap.parse_args()

    if args.queue or args.index is None:
        return cmd_queue(args)
    if not args.verdict:
        print("--verdict が要る", file=sys.stderr)
        return 1
    return cmd_grade(args)


if __name__ == "__main__":
    sys.exit(main())
