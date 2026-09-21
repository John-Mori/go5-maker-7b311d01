# -*- coding: utf-8 -*-
"""imagegen-itsumono の Claude閉室の検査(2026-09-22 イージス研究室)。

依頼= カスミ便 DISPATCH-aegis-gl-1790020180086 / Chami原文 msg 1551680397103071355=
  「ここでのClaudeでの配線は閉じて外部から不具合時対応するようにして。
    生成の依頼の単語を貼るのを忘れてた時に無駄なトークン使わせたくないし」

★固めるのは2つ。片方だけでは依頼を満たさない。
  ①Claudeが起きない= 番人の名簿に居ない / gatewayがqueueへ積まない / 名簿に無いのが
    正しい部屋として deadman に登録されている(安全網が狼にならない)
  ②★**生成は生きている**= 「生成依頼」で始まる便は今までどおり注文として通り、
    優依のローカル経路(local_pipeline_order)の仕事のままである
    (Chami=「生成そのものは残す」。閉室のついでに絵まで殺したら失敗)

    python scripts/imagegen/test_itsumono_claude_off.py
"""
import ast
import os
import re
import sys
import unittest

_HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.normpath(os.path.join(_HERE, "..", ".."))
sys.path.insert(0, _HERE)

import rooms                      # noqa: E402

DEPT = "imagegen-itsumono"
KEEPER = os.path.join(ROOT, "scripts", "_daemons", "daemon_keeper.py")
DEADMAN = os.path.join(ROOT, "scripts", "_daemons", "deadman_check.py")
GATEWAY = os.path.join(ROOT, "scripts", "queue", "discord_gateway.py")
DISPATCH = os.path.join(ROOT, "scripts", "llm", "dispatch.py")


def _keeper_depts():
    """番人の名簿を**本体と同じ読み方**で読む(正規表現は daemon_keeper._read_depts_file と同じ)。"""
    with open(KEEPER, "r", encoding="utf-8") as f:
        src = f.read()
    m = re.search(r"^DEPTS = (\[[^\]]*\])\s*$", src, re.M)
    assert m, "DEPTS 行が読めない(1行のまま保つ規律が破られている)"
    return ast.literal_eval(m.group(1))


class ClaudeClosed(unittest.TestCase):
    """①Claudeが起きない。"""

    def test_dept_is_in_no_claude_table(self):
        self.assertIn(DEPT, rooms.NO_CLAUDE_DEPTS)
        self.assertTrue(rooms.claude_off(DEPT))

    def test_closure_did_not_spill_outside_the_drawing_rooms(self):
        """★2026-09-22 05:16 Chami直令 msg 1551686873875742792 で兄弟3室も閉じた
        (「1548514430621319178 / 1526172345427824640 / 1548842219744657449
          この3部屋も同様の配線で削除後にGoして」・実装はプラットフォームSE室)。
        ここで見るのは「1室だけか」ではなく**描画室の外へ漏れていないか**=
        閉室の集合は ROOMS の部屋だけで、会話の部屋は1つも巻き込んでいない。"""
        for d in ("imagegen", "imagegen-fusoh-v0", "imagegen-fusoh-v2"):
            self.assertTrue(rooms.claude_off(d), d)
        self.assertEqual(set(rooms.NO_CLAUDE_DEPTS), set(rooms.ROOMS),
                         "閉室の集合が描画室(ROOMS)と食い違った")
        for d in ("imagetag", "imagetag-talk", "local-lab", "aegis-gl", "hq"):
            self.assertFalse(rooms.claude_off(d), d)

    def test_not_in_keeper_roster(self):
        depts = _keeper_depts()
        self.assertNotIn(DEPT, depts)
        self.assertGreaterEqual(len(depts), 40)   # 名簿ごと壊していない

    def test_gateway_skips_enqueue(self):
        """gatewayが閉室deptを見て積まない分岐を持っているか(呼び口の存在を実ファイルで見る)。"""
        with open(GATEWAY, "r", encoding="utf-8") as f:
            src = f.read()
        self.assertIn("def _claude_off(", src)
        self.assertIn("if _claude_off(rec[\"dept\"]):", src)

    def test_dispatch_does_not_enqueue_to_closed_room(self):
        """他部門から閉室へ出した便が queue へ溜まらないか(受信側と対の口)。"""
        with open(DISPATCH, "r", encoding="utf-8") as f:
            src = f.read()
        self.assertIn("def claude_off(", src)
        self.assertIn("if claude_off(dept):", src)

    def test_deadman_does_not_cry_wolf(self):
        sys.path.insert(0, os.path.join(ROOT, "scripts", "_daemons"))
        import importlib.util
        spec = importlib.util.spec_from_file_location("deadman_under_test", DEADMAN)
        dm = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(dm)
        self.assertIn(DEPT, dm.ROSTER_OTHER_OWNER)


class DrawingStillAlive(unittest.TestCase):
    """②★生成経路は生きている(ここが赤いなら閉室ごと戻せ)。

    ★2026-09-22 05:37→05:49 に合図の要否が動いた(msg 1551692713425117314 →
      msg 1551692776859631629「違う、４部屋か」)。この4室は「生成依頼」を**書かなくても**描く。
      ここの期待もその日のうちに2度書き直している= 室名ではなく**理由**で書くこと。
    """

    def test_cue_order_still_passes(self):
        order, prompt = rooms.order_of(DEPT, "生成依頼 銀髪ロング 制服 桜")
        self.assertTrue(order)
        self.assertEqual(prompt, "銀髪ロング 制服 桜")

    def test_a_bare_order_is_drawn_too(self):
        """★合図免除後の正しい姿= 合図が無くても描く。
        理由(Chami msg 1551692713425117314)= 「エラーが積まれないから」。
        Claudeが居ない純・生成室なので、来る便は全部「描いてほしい便」だと決めた。"""
        order, prompt = rooms.order_of(DEPT, "銀髪ロング 制服 桜")
        self.assertTrue(order, "合図の無い注文が描かれない=免除が効いていない")
        self.assertEqual(prompt, "銀髪ロング 制服 桜")

    def test_every_closed_room_still_draws(self):
        """★閉室が4室へ広がった以上、生きている証明も4室ぶん要る
        (Claudeの口を閉じたついでに絵まで死んでいないか)。"""
        for d in rooms.NO_CLAUDE_DEPTS:
            order, prompt = rooms.order_of(d, "生成依頼 銀髪ロング 制服 桜")
            self.assertTrue(order, d)
            self.assertEqual(prompt, "銀髪ロング 制服 桜", d)
            self.assertTrue(rooms.order_of(d, "銀髪ロング 制服 桜")[0], d)

    def test_room_row_is_intact(self):
        row = rooms.ROOMS[DEPT]
        self.assertEqual(row["lora_hint"], "itsumono")
        self.assertEqual(row["persona"], "優依")        # 絵の名義は変えていない
        self.assertFalse(rooms.cue_required(DEPT),
                         "msg 1551692776859631629(4部屋)で外した合図が戻っている")


class NoTokenIsSpentOnThisRoom(unittest.TestCase):
    """★依頼の核心=「無駄なトークン使わせたくない」を**押下点まで通して**測る(C-053)。

    2026-09-22 に判明した巻き添え= 「生成依頼便にClaude印を押さない」判定
    (rooms.local_pipeline_order)は1行目が `if not cue_required(dept): return False` なので、
    合図免除で**全描画室が False**になった= 便ごとの抑止は今や働いていない。
    ではこの部屋は大丈夫なのか、を文字列でなく実行で確かめる。
      答え= 閉室分岐(gatewayがqueueへ積まない)が手前で効くので印も押されない。
      つまり今この部屋を守っているのは合図ではなく**閉室**だ。そこが外れたら赤くする。
    """

    @classmethod
    def setUpClass(cls):
        sys.path.insert(0, os.path.join(ROOT, "scripts", "queue"))
        import discord_gateway            # noqa: E402
        cls.gw = discord_gateway

    def _deliver(self, dept, body):
        """人間の1便を gateway の本物の分岐へ通し、(押した印, 積んだdept) を返す。"""
        import asyncio
        import datetime
        gw = self.gw
        pressed, enqueued = [], []

        class _Msg(object):
            id = 900000000000000001
            guild = type("G", (), {"emojis": []})()
            author = type("A", (), {"name": "chami_fusoh", "bot": False, "id": 1})()
            webhook_id = None
            attachments = []
            reference = None
            created_at = datetime.datetime.now()

            def __init__(self):
                self.content = body
                self.channel = type("C", (), {"id": "777",
                                              "name": rooms.channel_name(dept) or dept})()

            async def add_reaction(self, emoji):
                pressed.append(str(emoji))

        class _Q(object):
            def enqueue(self, line, msg_id=None, dept=None):
                enqueued.append(dept)
                return True

            def stats(self):
                return {"ready": 0, "leased": 0}

        saved = (gw.ACTIVE_JOBS, gw.log, gw._ledger_append, gw._ledger_load)
        gw.ACTIVE_JOBS = True                      # 周期ジョブ稼働中=最も印が押されやすい条件
        gw.log = lambda *a, **k: None
        gw._ledger_append = lambda *a, **k: None   # 台帳と優依への写しは検査中に書かない
        gw._ledger_load = lambda *a, **k: set()
        try:
            asyncio.run(gw.handle_message(
                _Msg(), {"777": {"dept": dept, "name": rooms.channel_name(dept) or dept}}, _Q()))
        finally:
            (gw.ACTIVE_JOBS, gw.log, gw._ledger_append, gw._ledger_load) = saved
        return pressed, enqueued

    def test_a_real_order_wakes_nobody(self):
        pressed, enqueued = self._deliver(DEPT, "生成依頼 銀髪ロング 制服 桜")
        self.assertEqual(enqueued, [], "閉じた部屋の便がqueueへ積まれた=Claudeが起きる")
        self.assertEqual(pressed, [], "Claude印が押された=居ない者が受け取った顔をしている")

    def test_a_chat_line_wakes_nobody_either(self):
        """★合図を外した今、この部屋で一番多いのは合図の無い便だ。そちらも測る。"""
        pressed, enqueued = self._deliver(DEPT, "これいらん")
        self.assertEqual(enqueued, [])
        self.assertEqual(pressed, [])

    def test_all_four_closed_rooms_are_quiet(self):
        for d in rooms.NO_CLAUDE_DEPTS:
            pressed, enqueued = self._deliver(d, "生成依頼 銀髪ロング")
            self.assertEqual(enqueued, [], d)
            self.assertEqual(pressed, [], d)


if __name__ == "__main__":
    unittest.main(verbosity=2)
