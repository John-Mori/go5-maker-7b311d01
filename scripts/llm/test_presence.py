#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""presence の生存判定と、司令塔(main)の身元判定の検査。

なぜ要るか(2026-08-13 イージス研究室・C-044の2件目):
  presence.lab_alive() の2信号目(liveness= lab_tool_pulse.txt)が **23.9日間 黙って死んでいた**。
  コードは壊れていない。**打ち手の条件が切れただけ**で機能が消え、警報も出なかった。
  → ①判定の3分岐が本当に3分岐として動くこと ②身元判定が他部屋のセッションを司令塔と
    誤認しないこと、を機械で固定する。特に②は**実際に本番で誤認を踏んだ**(下のコメント)。

走らせ方: python scripts/llm/test_presence.py
"""
import os
import shutil
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.normpath(os.path.join(HERE, "..", ".."))

FAILED = []


def check(name, got, want):
    ok = got == want
    print(("  PASS  " if ok else "  FAIL  ") + name + ("" if ok else f"  (got={got} want={want})"))
    if not ok:
        FAILED.append(name)


def _fresh(path, age_sec):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write("x\n")
    t = time.time() - age_sec
    os.utime(path, (t, t))


def test_lab_alive(tmp):
    """lab_alive() の3分岐(HQの受け入れ条件)。"""
    os.environ["GO5_LOCAL_DIR"] = tmp
    for m in ("presence",):
        sys.modules.pop(m, None)
    sys.path.insert(0, HERE)
    import presence
    ready, busy = presence.LAB_PULSE, presence.LAB_TOOL_PULSE

    print("[1] lab_alive の3分岐")
    _fresh(ready, 10); _fresh(busy, 999999)
    check("readinessが新鮮 → 生存(livenessが死んでいても)", presence.lab_alive(), True)

    _fresh(ready, 600); _fresh(busy, 30)
    check("readinessが古い + livenessが新鮮 → 生存(長ターン中)", presence.lab_alive(), True)

    _fresh(ready, 600); _fresh(busy, 600)
    check("両方古い → 不在(代打が出てよい)", presence.lab_alive(), False)

    _fresh(ready, presence.HARD_CAP_SEC + 60); _fresh(busy, 5)
    check("livenessが新鮮でも耳が45分以上死んでいる → 不在(HARD_CAP)", presence.lab_alive(), False)

    os.remove(ready); os.remove(busy)
    check("脈ファイルが両方無い → 不在", presence.lab_alive(), False)


def test_is_lab_session(tmp):
    """pulse_touch の身元判定=「耳を武装したのは自分か」。"""
    os.environ["GO5_LOCAL_DIR"] = tmp
    sys.modules.pop("pulse_touch", None)
    sys.path.insert(0, os.path.join(ROOT, "scripts", "hooks"))
    import pulse_touch as pt
    os.makedirs(os.path.dirname(pt.LAB_ID_FILE), exist_ok=True)

    print("[2] 司令塔の身元判定")
    for p in (pt.LAB_ID_FILE, pt.LAB_OWNER_PID):
        if os.path.exists(p):
            os.remove(p)
    check("札もPIDも無い → 打たない(fail-open)",
          pt.is_lab_session({"session_id": "s1"}, my_pid=111), False)

    with open(pt.LAB_OWNER_PID, "w", encoding="utf-8") as f:
        f.write("111\n")
    check("耳を武装した窓と自分が同じPID → 司令塔",
          pt.is_lab_session({"session_id": "s1"}, my_pid=111), True)
    check("別のPID(=他の部屋のセッション) → 司令塔ではない",
          pt.is_lab_session({"session_id": "s1"}, my_pid=222), False)
    check("自分のPIDが取れない(0) → 打たない",
          pt.is_lab_session({"session_id": "s1"}, my_pid=0), False)

    with open(pt.LAB_OWNER_PID, "w", encoding="utf-8") as f:
        f.write("こわれた\n")
    check("PIDファイルが壊れている → 打たない", pt.is_lab_session({"session_id": "s1"}, my_pid=111), False)

    # ★旧経路(札)は消していない=C-003。札が一致するなら従来どおり司令塔として扱う。
    with open(pt.LAB_ID_FILE, "w", encoding="utf-8") as f:
        f.write("s9\n")
    check("札が一致 → 司令塔(旧経路は生きたまま)",
          pt.is_lab_session({"session_id": "s9"}, my_pid=222), True)

    # ★退行の固定(2026-08-13 17:21 に本番で実際に踏んだ事故):
    #   「自分のtranscriptに `inbox_waiter.py --name main` と書いてあるか」で判定していた頃、
    #   この機能をデバッグしていた aegis-gl のセッションが自分を司令塔と誤認し、
    #   実物の lab_tool_pulse.txt を打ち lab_session_id.txt を上書きした。
    #   文字列は誰でも書ける=判定に使わない。ここでその方式が戻っていないことを固定する。
    src = open(os.path.join(ROOT, "scripts", "hooks", "pulse_touch.py"), encoding="utf-8").read()
    body = src.split('"""', 2)[-1]          # docstring(事故の記録)は対象外
    check("transcriptを読んで判定する実装が戻っていない",
          ("transcript_path" in body) or ("json.load" in body and "tool_use" in body), False)


def main():
    tmp = tempfile.mkdtemp(prefix="presence_test_")
    try:
        test_lab_alive(tmp)
        test_is_lab_session(tmp)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    print()
    if FAILED:
        print(f"FAIL {len(FAILED)}件: " + ", ".join(FAILED))
        return 1
    print("ALL PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
