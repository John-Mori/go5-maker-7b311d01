# -*- coding: utf-8 -*-
"""ingest_video.py の純粋関数(json3字幕パース)のユニットテスト。
ネットワーク/yt-dlp/ffmpeg/whisperは呼ばない(それらはI/O境界なので対象外)。
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
import ingest_video as g


class TestParseJson3Events(unittest.TestCase):
    def test_basic_segments(self):
        raw = {
            "events": [
                {"tStartMs": 0, "dDurationMs": 4000},  # segsなし(ウィンドウ設定行)→除外
                {"tStartMs": 80, "dDurationMs": 4840, "segs": [
                    {"utf8": "こんにちは"}, {"utf8": "世界"},
                ]},
                {"tStartMs": 2000, "dDurationMs": 2000, "segs": [{"utf8": "\n"}]},  # 改行のみ→除外
            ]
        }
        segs = g.parse_json3_events(raw)
        self.assertEqual(len(segs), 1)
        self.assertEqual(segs[0]["text"], "こんにちは世界")
        self.assertEqual(segs[0]["start"], 0.08)
        self.assertEqual(segs[0]["end"], round(0.08 + 4.84, 2))

    def test_no_events_returns_none(self):
        self.assertIsNone(g.parse_json3_events({"events": []}))

    def test_all_empty_segs_returns_none(self):
        raw = {"events": [{"tStartMs": 0, "dDurationMs": 100, "segs": [{"utf8": "\n"}]}]}
        self.assertIsNone(g.parse_json3_events(raw))


if __name__ == "__main__":
    unittest.main(verbosity=2)
