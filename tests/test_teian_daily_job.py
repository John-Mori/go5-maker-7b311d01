# -*- coding: utf-8 -*-
"""run_daily_teian_job.py の「鳴らす/黙る」判断を固定する(2026-09-02 イージス研究室)。

なぜ試験が要るか:
  この起動器の値打ちは**チェーンを回すこと**ではなく、**チェーンが死んだ時に気づけること**だ。
  そして気づかせ方を間違えると死ぬ= 毎日鳴る網は読まれなくなり(規律§3)、鳴らなすぎる網は
  2026-08-24〜09-01 の「8日間の静かな凍結」をそのまま作り直す。**その境目だけを固定する。**

★must-fail= should_alert を `lambda *a, **k: True`(毎日鳴らす)へ変えると
  「連続する失敗では毎日鳴らさない」が赤。`lambda *a, **k: False` へ変えると
  「壊れた初日は鳴らす」「直った日に閉じる便を出す」が赤。どちらも見た。

走らせる= python tests/test_teian_daily_job.py
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                                "scripts", "_daemons"))
import run_daily_teian_job as J  # noqa: E402

OK = FAIL = 0


def check(name, cond):
    global OK, FAIL
    if cond:
        OK += 1
        print("  PASS: " + name)
    else:
        FAIL += 1
        print("  FAIL: " + name)


def main():
    # ---- 静かなのが正常(成功が続いている間は1通も出さない)
    check("成功が続く間は鳴らさない",
          J.should_alert({"last_ok": True}, True, "2026-09-02") is False)
    check("状態が空(初回)でも、成功なら鳴らさない",
          J.should_alert({}, True, "2026-09-02") is False)

    # ---- 壊れた瞬間は必ず鳴る(ここを落とすと8日間の凍結が再現する)
    check("壊れた初日は鳴らす",
          J.should_alert({"last_ok": True}, False, "2026-09-02") is True)
    check("状態が空でいきなり失敗なら鳴らす(fail-open)",
          J.should_alert({}, False, "2026-09-02") is True)

    # ---- 続く失敗では毎日鳴らさない(誤発火する網は無視される)
    st = {"last_ok": False, "last_alert_date": "2026-09-02"}
    check("失敗2日目は鳴らさない", J.should_alert(st, False, "2026-09-03") is False)
    check("失敗3日目も鳴らさない", J.should_alert(st, False, "2026-09-04") is False)
    check("失敗が3日続いたら鳴らし直す(忘れさせない)",
          J.should_alert(st, False, "2026-09-05") is True)

    # ---- 閉じる便は必ず出る(C-046: 閉じ方が決まらない起票を作らない)
    check("直った日は「戻った」を1回出す",
          J.should_alert({"last_ok": False, "last_alert_date": "2026-09-02"},
                         True, "2026-09-05") is True)
    check("戻った翌日はもう鳴らさない",
          J.should_alert({"last_ok": True, "last_alert_date": "2026-09-05"},
                         True, "2026-09-06") is False)

    # ---- 判定不能は黙らせる理由にしない(可用性に関わる所は fail-open)
    check("日付が壊れていても、失敗中なら鳴らす",
          J.should_alert({"last_ok": False, "last_alert_date": "ゴミ"},
                         False, "2026-09-05") is True)
    check("前便の日付が無くても、失敗中なら鳴らす",
          J.should_alert({"last_ok": False}, False, "2026-09-05") is True)

    # ---- 便の本文は推測を書かない= 空配信ガードの可能性を必ず添える
    body = J.build_body(False, 1, "guard: not all filled", "2026-09-02", 1)
    check("失敗便は空配信ガードの線を必ず書く(断定しない)", "空配信ガード" in body)
    check("失敗便は --publish-force を禁じる一文を持つ", "--publish-force" in body)
    check("失敗便に出力の末尾がそのまま載る", "guard: not all filled" in body)
    check("復旧便は「戻った」と言い切る", "戻った" in J.build_body(True, 0, "ok", "2026-09-05", 3))

    print("\n== %d/%d PASS ==" % (OK, OK + FAIL))
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
