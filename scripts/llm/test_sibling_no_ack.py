#!/usr/bin/env python3
"""must-fail試験(C-053): 兄弟常駐(gemini/local)も、機微部屋で中身の無い一次ackを出さない。

同じ炎上 DEF-otacon-radio-df36094b69 の**兄弟の口**。codex_responder.py:499 と
一字一句ほぼ同じ文型が、gemini_responder.py:136 と local_responder.py:1391 に写しで在った。
Chami原文=「これやめろって」(msg 1549628255173353625 / 2026-09-16 12:49:26 JST / hr-room)。

★この2本は撤去前 mark() を一度も押していなかった= **単純撤去だと部屋が無音になる**。
  だから「ackが出ない」だけでなく「回送(append_line)が生きている」「進捗印が残る」を
  同じ節で見る(共通規律§2=「内容の無い一次ackは沈黙より悪い。ただし黙って落とすな」)。

作法(共通規律§3): 外へ出る手(send=投稿 / mark=リアクション / append_line=書き込み / log)
  だけ偽物にし、判定と分岐(dept in SENSITIVE_DEPTS)は本物のまま handle() を実行で通す。

期待:
  - 撤去前の実装 = 赤(ack文が send に出る)= must-fail成立。
  - 撤去後の実装 = 緑(ackは出ない・回送と印は残る)。
使い方: python scripts/llm/test_sibling_no_ack.py   (exit 0=緑 / 1=赤)
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import gemini_responder as gr   # noqa: E402
import local_responder as lr    # noqa: E402

ACK = "受け取ったよ。ここは司令塔(アメスたち)が直接読む部屋だから、次に起きた時に必ず応えるね。"


def run_one(mod, name, call):
    """1本ぶん回す。戻り値= 失敗理由のリスト(空なら緑)。"""
    sent, marks, appended, logged = [], [], [], []

    # --- 外へ出る手だけ差し替える(判定と分岐は本物) ---
    mod.send = lambda channel, text: (sent.append(text) or True)
    mod.mark = lambda channel, msg_id, kind: marks.append(kind)
    mod.append_line = lambda path, line: appended.append(path)
    mod.log = lambda rec: logged.append(rec.get("mode"))

    rec = {
        "content": "人事の設定について相談したい。名前の扱いをどうするか決めたい。",
        "msg_id": "88888",
        "channel_id": "234567",
        "channel": "hr-room",
        "dept": "hr-room",          # ★ここが本物の分岐キー
        "author": "オタコン",
        "author_id": "999",
    }
    assert rec["dept"] in mod.SENSITIVE_DEPTS, f"前提が崩れた: {name} で hr-room が機微指定でない"

    call(mod, rec)

    print(f"[{name}] send呼び={sent} / marks={marks} / "
          f"append_line={len(appended)}本 / log={logged}")
    fails = []
    if sent:
        fails.append(f"{name}: 中身無し一次ackが部屋へ出た(NG): {sent!r}")
    if len(appended) < 2:
        fails.append(f"{name}: 司令塔への回送(append_line)が呼ばれていない"
                     f"= 部屋にも司令塔にも何も残らない(沈黙・NG): {len(appended)}本")
    if "既読" not in marks:
        fails.append(f"{name}: 進捗印『既読』が付いていない(撤去で無音にしないための信号)")
    if "即答" not in marks:
        fails.append(f"{name}: 進捗印『即答』が付いていない(その場で完結したことを示す信号)")
    if logged != ["sensitive_deferred"]:
        fails.append(f"{name}: 機微回送の記録が残っていない(防御が消えた): {logged!r}")
    return fails


def main():
    fails = []
    fails += run_one(gr, "gemini_responder", lambda m, r: m.handle(r, raw_line="{}"))
    fails += run_one(lr, "local_responder", lambda m, r: m.handle(r, raw_line="{}"))

    # 撤去した文面そのものがソースへ戻っていないかの保険(★これ単体は検査ではない=上が本体)
    for path in ("gemini_responder.py", "local_responder.py"):
        src = open(os.path.join(os.path.dirname(os.path.abspath(__file__)), path),
                   encoding="utf-8").read()
        if ("send(channel, \"" + ACK) in src:
            fails.append(f"{path}: 撤去したack文が send() で復活している")

    if fails:
        for f in fails:
            print("  ✗ " + f)
        print("赤(FAIL)")
        return 1
    print("  ✓ 兄弟2本とも 中身無しackは出ない / 回送は生きている / 既読・即答の印は残る")
    print("緑(PASS)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
