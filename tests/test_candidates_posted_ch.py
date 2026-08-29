#!/usr/bin/env python3
"""candidates_json.py の posted_ch(チャンネル別最終投稿状況)を検証する最小テスト。

対象= last_posted_by_channel() の戻り値 by_ch と、それを候補dictへ詰める形。
★D1(wrangler)は叩かない(dp.d1 をダミー行に差し替え=ネットワーク非依存)。
"""
import os, sys

TOOLS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..",
                          "docs", "departments", "product-scout", "tools")
sys.path.insert(0, os.path.abspath(TOOLS_DIR))

import daily_pick as dp
import candidates_json as cj

FAILS = []


def ok(name, cond):
    print(("PASS " if cond else "FAIL ") + name)
    if not cond:
        FAILS.append(name)


def fake_rows():
    # d_posted1: acc1のみ投稿(古い方が先に並んでもDESC想定=ここではPKの性質上cid×ch1行なので順不同でOK)
    # d_posted2: acc1/acc2 両方に投稿履歴あり(別日)
    # d_unposted: 投稿履歴なし(rowsに出てこない)
    return [
        {"cid": "d_posted2", "channel": "acc2", "posted_at": "2026-08-20T10:00:00Z"},
        {"cid": "d_posted2", "channel": "acc1", "posted_at": "2026-08-10T10:00:00Z"},
        {"cid": "d_posted1", "channel": "acc1", "posted_at": "2026-08-15T10:00:00Z"},
    ]


def main():
    orig_d1 = dp.d1
    dp.d1 = lambda sql: fake_rows()
    try:
        m, by_ch = cj.last_posted_by_channel()
    finally:
        dp.d1 = orig_d1

    # 1) by_ch のキーは acc1/acc2 のみ・値は日付文字列
    ok("d_posted2.acc1 と acc2 が両方入る",
       by_ch.get("d_posted2", {}).get("acc1") == "2026-08-10" and
       by_ch.get("d_posted2", {}).get("acc2") == "2026-08-20")
    ok("d_posted1.acc1 のみ入る", by_ch.get("d_posted1", {}).get("acc1") == "2026-08-15")
    ok("d_posted1.acc2 は無い(未投稿)", "acc2" not in by_ch.get("d_posted1", {}))

    # 2) 候補dictへ詰める形(main()内の詰め込みと同じロジック)を模擬し、
    #    未投稿cid(rowsに一切出てこない)は acc1/acc2 とも null になることを確認
    def build_posted_ch(cid):
        return {
            "acc1": by_ch.get(cid, {}).get("acc1"),
            "acc2": by_ch.get(cid, {}).get("acc2"),
        }

    pc_posted1 = build_posted_ch("d_posted1")
    ok("posted_ch: acc1キーが存在", "acc1" in pc_posted1)
    ok("posted_ch: acc2キーが存在", "acc2" in pc_posted1)
    ok("posted_ch: 値は日付文字列 or null(acc1=日付)", pc_posted1["acc1"] == "2026-08-15")
    ok("posted_ch: 値は日付文字列 or null(acc2=null)", pc_posted1["acc2"] is None)

    pc_unposted = build_posted_ch("d_never_posted")
    ok("未投稿cidはacc1がnull", pc_unposted["acc1"] is None)
    ok("未投稿cidはacc2がnull", pc_unposted["acc2"] is None)

    # 3) last_posted(既存フィールド)は従来通りの形(退行していないことの確認・追加のみを担保)
    ok("last_posted(既存)は変わらず全期間最新1件", m.get("d_posted2", {}).get("date") == "2026-08-20")
    ok("last_posted(既存)のchannel表示名も従来通り", m.get("d_posted2", {}).get("channel") == "宵桜艶帖")

    print()
    if FAILS:
        print(f"★FAIL {len(FAILS)}件: " + " / ".join(FAILS))
        sys.exit(1)
    print("ALL PASS")


if __name__ == "__main__":
    main()
