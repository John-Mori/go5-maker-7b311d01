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


def _note_recorder():
    """継ぎ目#4(受け手が読む面への追記)の偽物。本番 hq_open_items.md を触らせないため全テストで注入。"""
    got = []
    def n(kind, text, resolve=False):
        got.append((kind, "resolve" if resolve else "open"))
        return True
    return got, n


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
        notes, note = _note_recorder()
        fetch = _fetch_from(lambda s: [_row(1), _row(2), _row(3)], last_row=3)
        res = T.run_once(fetch, deliver, alert=alert, note=note, wm_path=p.wm, fail_path=p.fail)
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
        _, note = _note_recorder()
        fetch = _fetch_from(lambda s: [r for r in (_row(4), _row(5)) if r["row"] > s], last_row=5)
        res = T.run_once(fetch, deliver, alert=alert, note=note, wm_path=p.wm, fail_path=p.fail)
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
        _, note = _note_recorder()
        fetch = _fetch_from(lambda s: [_row(6)], last_row=6)   # sinceを無視し常にrow=6(重複ソース)
        T.run_once(fetch, deliver, alert=alert, note=note, wm_path=p.wm, fail_path=p.fail)
        T.run_once(fetch, deliver, alert=alert, note=note, wm_path=p.wm, fail_path=p.fail)
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
        notes, note = _note_recorder()
        fetch = _fetch_from(lambda s: [r for r in (_row(6),) if r["row"] > s], last_row=6)
        for i in range(4):            # 4周回す
            res = T.run_once(fetch, deliver, alert=alert, note=note, wm_path=p.wm, fail_path=p.fail, alert_at=3)
            assert res["status"] == "blocked", res
        assert attempted == [6, 6, 6, 6], attempted
        assert T._read_int(p.wm) == 5, "失敗時に水位が動いた: " + str(T._read_int(p.wm))
        assert T._read_int(p.fail) == 4, T._read_int(p.fail)
        assert len(alerts) == 1, f"部屋への警報が1回でない(毎周期/無警報): {len(alerts)}"
        # ★返す物2の追い込み: 受け手が読む面へも閾値ちょうどで1回(毎周期ではない)
        assert notes == [("deliver-blocked", "open")], f"durable面への追記が1回でない: {notes}"


# ---- 5. fail-open・未初期化(口がまだ無い)= 部屋へは鳴らさない(既知の待ち) -----

def t_fail_open_bootstrap_no_room_alert():
    with tempfile.TemporaryDirectory() as d:
        p = Paths(d)
        alerts, alert = _alert_recorder()
        notes, note = _note_recorder()
        _, deliver = _recorder()
        for _ in range(5):
            res = T.run_once(lambda s: None, deliver, alert=alert, note=note,
                             wm_path=p.wm, fail_path=p.fail, alert_at=3)
            assert res["status"] == "fail-open", res
        assert not os.path.exists(p.wm), "fail-open中に水位を作った(過去を流す危険)"
        assert T._read_int(p.fail) == 5, T._read_int(p.fail)
        assert alerts == [], f"口がまだ無い既知の待ちで部屋へ鳴らした(狼少年): {alerts}"
        # ローカルログには閾値で1行だけ出る(継ぎ目の内側=一時ディレクトリ)
        logtxt = open(os.path.join(d, "teian_decide_poll.log"), encoding="utf-8").read()
        assert logtxt.count("読み取り口がまだ無い") == 1, logtxt
        # ★部屋では鳴らさないが、受け手が読む面には「入れた(確認待ち)」を1回だけ残す(返す物2)
        assert notes == [("bootstrap-wait", "open")], f"口待ちの静観がdurable面に1回残っていない: {notes}"


# ---- 6. fail-open・初期化後(口が生えていたのに落ちた)= 部屋へ1回 --------------

def t_fail_open_after_init_alerts_room():
    with tempfile.TemporaryDirectory() as d:
        p = Paths(d)
        T._write_int(p.wm, 7)         # 既に初期化済み(口は生えていた)
        alerts, alert = _alert_recorder()
        notes, note = _note_recorder()
        _, deliver = _recorder()
        for _ in range(4):
            res = T.run_once(lambda s: None, deliver, alert=alert, note=note,
                             wm_path=p.wm, fail_path=p.fail, alert_at=3)
            assert res["status"] == "fail-open", res
        assert T._read_int(p.wm) == 7, "fail-openで水位が動いた"
        assert len(alerts) == 1, f"初期化後のfetch異常で部屋へ1回鳴らせていない: {len(alerts)}"
        assert notes == [("read-fail", "open")], f"初期化後のfetch異常がdurable面に1回残っていない: {notes}"


# ---- 7. きれいに1周できたら連続失敗カウンタを畳む ----------------------------

def t_clean_cycle_resets_counter():
    with tempfile.TemporaryDirectory() as d:
        p = Paths(d)
        T._write_int(p.wm, 5)
        T._write_int(p.fail, 2)       # 過去に2回失敗が積まれていた
        calls, deliver = _recorder()
        _, alert = _alert_recorder()
        _, note = _note_recorder()
        fetch = _fetch_from(lambda s: [], last_row=5)   # 新規なし=きれいに1周
        res = T.run_once(fetch, deliver, alert=alert, note=note, wm_path=p.wm, fail_path=p.fail)
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
        _, note = _note_recorder()
        # init(ログを書く分岐)を一時wm_pathで回す
        fetch = _fetch_from(lambda s: [], last_row=3)
        T.run_once(fetch, deliver, alert=alert, note=note, wm_path=p.wm, fail_path=p.fail)
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


# ---- 10. note_open_item: 追記のみで開閉が二重にならない(直接・一時パス) --------

def t_note_open_item_toggles_append_only():
    with tempfile.TemporaryDirectory() as d:
        f = os.path.join(d, "hq_open_items.md")
        # 開く→2度目は開かない(末尾がOPENなので冪等)
        assert T.note_open_item("read-fail", "口が落ちた", path=f) is True
        assert T.note_open_item("read-fail", "口が落ちた", path=f) is False, "OPENのまま二重に開いた"
        # 別種は独立に開ける
        assert T.note_open_item("deliver-blocked", "配達不能", path=f) is True
        # 復旧で1回だけ閉じる→2度目の復旧は何もしない
        assert T.note_open_item("read-fail", "戻った", resolve=True, path=f) is True
        assert T.note_open_item("read-fail", "戻った", resolve=True, path=f) is False, "RESOLVED後に二重に閉じた"
        # 閉じた後は再び開ける(再発)
        assert T.note_open_item("read-fail", "また落ちた", path=f) is True
        txt = open(f, encoding="utf-8").read()
        assert txt.count("teian-echo:read-fail OPEN") == 2, txt        # 初回 + 再発
        assert txt.count("teian-echo:read-fail RESOLVED") == 1, txt
        assert txt.count("teian-echo:deliver-blocked OPEN") == 1, txt


# ---- 11. ★run_once は本番 hq_open_items.md を1バイトも触らない(継ぎ目#4の証明) ---

def t_never_touches_hq_open_items():
    path = T.HQ_OPEN_ITEMS
    before = os.path.exists(path)
    before_sz = os.path.getsize(path) if before else -1
    with tempfile.TemporaryDirectory() as d:
        p = Paths(d)
        _, deliver = _recorder()
        _, alert = _alert_recorder()
        notes, note = _note_recorder()     # ★偽物を注入=本番HQファイルへ行かせない
        # 口が無い状態でfail-openを閾値まで回す(note を呼ぶ分岐)
        for _ in range(3):
            T.run_once(lambda s: None, deliver, alert=alert, note=note,
                       wm_path=p.wm, fail_path=p.fail, alert_at=3)
        assert notes == [("bootstrap-wait", "open")], notes
    after = os.path.exists(path)
    after_sz = os.path.getsize(path) if after else -1
    assert (before, before_sz) == (after, after_sz), \
        f"run_once が本番 hq_open_items.md を触った: {(before, before_sz)} -> {(after, after_sz)}"


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
        ("note 追記のみで開閉が二重にならない", t_note_open_item_toggles_append_only),
        ("★返す物2 本番hq_open_itemsを触らない", t_never_touches_hq_open_items),
    ]
    ok = sum(run(n, f) for n, f in tests)
    print(f"\n{ok}/{len(tests)} PASS")
    return 0 if ok == len(tests) else 1


if __name__ == "__main__":
    sys.exit(main())
