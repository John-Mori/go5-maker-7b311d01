#!/usr/bin/env python3
"""司令塔(研究室=main)の生存判定を一本化する共有ヘルパ(2026-07-18 INC対策)。

なぜ要るか(今回の事故の真因):
  代打系responderが「司令塔不在」の判定を各自コピペで持っていた。2026-07-18に
  claude_responderだけが2信号(readiness OR liveness)へ格上げされ、local/gemini responderは
  claude_active.txt 90秒単独ゲートのまま取り残された(格上げの取りこぼし=drift)。
  結果、mainが長い作業中(waiter脈=readinessが一時途切れ・toolフック脈=livenessは新鮮)でも
  local/geminiが「不在」と誤判定してgeneric即答を撃ち、キャラの本応答を代打が食う暴発が起きた。
  判定をここへ集約し、全responderが同じ1関数を呼ぶことで二度とdriftさせない。

2信号:
  readiness = local/llm/claude_active.txt   … waiter(inbox_waiter --name main)が箱を見張る脈(2秒毎)
  liveness  = local/llm/lab_tool_pulse.txt  … presence hook(pulse_touch.py)がツール実行時に打つ脈
判定(claude_responder.lab_alive と完全一致):
  readiness < READY_SEC                                        → 生存(耳が箱を見ている=本人が応対)
  さもなくば liveness < BUSY_SEC かつ readiness < HARD_CAP_SEC → 生存(処理中で耳が一時停止・猶予)
  それ以外                                                     → 不在(代打が出てよい)
HARD_CAP: livenessがいくら新しくても耳が45分止まったままなら不在扱い(耳が死んだまま作業を
  続けるmainが新着を永久放置するのを防ぐ硬い上限)。

テスト: 環境変数 GO5_LOCAL_DIR があれば local/ の代わりにそれを使う(全パス)。
"""
import os
import time

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.normpath(os.path.join(_HERE, "..", ".."))
_LOCAL = os.environ.get("GO5_LOCAL_DIR") or os.path.join(_ROOT, "local")

LAB_PULSE = os.path.join(_LOCAL, "llm", "claude_active.txt")       # readiness=waiterの脈
LAB_TOOL_PULSE = os.path.join(_LOCAL, "llm", "lab_tool_pulse.txt")  # liveness=presence hookの脈

READY_SEC = 90          # waiterは監視中2秒毎に脈を打つ=90秒あれば十分
BUSY_SEC = 300          # 直近5分以内にツール実行があれば「処理中」とみなす
HARD_CAP_SEC = 45 * 60  # 耳の停止がこれを超えたら、働いていても不在扱い


def _age(path):
    try:
        return time.time() - os.path.getmtime(path)
    except OSError:
        return float("inf")


def lab_alive():
    """司令塔(main)が生存しているか。2信号判定(readiness OR liveness+HARD_CAP)。"""
    ready = _age(LAB_PULSE)       # readiness: 耳(waiter)が箱を見ているか
    if ready < READY_SEC:
        return True
    busy = _age(LAB_TOOL_PULSE)   # liveness: 道具を使って働いているか(presence hook)
    return busy < BUSY_SEC and ready < HARD_CAP_SEC


if __name__ == "__main__":
    # 点検用: 現在の判定と各脈の鮮度を表示
    print(f"lab_alive={lab_alive()}  readiness={_age(LAB_PULSE):.1f}s  liveness={_age(LAB_TOOL_PULSE):.1f}s")
