#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""teian_echo_poll の検査(実行で通す・プラットフォームSE / 2026-08-23)。

偽物にするのは**外へ出る手だけ**= fetch(HTTP) と deliver(dispatchのPopen)。
水位の判定・分岐・冪等・fail-openは**本物の run_once** を回す。

must-fail(最低1本)= 「同じ行を2回渡したら2通目は出ない」。
  → この検査は run_once の冪等ガード(rownum <= since は continue)を消すと必ず赤になる。
     末尾の自己検証(mutation)で、実際に赤くなることまで確認する。

    python scripts/_daemons/test_teian_echo_poll.py
"""
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import teian_echo_poll as T


class Paths:
    def __init__(self, d):
        self.wm = os.path.join(d, "row.txt")
        self.fail = os.path.join(d, "fail.txt")


def _row(n, title="作品A", cid="d_1", ch="月詠み", comment="コメ"):
    return {"row": n, "values": ["2026-08-23 10:00", "2026-08-24", "cand-1",
                                  cid, "YouTube", ch, title, comment, "B"]}


def _fetch_from(rows_by_since, last_row):
    """since を受けて {ok, lastRow, rows} を返す偽fetch。rows_by_since(since)->rows。"""
    def f(since):
        return {"ok": True, "lastRow": last_row, "rows": rows_by_since(since)}
    return f


def _recorder():
    calls = []
    def d(row):
        calls.append(int(row["row"]))
        return True
    return calls, d


def run(name, fn):
    try:
        fn()
        print(f"  PASS  {name}")
        return True
    except AssertionError as e:
        print(f"  FAIL  {name}: {e}")
        return False


# ---- 1. 初回は水位を lastRow に置くだけ・配達しない ---------------------------

def t_init_sets_watermark_no_delivery():
    with tempfile.TemporaryDirectory() as d:
        p = Paths(d)
        calls, deliver = _recorder()
        # 既存に3行ある状態で導入 → 過去分は一斉に流さない
        fetch = _fetch_from(lambda s: [_row(1), _row(2), _row(3)], last_row=3)
        res = T.run_once(fetch, deliver, wm_path=p.wm, fail_path=p.fail)
        assert res["status"] == "init", res
        assert res["delivered"] == 0, res
        assert calls == [], f"初回に過去行を配達した: {calls}"
        assert T._read_int(p.wm) == 3, T._read_int(p.wm)


# ---- 2. 新しい行を配達し、水位を進める ---------------------------------------

def t_delivers_new_rows_and_advances():
    with tempfile.TemporaryDirectory() as d:
        p = Paths(d)
        T._write_int(p.wm, 3)          # 導入済み(水位3)
        calls, deliver = _recorder()
        # 正しいGAS= since より大きい行だけ返す
        fetch = _fetch_from(lambda s: [r for r in (_row(4), _row(5)) if r["row"] > s],
                            last_row=5)
        res = T.run_once(fetch, deliver, wm_path=p.wm, fail_path=p.fail)
        assert res["status"] == "ok", res
        assert calls == [4, 5], calls
        assert T._read_int(p.wm) == 5, T._read_int(p.wm)


# ---- 3. ★must-fail: 同じ行を2回渡しても2通目は出ない(冪等=水位1本) -----------

def t_same_row_twice_delivers_once():
    with tempfile.TemporaryDirectory() as d:
        p = Paths(d)
        T._write_int(p.wm, 5)
        calls, deliver = _recorder()
        # ★壊れた/重複するソースを模す= since を無視して**常に row=6 を返す**
        fetch = _fetch_from(lambda s: [_row(6)], last_row=6)
        T.run_once(fetch, deliver, wm_path=p.wm, fail_path=p.fail)   # 1周目: 配達
        T.run_once(fetch, deliver, wm_path=p.wm, fail_path=p.fail)   # 2周目: 水位6なので出ない
        assert calls == [6], f"同じ行を2回配達した(冪等が壊れている): {calls}"
        assert T._read_int(p.wm) == 6, T._read_int(p.wm)


# ---- 4. 配達失敗した行で止まる・水位を進めない --------------------------------

def t_failed_delivery_holds_watermark():
    with tempfile.TemporaryDirectory() as d:
        p = Paths(d)
        T._write_int(p.wm, 5)
        attempted = []
        def deliver(row):
            attempted.append(int(row["row"]))
            return int(row["row"]) != 6      # row=6 は失敗
        fetch = _fetch_from(lambda s: [r for r in (_row(6), _row(7)) if r["row"] > s],
                            last_row=7)
        res = T.run_once(fetch, deliver, wm_path=p.wm, fail_path=p.fail)
        assert res["status"] == "blocked", res
        assert attempted == [6], f"失敗行の先へ進んだ: {attempted}"
        assert T._read_int(p.wm) == 5, "失敗時に水位が動いた: " + str(T._read_int(p.wm))


# ---- 5. fail-open: 読めない時は水位を作らず・閾値ちょうどで1回だけ鳴らす -------

def t_fail_open_no_watermark_and_alert_once():
    with tempfile.TemporaryDirectory() as d:
        p = Paths(d)
        calls, deliver = _recorder()
        logs = []
        orig = T._log
        T._log = lambda line: logs.append(line)
        try:
            fetch = lambda since: None      # GASが読めない
            for _ in range(5):
                res = T.run_once(fetch, deliver, wm_path=p.wm, fail_path=p.fail, alert_at=3)
                assert res["status"] == "fail-open", res
        finally:
            T._log = orig
        assert calls == [], "fail-open中に配達した"
        assert not os.path.exists(p.wm), "fail-open中に水位を作った(過去を流す危険)"
        assert T._read_int(p.fail) == 5, T._read_int(p.fail)
        alerts = [l for l in logs if "fail-open" in l]
        assert len(alerts) == 1, f"鳴らした回数が1回でない(毎周期鳴らす等): {len(alerts)}"


# ---- 6. 成功でfail-openカウンタが畳まれる ------------------------------------

def t_success_resets_fail_counter():
    with tempfile.TemporaryDirectory() as d:
        p = Paths(d)
        T._write_int(p.fail, 2)         # 過去に2回失敗が積まれていた
        calls, deliver = _recorder()
        fetch = _fetch_from(lambda s: [], last_row=9)   # 初回=水位だけ置く(成功)
        T.run_once(fetch, deliver, wm_path=p.wm, fail_path=p.fail)
        assert not os.path.exists(p.fail), "成功後も失敗カウンタが残っている"


# ---- 7. 本文に必須項目(ch/題名/④コメント/cid/決定日時)が入る ----------------

def t_body_contains_required_fields():
    body = T.build_body(T.row_fields(_row(6, title="星降る夜", cid="d_42",
                                          ch="宵桜艶帖", comment="この一言")), 6)
    for must in ["宵桜艶帖", "星降る夜", "d_42", "この一言", "2026-08-23 10:00", "row=6"]:
        assert must in body, f"本文に {must} が無い:\n{body}"


def main():
    tests = [
        ("初回は水位を置くだけ・配達しない", t_init_sets_watermark_no_delivery),
        ("新規行を配達し水位を進める", t_delivers_new_rows_and_advances),
        ("★must-fail 同じ行は2回配達しない", t_same_row_twice_delivers_once),
        ("配達失敗で水位を据え置く", t_failed_delivery_holds_watermark),
        ("fail-openは水位を作らず1回だけ鳴らす", t_fail_open_no_watermark_and_alert_once),
        ("成功でfail-openカウンタを畳む", t_success_resets_fail_counter),
        ("本文に必須項目が入る", t_body_contains_required_fields),
    ]
    ok = sum(run(n, f) for n, f in tests)
    print(f"\n{ok}/{len(tests)} PASS")
    return 0 if ok == len(tests) else 1


if __name__ == "__main__":
    sys.exit(main())
