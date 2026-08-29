#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""箱ドレインのkill耐性= 処理の途中で落ちても便が1本も消えないこと(INC-100の回帰ガード)。

なぜこれを書くか(2026-08-26 イージス研究室):
  改善提案部門(トトリ)の型《研究室間デリバリ》I2=「消す前に退避する(drain窓を作らない)」の
  採否を判断するため、現状の配達経路を全部当たった。**live な経路は2本**で、どちらも既に
  不変条件を満たしていた:
    ① SQLite の leasequeue = claim→lease→ack。ackは行を**消さずdoneに変える**。
       落ちてもリース失効で再びclaimされる(test_leasequeue.py が実行で押さえている)。
    ② dept_daemon の箱 = os.replace で `.inflight` へ原子的退避 → 1件着地ごとに残りを書き戻し →
       起動時 recover_inflight() で箱へ戻す。
  ただし ② には**実行で押さえた検査が1本も無かった**(既存の "inflight" を含む検査は keeper の
  `_inflight_depts`=リース占有の話で、箱の退避とは別物)。コメントと運用でしか守られていない=
  「ソースの文字列一致は検査ではなく保険」(共通規律§3)。ここだけが未カバーだったので塞ぐ。
  ★I2 の残り1本= `bus/jsonl_adapter.py` は自身のdocstringが「本番未配線」と書いてある参考実装
    なので、live な経路として数えない。

使い方= python scripts/llm/test_drain_kill_resistance.py
"""
import json
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import dept_daemon as D  # noqa: E402


def _rec(mid):
    return {"msg_id": mid, "dept": "test-room", "content": f"本文{mid}", "author": "検査"}


def _make(box):
    """本物の Daemon を、drain/recover_inflight が触る所だけ立てて借りる(継ぎ目は handle)。"""
    d = object.__new__(D.Daemon)
    d.dept = "test-room"
    d.box = box
    d.dry_run = False
    d._relay_hold_until = 0
    d._relay_nack = False
    return d


def _write_box(box, mids):
    with open(box, "w", encoding="utf-8") as f:
        for m in mids:
            f.write(json.dumps(_rec(m), ensure_ascii=False) + "\n")


def _mids_in(path):
    if not os.path.exists(path):
        return []
    out = []
    for line in open(path, encoding="utf-8").read().splitlines():
        if line.strip():
            out.append(json.loads(line)["msg_id"])
    return out


def t_kill_midway_loses_nothing():
    """★2件目の処理中に落ちても、2件目と3件目が inflight に残っていること。"""
    with tempfile.TemporaryDirectory() as tmp:
        box = os.path.join(tmp, "test-room.jsonl")
        _write_box(box, ["A", "B", "C"])
        d = _make(box)
        seen = []

        def handle(rec, line):
            if rec["msg_id"] == "B":
                raise RuntimeError("kill(処理の最中に落ちた)")
            seen.append(rec["msg_id"])
            return True

        d.handle = handle
        try:
            d.drain()
            raise AssertionError("落ちるはずの処理が落ちていない=検査が成立していない")
        except RuntimeError:
            pass

        assert seen == ["A"], f"着地した便が違う: {seen}"
        inflight = box + ".inflight"
        assert _mids_in(inflight) == ["B", "C"], \
            f"落ちた便と未処理の便が退避に残っていない: {_mids_in(inflight)}"
        assert _mids_in(box) == [], f"箱にも残って二重になっている: {_mids_in(box)}"

        # 起動時の回収= 喪失を遅延に変える
        d.recover_inflight()
        assert _mids_in(box) == ["B", "C"], f"回収で箱へ戻っていない: {_mids_in(box)}"
        assert not os.path.exists(inflight), "回収後も退避が残っている(次回に二重復元する)"

        # 2周目= 残りが1回ずつ着地して、退避は消える
        d.handle = lambda rec, line: (seen.append(rec["msg_id"]), True)[1]
        d.drain()
        assert seen == ["A", "B", "C"], f"1回ずつ着地していない: {seen}"
        assert not os.path.exists(inflight), "きれいに終わったのに退避が残っている"


def t_session_notes_are_not_eaten():
    """★セッション宛て(session-note/followup)はデーモンが食わず箱へ戻ること(ORG-24第2幕)。"""
    with tempfile.TemporaryDirectory() as tmp:
        box = os.path.join(tmp, "test-room.jsonl")
        with open(box, "w", encoding="utf-8") as f:
            f.write(json.dumps({"msg_id": "N1", "type": "session-note", "content": "写し"},
                               ensure_ascii=False) + "\n")
            f.write(json.dumps(_rec("A"), ensure_ascii=False) + "\n")
        d = _make(box)
        seen = []
        d.handle = lambda rec, line: (seen.append(rec["msg_id"]), True)[1]
        d.drain()
        assert seen == ["A"], f"セッション宛てをデーモンが食った: {seen}"
        assert _mids_in(box) == ["N1"], f"セッション宛てが箱へ戻っていない: {_mids_in(box)}"


def t_the_check_can_tell_a_drain_window_apart():
    """★must-fail= 「消してから処理する」動く別実装だと、この検査が落ちること。

    行を消してではなく、**INC-100以前の形(全部読んで箱を消してから処理する)**へ戻して測る。
    ここが落ちなければ、上の2本は何も守っていない(偽の緑)。
    """
    with tempfile.TemporaryDirectory() as tmp:
        box = os.path.join(tmp, "test-room.jsonl")
        _write_box(box, ["A", "B", "C"])
        seen = []

        def drain_window(box_path):
            """動く別実装= 読む→消す→処理する(退避が無い)。"""
            lines = [l for l in open(box_path, encoding="utf-8").read().splitlines() if l.strip()]
            os.remove(box_path)                       # ★ここが窓
            for line in lines:
                rec = json.loads(line)
                if rec["msg_id"] == "B":
                    raise RuntimeError("kill(処理の最中に落ちた)")
                seen.append(rec["msg_id"])

        try:
            drain_window(box)
        except RuntimeError:
            pass
        lost = set("ABC") - set(seen) - set(_mids_in(box)) - set(_mids_in(box + ".inflight"))
        assert lost == {"B", "C"}, f"drain窓なのに喪失を検出できていない: {lost}"


def main():
    tests = [
        ("★処理の途中で落ちても1本も消えない(INC-100の回帰ガード)", t_kill_midway_loses_nothing),
        ("セッション宛ての写しをデーモンが食わない(ORG-24第2幕)", t_session_notes_are_not_eaten),
        ("★must-fail 消してから処理する実装なら喪失を検出する", t_the_check_can_tell_a_drain_window_apart),
    ]
    ok = 0
    for name, fn in tests:
        try:
            fn()
            print(f"  PASS  {name}")
            ok += 1
        except AssertionError as e:
            print(f"  FAIL  {name}: {e}")
    print(f"\n{ok}/{len(tests)} PASS")
    return 0 if ok == len(tests) else 1


if __name__ == "__main__":
    sys.exit(main())
