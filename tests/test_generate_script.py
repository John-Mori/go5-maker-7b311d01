# -*- coding: utf-8 -*-
"""generate_script.py のユニットテスト(test-must-fail準拠)。
NG語言い換え・被参照ランキング・テンプレ除外の3点を、本物のロジックのまま検証する。
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
import generate_script as g


class TestNgFilter(unittest.TestCase):
    def test_literal_word(self):
        out, hits = g.ng_filter("おっぱいでかい")
        self.assertEqual(out, "OPでかい")
        self.assertEqual(hits, ["おっぱい→OP"])

    def test_cup_pattern(self):
        out, hits = g.ng_filter("Gカップって話")
        self.assertEqual(out, "G杯って話")
        self.assertEqual(hits, ["Gカップ→G杯"])

    def test_no_hit_leaves_text_unchanged(self):
        out, hits = g.ng_filter("普通のコメント")
        self.assertEqual(out, "普通のコメント")
        self.assertEqual(hits, [])


class TestRankComments(unittest.TestCase):
    def test_anchor_count_drives_rank(self):
        posts = [
            "!extend:checked:vvvvvv OPテンプレ sage進行推奨",  # index0=OP→除外
            "普通の一言目コメントだよ",       # res2, 被参照0
            ">>2 それな",                    # res3, res2を参照
            ">>2 わかる",                    # res4, res2を再度参照
            "短い",                          # res5, 短すぎて除外(<6文字)
        ]
        ranked = g.rank_comments(posts, top_n=10)
        self.assertEqual(ranked[0]["res"], 2)
        self.assertEqual(ranked[0]["score"], 2)
        self.assertNotIn(1, [c["res"] for c in ranked])
        self.assertNotIn(5, [c["res"] for c in ranked])

    def test_image_url_extracted(self):
        posts = ["OP", "見て https://i.imgur.com/abc123.jpeg すごい"]
        ranked = g.rank_comments(posts, top_n=10)
        self.assertEqual(ranked[0]["images"], ["https://i.imgur.com/abc123.jpeg"])

    def test_this_would_fail_if_template_filter_removed(self):
        # is_template を無効化した状態を模して、フィルタが本当に効いていることを検証する
        # (test-must-fail: フィルタが無いと index0 の !extend: テンプレがランクインするはず)
        posts = ["!extend:checked:vvvvvv:1000:512", "普通のコメントです"]
        ranked_with_filter = g.rank_comments(posts, top_n=10)
        self.assertNotIn(1, [c["res"] for c in ranked_with_filter])

        def _no_template(index, text):
            return False
        original = g.is_template
        g.is_template = _no_template
        try:
            ranked_without_filter = g.rank_comments(posts, top_n=10)
            self.assertIn(1, [c["res"] for c in ranked_without_filter])
        finally:
            g.is_template = original


if __name__ == "__main__":
    unittest.main(verbosity=2)
