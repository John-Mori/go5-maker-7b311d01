#!/usr/bin/env python3
"""must-fail試験(C-053/C-056): 無人代打(claude_responder)は**セッション所有の部屋**へ
一次ack「受領。本対応は担当セッションへ引き継ぎます。」を打たない。

壊れていた実物(2026-09-16 Chamiスクショ, msg 1549628315248230543「引き継ぐなほんで」):
  hr-room の便へ `研究室(無人代打)` が ACK_TEXT を投稿していた。担当は対話セッション本人で
  「引き継ぐ」先が存在しない=ORG-04「存在しない担当に預けるな」と寸分違わぬ嘘。
  原因= claude_responder の SENSITIVE_DEPTS にも SESSION_OWNED_DEPTS にも hr-room が無く、
  cycle() が素通しで handle()(=ACK_TEXT投稿)へ落としていた=対処に穴が1つ残っていた。
止血(commit e560673): SESSION_OWNED_DEPTS へ hr-room を追加。cycle() 292行の
  `room_is_session_owned` が真になり、便は箱に残り handle() は呼ばれない=一次ackが出ない。

再発した別形(2026-09-17 ククール転送=Chami直「受領すんな、そして預けるな」
  msg 1549968086147530833): astro-room は専任デーモン(port 18840)が居るのに、
  _daemon_keeper.py の再起動と便の到着が接近し `room_has_own_responder()` が
  瞬断でFalseを返す窓に代打が便を掴み ACK_TEXT を投稿していた(msg 1549966975546167388)。
止血: SESSION_OWNED_DEPTS へ astro-room を追加(デーモンの生死に関わらず一次ackを打たない)。

この試験が在る理由(改悪の恒久対策=C-038/C-056):
  Codex側の口は test_codex_chami_summon.py Test B が握っているが、無人代打側の口は
  どのテストも握っていなかった。SESSION_OWNED_DEPTS から hr-room を戻した日に、この行が赤で拾う。

作法(共通規律§手順_must-fail): 外へ出る手(handle=一次ack投稿)だけ偽物にし、
  判定と分岐(SENSITIVE_DEPTS / room_is_session_owned / cycle の残す/落とす)は本物のまま
  cycle() を実行で通す。

期待:
  - hr-room便 = handle() が呼ばれない(ACKが出ない・箱に残る)。
  - 対照の通常部屋便 = handle() が呼ばれる(=この試験が「全部抑止」で偽緑になっていない証拠)。
  - 止血前(hr-roomをSESSION_OWNED_DEPTSから抜く)= hr-roomでhandle()が呼ばれ赤=must-fail成立。
使い方: python scripts/llm/test_muninn_session_owned_ack.py   (exit 0=緑 / 1=赤)
"""
import json
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import claude_responder as cr  # noqa: E402

CTRL_DEPT = "kaizen-report"  # 対照=機微でもセッション所有でもない通常部屋(handleが呼ばれるべき)


def run_cycle(records):
    """外へ出る手(handle)だけ差し替えて cycle() を実行し、handle が呼ばれた dept 一覧を返す。"""
    handled = []
    tmp = tempfile.NamedTemporaryFile("w", suffix=".jsonl", delete=False, encoding="utf-8")
    for r in records:
        tmp.write(json.dumps(r, ensure_ascii=False) + "\n")
    tmp.close()
    cr.INBOX = tmp.name
    cr.lab_alive = lambda: False               # 研究室は死=代打が動く条件
    cr.cycle_queue = lambda token=None: None    # queue経路は別便=ここでは触らない
    cr.processed_ids = lambda: set()            # 未処理として扱う
    cr.append_processed = lambda line: None      # 台帳書き込みは黙らせる
    cr.room_has_own_responder = lambda dept: False  # 専任デーモンは居ない=素の分岐を通す
    cr.handle = lambda rec, token=None: (handled.append(rec.get("dept")) or True)
    try:
        cr.cycle()
    finally:
        try:
            os.unlink(tmp.name)
        except OSError:
            pass
    return handled


def main():
    fails = []

    assert "hr-room" not in cr.SENSITIVE_DEPTS, "前提が崩れた: hr-roomが機微指定に入った(この試験は別経路を守る)"
    if not cr.room_is_session_owned("hr-room"):
        fails.append("hr-room が SESSION_OWNED_DEPTS から外れている(止血が戻された)")
    if not cr.room_is_session_owned("astro-room"):
        fails.append("astro-room が SESSION_OWNED_DEPTS から外れている(止血が戻された)")
    assert not cr.room_is_session_owned(CTRL_DEPT), f"前提が崩れた: 対照 {CTRL_DEPT} がセッション所有になった"

    hr = {"dept": "hr-room", "channel": "👤人事部門", "msg_id": "1549628315248230543",
          "author": "chami_fusoh", "content": "引き継ぐなほんで"}
    astro = {"dept": "astro-room", "channel": "秘境占星術-for-chami", "msg_id": "1549966975546167388",
             "author": "chami_fusoh", "content": "ちょっと口調が邪魔してよくわからんから..."}
    ctrl = {"dept": CTRL_DEPT, "channel": "kaizen", "msg_id": "9000000000000000001",
            "author": "someone", "content": "対照便"}
    handled = run_cycle([hr, astro, ctrl])
    print(f"[cycle] handle が呼ばれた dept={handled}")

    if "hr-room" in handled:
        fails.append("hr-room便で handle()=一次ack を打った(ORG-04の嘘の復活・NG)")
    if "astro-room" in handled:
        fails.append("astro-room便で handle()=一次ack を打った(受領すんな・預けるな違反・NG)")
    if CTRL_DEPT not in handled:
        fails.append(f"対照 {CTRL_DEPT} で handle() が呼ばれていない(全部抑止=偽緑・試験が壊れている)")

    if fails:
        for f in fails:
            print("NG:", f)
        return 1
    print("OK: 無人代打はセッション所有部屋(hr-room)へ一次ackを打たない / 通常部屋へは打つ")
    return 0


if __name__ == "__main__":
    sys.exit(main())
