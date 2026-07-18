#!/usr/bin/env python3
"""反省バッチ — Chamiの方針変更を検出して「見直し候補」を出す(恒久解D・第一版)。

解く問題(P4-2): コーパスは追記のみ。Chamiが意見を変えても古い発言・古い方針が
知識パックに残り続ける。qwenは古い方針を今も正しいと思って答える。

mem0の設計(新事実 vs 既存事実で ADD/UPDATE/DELETE/NOOP を判定)を借りる。ただし:
- **自動でDELETE/UPDATEしない。** 「見直し候補」を出して人間/司令塔の判断に回す(安全側)。
  古い方針を機械が勝手に消すと、判定を誤った時に沈黙で失われる。今日の教訓=壊す前に確認。
- **第一版はLLMを使わない**(ルールベース)。日次でqwen[55秒/回]を回すコストと、8GBモデルの
  判定精度への公式懸念(調査書§2.1)を踏まえ、まず「変更シグナルの抽出」で当たりを付ける。
  LLM判定(mem0完全版)はL2採点運用が回り、精度検証ができてから第二版で足す。

やること: コーパスからChamiの「やめて/変えて/違う」等の変更シグナルを含む発言を時系列で拾い、
既存の記憶(knowledge.md・lessons.jsonl)にその話題のキーワードが残っていれば「衝突の疑い」として
見直しキュー(local/llm/reflect/YYYY-MM-DD.md)に出す。自動変更はゼロ。

使い方:
  python scripts/llm/reflect.py                 # 直近14日を見て標準出力
  python scripts/llm/reflect.py --days 0 --out-dir local/llm/reflect
"""
import argparse
import datetime as dt
import io
import os
import re
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.normpath(os.path.join(HERE, "..", ".."))
sys.path.insert(0, os.path.join(ROOT, "scripts", "lib"))
from jsonl_store import read_jsonl, SCHEMAS  # noqa: E402

CORPUS = os.path.join(ROOT, "local", "corpus", "chami.jsonl")
KNOWLEDGE = os.path.join(ROOT, "local", "llm", "knowledge.md")
LESSONS = os.path.join(ROOT, "local", "llm", "lessons.jsonl")

# 方針変更・撤回・否定を示すシグナル語。過検出は許容(人が最終判断するので)。
CHANGE_SIGNALS = [
    "やめて", "やめる", "やめとく", "廃止", "不要", "いらない", "いらん", "もういい",
    "変えて", "変更", "じゃなくて", "ではなく", "でなく", "取り消", "撤回",
    "やっぱり", "やっぱ", "訂正", "間違って", "間違い", "違うくて", "なしで",
    "今後は", "これからは", "もう", "前に言った", "さっきの",
]
# 話題キーを拾うための最低長(1〜2文字のノイズを除く)
KEY_MIN = 3


def in_window(ts, days):
    if days <= 0:
        return True
    try:
        d = dt.datetime.fromisoformat((ts or "").replace("Z", "+00:00"))
    except ValueError:
        return False
    if d.tzinfo is None:
        d = d.replace(tzinfo=dt.timezone.utc)
    return d >= dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=days)


def keywords(text):
    """発言から話題キーワード(カタカナ語・英単語・漢字2字以上)をざっくり抽出。"""
    kws = set()
    for m in re.findall(r"[ァ-ヴー]{3,}|[A-Za-z][A-Za-z0-9_]{2,}|[一-龠]{2,}", text or ""):
        if len(m) >= KEY_MIN:
            kws.add(m)
    return kws


def main():
    ap = argparse.ArgumentParser(description="反省バッチ(方針変更の見直し候補・自動変更なし)")
    ap.add_argument("--days", type=int, default=14, help="観測期間(日)。0=全期間")
    ap.add_argument("--out-dir", default="", help="<dir>/YYYY-MM-DD.md へ書き出す")
    ap.add_argument("--limit", type=int, default=20, help="表示する上位件数(既存記憶と衝突する順)")
    ap.add_argument("--conflicts-only", action="store_true",
                    help="知識パック/教訓に関連語が残るものだけ(=見直し価値が高いものだけ)")
    args = ap.parse_args()

    corpus, bad = read_jsonl(CORPUS, SCHEMAS["corpus"], on_bad="skip")
    know = io.open(KNOWLEDGE, encoding="utf-8").read() if os.path.exists(KNOWLEDGE) else ""
    lessons, _ = read_jsonl(LESSONS)
    lesson_text = " ".join((l.get("q", "") + l.get("correction", "")) for l in lessons)

    # 機微は本文を出さない(見直しキューはローカルだが露出面を増やさない・R4準拠)
    candidates = []
    for r in corpus:
        if r.get("sensitive"):
            continue
        # Chami本人の発言だけを対象にする。台帳には人格の自動投函(past-room/アメス、
        # dream-care-session、copy-director部門(三笘薫)等)も少数混ざるが、方針を決めるのは
        # Chamiなので、反省(=方針変更の検出)はChami発言に限る。
        if "chami" not in (r.get("author") or "").lower():
            continue
        if not in_window(r.get("ts", ""), args.days):
            continue
        content = r.get("content", "")
        hit = [s for s in CHANGE_SIGNALS if s in content]
        if not hit:
            continue
        kws = keywords(content)
        in_know = sorted(k for k in kws if k in know)
        in_less = sorted(k for k in kws if k in lesson_text)
        # 既存記憶に話題が残っている発言ほど「見直しの価値」が高い
        candidates.append({
            "ts": r.get("ts", "")[:19],
            "channel": r.get("channel", ""),
            "signals": hit,
            "content": content,
            "in_knowledge": in_know,
            "in_lessons": in_less,
        })

    # 既存記憶と衝突しうるもの(in_knowledge/in_lessonsが空でない)を上位に
    candidates.sort(key=lambda c: (len(c["in_knowledge"]) + len(c["in_lessons"]), c["ts"]), reverse=True)
    total_detected = len(candidates)
    if args.conflicts_only:
        candidates = [c for c in candidates if c["in_knowledge"] or c["in_lessons"]]
    shown = candidates[: args.limit]

    span = "全期間" if args.days <= 0 else f"直近{args.days}日"
    now = dt.datetime.now().strftime("%Y-%m-%d %H:%M")
    L = [f"# 反省バッチ 見直しキュー({span}・{now})", ""]
    L.append("Chamiが方針を変えた/撤回した可能性のある発言。**機械は何も変更していない。**")
    L.append("各項目を見て、古い方針を廃止/更新するか人が判断する(採用時は lessons.jsonl か knowledge へ反映)。")
    L.append(f"\n対象コーパス {len(corpus)}件 / 変更シグナル検出 **{total_detected}件** / 表示 {len(shown)}件"
             + (" (既存記憶と衝突するもののみ)" if args.conflicts_only else "")
             + (f" / 壊れ行skip {len(bad)}" if bad else "") + "\n")

    if not shown:
        L.append("該当なし(この期間に方針変更のシグナルは検出されなかった)。")
    for i, c in enumerate(shown, 1):
        L.append(f"## {i}. {c['ts']} [{c['channel']}]")
        L.append(f"- シグナル: {' / '.join(c['signals'])}")
        L.append(f"- 発言: {c['content'][:200]}")
        if c["in_knowledge"]:
            L.append(f"- ⚠ 知識パックに残る関連語: {', '.join(c['in_knowledge'][:8])} ← **古い方針が残っている疑い**")
        if c["in_lessons"]:
            L.append(f"- 教訓に残る関連語: {', '.join(c['in_lessons'][:8])}")
        L.append("")

    body = "\n".join(L)
    print(body)
    if args.out_dir:
        path = os.path.join(args.out_dir, dt.datetime.now().strftime("%Y-%m-%d") + ".md")
        os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
        io.open(path, "w", encoding="utf-8").write(body + "\n")
        print(f"\n書き出し: {path}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
