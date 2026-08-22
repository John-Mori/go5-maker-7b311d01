#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""再修正チェーン検出器(改善提案部門・自室ツール / C-019)。

Chami依頼(2026-08-22 msg1540617870248124498)=
  「改修αに色々頼んだけど何回も治らなくて…を繰り返しまくってトークンを無駄にした。
   そこの事実を数字でよくわかるように。Pythonでできる事はないか」。

これは Z1-C(こちらの落ち度の再依頼)/「何度直しても再発」を **change_log.jsonl から
機械で拾う** 道具。今までClaudeが台帳を目で読んで数えていた作業をPythonへ寄せる=
Chamiの言う「Claudeでやっていた部分をPythonへ」の実体の1つ。

数え方(=出力に添える。§1)=
  ①同じ「触った」ファイルを、同じ部門が **≥MIN_ROWS回・≥MIN_DAYS日にまたがって** 触った系列
    = 再修正チェーンの候補(1日で終わる健全な連投は除く)。
  ②症状キーワード(Drive/保存/R2 …)でも束ね、ファイル名が割れても同じ火を拾う。
  ★これは「疑い」を数える道具=真因が別にあった往復も、健全な多段実装も混じる。
    A健全/B前提ずれ/C落ち度 の仕分けは人が最後にやる(数だけで良し悪しを言わない・KPI Z1注記)。

規律= tsは自前パースせず scripts/lib/jsonl_store.py の read_jsonl()/ts_epoch() を通す
      (Zの6行が9時間ずれる・BOM/壊れ行が黙って消える穴を塞ぐ)。読み取りのみ=貯め先を作らない。

使い方:
  python scripts/kaizen/refix_chains.py               # 全期間
  python scripts/kaizen/refix_chains.py --days 30     # 直近30日
  python scripts/kaizen/refix_chains.py --dept system-engineer
  python scripts/kaizen/refix_chains.py --min-rows 3 --min-days 2
"""
import argparse
import collections
import datetime as dt
import os
import sys

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
sys.path.insert(0, os.path.join(ROOT, "scripts", "lib"))
import jsonl_store  # noqa: E402

LOG = os.path.join(ROOT, "local", "llm", "change_log.jsonl")
JST = dt.timezone(dt.timedelta(hours=9))

# 症状クラスタ(ファイル名が割れても同じ火を拾う)。何/なぜ/触った を連結して照合。
SYMPTOMS = {
    "Drive保存/R2着地": ["drive", "保存", "r2", "save_job", "再生成", "着地", "mirror"],
    "投稿導線/短縮リンク": ["投稿", "短縮", "link", "アフィリンク", "bluesky", "x投稿", "facet"],
    "版ずれ/CI門番": ["?v=", "バンプ", "bump", "smoke", "スモーク", "版ずれ"],
    "ドラフト/在庫": ["ドラフト", "draft", "在庫", "stock", "作成履歴"],
}


def _s(v):
    """台帳の値を文字列へ。listで書かれた行が実在する(触った/何がlistの記録)。"""
    if isinstance(v, list):
        return " / ".join(_s(x) for x in v)
    return "" if v is None else str(v)


CODE_EXT = (".js", ".css", ".html", ".gs", ".py", ".mjs", ".ps1", ".bat")


def is_code(path):
    """コード系(=直せば消えるべき再修正)か、追記台帳(=積み上がるのが正常)か。

    docs/*.md や *.json の台帳は『何回も足す』のが健全(勝ちパターン等)=
    再修正ループではない。真のトークン食いはコード系の再タッチ。
    """
    p = path.lower()
    return any(x in p for x in CODE_EXT) and "/docs/" not in p


def day_str(epoch):
    return dt.datetime.fromtimestamp(epoch, JST).strftime("%Y-%m-%d")


def load(days, dept):
    rows, bad = jsonl_store.read_jsonl(LOG)
    now = dt.datetime.now(JST).timestamp() if days else None
    cut = (now - days * 86400) if days else None
    out = []
    for r in rows:
        ep = jsonl_store.ts_epoch(r.get("ts"))
        if ep is None:
            continue  # ts読めない行は集計に混ぜない(1970年扱いを避ける)
        if cut is not None and ep < cut:
            continue
        if dept and r.get("dept") != dept:
            continue
        out.append((ep, r))
    return out, bad


def chains_by_file(rows, min_rows, min_days):
    by = collections.defaultdict(list)   # (dept, 触った) -> [(ep, 何)]
    for ep, r in rows:
        f = _s(r.get("触った")).strip()
        if not f:
            continue
        by[(r.get("dept", "?"), f)].append((ep, _s(r.get("何"))))
    chains = []
    for (dept, f), items in by.items():
        items.sort()
        ndays = len({day_str(ep) for ep, _ in items})
        if len(items) >= min_rows and ndays >= min_days:
            chains.append({
                "dept": dept, "file": f, "rows": len(items), "days": ndays,
                "code": is_code(f),
                "first": day_str(items[0][0]), "last": day_str(items[-1][0]),
                "samples": [w[:36] for _, w in items[:3]],
            })
    # コード系(真の再修正ループ)を先頭へ、次に回数・日数で降順
    chains.sort(key=lambda c: (c["code"], c["rows"], c["days"]), reverse=True)
    return chains


def clusters_by_symptom(rows):
    counts = collections.Counter()
    days = collections.defaultdict(set)
    for ep, r in rows:
        blob = " ".join([_s(r.get("何")), _s(r.get("なぜ")), _s(r.get("触った"))]).lower()
        for name, kws in SYMPTOMS.items():
            if any(k in blob for k in kws):
                counts[name] += 1
                days[name].add(day_str(ep))
    return [(n, counts[n], len(days[n])) for n in sorted(counts, key=lambda x: -counts[x])]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=0, help="0=全期間")
    ap.add_argument("--dept", default="")
    ap.add_argument("--min-rows", type=int, default=3)
    ap.add_argument("--min-days", type=int, default=2)
    a = ap.parse_args()

    rows, bad = load(a.days, a.dept)
    span = "全期間" if not a.days else f"直近{a.days}日"
    print(f"# 再修正チェーン(change_log / {span}"
          f"{'・' + a.dept if a.dept else ''} / 対象{len(rows)}行)")
    if bad:
        print(f"※読めない行 {len(bad)}件(集計から除外)= " +
              ", ".join(f"L{ln}" for ln, _ in bad[:5]))

    print(f"\n## 同一ファイルの再修正チェーン(≥{a.min_rows}回・≥{a.min_days}日)")
    ch = chains_by_file(rows, a.min_rows, a.min_days)
    if not ch:
        print("該当なし。")
    for c in ch:
        tag = "⚙️コード=再修正ループ候補" if c["code"] else "📄台帳=追記が正常(除外目安)"
        print(f"- **{c['rows']}回/{c['days']}日** [{c['dept']}] `{c['file']}` "
              f"({c['first']}→{c['last']}) {tag}")
        for s in c["samples"]:
            print(f"    - {s}")

    print("\n## 症状クラスタ(ファイル名が割れても束ねる)")
    for name, n, d in clusters_by_symptom(rows):
        print(f"- {name}: {n}件 / {d}日")

    print("\n※この一覧は「再修正の疑い」。A健全な多段実装/B前提ずれ/C落ち度 の"
          "仕分けは人が最後にやる(数だけで良し悪しを言わない=KPI Z1)。")


if __name__ == "__main__":
    main()
