# -*- coding: utf-8 -*-
"""check_lab_pulse の状態遷移を検査する(2026-08-13 イージス研究室・裁定C-044⑤)。

なぜ要るか(実測): 司令塔のliveness脈 local/llm/lab_tool_pulse.txt が **2026-07-20 19:22 で
止まり、23.9日間 誰も気づかなかった**。打ち手のコードは壊れていない——「自分が司令塔か」を
判定する条件が切れただけで機能が消え、**警報が無かったので沈黙のまま**だった。
C-044②が言うとおり、**沈黙して消えた安全網は誰も文句を言わない**。だから見張りを置く。

この検査が固定する規則=
  ① 鳴るのは「脈が古い」**かつ**「司令塔の耳は動いている」の2つが揃った時だけ
     (司令塔が閉じているだけの時に鳴らすと狼少年になる=規律§3)
  ② 継続中は鳴らさない(状態遷移で1回だけ)
  ③ 脈が戻ったら✅を1回だけ出して状態を戻す

実行: python scripts/discord/test_lab_pulse.py
"""
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import absence_watchdog as aw  # noqa: E402

sent = []
FAILED = []


def _fake_send(dept, body, dry_run, by_dept=False):
    sent.append(body)
    return True


def _run(live_age, ready_age, state):
    """脈の古さを差し替えて1周回す。None=ファイルなし。"""
    aw._age_or_none = lambda p: (live_age if p == aw.LAB_TOOL_PULSE else ready_age)
    aw.check_lab_pulse(state, dry_run=False)


def check(name, cond):
    print(("  PASS  " if cond else "  FAIL  ") + name)
    if not cond:
        FAILED.append(name)


def main():
    aw.bot_send = _fake_send
    state = {}

    del sent[:]
    _run(live_age=30, ready_age=10, state=state)
    check("正常(脈が新鮮) → 鳴らない", not sent and not state.get("lab_pulse_down"))

    del sent[:]
    _run(live_age=40 * 3600, ready_age=None, state=state)
    check("脈は古いが司令塔の耳が止まっている(窓が閉じている) → 鳴らない", not sent)

    del sent[:]
    _run(live_age=40 * 3600, ready_age=10, state=state)
    check("脈が古い + 耳は動いている → 1回だけ鳴る", len(sent) == 1)
    check("  本文に脈の古さ(時間)が入っている", sent and "40.0時間前" in sent[0])
    check("  状態が down になっている", state.get("lab_pulse_down") is True)

    del sent[:]
    _run(live_age=41 * 3600, ready_age=10, state=state)
    check("継続中は鳴らさない(狼少年にしない)", not sent)

    del sent[:]
    _run(live_age=40 * 3600, ready_age=None, state=state)
    check("異常のまま司令塔が閉じた → ✅を出さない(直っていないので)",
          not sent and state.get("lab_pulse_down") is True)

    del sent[:]
    _run(live_age=20, ready_age=10, state=state)
    check("脈が戻った → ✅が1回だけ出る", len(sent) == 1 and sent[0].startswith("✅"))
    check("  状態が戻っている", state.get("lab_pulse_down") is False)

    del sent[:]
    _run(live_age=25, ready_age=10, state=state)
    check("復旧後は静か", not sent)

    del sent[:]
    state2 = {}
    _run(live_age=None, ready_age=10, state=state2)
    check("脈ファイルが存在しない + 耳は動いている → 鳴る", len(sent) == 1 and "脈ファイルなし" in sent[0])

    del sent[:]
    state3 = {"lab_pulse_down": True, "last_lab_pulse_alert": time.time()}
    _run(live_age=40 * 3600, ready_age=10, state=state3)
    check("クールダウン中の再発は鳴らない(バックストップ)", not sent)

    print()
    if FAILED:
        print(f"FAIL {len(FAILED)}件: " + ", ".join(FAILED))
        return 1
    print("ALL PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
