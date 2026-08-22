#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""teian_echo_poll の検査(実行で通す・プラットフォームSE / 2026-08-23)。

偽物にするのは**外へ出る手だけ**= fetch(HTTP) / deliver(dispatch) / alert(部屋への警報)。
水位の判定・分岐・冪等・fail-open・連続失敗カウンタは**本物の run_once** を回す。

★返す物1の恒久対策も検査する= run_once は log 先を wm_path と同じディレクトリへ導出する。
  検査は一時ディレクトリの wm_path を渡すので、**本番ログ(local/_state/…)を1バイトも触らない**。
  t_never_touches_production_log がそれを実測する(この検査は、run_once が POLL_LOG を直握りに
  戻すと必ず赤くなる)。

must-fail(最低1本)= 「同じ行を2回渡したら2通目は出ない」。
  → run_once の冪等ガード(rownum <= since は continue)を消すと必ず赤になる(末尾でmutation実証済)。

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
    def f(since):
        return {"ok": True, "lastRow": last_row, "rows": rows_by_since(since)}
    return f


def _recorder():
    calls = []
    def d(row):
        calls.append(int(row["row"]))
        return True
    return calls, d


def _alert_recorder():
    got = []
    def a(reason, dept=None):
        got.append(reason)
    return got, a


def run(name, fn):
    try:
        fn()
        print(f"  PASS  {name}")
        return True
    except AssertionError as e:
        print(f"  FAIL  {name}: {e}")
        return False


# ---- 1. 初回は水位を lastRow に置くだけ・配達も警報もしない -------------------

def t_init_sets_watermark_no_delivery():
    with tempfile.TemporaryDirectory() as d:
        p = Paths(d)
        calls, deliver = _recorder()
        alerts, alert = _alert_recorder()
        fetch = _fetch_from(lambda s: [_row(1), _row(2), _row(3)], last_row=3)
        res = T.run_once(fetch, deliver, alert=alert, wm_path=p.wm, fail_path=p.fail)
        assert res["status"] == "init", res
        assert calls == [] and alerts == [], (calls, alerts)
        assert T._read_int(p.wm) == 3, T._read_int(p.wm)


# ---- 2. 新しい行を配達し、水位を進める ---------------------------------------

def t_delivers_new_rows_and_advances():
    with tempfile.TemporaryDirectory() as d:
        p = Paths(d)
        T._write_int(p.wm, 3)
        calls, deliver = _recorder()
        alerts, alert = _alert_recorder()
        fetch = _fetch_from(lambda s: [r for r in (_row(4), _row(5)) if r["row"] > s], last_row=5)
        res = T.run_once(fetch, deliver, alert=alert, wm_path=p.wm, fail_path=p.fail)
        assert res["status"] == "ok", res
        assert calls == [4, 5], calls
        assert T._read_int(p.wm) == 5, T._read_int(p.wm)


# ---- 3. ★must-fail: 同じ行を2回渡しても2通目は出ない(冪等=水位1本) -----------

def t_same_row_twice_delivers_once():
    with tempfile.TemporaryDirectory() as d:
        p = Paths(d)
        T._write_int(p.wm, 5)
        calls, deliver = _recorder()
        _, alert = _alert_recorder()
        fetch = _fetch_from(lambda s: [_row(6)], last_row=6)   # sinceを無視し常にrow=6(重複ソース)
        T.run_once(fetch, deliver, alert=alert, wm_path=p.wm, fail_path=p.fail)
        T.run_once(fetch, deliver, alert=alert, wm_path=p.wm, fail_path=p.fail)
        assert calls == [6], f"同じ行を2回配達した(冪等が壊れている): {calls}"
        assert T._read_int(p.wm) == 6, T._read_int(p.wm)


# ---- 4. 配達失敗(blocked)は水位据え置き・カウンタに積む・閾値で部屋へ1回(返す物2) -

def t_blocked_holds_counts_and_alerts_once():
    with tempfile.TemporaryDirectory() as d:
        p = Paths(d)
        T._write_int(p.wm, 5)
        attempted = []
        def deliver(row):
            attempted.append(int(row["row"]))
            return False              # 常に配達失敗
        alerts, alert = _alert_recorder()
        fetch = _fetch_from(lambda s: [r for r in (_row(6),) if r["row"] > s], last_row=6)
        for i in range(4):            # 4周回す
            res = T.run_once(fetch, deliver, alert=alert, wm_path=p.wm, fail_path=p.fail, alert_at=3)
            assert res["status"] == "blocked", res
        assert attempted == [6, 6, 6, 6], attempted
        assert T._read_int(p.wm) == 5, "失敗時に水位が動いた: " + str(T._read_int(p.wm))
        assert T._read_int(p.fail) == 4, T._read_int(p.fail)
        assert len(alerts) == 1, f"部屋への警報が1回でない(毎周期/無警報): {len(alerts)}"


# ---- 5. fail-open・未初期化(口がまだ無い)= 部屋へは鳴らさない(既知の待ち) -----

def t_fail_open_bootstrap_no_room_alert():
    with tempfile.TemporaryDirectory() as d:
        p = Paths(d)
        alerts, alert = _alert_recorder()
        _, deliver = _recorder()
        for _ in range(5):
            res = T.run_once(lambda s: None, deliver, alert=alert,
                             wm_path=p.wm, fail_path=p.fail, alert_at=3)
            assert res["status"] == "fail-open", res
        assert not os.path.exists(p.wm), "fail-open中に水位を作った(過去を流す危険)"
        assert T._read_int(p.fail) == 5, T._read_int(p.fail)
        assert alerts == [], f"口がまだ無い既知の待ちで部屋へ鳴らした(狼少年): {alerts}"
        # ローカルログには閾値で1行だけ出る(継ぎ目の内側=一時ディレクトリ)
        logtxt = open(os.path.join(d, "teian_decide_poll.log"), encoding="utf-8").read()
        assert logtxt.count("読み取り口がまだ無い") == 1, logtxt


# ---- 6. fail-open・初期化後(口が生えていたのに落ちた)= 部屋へ1回 --------------

def t_fail_open_after_init_alerts_room():
    with tempfile.TemporaryDirectory() as d:
        p = Paths(d)
        T._write_int(p.wm, 7)         # 既に初期化済み(口は生えていた)
        alerts, alert = _alert_recorder()
        _, deliver = _recorder()
        for _ in range(4):
            res = T.run_once(lambda s: None, deliver, alert=alert,
                             wm_path=p.wm, fail_path=p.fail, alert_at=3)
            assert res["status"] == "fail-open", res
        assert T._read_int(p.wm) == 7, "fail-openで水位が動いた"
        assert len(alerts) == 1, f"初期化後のfetch異常で部屋へ1回鳴らせていない: {len(alerts)}"


# ---- 7. きれいに1周できたら連続失敗カウンタを畳む ----------------------------

def t_clean_cycle_resets_counter():
    with tempfile.TemporaryDirectory() as d:
        p = Paths(d)
        T._write_int(p.wm, 5)
        T._write_int(p.fail, 2)       # 過去に2回失敗が積まれていた
        calls, deliver = _recorder()
        _, alert = _alert_recorder()
        fetch = _fetch_from(lambda s: [], last_row=5)   # 新規なし=きれいに1周
        res = T.run_once(fetch, deliver, alert=alert, wm_path=p.wm, fail_path=p.fail)
        assert res["status"] == "ok", res
        assert not os.path.exists(p.fail), "きれいに1周したのに失敗カウンタが残っている"


# ---- 8. ★返す物1: run_once は本番ログ(POLL_LOG)を1バイトも触らない ----------

def t_never_touches_production_log():
    before = os.path.exists(T.POLL_LOG)
    before_sz = os.path.getsize(T.POLL_LOG) if before else -1
    with tempfile.TemporaryDirectory() as d:
        p = Paths(d)
        calls, deliver = _recorder()
        _, alert = _alert_recorder()
        # init(ログを書く分岐)を一時wm_pathで回す
        fetch = _fetch_from(lambda s: [], last_row=3)
        T.run_once(fetch, deliver, alert=alert, wm_path=p.wm, fail_path=p.fail)
        # ログは一時ディレクトリ側に出ているはず
        assert os.path.exists(os.path.join(d, "teian_decide_poll.log")), "ログが一時側に出ていない"
    after = os.path.exists(T.POLL_LOG)
    after_sz = os.path.getsize(T.POLL_LOG) if after else -1
    assert (before, before_sz) == (after, after_sz), \
        f"run_once が本番ログを触った(返す物1の再発): {(before, before_sz)} -> {(after, after_sz)}"


# ---- 9. 本文に必須項目(ch/題名/④コメント/cid/決定日時)が入る ----------------

def t_body_contains_required_fields():
    body = T.build_body(T.row_fields(_row(6, title="星降る夜", cid="d_42",
                                          ch="宵桜艶帖", comment="この一言")), 6)
    for must in ["宵桜艶帖", "星降る夜", "d_42", "この一言", "2026-08-23 10:00", "row=6"]:
        assert must in body, f"本文に {must} が無い:\n{body}"


def main():
    tests = [
        ("初回は水位を置くだけ・配達も警報もしない", t_init_sets_watermark_no_delivery),
        ("新規行を配達し水位を進める", t_delivers_new_rows_and_advances),
        ("★must-fail 同じ行は2回配達しない", t_same_row_twice_delivers_once),
        ("blocked=据え置き+カウンタ+閾値で部屋へ1回", t_blocked_holds_counts_and_alerts_once),
        ("fail-open未初期化は部屋へ鳴らさない(既知の待ち)", t_fail_open_bootstrap_no_room_alert),
        ("fail-open初期化後は部屋へ1回", t_fail_open_after_init_alerts_room),
        ("きれいに1周で失敗カウンタを畳む", t_clean_cycle_resets_counter),
        ("★返す物1 本番ログを触らない", t_never_touches_production_log),
        ("本文に必須項目が入る", t_body_contains_required_fields),
    ]
    ok = sum(run(n, f) for n, f in tests)
    print(f"\n{ok}/{len(tests)} PASS")
    return 0 if ok == len(tests) else 1


if __name__ == "__main__":
    sys.exit(main())
