#!/usr/bin/env python3
"""must-fail試験(C-053): 機微部屋でも**Chami本人の@ボス名指し**は司令塔へ回さず、その場でCodexが考える。

壊れていた実物(2026-09-16 local/llm/codex_responder_log.jsonl):
  11:47:35 / 11:48:38 の2連続 sensitive_deferred(👤人事部門-補強•キャラ設定)。
  2通目はChami本人の「＠ボス 引き継がず、ここで考えてくれ」(msg 1549612874945663090)=
  **回すなという指示そのものを回し返していた**。
根拠: 共通規律§3.8「Chamiが相手を名指しした時は階梯を経由せず直送してよい」/
  §3.7「Chamiの直接指示はどの裁定より上」。ここへ来る便は discord_gateway.route_codex_summon を
  通った@ボス名指しだけ= 名指しは既に成立している。

作法(共通規律§3): 外へ出る手(notify_room=送信 / codex_answer=Codex起動 / mark=リアクション /
  append_line=書き込み / lease延長)だけ偽物にし、判定と分岐(from_chami・origin_dept_for・
  SENSITIVE_DEPTS・scripted_reply)は本物のまま handle() を実行で通す。

期待:
  - 止血前の実装 = 赤(Chami便が sensitive_deferred で回される)= must-fail成立。
  - 止血後の実装 = 緑(Chami便はCodexへ渡る / 他人の名指しは従来どおり司令塔へ回る)。
使い方: python scripts/llm/test_codex_chami_summon.py   (exit 0=緑 / 1=赤)
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import codex_responder as cr  # noqa: E402

BOUNCE = "受け取りました。ここは司令塔が直接読む部屋なので、そちらへ回しました。"


def run_once(rec):
    """外へ出る手だけ差し替えて handle() を実行し、(mode, 送信文, 押した印, Codex起動) を返す。"""
    sent, marks, ran = [], [], []
    cr.notify_room = lambda channel, text: (sent.append(text) or True)
    cr.mark = lambda channel, msg_id, kind: marks.append(kind)
    cr.codex_answer = lambda channel, content, msg_id="", origin_dept="": (
        ran.append(content) or (True, "", ""))
    cr._start_lease_extender = lambda *a, **k: None
    cr.append_line = lambda *a, **k: None
    cr.escalate = lambda *a, **k: None
    cr.usage_limit_hold = lambda: (False, None)
    cr.clear_usage_limit = lambda why="": False
    cr.log = lambda rec_: None
    mode = cr.handle(rec, raw_line="{}", lease_id="dummy", deliveries=1)
    return mode, sent, marks, ran


def main():
    fails = []

    # --- A: Chami本人が機微部屋(hr-room)でボスを名指し= 回さずCodexへ渡す ---
    chami = {
        "content": "＠ボス 　引き継がず、ここで考えてくれ",
        "msg_id": "1549612874945663090",
        "channel_id": "1525946809695076585",
        "channel": "👤人事部門-補強•キャラ設定",
        "codex_origin_dept": "hr-room",
        "dept": "codex",
        "author": "chami_fusoh",
        "author_id": "490925528367497227",
    }
    assert cr.origin_dept_for(chami) == "hr-room", "前提が崩れた: 元部門がhr-roomでない"
    assert "hr-room" in cr.SENSITIVE_DEPTS, "前提が崩れた: hr-roomが機微指定でない"
    mode, sent, marks, ran = run_once(chami)
    print(f"[A Chami] mode={mode!r} sent={sent} marks={marks} codex起動={bool(ran)}")
    if mode == "sensitive_deferred":
        fails.append("A: Chami本人の名指しを司令塔へ回した(NG)")
    if any(BOUNCE in t for t in sent):
        fails.append(f"A: 回送の定型文を部屋へ出した(NG): {BOUNCE!r}")
    if not ran:
        fails.append("A: Codexを起動していない(その場で考えていない)")

    # --- B: Chami以外(AI)が同じ機微部屋でボスを名指し= 従来どおり司令塔へ回す(防御は残す) ---
    other = dict(chami, author="オタコン", author_id="999", msg_id="1")
    mode, sent, marks, ran = run_once(other)
    print(f"[B 他人] mode={mode!r} sent={sent} marks={marks} codex起動={bool(ran)}")
    if mode != "sensitive_deferred":
        fails.append(f"B: 機微部屋の他人名指しを回していない(防御が消えた): mode={mode!r}")
    if ran:
        fails.append("B: 機微部屋で他人の名指しからCodexを起動した(NG)")
    # ★2026-09-16 追加(Chami直接指示「これやめろって」msg 1549628255173353625)=
    #   回すこと自体は残すが、**部屋へ出す中身の無い定型文は撤去した**。
    #   ここが在るのは、この試験が定型文(BOUNCE)を握っている唯一の場所だからだ
    #   = 撤去を戻した日に、この行が赤で拾う。
    if sent:
        fails.append(f"B: 回送時に部屋へテキストを出した(中身無しackの復活・NG): {sent!r}")

    if fails:
        for f in fails:
            print("NG:", f)
        return 1
    print("OK: 機微部屋でもChami本人の@ボスは回さない / 他人の名指しは従来どおり回す")
    return 0


if __name__ == "__main__":
    sys.exit(main())
