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


class TestCompressForTelop(unittest.TestCase):
    def test_short_text_unchanged(self):
        text = "それな"
        self.assertEqual(g.compress_for_telop(text), text)

    def test_long_text_capped_to_two_lines_worth(self):
        text = "あ" * 80
        out = g.compress_for_telop(text)
        self.assertLessEqual(len(out), g.TELOP_MAX_CHARS + 1)  # 「…」1字ぶんの余裕
        self.assertTrue(out.endswith("…"))

    def test_breaks_on_punctuation_when_possible(self):
        text = "これはマジですごい。でも後半はもう関係ない長い蛇足の文がずっと続くだけの部分"
        out = g.compress_for_telop(text, max_len=20)
        self.assertTrue(out.startswith("これはマジですごい。"))

    def test_original_text_preserved_alongside_telop(self):
        # 圧縮は表示専用。build_script経由でも元のtextフィールド(comments[]["text"])は
        # 削れておらず、telopフィールドだけが2行以内に短縮されていることを確認する。
        long_comment = "い" * 100  # 100字(6〜120字の候補範囲に収まる長文)
        thread = {
            "board": "test", "key": "1", "url": "http://example.com",
            "ikioi": 1.0, "res": 1,
            "title": "テストスレ", "posts": ["OP本文", long_comment],
        }
        script = g.build_script(thread)
        c = script["blocks"][2]["comments"][0]
        self.assertEqual(c["text"], long_comment)  # 元本文は無傷
        self.assertLessEqual(len(c["telop"]), g.TELOP_MAX_CHARS + 1)
        self.assertNotEqual(c["telop"], c["text"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
