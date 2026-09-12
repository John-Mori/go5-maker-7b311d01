# -*- coding: utf-8 -*-
"""neta_shelf.py のユニットテスト。時事/常在の棚分けと失効の向きを検証する
(2026-09-12 Chami直 ESC-copy-director-1548134259490029629 / ad研究室裁定v2の運用)。
基準の正本= docs/departments/research-room/裁定_ネタの時事常在の棚分けの置き場_2026-09-12.md。
ここは「運用が正本を正しく写しているか」だけを守る(閾値の是非は正本側の較正で動く)。
"""
import os
import sys
import unittest
from datetime import datetime, timedelta

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
import neta_shelf as ns


FETCHED = "2026-09-12T06:00:00+09:00"


class TestClassify(unittest.TestCase):
    def test_specific_date_is_jiji_expire_next_midnight(self):
        shelf, reason, exp = ns.classify(
            "【にじさんじ】9/14 21:00から、EXゲーマーズでラウンドワン-1王を決めます。", FETCHED)
        self.assertEqual(shelf, "時事")
        # 9/14 のイベント→ 翌0時(9/15 00:00 JST)で失効
        self.assertEqual(exp, datetime(2026, 9, 15, tzinfo=ns.JST))

    def test_announce_word_is_jiji_expire_72h(self):
        shelf, reason, exp = ns.classify("いよいよ本日20時から3Dお披露目", FETCHED)
        self.assertEqual(shelf, "時事")
        base = datetime(2026, 9, 12, 6, 0, tzinfo=ns.JST)
        self.assertEqual(exp, base + timedelta(hours=ns.ANNOUNCE_TTL_H))

    def test_flare_word_is_jiji(self):
        shelf, reason, exp = ns.classify("○○さんお気持ち表明で炎上", FETCHED)
        self.assertEqual(shelf, "時事")
        self.assertIsNotNone(exp)

    def test_timeless_is_joza_failopen_no_expire(self):
        # 性格・ネタ化=時間で価値が減らない→常在。材料が無いので fail-open。
        shelf, reason, exp = ns.classify("みかるんのでかるん", FETCHED)
        self.assertEqual(shelf, "常在")
        self.assertIsNone(exp)

    # --- must-fail(誤検知が起きたら落ちる)---
    def test_ratio_slash_not_treated_as_date(self):
        # 「1/2」等の比率・分数をイベント日付と取り違えない(境界の守り)。
        shelf, reason, exp = ns.classify("勝率が1/2を切ったキャラ雑談", FETCHED)
        # 分数を日付と誤認して時事にしないこと。材料が他に無ければ常在へ落ちる。
        self.assertEqual(shelf, "常在", msg=f"1/2を日付誤認: {reason}")

    def test_missing_fetched_falls_back_to_now_not_crash(self):
        # fetched_at が無くても落ちない(distilled ヘッダと matome の join が外れた時の保険)。
        shelf, reason, exp = ns.classify("いよいよ開催", None)
        self.assertEqual(shelf, "時事")
        self.assertIsNotNone(exp)

    # --- v1.1 語彙を当てる範囲=記事本体だけ(モドリッチ較正1)---
    def test_site_name_after_separator_not_matched(self):
        # サイト名『VTuberまとめ速報』の『速報』を語彙判定に混ぜない=本体は雑談なので常在。
        shelf, reason, exp = ns.classify(
            "みかるんのでかるんが好きすぎる件 : VTuberまとめ速報", FETCHED)
        self.assertEqual(shelf, "常在", msg=f"サイト名の語で誤爆: {reason}")

    def test_announce_word_in_body_still_matched(self):
        # 本体側の告知語はこれまで通り拾う(範囲を狭めても本体の判定は死なない)。
        shelf, reason, exp = ns.classify(
            "いよいよ本日3Dお披露目 : VTuberまとめ速報", FETCHED)
        self.assertEqual(shelf, "時事")


class TestSplitTitle(unittest.TestCase):
    def test_last_separator_splits_body_and_site(self):
        body, site = ns.split_title("本体の話 : VTuberまとめ速報")
        self.assertEqual(body, "本体の話")
        self.assertEqual(site, "VTuberまとめ速報")

    def test_no_separator_whole_is_body(self):
        body, site = ns.split_title("みかるんのでかるん")
        self.assertEqual(body, "みかるんのでかるん")
        self.assertEqual(site, "")


class TestEntranceDrop(unittest.TestCase):
    def test_site_name_only_record_is_dropped(self):
        # 区切り無しでサイト名署名に当たる(インデックスページ)→ 入口で外す。
        self.assertTrue(ns.is_site_name_only("VTuberまとめ速報", set()))

    def test_known_site_from_suffix_is_dropped(self):
        # 他レコードの接尾辞から集めた既知サイト名に一致→ 外す(まとめるよ～ん系)。
        known = {"Vtuberまとめるよ～ん"}
        self.assertTrue(ns.is_site_name_only("Vtuberまとめるよ～ん", known))

    def test_genuine_article_with_separator_is_kept(self):
        # 記事本体 : サイト名 の形は本体が在る→ 外さない。
        self.assertFalse(ns.is_site_name_only("本体の話 : VTuberまとめ速報", set()))


class TestExpireDirection(unittest.TestCase):
    def test_next_midnight_after_rolls_to_reachable_year(self):
        base = datetime(2026, 9, 12, tzinfo=ns.JST)
        exp = ns._next_midnight_after(9, 14, base)
        self.assertEqual(exp, datetime(2026, 9, 15, tzinfo=ns.JST))


if __name__ == "__main__":
    unittest.main()
