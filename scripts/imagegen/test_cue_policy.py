# -*- coding: utf-8 -*-
"""合図(「生成依頼」)の要否が**台帳から導かれている**ことの検査(2026-09-22 イージス研究室)。

依頼= 研究室HQ シャビ・アロンソ便 DISPATCH-aegis-gl-1790022388784 手番(2)の①②
  ①cue_required() が CUE_REQUIRED_DEPTS と食い違ったら落ちる
  ②ROOMS に室を足したのに合図が継がれない形へ戻ったら落ちる

★なぜ要るか= この規則は1日で2回動いた。
  05:14 Chami msg 1551685142806925366「生成依頼 って冒頭につけないと画像生成されないようにして」
        → 条件を lora_hint から dept in ROOMS へ(研究室HQが止血)
  05:37 Chami msg 1551692713425117314「この3部屋は生成依頼って書かなくても生成するようにしてよ、
        そうすればエラーが積まれないから」→ 3室だけ除外(NO_CUE_DEPTS・プラットフォームSE室)
  05:49 Chami msg 1551692776859631629「違う、４部屋か」→ itsumono も除外(=NO_CLAUDE_DEPTSと同集合)
  動くものは、動くたびに**定数と判定が別々に書き換わる**危険を持つ。落ちるのはいつもその継ぎ目だ。
  ここで固めるのは室名そのものではなく、**室名を二箇所に書かない形**である。

★実装(rooms.py)は当室の持ち物ではない。ここは検査だけを置く=直す時は持ち主へ返す。

    python scripts/imagegen/test_cue_policy.py
"""
import ast
import os
import sys
import unittest

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _HERE)

import rooms   # noqa: E402

ROOMS_PY = os.path.join(_HERE, "rooms.py")


class TheConstantAndTheJudgeAgree(unittest.TestCase):
    """①定数(CUE_REQUIRED_DEPTS)と判定(cue_required)が食い違ったら落ちる。"""

    def test_every_room_is_judged_the_same_way_the_constant_says(self):
        for dept in rooms.ROOMS:
            self.assertEqual(
                rooms.cue_required(dept), dept in rooms.CUE_REQUIRED_DEPTS,
                "%s: cue_required()=%s なのに CUE_REQUIRED_DEPTS には %s"
                % (dept, rooms.cue_required(dept),
                   "居る" if dept in rooms.CUE_REQUIRED_DEPTS else "居ない"))

    def test_the_constant_is_exactly_the_drawing_rooms_minus_the_exempt_ones(self):
        self.assertEqual(set(rooms.CUE_REQUIRED_DEPTS),
                         set(rooms.ROOMS) - set(rooms.NO_CUE_DEPTS))

    def test_rooms_that_do_not_draw_are_outside_the_rule(self):
        """絵を描かない部屋(ROOMSに居ない)まで合図を要求しない=規律を勝手に広げない。"""
        for dept in ("imagetag", "imagetag-talk", "local-lab", "aegis-gl", "hq", "", None):
            self.assertFalse(rooms.cue_required(dept), repr(dept))


class TheExemptionKeepsItsReason(unittest.TestCase):
    """合図を外した部屋は、Chamiが外した**理由**の内側に留まっているか。"""

    def test_exempt_rooms_are_drawing_rooms(self):
        for dept in rooms.NO_CUE_DEPTS:
            self.assertIn(dept, rooms.ROOMS, dept)

    def test_exempt_rooms_have_no_claude_listening(self):
        """★理由= 「Claude常駐を閉じた純・生成室だから、来る便は全部“描いてほしい便”だ」。
        会話の相手が居る部屋で合図を外すと、雑談がそのまま絵になる
        (2026-09-22 05:06:18 の実害= Chamiの指示文そのものが49秒かけて絵にされた)。
        よって NO_CUE_DEPTS は NO_CLAUDE_DEPTS の内側にしか置けない。"""
        self.assertLessEqual(set(rooms.NO_CUE_DEPTS), set(rooms.NO_CLAUDE_DEPTS))

    def test_a_room_where_claude_still_listens_keeps_the_cue(self):
        """★Claudeが聞いている部屋からは、合図を外してはいけない。

        ここは当初 itsumono を名指しで「据え置き」と書いていたが、その30秒後に
        Chami msg 1551692776859631629「違う、４部屋か」で itsumono も外れた。
        名指しを検査に書くと、Chamiが方針を動かすたびに赤が出る=検査が方針の邪魔をする。
        守るべきは室名ではなく**免除の理由**だ= 聞いている者が居る部屋は合図を継ぐ。
        """
        for dept in rooms.ROOMS:
            if not rooms.claude_off(dept):
                self.assertTrue(rooms.cue_required(dept),
                                "%s は Claude が聞いている部屋なのに合図を外している" % dept)


class AClosedRoomIsNeverLeftSilent(unittest.TestCase):
    """★もう一方の向きの退行= **Claudeを閉じた描画室に合図が残る**形を捕まえる。

    ここまでの検査は「免除した部屋は閉室か(NO_CUE ⊆ NO_CLAUDE)」しか見ていない。
    逆向き(NO_CLAUDE ⊆ NO_CUE)は今たまたま両者が同じ4室なので**素通りで緑**だ。
    だが免除の名簿(NO_CUE_DEPTS)は室名の直書きで、閉室の名簿(NO_CLAUDE_DEPTS)とは別物=
    5室目のClaudeを閉じた時に片方へ足し忘れる入口が開いている。

    足し忘れると何が起きるか(2026-09-22 実測で確認した形)=
      閉室 + 合図が要る → 合図なしの便は local_responder L1859-1865 で
      append_line(PROCESSED) と mode=image_no_cue のログだけ残して **send を呼ばずに return**。
      その部屋にはClaude常駐も居ない= **Chamiには何も返らない**。
    Chamiが4室を免除した原文の理由は「そうすればエラーが積まれないから」
    (msg 1551692713425117314 → 訂正 1551692776859631629「違う、4部屋か」)であり、
    守るのは室名ではなく**応答者の居ない部屋を黙らせない**というこの理由の方だ。

    ★赤い時に直すのは検査ではない= その部屋を NO_CUE_DEPTS へ入れるか、Claudeを戻すか。
    """

    def test_a_room_with_no_claude_does_not_still_demand_the_cue(self):
        for dept in rooms.NO_CLAUDE_DEPTS:
            if dept not in rooms.ROOMS:
                continue
            self.assertFalse(
                rooms.cue_required(dept),
                "%s はClaudeを閉じた部屋なのに合図を要求している="
                "合図なしの便は捨てられ、返事をする者も居ない(沈黙する)" % dept)

    def test_the_silence_is_real_not_theoretical(self):
        """★形の一致で満足しない= 入口(order_of)まで通して「拾われない」ことを見る。
        閉室で拾われない便は、そのまま誰の口にも乗らない。"""
        for dept in rooms.NO_CLAUDE_DEPTS:
            if dept not in rooms.ROOMS:
                continue
            taken, _ = rooms.order_of(dept, "これいらん")
            self.assertTrue(taken, "%s: 閉室に来た一言が拾われない=沈黙する便になる" % dept)


class ANewRoomInheritsTheRule(unittest.TestCase):
    """②ROOMS へ室を足すだけで合図が継がれる(足す手番をもう一つ作らない)。"""

    DEPT = "imagegen-policy-test"

    def tearDown(self):
        rooms.ROOMS.pop(self.DEPT, None)

    def _add(self):
        rooms.ROOMS[self.DEPT] = {"lora_hint": None, "persona": "優依",
                                  "ckpt": rooms.ROOMS["imagegen"]["ckpt"],
                                  "label": "検査用(架空)"}

    def test_a_room_added_after_import_still_needs_the_cue(self):
        """★CUE_REQUIRED_DEPTS は読み込んだ瞬間の写しでしかない。
        判定が写しを読んでいると、新しい部屋が素通しで開く(これが 05:14 に潰した形だ)。"""
        self._add()
        self.assertTrue(rooms.cue_required(self.DEPT),
                        "ROOMSへ足した部屋に合図が継がれていない=判定が定数を読んでいる")

    def test_the_new_room_actually_rejects_a_chat_and_takes_an_order(self):
        """導出だけでなく、入口(order_of)まで通して見る=文字列一致で満足しない。"""
        self._add()
        self.assertFalse(rooms.order_of(self.DEPT, "これいらん")[0])
        self.assertFalse(rooms.order_of(self.DEPT, "探偵っぽい女の子の絵を描いて", natural=True)[0])
        order, prompt = rooms.order_of(self.DEPT, "生成依頼 銀髪ロング 制服 桜")
        self.assertTrue(order)
        self.assertEqual(prompt, "銀髪ロング 制服 桜")

    def test_the_cue_list_is_derived_not_hand_written(self):
        """★②の退行を**形**で止める= CUE_REQUIRED_DEPTS の右辺に室名を直書きした瞬間に落ちる。
        (「CUE_REQUIRED_DEPTSに1行足す」という上申が 05:14 に退けられたのは、
          足し忘れが素通しになる形だからだ。同じ形へ戻す改修をここで捕まえる)"""
        with open(ROOMS_PY, "r", encoding="utf-8") as f:
            tree = ast.parse(f.read())
        found = None
        for node in tree.body:
            if isinstance(node, ast.Assign) and any(
                    isinstance(t, ast.Name) and t.id == "CUE_REQUIRED_DEPTS" for t in node.targets):
                found = node.value
        self.assertIsNotNone(found, "CUE_REQUIRED_DEPTS の代入が見つからない")
        self.assertNotIsInstance(found, (ast.Tuple, ast.List, ast.Set),
                                 "室名の直書きに戻っている(ROOMSから導け)")
        names = {n.id for n in ast.walk(found) if isinstance(n, ast.Name)}
        self.assertIn("ROOMS", names, "ROOMS を読まずに合図の名簿を作っている")


class TheCueLeverHasASecondConsumer(unittest.TestCase):
    """★合図のレバーは、合図だけを動かしていない(2026-09-22 実測)。

    local_pipeline_order() は「この便にClaude印(送信/既読/着手)を押さない」判定の正本で
    (Chami hq msg 1549650439178428447・2026-09-16)、1行目が
      if not cue_required(dept): return False
    だ。だから合図を外した瞬間、その部屋では**印の抑止も一緒に外れる**。
    実測(local/_work/measure_mark_press_20260922.py)=
      rooms.local_pipeline_order(<4室>, "生成依頼 …") は今どれも False。
      ただし押下点までは届いていない= 閉室分岐が手前で積まないので印は0件だった。
    つまり今この4室を守っているのは合図ではなく**閉室**だ。
    レバーを動かす人がこの二つ目の消費者を見落とさないよう、関係をここに固定する。
    """

    DEPT = "imagegen-lever-test"
    ORDER = "生成依頼 銀髪ロング 制服 桜"

    def tearDown(self):
        rooms.ROOMS.pop(self.DEPT, None)

    def test_a_cue_room_keeps_the_mark_suppressed(self):
        """合図が要る部屋では、注文便はローカルの仕事=Claude印を押さない側に居る。"""
        rooms.ROOMS[self.DEPT] = {"lora_hint": None, "persona": "優依",
                                  "ckpt": rooms.ROOMS["imagegen"]["ckpt"],
                                  "label": "検査用(架空)"}
        self.assertTrue(rooms.cue_required(self.DEPT))
        self.assertTrue(rooms.local_pipeline_order(self.DEPT, self.ORDER),
                        "合図が要る部屋で印の抑止が外れている=注文便にClaude印が戻る")

    def test_a_cue_free_room_must_be_closed_because_the_suppression_is_gone(self):
        """★免除した部屋は印の抑止を失う。よって**Claudeが居ない部屋でしか免除できない**。
        ここが赤い時に直すのは検査ではなく、どちらかのレバーだ
        (合図を戻すか、その部屋のClaudeを閉じるか)。"""
        for dept in rooms.NO_CUE_DEPTS:
            self.assertFalse(rooms.local_pipeline_order(dept, self.ORDER), dept)
            self.assertTrue(rooms.claude_off(dept),
                            "%s は印の抑止が外れているのにClaudeが聞いている" % dept)


class EveryRoomBehavesAsItsPolicySays(unittest.TestCase):
    """台帳の要否と、入口(order_of)の実際の振る舞いが一致しているか。"""

    ORDER = "生成依頼 銀髪ロング 制服 桜"
    CHAT = "これいらん"

    SAMPLE = "imagegen-behaviour-test"

    def tearDown(self):
        rooms.ROOMS.pop(self.SAMPLE, None)

    def test_cue_rooms_take_only_the_cue(self):
        """★合図が要る実在室が0になっても、この検査を空回りさせない。

        2026-09-22 05:49 の訂正(msg 1551692776859631629)で実在の描画室は全室が免除になった。
        名簿を回すだけの書き方だと、ここは**1件も試さずに緑**になる=合図機構が壊れても気づけない。
        だから要る部屋を1つ建てて、必ず実物を1件通す。
        """
        rooms.ROOMS[self.SAMPLE] = {"lora_hint": None, "persona": "優依",
                                    "ckpt": rooms.ROOMS["imagegen"]["ckpt"],
                                    "label": "検査用(架空)"}
        for dept in tuple(rooms.CUE_REQUIRED_DEPTS) + (self.SAMPLE,):
            self.assertTrue(rooms.cue_required(dept), dept)
            order, prompt = rooms.order_of(dept, self.ORDER)
            self.assertTrue(order, dept)
            self.assertEqual(prompt, "銀髪ロング 制服 桜", dept)
            self.assertFalse(rooms.order_of(dept, self.CHAT)[0], dept)

    def test_cue_free_rooms_take_everything_and_still_strip_the_cue(self):
        """合図を外しても、付けて来た便で「生成依頼」が絵の指示に混ざってはいけない。"""
        for dept in rooms.NO_CUE_DEPTS:
            self.assertTrue(rooms.order_of(dept, self.CHAT)[0], dept)
            order, prompt = rooms.order_of(dept, self.ORDER)
            self.assertTrue(order, dept)
            self.assertEqual(prompt, "銀髪ロング 制服 桜", dept)

    def test_an_empty_body_is_never_an_order(self):
        for dept in rooms.ROOMS:
            self.assertFalse(rooms.order_of(dept, "   ")[0], dept)


if __name__ == "__main__":
    unittest.main(verbosity=2)
