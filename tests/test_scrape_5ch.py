# -*- coding: utf-8 -*-
"""scrape_5ch.py のユニットテスト。スレ選定の前フィルタ層(A/B/C)を検証する
(2026-09-02 モドリッチ発注 msg1544677874911678468「核心の改善」対応)。
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
import scrape_5ch as s


class TestSelectionWeight(unittest.TestCase):
    def test_mega_thread_excluded(self):
        for title in ["ホロライブ総合スレ#453", "なんJ雑談スレ", "アイドル総合", "実況避難所"]:
            excluded, weight = s.selection_weight(title)
            self.assertTrue(excluded, msg=title)

    def test_single_topic_not_excluded(self):
        excluded, weight = s.selection_weight("【朗報】ワイの推し、ガチで結婚した結果www")
        self.assertFalse(excluded)
        self.assertGreater(weight, 1.0)

    def test_edgy_hint_boosts_weight(self):
        excluded, w_plain = s.selection_weight("最近の物価について語るスレ")
        excluded2, w_edgy = s.selection_weight("最近の物価について語るスレ(巨乳限定)")
        self.assertFalse(excluded)
        self.assertFalse(excluded2)
        self.assertGreater(w_edgy, w_plain)

    def test_this_would_fail_if_mega_filter_removed(self):
        # test-must-fail: フィルタが無いと総合スレも除外されずに残るはず
        excluded, _ = s.selection_weight("声優総合スレ#901")
        self.assertTrue(excluded)

        def _no_mega(title):
            return False, 1.0
        original = s.selection_weight
        s.selection_weight = _no_mega
        try:
            excluded2, _ = s.selection_weight("声優総合スレ#901")
            self.assertFalse(excluded2)
        finally:
            s.selection_weight = original


if __name__ == "__main__":
    unittest.main(verbosity=2)
