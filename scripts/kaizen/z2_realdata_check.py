#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Z2 実物着地チェック(改善提案部門・自室ツール / C-019)

型《実物着地》= docs/departments/kaizen-analyst/preflight_claimed-fix-realdata-assert.md の b面。
change_log.jsonl から「GAS記録シートの後埋まり列(ピーク値・成約・クリック数など)を直した」と
主張している行を拾い、改修後 N 時間の実データで当該列が非空になったかを突き合わせて
「入れた(確認待ち)」/「効いた」/「未着地」に仕分ける。Z2 の分子(効いた)/分母(入れた)を機械で出す。

★実データ読取口(GAS記録シートの当該列を読む)は改修部門αへ相乗り(a面)。
  読取口が未配線の間は sheet_reader が None を返す=全件「入れた(確認待ち)」に留まる(§4.55)。
  ソース文字列一致も「入れた」も合否にしない。窓を過ぎて空なら未着地=オープン継続でZ2分母に残す。
"""
import argparse
import json
import os
from datetime import datetime, timedelta, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
DEFAULT_LOG = os.path.normpath(os.path.join(HERE, "..", "..", "local", "llm", "change_log.jsonl"))

# 「後埋まり列を直した」を指す語(何をどう数えたか=共通規律§1)。過剰一致を避け、
# GAS記録シートの後から埋まる列に限定する。マッチ語は結果に添えて出す。
RECORD_COLUMN_KEYWORDS = [
    "ピーク",
    "成約",
    "クリック数",
    "記録シート",
    "記録_ch",
    "後埋まり",
    "refreshClicks",
    "refreshEngagement",
    "エンゲージ",
]


def parse_ts(s):
    """ISO8601(+09:00等)を aware datetime へ。失敗時は None。"""
    if not s:
        return None
    try:
        return datetime.fromisoformat(s)
    except ValueError:
        return None


def matched_keywords(rec):
    """このレコードが後埋まり列の改修を主張しているか。マッチ語のリストを返す(空=非該当)。"""
    hay = " ".join(str(rec.get(k, "")) for k in ("何", "なぜ", "触った"))
    return [w for w in RECORD_COLUMN_KEYWORDS if w in hay]


def is_record_column_fix(rec):
    return len(matched_keywords(rec)) > 0


def classify(rec, sheet_reader, now, window_hours):
    """
    1レコードを Z2 の3語へ仕分ける。
    sheet_reader(rec) の戻り: True=当該列が実データで非空 / False=空 / None=読取口が無く判定不能。
    戻り status: "効いた" / "入れた(確認待ち)" / "未着地"
    """
    ts = parse_ts(rec.get("ts"))
    deadline = ts + timedelta(hours=window_hours) if ts else None
    val = sheet_reader(rec)
    if val is True:
        status = "効いた"
    elif val is None:
        status = "入れた(確認待ち)"  # 読取口が無い=まだ確認できない
    else:  # val is False = 実データで空
        if deadline is not None and now >= deadline:
            status = "未着地"          # 窓を過ぎても空=オープン継続・Z2分母に残す
        else:
            status = "入れた(確認待ち)"  # まだ窓の中
    return {
        "ts": rec.get("ts"),
        "commit": rec.get("commit"),
        "dept": rec.get("dept"),
        "何": rec.get("何"),
        "matched": matched_keywords(rec),
        "deadline": deadline.isoformat() if deadline else None,
        "status": status,
    }


def no_reader(_rec):
    """既定の読取口=まだ配線されていない(改修部門αへ相乗り予定)。常に判定不能。"""
    return None


def load_rows(path):
    rows = []
    with open(path, "r", encoding="utf-8") as f:
        for ln in f:
            ln = ln.strip()
            if not ln:
                continue
            try:
                rows.append(json.loads(ln))
            except json.JSONDecodeError:
                continue  # 壊れ行は飛ばす(生JSON手打ち事故の耐性)
    return rows


def run(path, window_hours, now, sheet_reader=no_reader):
    rows = load_rows(path)
    fixes = [r for r in rows if is_record_column_fix(r)]
    results = [classify(r, sheet_reader, now, window_hours) for r in fixes]
    counts = {"効いた": 0, "入れた(確認待ち)": 0, "未着地": 0}
    for r in results:
        counts[r["status"]] += 1
    denom = len(results)                      # 入れた(=記録列を直したと主張した数)
    numer = counts["効いた"]                   # 効いた(=実データで確認できた数)
    return {"denom": denom, "numer": numer, "counts": counts, "results": results,
            "reader_wired": sheet_reader is not no_reader}


def main():
    ap = argparse.ArgumentParser(description="Z2 実物着地チェック")
    ap.add_argument("--log", default=DEFAULT_LOG, help="change_log.jsonl のパス")
    ap.add_argument("--hours", type=int, default=24, help="実データ確認の窓(時間)")
    ap.add_argument("--json", action="store_true", help="JSONで出す")
    args = ap.parse_args()

    now = datetime.now(timezone(timedelta(hours=9)))  # JST
    out = run(args.log, args.hours, now)

    if args.json:
        print(json.dumps(out, ensure_ascii=False, indent=2))
        return

    print("=== Z2 実物着地チェック(窓=%dh / now=%s JST)===" % (args.hours, now.strftime("%m/%d(%a) %H:%M")))
    print("記録列を直したと主張=%d件(=分母) / 効いた(実データ確認済)=%d件(=分子)" % (out["denom"], out["numer"]))
    print("内訳:", ", ".join("%s %d" % (k, v) for k, v in out["counts"].items()))
    if not out["reader_wired"]:
        print("※ 実データ読取口が未配線(改修部門αへ相乗り予定)=全件『入れた(確認待ち)』に留まる。")
        print("  これは仕様どおり(§4.55/型I1)。読取口が入るまで『効いた』は0で正しい。")
    print("--- 該当行 ---")
    for r in out["results"]:
        print("[%s] %s / %s / 語:%s / 期限:%s / %s" % (
            r["status"], r["ts"], r["commit"], ",".join(r["matched"]),
            r["deadline"], (r["何"] or "")[:40]))


if __name__ == "__main__":
    main()
