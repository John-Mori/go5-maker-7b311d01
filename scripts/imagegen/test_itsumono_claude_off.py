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

    def test_other_image_rooms_are_not_closed(self):
        # 閉じたのはこの1室だけ= 巻き込みを起こしていない
        for d in ("imagegen", "imagegen-fusoh-v0", "imagegen-fusoh-v2"):
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

    def test_deadman_does_not_cry_wolf(self):
        sys.path.insert(0, os.path.join(ROOT, "scripts", "_daemons"))
        import importlib.util
        spec = importlib.util.spec_from_file_location("deadman_under_test", DEADMAN)
        dm = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(dm)
        self.assertIn(DEPT, dm.ROSTER_OTHER_OWNER)


class DrawingStillAlive(unittest.TestCase):
    """②★生成経路は生きている(ここが赤いなら閉室ごと戻せ)。"""

    def test_cue_order_still_passes(self):
        order, prompt = rooms.order_of(DEPT, "生成依頼 銀髪ロング 制服 桜")
        self.assertTrue(order)
        self.assertEqual(prompt, "銀髪ロング 制服 桜")

    def test_cue_order_is_local_pipeline_work(self):
        self.assertTrue(rooms.local_pipeline_order(DEPT, "生成依頼 銀髪ロング"))

    def test_chitchat_is_still_not_drawn(self):
        order, _ = rooms.order_of(DEPT, "これいらん")
        self.assertFalse(order)

    def test_room_row_is_intact(self):
        row = rooms.ROOMS[DEPT]
        self.assertEqual(row["lora_hint"], "itsumono")
        self.assertEqual(row["persona"], "優依")        # 絵の名義は変えていない
        self.assertTrue(rooms.cue_required(DEPT))


if __name__ == "__main__":
    unittest.main(verbosity=2)
