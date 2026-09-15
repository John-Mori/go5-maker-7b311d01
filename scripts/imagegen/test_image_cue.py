# -*- coding: utf-8 -*-
"""合図ゲート(雑談と画像注文の線引き)の検査。

依頼= アメス便 1549468992396329025(依頼元 imagegen-fusoh-v0)。
★この検査は**判定と分岐を本物のまま**通す。偽物にするのは外へ出る手だけ=
  Discordへの送信(send)・ファイル追記(append_line/log)・ComfyUIの起動(subprocess.run)。
★旧コード(scripts/llm/local_responder.py.bak_20260916_cue)に当てると
  test_chitchat_is_not_drawn が落ちる=直る前に落ちる検査になっている。

    python scripts/imagegen/test_image_cue.py
"""
import os
import sys
import unittest

_HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.normpath(os.path.join(_HERE, "..", ".."))
sys.path.insert(0, _HERE)
sys.path.insert(0, os.path.join(ROOT, "scripts", "llm"))

import rooms                      # noqa: E402
import local_responder as lr      # noqa: E402

# 実害そのものの文(アメス便の実例)
CHITCHAT = "これデーモン?デーモンの返信いらんよ"


class _Proc(object):
    returncode = 0
    stdout = ""
    stderr = ""


class Harness(object):
    """外へ出る手だけを受け止める。分岐は本物が決める。"""

    def __init__(self):
        self.sent = []          # (channel, text)
        self.sent_as = []       # (channel, text, persona)
        self.logged = []        # log() の辞書
        self.appended = []      # (path, line)
        self.spawned = []       # local_chain へ渡した argv
        self._orig = {}

    def __enter__(self):
        self._orig = {
            "send": lr.send, "send_as": lr.send_as, "log": lr.log,
            "append_line": lr.append_line, "run": lr.subprocess.run,
        }
        lr.send = lambda ch, text, **kw: (self.sent.append((ch, text)), True)[1]
        lr.send_as = lambda ch, text, persona, suffix="": (
            self.sent_as.append((ch, text, persona)), True)[1]
        lr.log = lambda d: self.logged.append(d)
        lr.append_line = lambda p, l: self.appended.append((p, l))
        lr.subprocess.run = self._run
        return self

    def _run(self, argv, **kw):
        self.spawned.append(list(argv))
        return _Proc()

    def __exit__(self, *a):
        lr.send = self._orig["send"]
        lr.send_as = self._orig["send_as"]
        lr.log = self._orig["log"]
        lr.append_line = self._orig["append_line"]
        lr.subprocess.run = self._orig["run"]
        return False

    def modes(self):
        return [d.get("mode") for d in self.logged]

    def prompt(self):
        """local_chain へ実際に渡した本文(=絵になる文)。"""
        self.assertish()
        return self.spawned[0][2]

    def assertish(self):
        if not self.spawned:
            raise AssertionError("local_chain が起動されていない")


def deliver(text, dept, channel="ローカルllm-画像生成ルーム-優依"):
    """本物の handle() をそのまま通す。"""
    rec = {"content": text, "channel": channel, "dept": dept,
           "msg_id": "test-0001", "author": "chami_fusoh"}
    h = Harness()
    with h:
        lr.handle(rec, '{"test": true}')
    return h


class TestCueTable(unittest.TestCase):
    """正本(rooms.py)の合図表そのもの。"""

    def test_only_the_two_named_rooms_require_a_cue(self):
        self.assertTrue(rooms.cue_required("imagegen-fusoh-v0"))
        self.assertTrue(rooms.cue_required("imagegen-fusoh-v2"))
        self.assertFalse(rooms.cue_required("imagegen"))   # 既存室は変えない(C-035)

    def test_cue_is_stripped_from_the_prompt(self):
        ok, body = rooms.order_of("imagegen-fusoh-v0", "!描 銀髪ロング 制服 桜", None)
        self.assertTrue(ok)
        self.assertEqual(body, "銀髪ロング 制服 桜")

    def test_fullwidth_and_halfwidth_colon_both_work(self):
        for head in ("絵:", "絵:", "画:", "画:"):
            ok, body = rooms.order_of("imagegen-fusoh-v0", head + "猫", None)
            self.assertTrue(ok, head)
            self.assertEqual(body, "猫", head)

    def test_natural_japanese_is_accepted_when_given(self):
        ok, _ = rooms.order_of("imagegen-fusoh-v0", "女の子の絵を描いて", lr.wants_image)
        self.assertTrue(ok)

    def test_chitchat_is_rejected(self):
        ok, _ = rooms.order_of("imagegen-fusoh-v0", CHITCHAT, lr.wants_image)
        self.assertFalse(ok)

    def test_cue_only_returns_empty_body(self):
        ok, body = rooms.order_of("imagegen-fusoh-v0", "!描", None)
        self.assertTrue(ok)
        self.assertEqual(body, "")

    def test_help_line_is_built_from_the_table(self):
        self.assertIn(rooms.CUE_PREFIXES[0], rooms.cue_help())


class TestRoomV0(unittest.TestCase):
    """fusoh_v0(手描き風・カスミ)。実害が起きた部屋。"""

    DEPT = "imagegen-fusoh-v0"

    def test_chitchat_is_not_drawn(self):
        """★これが直る前に落ちる本体。雑談でComfyUIを起こさない・部屋へ喋らない。"""
        h = deliver(CHITCHAT, self.DEPT)
        self.assertEqual(h.spawned, [], "雑談で local_chain を起動した")
        self.assertEqual(h.sent, [], "雑談に返事をした(Chami「デーモンの返信いらんよ」)")
        self.assertIn("image_no_cue", h.modes())

    def test_chitchat_is_still_counted(self):
        """黙って捨てない=台帳に残り、二度読みしないよう済にする。"""
        h = deliver(CHITCHAT, self.DEPT)
        self.assertEqual(len(h.logged), 1)
        self.assertEqual(h.logged[0].get("dept"), self.DEPT)
        self.assertTrue(h.appended, "PROCESSED に積んでいない(同じ便を何度も読む)")

    def test_cue_order_is_drawn_without_the_cue_mark(self):
        h = deliver("!描 銀髪ロング 制服 桜", self.DEPT)
        self.assertTrue(h.spawned, "合図付きの注文を描かなかった")
        self.assertIn("銀髪ロング 制服 桜", h.spawned[0])
        self.assertNotIn("!描", " ".join(h.spawned[0]))

    def test_natural_order_is_drawn(self):
        h = deliver("探偵っぽい女の子の絵を描いて", self.DEPT)
        self.assertTrue(h.spawned, "「絵を描いて」を拾えなかった")

    def test_cue_only_asks_back_and_does_not_draw(self):
        h = deliver("!描", self.DEPT)
        self.assertEqual(h.spawned, [])
        self.assertEqual(len(h.sent), 1)
        self.assertIn("image_cue_only", h.modes())

    def test_room_persona_is_kasumi(self):
        self.assertEqual(rooms.ROOMS[self.DEPT]["persona"], "カスミ")


class TestRoomV2(TestRoomV0):
    """★姉妹室にも同じ配線を効かせる(アメス便「両室に効かせてほしい」)。"""

    DEPT = "imagegen-fusoh-v2"

    def test_room_persona_is_kasumi(self):
        self.assertEqual(rooms.ROOMS[self.DEPT]["persona"], "中野五月")


class TestExistingRoomUnchanged(unittest.TestCase):
    """既存の imagegen 室= Chamiは名指ししていない。挙動を1文字も変えない(C-035)。"""

    def test_chitchat_is_still_drawn_there(self):
        h = deliver(CHITCHAT, "imagegen")
        self.assertTrue(h.spawned, "既存室の挙動を勝手に変えた")


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    unittest.main(verbosity=2)
