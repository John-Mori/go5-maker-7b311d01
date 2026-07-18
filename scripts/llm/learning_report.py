#!/usr/bin/env python3
"""ローカルLLMの成長KPIを集計する(L3・週次成長便の材料)。

指標の定義・様式は `docs/設計・調査/改善設計書_ローカルllm成長進捗セッション_2026-07-17.md`
§5.1-5.3(中野五月・llm-growth)に従う。**本スクリプトは集計するだけで、指標を再定義しない。**

使い方:
  python scripts/llm/learning_report.py            # 直近7日
  python scripts/llm/learning_report.py --days 0   # 全期間
  python scripts/llm/learning_report.py --out local/llm/reports/2026-07-17.md

設計上の要点:
- **R5(N=0週は発行しない)**: 観測期間に1件も無ければ本文を出さず終了コード3を返す。
  呼び出し側(週次タスク)はこれを見て送信を抑止する=無変化の週報でChamiの画面を汚さない。
- **必須欄(§5.3)**: レコード件数・最終記録日時・欠測有無。数字が無いことも報告に含める。
- **グッドハート対策(§5.2)**: 即答率と不要エスカレ率は必ず対で出す。エスカレ加点だけだと
  「何でも回す方が高得点」になり、Chamiの叱責(「何でも司令塔に回す」07-14)と逆走する。
- **機微(R4)**: sensitive_deferred 由来のq/aは原文を出さない(件数・類型のみ)。
"""
import argparse
import collections
import datetime as dt
import io
import json
import os
import re
import sys

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.normpath(os.path.join(HERE, "..", ".."))
LOGS = {
    "ローカルqwen": os.path.join(ROOT, "local", "llm", "responder_log.jsonl"),
    "ホイミン(Gemini)": os.path.join(ROOT, "local", "llm", "gemini_responder_log.jsonl"),
}
LESSONS = os.path.join(ROOT, "local", "llm", "lessons.jsonl")
KNOWLEDGE = os.path.join(ROOT, "local", "llm", "knowledge.md")

EXIT_NO_DATA = 3  # R5: 観測期間に流入ゼロ


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


def in_window(ts, days):
    """観測期間内か。境界はカットオフ時刻との比較で厳密に取る。

    (now - d).days は切り捨てなので、47時間前の記録が .days==1 となり
    「直近1日」に紛れ込む(最大+1日の水増し)。週報の観測期間がずれると
    「今週の数字」が先週を含むことになるため、時刻で切る。
    """
    if days <= 0:
        return True
    if not re.match(r"^\d{4}-\d{2}-\d{2}", ts or ""):
        return False  # ts不正(接続テストの残骸等)は期間集計から外す
    try:
        d = dt.datetime.fromisoformat(ts.replace("Z", "+00:00"))
    except Exception:
        return False
    if d.tzinfo is None:
        d = d.replace(tzinfo=dt.timezone.utc)
    cutoff = dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=days)
    return d >= cutoff


def pct(a, b):
    return f"{round(100.0 * a / b)}%" if b else "—"


def section_actor(name, rows_all, days):
    rows = [r for r in rows_all if in_window(r.get("ts", ""), days)]
    total = len(rows)
    out = [f"### {name}"]
    if not rows_all:
        out.append("- ログなし(ファイル未生成)")
        return out, 0
    last = max((r.get("ts", "") for r in rows_all if r.get("ts")), default="")
    if total == 0:
        out.append(f"- **観測期間の記録: 0件(欠測)**。最終記録={last[:19] or '不明'}")
        out.append("  - 常駐が生きていても流入がゼロなら数字は出ない。『動いている』と『使われている』は別。")
        return out, 0
    modes = collections.Counter(r.get("mode") for r in rows)
    answered = modes.get("answered", 0)
    esc = modes.get("escalated", 0)
    sens = modes.get("sensitive_deferred", 0)
    sent = collections.Counter(r.get("sent") for r in rows)
    byday = collections.Counter((r.get("ts") or "")[:10] for r in rows)
    bych = collections.Counter(r.get("channel") for r in rows)
    out.append(f"- 件数 **{total}** / 最終記録 {last[:19]}")
    out.append(f"- **即答率 {pct(answered, total)}** ({answered}/{total})")
    out.append(f"- mode: answered {answered} / escalated {esc} / sensitive_deferred {sens}"
               + (f" / その他 {total - answered - esc - sens}" if total - answered - esc - sens else ""))
    out.append(f"- 送信: 成功 {sent.get(True, 0)} / 失敗 {sent.get(False, 0)} / 記録なし {sent.get(None, 0)}")
    out.append("- 日別: " + " → ".join(f"{d}: {n}" for d, n in sorted(byday.items()) if d))
    top = " / ".join(f"{c or '?'} {n}" for c, n in bych.most_common(5))
    out.append(f"- チャンネル別(上位): {top}")
    return out, total


def section_grading(days):
    """採点(L2)の集計。lessons.jsonl が空でも『未採点である』ことを数字で出す。"""
    lessons = read_jsonl(LESSONS)
    win = [l for l in lessons if in_window(l.get("ts", ""), days)]
    out = ["### 採点(L2)"]
    if not lessons:
        out.append("- **採点0件。good率は算出不能。**")
        out.append("  - 配管(lessons.jsonl→知識パック30_lessons層)は検証済み。**採点する人が決まれば即日回る。**")
        return out
    v = collections.Counter(l.get("verdict") for l in lessons)
    good, bad, esc = v.get("good", 0), v.get("bad", 0), v.get("escalate", 0)
    graded = good + bad + esc
    out.append(f"- 採点済み **{graded}件**(今期間 {len(win)}件): good {good} / bad {bad} / escalate {esc}")
    out.append(f"- **good率 {pct(good + esc, graded)}**(escalate=正しく回した=良い挙動として加点・§5.2の既決基準)")
    # グッドハート対策(§5.2): エスカレ加点の裏返しを必ず併記する
    bad_esc = sum(1 for l in lessons if l.get("verdict") == "bad" and l.get("mode") == "escalated")
    all_esc = sum(1 for l in lessons if l.get("mode") == "escalated")
    out.append(f"- **不要エスカレ率 {pct(bad_esc, all_esc)}**({bad_esc}/{all_esc})"
               " ← 即答率と対で見る。これが無いと「何でも回す」が高得点になる")
    types = collections.Counter((l.get("why") or "")[:24] for l in lessons if l.get("verdict") == "bad")
    if types:
        out.append("- bad類型(上位): " + " / ".join(f"「{t}…」×{n}" for t, n in types.most_common(3)))
    nxt = [l for l in lessons if l.get("verdict") == "bad"][-1:]
    if nxt:
        out.append(f"- **次に教えること**: {(nxt[0].get('correction') or '')[:90]}")
    return out


def main():
    ap = argparse.ArgumentParser(description="ローカルLLM成長KPIの集計(§5準拠)")
    ap.add_argument("--days", type=int, default=7, help="観測期間(日)。0=全期間")
    ap.add_argument("--out", default="", help="書き出し先。省略時は標準出力のみ")
    ap.add_argument("--out-dir", default="", help="<dir>/YYYY-MM-DD.md へ書き出す(週次タスク用)")
    args = ap.parse_args()
    if args.out_dir and not args.out:
        args.out = os.path.join(args.out_dir, dt.datetime.now().strftime("%Y-%m-%d") + ".md")

    now = dt.datetime.now().strftime("%Y-%m-%d %H:%M")
    span = "全期間" if args.days <= 0 else f"直近{args.days}日"
    lines = [f"# ローカルLLM 成長便({span}・{now}時点)", ""]

    total_all = 0
    for name, path in LOGS.items():
        body, n = section_actor(name, read_jsonl(path), args.days)
        lines += body + [""]
        total_all += n

    lines += section_grading(args.days) + [""]

    lines.append("### 知識パック(L1)")
    if os.path.exists(KNOWLEDGE):
        t = io.open(KNOWLEDGE, encoding="utf-8").read()
        mt = dt.datetime.fromtimestamp(os.path.getmtime(KNOWLEDGE)).strftime("%Y-%m-%d %H:%M")
        heads = len(re.findall(r"^#{1,3} ", t, re.M))
        corpus = os.path.join(ROOT, "local", "corpus", "chami.jsonl")
        n_corpus = len(read_jsonl(corpus))
        lines.append(f"- {len(t)}文字 / 見出し{heads} / 最終更新 {mt}(日次タスク go5_build_knowledge_daily)")
        lines.append(f"- 発言コーパス {n_corpus}件")
    else:
        lines.append("- **knowledge.md が無い**(build_knowledge.py 未実行)")

    body = "\n".join(lines)
    print(body)
    if args.out:
        os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)
        io.open(args.out, "w", encoding="utf-8").write(body + "\n")
        print(f"\n書き出し: {args.out}", file=sys.stderr)

    if total_all == 0:
        # R5: 流入ゼロの期間は週報を発行しない。呼び出し側がこの終了コードで送信を止める。
        print("\n(R5: 観測期間の流入ゼロ → 週報は発行しない)", file=sys.stderr)
        # ただしタスクモード(--out/--out-dir)では0を返す。意味つき終了コードをスケジュール
        # タスクに漏らすと流入ゼロの週が「失敗したタスク」に見え、本物の故障と区別できない
        # (context_budgetと同じ判断・reregister_tasksの発火検証で実測)。R5の「発行しない」
        # 判断は送信側がレポートファイルの有無/内容で行う。
        return 0 if args.out else EXIT_NO_DATA
    return 0


if __name__ == "__main__":
    sys.exit(main())
