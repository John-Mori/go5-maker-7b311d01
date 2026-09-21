# -*- coding: utf-8 -*-
"""合図ゲートの見張り(cue_gate_watch.py)の検査(2026-09-22 イージス研究室)。

依頼= 研究室HQ シャビ・アロンソ便 DISPATCH-aegis-gl-1790022388784 手番(2)の③
  「常駐の再読込後、responder_log.jsonl に mode=image_no_cue が出ているかを見る導線」。

★ここで固めるのは、見張りが**嘘をつかない**こと。
  ①合図が要る部屋でゲートが外れたまま描いた行(cue=False)だけを漏れと呼ぶ
  ②★合図を剥がした本文(q)から合図の有無を読み直さない= 正しく通った注文を漏れと呼ばない
    (初版はこれで16件を誤報した。ログのqは剥がした後の本文だ)
  ③`cue` を持たない古い行は「判定不能」と言う。無事だとも漏れだとも言わない
  ④描画室以外の部屋の行は数に入れない
  ⑤範囲に1件も無い時は「未通電(確認待ち)」と言う=「漏れ0件」と言い換えない(§4.55)
  ⑥★合図が**要らない**部屋(2026-09-22 Chami直令 msg 1551692713425117314 → 訂正
    1551692776859631629「違う、４部屋か」= rooms.NO_CUE_DEPTS)の cue=False は正常= 漏れと呼ばない

★入力(ログの実ファイル)だけ差し替えて、判定と分岐は本物のまま通す。
★常駐の生死(codever)は見ない(check_code=False)= この機械の状態で検査の色が変わらないように。

    python scripts/imagegen/test_cue_gate_watch.py
"""
import json
import os
import sys
import tempfile
import time
import unittest

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _HERE)

import cue_gate_watch as w   # noqa: E402
import rooms                 # noqa: E402

# ★標本の「合図が要る部屋」は**検査用の架空室を台帳へ足して**自前で建てる。
#   2026-09-22 だけで規則は3回動き、05:49(Chami msg 1551692776859631629「違う、４部屋か」)で
#   実在の描画室は**全室が合図不要**になった= 実在室から標本を取る書き方は、その瞬間に
#   検査そのものが落ちる(実際 sorted(CUE_REQUIRED_DEPTS)[0] が IndexError で落ちた)。
#   見張りの仕事は「合図が要る部屋でゲートが外れた行を拾う」形を守ることで、今どの実在室が
#   要るかとは別だ。だから要否の名簿には依存させず、要る部屋を1つ建てて使う。
CUE_ROOM = "imagegen-cue-sample"
rooms.ROOMS[CUE_ROOM] = {"lora_hint": None, "persona": "優依",
                         "ckpt": rooms.ROOMS["imagegen"]["ckpt"], "label": "検査用(架空)"}
CUE_ROOM_CHANNEL = "検査用-架空の生成室"       # 台帳に無い名=表示名からは引けない(引く検査は別に置く)
NO_CUE_ROOM = sorted(rooms.NO_CUE_DEPTS)[0]
REAL_ROOM = sorted(rooms.ROOMS)[0]            # 表示名→部屋の引き直しだけは実在の部屋で見る


def row(ts, **kw):
    r = {"ts": ts, "channel": CUE_ROOM_CHANNEL}
    r.update(kw)
    return r


def drew(ts, dept=CUE_ROOM, cue=None, q="銀髪ロング 制服 桜", with_cue_key=True):
    r = row(ts, mode="answered", dept=dept, q=q, image=True,
            a="[画像生成/local_chain] prompt_id=deadbeef(batch=4)", sent=True)
    if with_cue_key:
        r["cue"] = cue
    return r


def write_log(rows):
    fd, path = tempfile.mkstemp(prefix="cue_watch_", suffix=".jsonl")
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    return path


class Watch(unittest.TestCase):

    def setUp(self):
        self.paths = []

    def tearDown(self):
        for p in self.paths:
            try:
                os.remove(p)
            except OSError:
                pass

    def _log(self, rows):
        p = write_log(rows)
        self.paths.append(p)
        return p

    def test_a_drawing_without_the_gate_is_a_leak(self):
        p = self._log([drew("2026-09-22T06:00:00", cue=False)])
        rows = w.read_rows(p, since=0)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0][2], "drew")
        self.assertEqual(len(w.leaks(rows)), 1)
        text, rc = w.report(since=0, log=p, check_code=False)
        self.assertEqual(rc, 1, text)
        self.assertIn("漏れ 1 件", text)

    def test_a_cleared_order_is_not_a_leak_even_though_the_cue_is_gone_from_the_text(self):
        """★誤報の型。合図は剥がされているので q には残っていない。それでも漏れではない。"""
        p = self._log([drew("2026-09-22T06:00:00", cue=True, q="【構図】全身。")])
        rows = w.read_rows(p, since=0)
        self.assertEqual(w.leaks(rows), [], "合図を通った注文を漏れと呼んだ")
        text, rc = w.report(since=0, log=p, check_code=False)
        self.assertEqual(rc, 0, text)

    def test_old_rows_without_the_cue_field_are_undecidable(self):
        p = self._log([drew("2026-09-22T05:06:18", q="って冒頭につけないと画像生成されないようにして",
                            with_cue_key=False)])
        rows = w.read_rows(p, since=0)
        self.assertEqual(w.leaks(rows), [])
        self.assertEqual(len(w.undecidable(rows)), 1)
        text, rc = w.report(since=0, log=p, check_code=False)
        self.assertEqual(rc, 0, text)
        self.assertIn("判定不能", text)

    def test_the_gate_firing_is_counted(self):
        p = self._log([row("2026-09-22T06:01:00", mode="image_no_cue", dept=CUE_ROOM,
                           q="これとかね", image=True, sent=False),
                       drew("2026-09-22T06:02:00", cue=True)])
        rows = w.read_rows(p, since=0)
        kinds = [r[2] for r in rows]
        self.assertIn("image_no_cue", kinds)
        text, rc = w.report(since=0, log=p, check_code=False)
        self.assertEqual(rc, 0, text)
        self.assertIn("image_no_cue で捨てられている", text)

    def test_a_room_that_needs_no_cue_is_not_a_leak(self):
        """★2026-09-22 Chami直令 msg 1551692713425117314=
        「この3部屋は生成依頼って書かなくても生成するようにしてよ、そうすればエラーが積まれないから」
        (直後の msg 1551692776859631629「違う、４部屋か」で itsumono を含む4室へ訂正)。
        合図を外した部屋(rooms.NO_CUE_DEPTS)の cue=False は**設計どおりの姿**だ。
        ここを漏れと数えると、見張りが毎回鳴いて誰も見なくなる(狼少年にしない)。"""
        r = drew("2026-09-22T06:07:00", dept=NO_CUE_ROOM, cue=False)
        r["channel"] = rooms.channel_name(NO_CUE_ROOM)
        p = self._log([r])
        rows = w.read_rows(p, since=0)
        self.assertEqual(len(rows), 1)
        self.assertEqual(w.leaks(rows), [], "合図の要らない部屋の描画を漏れと呼んだ")
        self.assertEqual(len(w.cue_free_draws(rows)), 1)
        text, rc = w.report(since=0, log=p, check_code=False)
        self.assertEqual(rc, 0, text)
        self.assertIn("ゲートの対象外", text)

    def test_rooms_that_do_not_draw_are_not_counted(self):
        p = self._log([{"ts": "2026-09-22T06:03:00", "mode": "answered", "dept": "hq",
                        "channel": "研究室hq", "q": "これ", "a": "[画像生成/local_chain] x",
                        "image": True, "cue": False}])
        rows = w.read_rows(p, since=0)
        self.assertEqual(rows, [], "描画室でない部屋の行を数えた")

    def test_the_channel_alone_is_enough_to_find_the_room(self):
        """dept を持たない古い行= 表示名から台帳で引き直す(落とさない)。

        ★ここだけは実在の部屋で見る= 引く先は discord_channels.json(台帳)で、架空室は載っていない。
        """
        r = drew("2026-09-22T06:04:00", dept=REAL_ROOM, cue=False)
        r["channel"] = rooms.channel_name(REAL_ROOM)
        r.pop("dept")
        p = self._log([r])
        rows = w.read_rows(p, since=0)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0][1], REAL_ROOM)

    def test_an_empty_window_is_called_untested_not_clean(self):
        """★§4.55= 通っていないものを「効いた」と言い換えない。"""
        p = self._log([drew("2026-09-20T01:00:00", cue=True)])
        text, rc = w.report(since=time.time(), log=p, check_code=False)
        self.assertEqual(rc, 0, text)
        self.assertIn("未通電", text)
        self.assertNotIn("漏れ0件", text)

    def test_rows_before_the_window_are_dropped(self):
        old = drew("2026-09-20T01:00:00", cue=False)
        new = drew("2026-09-22T06:05:00", cue=True)
        p = self._log([old, new])
        since = w.parse_ts("2026-09-22T00:00:00")
        rows = w.read_rows(p, since=since)
        self.assertEqual(len(rows), 1)
        self.assertEqual(w.leaks(rows), [], "範囲外の古い漏れを今の漏れとして数えた")


class TheRoomTableIsTheSource(unittest.TestCase):
    """見張りが見る部屋の集合は rooms.py から引く= 名簿を二重に持たない。"""

    DEPT = "imagegen-watch-test"

    def tearDown(self):
        rooms.ROOMS.pop(self.DEPT, None)

    def test_a_new_room_is_watched_without_editing_this_tool(self):
        rooms.ROOMS[self.DEPT] = {"lora_hint": None, "persona": "優依",
                                  "ckpt": rooms.ROOMS["imagegen"]["ckpt"],
                                  "label": "検査用(架空)"}
        r = drew("2026-09-22T06:06:00", dept=self.DEPT, cue=False)
        fd, p = tempfile.mkstemp(prefix="cue_watch_", suffix=".jsonl")
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
        try:
            rows = w.read_rows(p, since=0)
            self.assertEqual(len(rows), 1, "ROOMSへ足した部屋を見張りが拾わなかった")
            self.assertEqual(len(w.leaks(rows)), 1)
        finally:
            os.remove(p)


if __name__ == "__main__":
    unittest.main(verbosity=2)
