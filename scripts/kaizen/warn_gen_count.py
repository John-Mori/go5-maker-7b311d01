# -*- coding: utf-8 -*-
"""毎朝の「⚠️(自動)生成不良」集計(改善提案部門)。

なぜ要るか= Chami依頼 2026-09-17(便 msg=1549984430041595997)
  「⚠️ のやつちゃんと数えたりして欲しいなこれから。0の日は何も言わなくていいよ」

「⚠️(自動)生成不良」とは=
  dept_daemon.py が bot の出力に**自動で付ける自己申告フラグ**。生成そのものが
  壊れている(非日本語混入・名乗り無し)のを機械が検知した印で、絵文字監視の
  「Chamiが押したスタンプ」台帳とは**別物**(あちらは「機械の印…は除外」と明記)。
  だからこの集計は、既存の絵文字ダイジェストとは**独立した新しい数え**として足す。

  4種(dept_daemon.py の定数が正本。文面が動いたらここの部分一致も見直す)=
    ・ハングル混入   … HANGUL_WARN     "…(ハングル)混入を検知"
    ・簡体字混入     … SIMPLIFIED_WARN "…簡体字の混入を検知"
    ・キリル文字混入 … CYRILLIC_WARN   "…キリル文字混入を検知"
    ・名乗り無し     … NARRATION_WARN  "…名乗りも話者も無い機械ログ…"

正直さ(共通規律§1)=
  ・件数は send_audit.jsonl(実際に送られた本文)を**読んで**数える。推測しない。
  ・0件の日は**何も返さない**(render が "" を返す= 便に何も乗らない。Chami明示)。
  ・種別が4つのどれにも当たらない⚠️は「その他」で数える(取りこぼしを隠さない)。

窓の既定= 直近24h(毎朝の便に1回ずつ乗る形。二重に数えない)。
手で試す= PYTHONIOENCODING=utf-8 python scripts/kaizen/warn_gen_count.py
          （窓を変える例）--hours 48
"""
import argparse
import datetime as dt
import io
import json
import os

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
AUDIT = os.path.join(ROOT, "local", "llm", "send_audit.jsonl")

WARN_MARK = "⚠️(自動)生成不良"       # dept_daemon.py が全4種の頭に必ず付ける印
# 部分一致キー→ 表示名。dept_daemon.py の *_WARN 定数の**本文の一部**を写す
#   (完全一致にしない= 文面末尾が微調整されても取りこぼさないため)。
KINDS = [
    ("ハングル", "ハングル混入"),
    ("簡体字", "簡体字混入"),
    ("キリル", "キリル文字混入"),
    ("名乗りも話者も無い", "名乗り無し"),
]


def _parse_ts(s):
    """send_audit.jsonl の ts(例 '2026-09-05T03:07:53')を naive datetime に。失敗は None。"""
    if not s:
        return None
    try:
        return dt.datetime.strptime(s[:19], "%Y-%m-%dT%H:%M:%S")
    except (ValueError, TypeError):
        return None


def collect(now, hours):
    """窓の間に送られた⚠️(自動)生成不良を数える。

    返り値= (total, by_kind{表示名:件数}, by_dept{slug:件数})
    """
    lo = dt.datetime.fromtimestamp(now - hours * 3600)
    hi = dt.datetime.fromtimestamp(now)
    by_kind = {}
    by_dept = {}
    total = 0
    if not os.path.exists(AUDIT):
        return total, by_kind, by_dept
    with io.open(AUDIT, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                o = json.loads(line)
            except ValueError:
                continue
            body = o.get("body") or ""
            if WARN_MARK not in body:
                continue
            t = _parse_ts(o.get("ts"))
            if t is None or not (lo <= t <= hi):
                continue
            total += 1
            label = "その他"
            for needle, name in KINDS:
                if needle in body:
                    label = name
                    break
            by_kind[label] = by_kind.get(label, 0) + 1
            dept = o.get("dept") or "(不明)"
            by_dept[dept] = by_dept.get(dept, 0) + 1
    return total, by_kind, by_dept


def _span(now, hours):
    fmt = "%#m/%#d %H:%M" if os.name == "nt" else "%-m/%-d %H:%M"
    dfrom = dt.datetime.fromtimestamp(now - hours * 3600).strftime(fmt)
    duntil = dt.datetime.fromtimestamp(now).strftime(fmt)
    return "%s〜%s" % (dfrom, duntil)


def render(now, hours):
    """便に乗せる1ブロックを返す。0件なら "" (= 便に何も乗らない。Chami明示)。"""
    total, by_kind, by_dept = collect(now, hours)
    if total == 0:
        return ""
    span = _span(now, hours)
    out = ["◆⚠️(自動)生成不良 直近%.0fh(%s)= %d件" % (hours, span, total)]
    # 種別= 多い順。生成のどこが壊れているかの内訳。
    kinds = sorted(by_kind.items(), key=lambda kv: (-kv[1], kv[0]))
    out.append("  種別= " + " / ".join("%s %d" % (k, v) for k, v in kinds))
    # 部屋(部門slug)= 多い順。どの部屋の出力が壊れているか。
    depts = sorted(by_dept.items(), key=lambda kv: (-kv[1], kv[0]))
    out.append("  部屋= " + " / ".join("%s %d" % (d, v) for d, v in depts))
    out.append("  ※これは機械が本文に自動で付けた自己申告フラグ(生成不良)の集計。"
               "絵文字スタンプ一覧とは別物。0件の日はこの行を出さない。")
    return "\n".join(out)


def main():
    import time
    ap = argparse.ArgumentParser(description="毎朝の⚠️(自動)生成不良を数えて報告する")
    ap.add_argument("--hours", type=float, default=24.0)
    ap.add_argument("--now", type=float, default=None, help="epoch秒。既定=現在時刻")
    a = ap.parse_args()
    now = a.now if a.now is not None else time.time()
    blk = render(now, a.hours)
    if blk:
        print(blk)
    # 0件は何も出さない(Chami明示「0の日は何も言わなくていいよ」)= main も沈黙する。


if __name__ == "__main__":
    main()
