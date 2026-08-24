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
    """部屋への便の偽物。警報だけを got に積み、復旧の一報は recovered に分けて積む。"""
    got, rec = [], []
    def a(reason, dept=None, recovered=False):
        (rec if recovered else got).append(reason)
    a.recovered = rec
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


# ---- 12. ★返す物4: 未初期化のまま滞留したら周期ちょうどで部屋へ1回escalate --------
#   n(連続失敗数)は5分刻み=経過時間の代理。wait_alert_every=288(=約24h)ちょうどで部屋へ1回。
#   287/289では出ない(閾値を外すと赤くなる形=must-fail)。初期化後は「時間で」escalateしない
#   (=名指しの未初期化枝だけ・C-035)。

def _run_bootstrap_with_fail(d_fail_seed, every=288):
    """未初期化(wm無し)・fetch=None で1周回し、seed後の連続失敗数nで daily escalate するか測る。"""
    with tempfile.TemporaryDirectory() as d:
        p = Paths(d)
        assert not os.path.exists(p.wm)          # 未初期化(口がまだ無い)
        T._write_int(p.fail, d_fail_seed)        # この周で n = seed+1 になる
        alerts, alert = _alert_recorder()
        notes, note = _note_recorder()
        _, deliver = _recorder()
        res = T.run_once(lambda s: None, deliver, alert=alert, note=note,
                         wm_path=p.wm, fail_path=p.fail, alert_at=3, wait_alert_every=every)
        assert res["status"] == "fail-open", res
        return alerts


def t_bootstrap_daily_escalation_on_period():
    # n=288(=seed 287+1)ちょうど → 部屋へ1回。時間の滞留を語る本文であること。
    at = _run_bootstrap_with_fail(287, every=288)
    assert len(at) == 1, f"周期ちょうど(n=288)で部屋へ1回出ていない: {len(at)}"
    assert "24時間" in at[0], f"滞留時間(約24h)を語っていない: {at[0]}"
    # 直前(n=287)・直後(n=289)では出ない=閾値を外すと赤くなる(must-fail)
    assert _run_bootstrap_with_fail(286, every=288) == [], "n=287で誤発火した(狼少年)"
    assert _run_bootstrap_with_fail(288, every=288) == [], "n=289で誤発火した(毎周期化)"


def _run_initfail_with_fail(kind, d_fail_seed, every=288):
    """初期化済み(wm有り)で異常を1周回し、seed後の連続失敗数nで周期escalateするか測る。
    kind='read'= fetch=None(口が落ちた) / kind='blocked'= 配達失敗。返り値= 部屋への警報list。"""
    with tempfile.TemporaryDirectory() as d:
        p = Paths(d)
        T._write_int(p.wm, 7)                    # 初期化済み(口は生えていた)
        T._write_int(p.fail, d_fail_seed)        # この周で n = seed+1
        alerts, alert = _alert_recorder()
        _, note = _note_recorder()
        if kind == "read":
            _, deliver = _recorder()
            res = T.run_once(lambda s: None, deliver, alert=alert, note=note,
                             wm_path=p.wm, fail_path=p.fail, alert_at=3, wait_alert_every=every)
            assert res["status"] == "fail-open", res
        else:
            def deliver(row):
                return False                     # 常に配達失敗=blocked
            fetch = _fetch_from(lambda s: [r for r in (_row(8),) if r["row"] > s], last_row=8)
            res = T.run_once(fetch, deliver, alert=alert, note=note,
                             wm_path=p.wm, fail_path=p.fail, alert_at=3, wait_alert_every=every)
            assert res["status"] == "blocked", res
        return alerts


def t_initialized_read_fail_daily_escalation_on_period():
    # ★デブライネさん 2026-08-23: 初期化後の read-fail(口が落ちた)は n==alert_at の一発だけでなく
    #   周期ちょうど(n=288=約24h)でも部屋へ1回。287/289では出ない(閾値を外すと赤=must-fail)。
    at = _run_initfail_with_fail("read", 287, every=288)
    assert len(at) == 1, f"初期化後read-failが周期(n=288)で部屋へ1回出ていない: {len(at)}"
    assert _run_initfail_with_fail("read", 286, every=288) == [], "n=287で誤発火した(狼少年)"
    assert _run_initfail_with_fail("read", 288, every=288) == [], "n=289で誤発火した(毎周期化)"


def t_initialized_blocked_daily_escalation_on_period():
    # ★同上: 配達不能(blocked)が続いても周期(n=288)で部屋へ1回=静かな死を防ぐ。287/289では出ない。
    at = _run_initfail_with_fail("blocked", 287, every=288)
    assert len(at) == 1, f"blockedが周期(n=288)で部屋へ1回出ていない: {len(at)}"
    assert "row=8" in at[0], f"blocked警報が対象行を語っていない: {at[0]}"
    assert _run_initfail_with_fail("blocked", 286, every=288) == [], "n=287で誤発火した(狼少年)"
    assert _run_initfail_with_fail("blocked", 288, every=288) == [], "n=289で誤発火した(毎周期化)"


# ---- 15. ★復旧の一報: 部屋で鳴らした警報にだけ、部屋で「戻った」を1回返す -----------
#   実害(2026-08-23 14:47〜15:37)= 読み取り口が12回連続で落ち、警報だけが部屋に残った。
#   durable面(hq_open_items.md)はRESOLVEDで閉じたが**部屋には壊れたままに見え**、
#   イージス研究室が「まだ壊れているのか」を人手で測り直す羽目になった。
#   must-fail= 閾値未満(=部屋で鳴っていない失敗)で復旧を出したら赤。

def _run_recover_after(seed, initialized=True, every=288):
    """seed回の失敗が積まれた状態から「きれいに1周」して、部屋への復旧が何回出るかを測る。"""
    with tempfile.TemporaryDirectory() as d:
        p = Paths(d)
        if initialized:
            T._write_int(p.wm, 5)
        T._write_int(p.fail, seed)
        _, deliver = _recorder()
        alerts, alert = _alert_recorder()
        _, note = _note_recorder()
        fetch = _fetch_from(lambda s: [], last_row=5)
        res = T.run_once(fetch, deliver, alert=alert, note=note, wm_path=p.wm,
                         fail_path=p.fail, alert_at=3, wait_alert_every=every)
        assert res["status"] == ("ok" if initialized else "init"), res
        assert not os.path.exists(p.fail), "きれいに1周したのに失敗カウンタが残っている"
        assert alerts == [], f"復旧の周で警報を鳴らした: {alerts}"
        return alert.recovered


def t_recovery_notice_only_when_alarm_rang():
    # 閾値以上(部屋で鳴っていた)→ 復旧を1回だけ出す。滞留量も語る。
    rec = _run_recover_after(3)
    assert len(rec) == 1, f"鳴らした警報の復旧が部屋へ1回出ていない: {rec}"
    assert "連続3回" in rec[0] and "約15分" in rec[0], f"復旧が滞留量を語っていない: {rec[0]}"
    assert len(_run_recover_after(12)) == 1, "12回連続の後の復旧が出ていない"
    # ★must-fail: 閾値未満(部屋では鳴っていない)→ 復旧も出さない=警報より復旧が多くなる形を禁じる
    assert _run_recover_after(2) == [], "部屋で鳴っていない失敗に復旧を出した(通知の水増し)"
    assert _run_recover_after(0) == [], "失敗0回なのに復旧を出した"
    # 未初期化(口がまだ無い既知の待ち)は閾値では鳴らさない=復旧も周期に達するまで出さない
    assert _run_recover_after(3, initialized=False) == [], "既知の待ちに復旧を出した(狼少年の裏返し)"
    assert len(_run_recover_after(288, initialized=False)) == 1, "周期escalate後の初期化で復旧が出ていない"


# ---- 16. ★1時間未満の滞留を「約0時間」と言わない(実際にそう届いた便がある) -------

def t_age_text_uses_minutes_under_one_hour():
    assert T._age_text(3) == "約15分", T._age_text(3)      # 閾値ちょうど=旧実装は「約0時間」
    assert T._age_text(11) == "約55分", T._age_text(11)
    assert T._age_text(12) == "約1時間", T._age_text(12)
    assert T._age_text(288) == "約24時間", T._age_text(288)


# ---- 17〜19. ★2026-08-25 失敗の理由を持ち回る/失敗した周は必ず1行残す(イージス研究室) ----
#   事故= 00:52 に「3回連続で読めない」が鳴ったが、本番ログの最終行は 8/23 08:02 のまま=
#   本物の失敗の枝が logf を1行も書いていなかった。**警報から原因を知る術が無かった。**

def t_fetch_fail_reason_is_recorded():
    """`fetch_decisions` が None を返した時、理由の1語が残ること(HTTPは実際に通す)。"""
    import urllib.error

    keep = (T.exec_url, T.urllib.request.urlopen)
    try:
        T.exec_url = lambda: "https://example.invalid/exec"

        def raise_http(req, timeout=None):
            raise urllib.error.HTTPError(req.full_url, 404, "Not Found", None, None)

        T.urllib.request.urlopen = raise_http
        assert T.fetch_decisions(2) is None
        assert T.last_fetch_fail() == "http-404", T.last_fetch_fail()

        class _R:                                   # HTMLが返る(GASのエラーページ)
            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

            def read(self):
                return b"<!DOCTYPE html><html>..."

        T.urllib.request.urlopen = lambda req, timeout=None: _R()
        assert T.fetch_decisions(2) is None
        assert T.last_fetch_fail() == "not-json", T.last_fetch_fail()

        class _R2(_R):
            def read(self):
                return b'{"ok":false}'

        T.urllib.request.urlopen = lambda req, timeout=None: _R2()
        assert T.fetch_decisions(2) is None
        assert T.last_fetch_fail() == "ok-false", T.last_fetch_fail()

        class _R3(_R):
            def read(self):
                return b'{"ok":true,"rows":[],"lastRow":5}'

        T.urllib.request.urlopen = lambda req, timeout=None: _R3()
        assert T.fetch_decisions(2) == {"ok": True, "rows": [], "lastRow": 5}
        assert T.last_fetch_fail() == "", "成功したのに理由が残っている"
    finally:
        T.exec_url, T.urllib.request.urlopen = keep


def t_read_fail_always_writes_a_log_line():
    """★閾値で鳴らない周(1回目・4回目)でもログに1行残ること=これが今回の穴。"""
    with tempfile.TemporaryDirectory() as d:
        p = Paths(d)
        T._write_int(p.wm, 7)
        alerts, alert = _alert_recorder()
        _, note = _note_recorder()
        _, deliver = _recorder()
        log = os.path.join(d, "teian_decide_poll.log")
        for _ in range(4):
            T.run_once(lambda s: None, deliver, alert=alert, note=note,
                       wm_path=p.wm, fail_path=p.fail, alert_at=3)
        assert len(alerts) == 1, alerts
        lines = [x for x in open(log, encoding="utf-8").read().splitlines() if x.strip()]
        assert len(lines) == 4, f"失敗4回に対しログが{len(lines)}行(鳴らない周が消えている)"
        assert "水位=7据え置き" in lines[0], lines[0]
        assert "4回連続" in lines[3], lines[3]


def t_alert_text_carries_the_reason():
    """★警報の本文に理由の1語が載ること(載らないと受け手はまた口を叩き直す羽目になる)。"""
    with tempfile.TemporaryDirectory() as d:
        p = Paths(d)
        T._write_int(p.wm, 7)
        alerts, alert = _alert_recorder()
        _, note = _note_recorder()
        _, deliver = _recorder()
        keep = T.last_fetch_fail
        T.last_fetch_fail = lambda: "http-TimeoutError"
        try:
            for _ in range(3):
                T.run_once(lambda s: None, deliver, alert=alert, note=note,
                           wm_path=p.wm, fail_path=p.fail, alert_at=3)
        finally:
            T.last_fetch_fail = keep
        assert len(alerts) == 1, alerts
        assert "http-TimeoutError" in str(alerts[0]), alerts[0]


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
        ("★返す物4 未初期化の滞留は周期ちょうどで部屋へ1回", t_bootstrap_daily_escalation_on_period),
        ("★初期化後read-failは周期でも部屋へ1回(静かな死を防ぐ)", t_initialized_read_fail_daily_escalation_on_period),
        ("★初期化後blockedは周期でも部屋へ1回(静かな死を防ぐ)", t_initialized_blocked_daily_escalation_on_period),
        ("★鳴らした警報にだけ部屋へ復旧を1回返す", t_recovery_notice_only_when_alarm_rang),
        ("★1時間未満の滞留を「約0時間」と言わない", t_age_text_uses_minutes_under_one_hour),
        ("★fetchの失敗は理由の1語を残す", t_fetch_fail_reason_is_recorded),
        ("★★鳴らない周でもログに1行残る(00:52の穴)", t_read_fail_always_writes_a_log_line),
        ("★警報の本文に理由が載る", t_alert_text_carries_the_reason),
    ]
    ok = sum(run(n, f) for n, f in tests)
    print(f"\n{ok}/{len(tests)} PASS")
    return 0 if ok == len(tests) else 1


if __name__ == "__main__":
    sys.exit(main())
