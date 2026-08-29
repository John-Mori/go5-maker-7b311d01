#!/usr/bin/env python3
"""daily_pick.py の ch別「直近枠」判定(excluded_cids_ch)を検証する最小テスト。

★Chami 2026-08-29『直近枠が開けば可』(msg 1543050908)= 提案ページの投稿可否を
  「そのchで完全未投稿」ではなく「そのchの直近枠(直近3日 ∪ 直近10件)が開いているか」で分岐する。
  ここでは excluded_cids_ch(ch) の"閉じている"集合と、ready_ch(=閉集合に含まれない)を検証。
★D1(wrangler)は叩かない(dp.d1 を SQL文字列で分岐するダミーへ差し替え=ネットワーク非依存)。
"""
import os, sys

TOOLS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..",
                          "docs", "departments", "product-scout", "tools")
sys.path.insert(0, os.path.abspath(TOOLS_DIR))

import daily_pick as dp

FAILS = []


def ok(name, cond):
    print(("PASS " if cond else "FAIL ") + name)
    if not cond:
        FAILS.append(name)


# 想定履歴(posted_log):
#   d_recent1  : acc1 に直近3日内(第1ゲート=日数窓で acc1 は閉)
#   d_countA   : acc2 に直近10件内だが3日より前(第2ゲート=件数窓で acc2 は閉・acc1 は開)
#   d_old1     : acc1 に大昔だけ(どちらの窓にも入らない=両ch開=共通)
DATE_ROWS = {
    "acc1": [{"cid": "d_recent1"}],  # 直近3日: acc1
    "acc2": [],                       # 直近3日: acc2 は無し
}
COUNT_ROWS = {
    "acc1": [{"cid": "d_recent1"}],              # acc1 の直近10件
    "acc2": [{"cid": "d_countA"}, {"cid": "d_recent1"}],  # acc2 の直近10件
}


def fake_d1(sql):
    ch = "acc1" if "channel='acc1'" in sql else ("acc2" if "channel='acc2'" in sql else None)
    if ch is None:
        return []
    if "datetime('now'" in sql:      # 日数窓(第1ゲート)
        return DATE_ROWS.get(ch, [])
    if "ORDER BY posted_at DESC LIMIT" in sql:  # 件数窓(第2ゲート)
        return COUNT_ROWS.get(ch, [])
    return []


def main():
    orig = dp.d1
    dp.d1 = fake_d1
    try:
        closed1 = dp.excluded_cids_ch("acc1")
        closed2 = dp.excluded_cids_ch("acc2")
    finally:
        dp.d1 = orig

    # acc1 の閉集合=日数窓 ∪ 件数窓 = {d_recent1}
    ok("acc1 の閉集合に d_recent1 が入る", "d_recent1" in closed1)
    ok("acc1 の閉集合に d_countA は入らない", "d_countA" not in closed1)
    # acc2 の閉集合=件数窓の {d_countA, d_recent1}(日数窓は空)
    ok("acc2 の閉集合に d_countA が入る(件数窓)", "d_countA" in closed2)
    ok("acc2 の閉集合に d_recent1 も入る(件数窓)", "d_recent1" in closed2)

    # ready_ch = 閉集合に含まれない(=直近枠が開いている)
    def ready_ch(cid):
        return {"acc1": cid not in closed1, "acc2": cid not in closed2}

    # d_recent1: acc1 閉/acc2 閉(件数窓) → 両ch閉=今すぐ枠には出ない(both)
    ok("d_recent1 は acc1 閉", ready_ch("d_recent1")["acc1"] is False)
    ok("d_recent1 は acc2 閉", ready_ch("d_recent1")["acc2"] is False)
    # d_countA: acc1 開/acc2 閉 → 月詠みだけ開(acc1 バケット)
    ok("d_countA は acc1 開", ready_ch("d_countA")["acc1"] is True)
    ok("d_countA は acc2 閉", ready_ch("d_countA")["acc2"] is False)
    # d_old1: どちらの窓にも無い → 両ch開=共通
    ok("d_old1 は acc1 開(共通)", ready_ch("d_old1")["acc1"] is True)
    ok("d_old1 は acc2 開(共通)", ready_ch("d_old1")["acc2"] is True)

    # 未知chはfail-open=空集合(SQLを組まない)
    dp.d1 = orig
    ok("未知chは空集合(SQLを叩かない)", dp.excluded_cids_ch("accX") == set())

    print()
    if FAILS:
        print(f"★FAIL {len(FAILS)}件: " + " / ".join(FAILS))
        sys.exit(1)
    print("ALL PASS")


if __name__ == "__main__":
    main()
