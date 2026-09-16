#!/usr/bin/env python3
"""must-fail試験(C-053): @ボス(Codex)への重い依頼で、中身の無い一次ackテキストを部屋へ出さない。

炎上(enjoh/恒久)+再発 DEF-otacon-radio-df36094b69 の恒久対策の検証。
Chami原文「このやり取りいらない」→ 進捗印👀(着手)は残す・テキストackだけ止める。

作法(共通規律§3): 外へ出る手(notify_room=送信 / codex_answer=Codex起動 / mark=リアクション /
  append_line=書き込み / lease延長)だけ偽物にし、判定と分岐(heavy_request・delivery_count==1・
  scripted_reply・origin_dept_for)は本物のまま handle() を実行で通す。

期待:
  - 現行(撤去前)の実装 = 赤(ackテキストが notify_room に出る)= must-fail成立。
  - 恒久対策(撤去後)の実装 = 緑(ackテキストは出ない・着手印👀は残る)。
使い方: python scripts/llm/test_codex_no_ack.py   (exit 0=緑 / 1=赤)
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import codex_responder as cr  # noqa: E402

ACK = "受け取った。処理を開始する。完了結果は保存してから返す。"

sent_texts = []
marks = []


def main():
    # --- 外へ出る手だけ差し替える ---
    cr.notify_room = lambda channel, text: (sent_texts.append(text) or True)
    cr.mark = lambda channel, msg_id, kind: marks.append(kind)
    cr.codex_answer = lambda channel, content, msg_id="", origin_dept="": (True, None, "")
    cr._start_lease_extender = lambda *a, **k: None
    cr.append_line = lambda *a, **k: None
    cr.usage_limit_hold = lambda: (False, None)
    cr.clear_usage_limit = lambda why="": False

    # --- 本物の判定を通す重い@ボス便(len>=40=heavy_request True) ---
    rec = {
        "content": "@ボス この画像生成ルームのフローを実装して、優依が受け取って部屋へ返すところまで通してほしい。設計から実装まで。",
        "msg_id": "77777",
        "channel_id": "123456",
        "channel": "cq-otacon",
        "origin_dept": "otacon-radio",  # 非SENSITIVE
        "dept": "codex",
    }
    assert cr.heavy_request(rec) is True, "前提が崩れた: この便がheavy扱いでない"

    mode = cr.handle(rec, raw_line="{}", lease_id="dummy", deliveries=1)

    ack_out = ACK in sent_texts
    chakusyu_ok = "着手" in marks

    print(f"mode={mode!r} / notify_room呼び={sent_texts} / marks={marks}")
    fails = []
    if ack_out:
        fails.append(f"中身無し一次ackが部屋へ出た(NG): {ACK!r}")
    if not chakusyu_ok:
        fails.append("進捗印『着手』👀が付いていない(この信号は残すこと)")
    # --- 第2の口(2026-09-16 追加)= 機微部屋の他人便を司令塔へ回す時の定型文 -------------
    #   ★同じ炎上(DEF-otacon-radio-df36094b69)の**2つ目の出口**だ。
    #     1つ目(上)を撤去した後も、こちらは9/16 12:49までChamiの目の前に出続けていた。
    #     Chami原文=「これやめろって」(msg 1549628255173353625 / hr-room)。
    #   ★回すのをやめたのではない= escalate(司令塔の主受付箱へ生便を入れる)が
    #     呼ばれ続けることも、ここで一緒に見る。これを外すと**沈黙**になる=最悪の事故。
    del sent_texts[:]
    del marks[:]
    escalated = []
    cr.escalate = lambda channel, raw_line, note="": escalated.append(channel)
    rec_b = {
        "content": "@ボス 人事の設定について相談したい。名前の扱いをどうするか決めたい。",
        "msg_id": "88888",
        "channel_id": "234567",
        "channel": "hr-room",
        "origin_dept": "hr-room",     # SENSITIVE
        "author": "オタコン",
        "author_id": "999",
        "dept": "codex",
    }
    assert cr.origin_dept_for(rec_b) == "hr-room", "前提が崩れた: 元部門がhr-roomでない"
    assert "hr-room" in cr.SENSITIVE_DEPTS, "前提が崩れた: hr-roomが機微指定でない"
    assert cr.from_chami(rec_b) is False, "前提が崩れた: 他人便がChami扱いになっている"

    mode_b = cr.handle(rec_b, raw_line="{}", lease_id="dummy", deliveries=1)
    print(f"[第2の口] mode={mode_b!r} / notify_room呼び={sent_texts} / "
          f"marks={marks} / escalate={escalated}")
    if mode_b != "sensitive_deferred":
        fails.append(f"機微部屋の他人便を回していない(防御が消えた): mode={mode_b!r}")
    if sent_texts:
        fails.append(f"回送の中身無しackが部屋へ出た(NG): {sent_texts!r}")
    if not escalated:
        fails.append("escalateが呼ばれていない= 部屋にも司令塔にも何も残らない(沈黙・NG)")
    if "既読" not in marks:
        fails.append("進捗印『既読』が付いていない(この信号は残すこと)")

    if fails:
        for f in fails:
            print("  ✗ " + f)
        print("赤(FAIL)")
        return 1
    print("  ✓ 中身無しackは2つの口とも出ない / 着手👀・既読は残っている / 回送は生きている")
    print("緑(PASS)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
