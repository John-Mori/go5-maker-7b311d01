#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
z2_realdata_check.py の検査。★空PASSにしない=判定と分岐を本物のまま通す(test-must-fail)。
入力を差し替えて classify の3語仕分けを実行で確かめる。
"""
import sys
from datetime import datetime, timedelta, timezone

import z2_realdata_check as z

JST = timezone(timedelta(hours=9))
NOW = datetime(2026, 8, 18, 14, 0, tzinfo=JST)


def rec(ts, nani):
    return {"ts": ts, "何": nani, "なぜ": "", "触った": "", "commit": "abc1234", "dept": "system-engineer"}


def main():
    fails = []

    # 1) 後埋まり列の語を拾う / 無関係な改修は拾わない
    if not z.is_record_column_fix(rec("2026-08-18T10:00:00+09:00", "ピーク値の列を埋める改修")):
        fails.append("ピーク改修を後埋まり列と認識できていない")
    if z.is_record_column_fix(rec("2026-08-18T10:00:00+09:00", "¥価格の横位置をslot中心へ")):
        fails.append("価格ラベル位置の改修を誤って後埋まり列と判定した")

    # 2) 読取口が無い(None)= 窓の内外に関わらず「入れた(確認待ち)」
    r_in_window = rec("2026-08-18T10:00:00+09:00", "ピーク列を直した")   # 4h前・窓24h内
    r_expired = rec("2026-08-15T10:00:00+09:00", "成約列を直した")       # 3日前・窓超過
    c1 = z.classify(r_in_window, z.no_reader, NOW, 24)["status"]
    c2 = z.classify(r_expired, z.no_reader, NOW, 24)["status"]
    if c1 != "入れた(確認待ち)":
        fails.append("読取口無し+窓内が『入れた(確認待ち)』でない: %s" % c1)
    if c2 != "入れた(確認待ち)":
        fails.append("読取口無し(判定不能)は窓超過でも確認待ちのはず: %s" % c2)

    # 3) 読取口あり: 非空=効いた / 窓超過で空=未着地 / 窓内で空=確認待ち
    reader_true = lambda _r: True
    reader_false = lambda _r: False
    if z.classify(r_in_window, reader_true, NOW, 24)["status"] != "効いた":
        fails.append("実データ非空なのに『効いた』にならない")
    if z.classify(r_expired, reader_false, NOW, 24)["status"] != "未着地":
        fails.append("窓超過で空なのに『未着地』にならない")
    if z.classify(r_in_window, reader_false, NOW, 24)["status"] != "入れた(確認待ち)":
        fails.append("窓内で空はまだ確認待ちのはず")

    # 4) run の分子/分母(既定reader=読取口無し=効いた0)
    import os, json, tempfile
    rows = [r_in_window, r_expired, rec("2026-08-18T09:00:00+09:00", "無関係なCSS修正")]
    fd, p = tempfile.mkstemp(suffix=".jsonl"); os.close(fd)
    with open(p, "w", encoding="utf-8") as f:
        for x in rows:
            f.write(json.dumps(x, ensure_ascii=False) + "\n")
    out = z.run(p, 24, NOW)
    os.remove(p)
    if out["denom"] != 2:
        fails.append("分母(後埋まり列の改修)が2でない: %d" % out["denom"])
    if out["numer"] != 0:
        fails.append("読取口無しなら分子(効いた)は0のはず: %d" % out["numer"])

    if fails:
        print("FAIL(%d):" % len(fails))
        for m in fails:
            print("  -", m)
        sys.exit(1)
    print("PASS: 4群すべて通過(語の抽出/読取口無し/読取口あり3分岐/run集計)")


if __name__ == "__main__":
    main()
