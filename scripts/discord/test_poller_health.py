# -*- coding: utf-8 -*-
"""check_poller_health の状態遷移を検査する(2026-08-13 イージス研究室)。

なぜ要るか(実測): incidentの直近400件のうち **341件(85%)** が同一文の
「⚠inbox_poller 停止の可能性」だった。原因は2つ——
  ① 見る先が **2026-07-20に退役した inbox_poller** の脈(2026-07-19で更新停止)
  ② 異常な間ずっと30分毎に鳴らす作りで、**状態遷移になっていなかった**
狼少年になった警報は読まれない(規律§3)。この検査は「1回だけ鳴る/復旧で1回だけ戻す」
という**守りたい規則**を固定する(現在の値ではなく規則を書く=規律§3)。

実行: python scripts/discord/test_poller_health.py
"""
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import absence_watchdog as aw  # noqa: E402

sent = []


def _fake_send(dept, body, dry_run, by_dept=False):
    sent.append(body)
    return True


def _run(age_sec, state):
    """脈の古さを age_sec に見せかけて1周回す。age_sec=None は脈ファイルなし。"""
    if age_sec is None:
        aw.poller_age_sec = lambda: None
    else:
        aw.poller_age_sec = lambda: age_sec
    aw.check_poller_health(state, dry_run=False)


def main():
    aw.bot_send = _fake_send
    fails = []

    # 1) 正常な間は一度も鳴らない
    st = {"last_poller_alert": 0, "poller_down": False}
    for _ in range(5):
        _run(24, st)
    if sent:
        fails.append("正常なのに鳴った: %r" % sent)

    # 2) 停止した瞬間に1回だけ鳴る(継続中は鳴らさない=狼少年にしない)
    sent.clear()
    for _ in range(5):
        _run(9999, st)
    if len(sent) != 1:
        fails.append("停止の発報が%d回(期待1回)" % len(sent))
    elif "discord_gateway" not in sent[0]:
        fails.append("発報の宛先が現行の受信を指していない: %r" % sent[0][:60])
    if not st.get("poller_down"):
        fails.append("poller_down が立っていない")

    # 3) 復旧で ✅ を1回だけ出し、状態が戻る
    sent.clear()
    for _ in range(3):
        _run(24, st)
    if len(sent) != 1:
        fails.append("復旧の通知が%d回(期待1回)" % len(sent))
    elif not sent[0].startswith("✅"):
        fails.append("復旧通知が✅で始まっていない: %r" % sent[0][:40])
    if st.get("poller_down"):
        fails.append("復旧後も poller_down が立ったまま")

    # 4) 再発したらまた1回鳴る(1度きりの通知で終わらない)
    sent.clear()
    st["last_poller_alert"] = 0  # クールダウンは別ガード。ここでは遷移だけを見る
    for _ in range(4):
        _run(None, st)
    if len(sent) != 1:
        fails.append("再発時の発報が%d回(期待1回)" % len(sent))

    # 5) 見る先が退役済みの inbox_poller ではないこと(退行の固定)
    if "poller_active" in aw.GATEWAY_PULSE:
        fails.append("退役済み inbox_poller の脈を見ている")
    if not aw.GATEWAY_PULSE.endswith(os.path.join("queue", "_gateway_pulse.txt")):
        fails.append("脈の場所が discord_gateway のものでない: %s" % aw.GATEWAY_PULSE)

    for f in fails:
        print("FAIL: " + f)
    print("%s (%d件)" % ("ALL PASS" if not fails else "FAILED", len(fails)))
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
