#!/usr/bin/env python3
"""presence hook: ツール実行のたびに研究室の脈を打つ (PostToolUse・S1/P1根治)。

なぜ要るか(INC-94):
  脈(claude_active.txt)を打つのは従来waiterだけ。waiterは新着配達と同時に自了するため、
  研究室が長いターンを処理している間は脈が止まり、無人代打が「死亡」と誤判定して発火していた。
  このフックは「実際にツールを使って働いている間、脈が打たれ続ける」を保証する=閾値調整に
  依存しない本質解(改善設計書_基盤恒久化_世界OSS調査 §3.4 / k8sのliveness相当)。

仕組み:
  - .claude/settings.json の PostToolUse に登録=このrepoの全セッションで発火する。
  - stdinのJSON(session_id)を local/llm/lab_session_id.txt(研究室が起動時に名乗った札)と照合し、
    **一致した時だけ** lab_tool_pulse.txt をtouchする。
  - ★touch先はwaiterの脈(claude_active.txt)とは**別ファイル**(出荷前批評のfatal指摘・2026-07-18):
    liveness(道具を使って働いている)とreadiness(waiterが箱を見ている)を同じファイルに混ぜると、
    耳が死んだまま長時間作業した場合に代打が永久に抑止され、45分/900秒級の安全上限が消える。
    判定の合成は claude_responder.lab_alive() 側で行う(readiness主信号+liveness猶予+硬い上限)。
  - 部門セッションでは何もしない(部門の脈で研究室を生存偽装すると、研究室が本当に死んだ時に
    代打が永久に出ない=INC-94の逆事故になるため)。
  - 札が古い/無い場合も何もしない=現行動作(waiterの脈)に安全に退化する。fail-open。

研究室の名乗り方(起動時1回): python scripts/hooks/claim_lab.py <自分のsession_id>
"""
import json
import os
import sys

ROOT = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
LAB_ID_FILE = os.path.join(ROOT, "local", "llm", "lab_session_id.txt")
PULSE = os.path.join(ROOT, "local", "llm", "lab_tool_pulse.txt")  # liveness専用(readinessと分離)


def main():
    try:
        sid = json.load(sys.stdin).get("session_id", "")
    except Exception:
        return 0
    if not sid:
        return 0
    try:
        with open(LAB_ID_FILE, "r", encoding="utf-8") as f:
            lab_id = f.read().strip()
    except OSError:
        return 0
    if lab_id and sid == lab_id:
        try:
            os.makedirs(os.path.dirname(PULSE), exist_ok=True)
            with open(PULSE, "a", encoding="utf-8"):
                pass
            os.utime(PULSE, None)
        except OSError:
            pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
