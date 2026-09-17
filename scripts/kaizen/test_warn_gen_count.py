# -*- coding: utf-8 -*-
"""warn_gen_count.py の受け入れ試験。

なぜ要るか= Chami依頼「⚠️ のやつちゃんと数えたりして」の肝は2つ。
  ①種別を取り違えず数える(簡体字/ハングル/キリル/名乗り無し)。
  ②「0の日は何も言わなくていい」= 0件で render が **空文字** を返す。
このテストは実データに依存させない= 一時ファイルに既知の行を書いて数える。

手で走らせる= PYTHONIOENCODING=utf-8 python scripts/kaizen/test_warn_gen_count.py
"""
import io
import json
import os
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import warn_gen_count as W  # noqa: E402

PASS = 0
FAIL = 0


def check(name, cond):
    global PASS, FAIL
    if cond:
        PASS += 1
    else:
        FAIL += 1
        print("  NG: %s" % name)


def _row(ts, dept, kind_body):
    return json.dumps({"ts": ts, "dept": dept, "body": kind_body, "event": "send"},
                      ensure_ascii=False)


def _with_audit(rows, fn):
    """AUDIT を一時ファイルへ差し替えて fn() を呼ぶ。"""
    old = W.AUDIT
    fd, path = tempfile.mkstemp(suffix=".jsonl")
    os.close(fd)
    try:
        with io.open(path, "w", encoding="utf-8") as f:
            for r in rows:
                f.write(r + "\n")
        W.AUDIT = path
        return fn()
    finally:
        W.AUDIT = old
        os.remove(path)


def main():
    M = W.WARN_MARK
    now = time.mktime((2026, 9, 17, 12, 0, 0, 0, 0, -1))
    ts_in = "2026-09-17T09:00:00"      # 窓内(直近24h)
    ts_old = "2026-08-01T09:00:00"     # 窓外(古い)

    # --- 種別を取り違えないか ---
    rows = [
        _row(ts_in, "manga-shorts", M + ": 日本の漢字でない簡体字の混入を検知。要確認。"),
        _row(ts_in, "manga-shorts", M + ": 日本の漢字でない簡体字の混入を検知。要確認。"),
        _row(ts_in, "hq", M + ": 非日本語スクリプト(ハングル)混入を検知。要確認。"),
        _row(ts_in, "hq", M + ": ラテン文字そっくりのキリル文字混入を検知。名乗りが壊れている恐れ。要確認。"),
        _row(ts_in, "qa-reviewer", M + ": 名乗りも話者も無い機械ログのままの本文を検知。要確認。"),
    ]
    total, by_kind, by_dept = _with_audit(rows, lambda: W.collect(now, 24.0))
    check("total=5", total == 5)
    check("簡体字=2", by_kind.get("簡体字混入") == 2)
    check("ハングル=1", by_kind.get("ハングル混入") == 1)
    check("キリル=1", by_kind.get("キリル文字混入") == 1)
    check("名乗り無し=1", by_kind.get("名乗り無し") == 1)
    check("部屋 manga-shorts=2", by_dept.get("manga-shorts") == 2)
    check("部屋 hq=2", by_dept.get("hq") == 2)

    # --- 窓外は数えない ---
    total2, _, _ = _with_audit([_row(ts_old, "hq", M + ": 簡体字の混入を検知")],
                               lambda: W.collect(now, 24.0))
    check("窓外は0", total2 == 0)

    # --- ⚠️印が無い普通の本文は拾わない ---
    total3, _, _ = _with_audit([_row(ts_in, "hq", "普通の返信本文。何の問題もない。")],
                               lambda: W.collect(now, 24.0))
    check("印無しは0", total3 == 0)

    # --- 4種のどれでもない⚠️は「その他」へ(取りこぼしを隠さない) ---
    _, bk4, _ = _with_audit([_row(ts_in, "hq", M + ": 未知の新種の不良を検知")],
                            lambda: W.collect(now, 24.0))
    check("未知はその他", bk4.get("その他") == 1)

    # --- ★0件で render は空文字(Chami「0の日は何も言わなくていい」) ---
    blk0 = _with_audit([], lambda: W.render(now, 24.0))
    check("0件で render は空", blk0 == "")

    # --- 非0件で render は中身を出す ---
    blk1 = _with_audit(rows, lambda: W.render(now, 24.0))
    check("非0件で見出しが出る", blk1.startswith("◆⚠️(自動)生成不良"))
    check("非0件で件数が乗る", "= 5件" in blk1)

    n = PASS + FAIL
    print("=== %d/%d %s ===" % (PASS, n, "PASS" if FAIL == 0 else "FAIL"))
    return 0 if FAIL == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
