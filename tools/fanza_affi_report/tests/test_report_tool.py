"""ユニットテスト + 全体ドライラン。stdlib unittest のみ。

    python -m unittest discover -s tests -v
"""
from __future__ import annotations

import io
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

from fanza_affi_report.aggregate import summarize
from fanza_affi_report.cli import run
from fanza_affi_report.parser import ReportFormatError, load_report_csv, parse_report_text
from fanza_affi_report.report import format_report
from fanza_affi_report.senders import (
    DiscordWebhookSender,
    SendError,
    StdoutSender,
    _split_for_discord,
)
from fanza_affi_report.state import StateStore

from tests.fixtures import ROWS_DAY1, ROWS_DAY2, write_bad_csv, write_cp932_csv


class TestParser(unittest.TestCase):
    def test_parse_cp932(self):
        with tempfile.TemporaryDirectory() as d:
            p = write_cp932_csv(Path(d) / "day1.csv", ROWS_DAY1)
            rows = load_report_csv(p)
        self.assertEqual(len(rows), 5)
        self.assertEqual(rows[0].product_code, "d_000001")
        self.assertEqual(rows[0].reward_type, "ダイレクト")
        self.assertEqual(rows[0].reward_amount, 385)

    def test_comma_and_yen(self):
        text = "サービス,品番,商品タイトル,販売金額,報酬体系,報酬件数,報酬額\n同人,d_1,t,\"1,100\",ダイレクト,\"1\",\"1,912円\"\n"
        rows = parse_report_text(text)
        self.assertEqual(rows[0].reward_amount, 1912)
        self.assertEqual(rows[0].sale_price, 1100)

    def test_missing_column_raises(self):
        with tempfile.TemporaryDirectory() as d:
            p = write_bad_csv(Path(d) / "bad.csv")
            with self.assertRaises(ReportFormatError):
                load_report_csv(p)

    def test_empty_raises(self):
        with self.assertRaises(ReportFormatError):
            parse_report_text("")


class TestAggregate(unittest.TestCase):
    def setUp(self):
        with tempfile.TemporaryDirectory() as d:
            self.rows = load_report_csv(write_cp932_csv(Path(d) / "d.csv", ROWS_DAY1))

    def test_totals(self):
        s = summarize(self.rows, date="2026-09-01")
        self.assertEqual(s.total_amount, 385 + 1000 + 500 + 560 + 1800)
        self.assertEqual(s.total_count, 1 + 3 + 2 + 2 + 1)
        self.assertEqual(s.n_rows, 5)

    def test_by_type(self):
        s = summarize(self.rows, date="2026-09-01")
        self.assertEqual(s.by_type["ダイレクト"].amount, 385 + 560)
        self.assertEqual(s.by_type["カテゴリ"].amount, 1000 + 500)
        self.assertEqual(s.by_type["サービス新規"].amount, 1800)

    def test_by_service_dedup(self):
        s = summarize(self.rows, date="2026-09-01")
        self.assertIn("同人", s.by_service)  # "同人 同人" → "同人"
        self.assertIn("FANZAブックス", s.by_service)

    def test_top_products_sorted(self):
        s = summarize(self.rows, date="2026-09-01")
        amounts = [p["amount"] for p in s.top_products]
        self.assertEqual(amounts, sorted(amounts, reverse=True))
        self.assertEqual(s.top_products[0]["amount"], 1800)

    def test_conversion_rate_with_clicks(self):
        s = summarize(self.rows, date="2026-09-01", clicks=100)
        self.assertAlmostEqual(s.conversion_rate, 9 / 100)

    def test_unknown_type_flagged(self):
        text = "サービス,品番,商品タイトル,販売金額,報酬体系,報酬件数,報酬額\n同人,d_1,t,100,ミステリー報酬,1,50\n"
        s = summarize(parse_report_text(text), date="2026-09-01")
        self.assertIn("ミステリー報酬", s.unknown_types)


class TestState(unittest.TestCase):
    def test_delta_first_and_second(self):
        with tempfile.TemporaryDirectory() as d:
            state_path = Path(d) / "state.json"
            r1 = load_report_csv(write_cp932_csv(Path(d) / "d1.csv", ROWS_DAY1))
            r2 = load_report_csv(write_cp932_csv(Path(d) / "d2.csv", ROWS_DAY2))
            s1 = summarize(r1, date="2026-09-01")
            s2 = summarize(r2, date="2026-09-02")

            store = StateStore(state_path)
            d1 = store.delta_against_previous(s1)
            self.assertIsNone(d1.prev_date)  # 初回は基準
            store.record(s1)

            store2 = StateStore(state_path)  # 保存が効いているか別インスタンスで確認
            d2 = store2.delta_against_previous(s2)
            self.assertEqual(d2.prev_date, "2026-09-01")
            self.assertEqual(d2.amount, s2.total_amount - s1.total_amount)


class TestReport(unittest.TestCase):
    def test_format_contains_key_lines(self):
        with tempfile.TemporaryDirectory() as d:
            rows = load_report_csv(write_cp932_csv(Path(d) / "d.csv", ROWS_DAY1))
            s = summarize(rows, date="2026-09-01")
            store = StateStore(Path(d) / "s.json")
            body = format_report(s, store.delta_against_previous(s))
        self.assertIn("報酬合計", body)
        self.assertIn("報酬体系別", body)
        self.assertIn("上位作品", body)


class TestSenders(unittest.TestCase):
    def test_stdout(self):
        buf = io.StringIO()
        with redirect_stdout(buf):
            StdoutSender().send("件名", "本文")
        self.assertIn("dry-run", buf.getvalue())

    def test_webhook_requires_url(self):
        with self.assertRaises(SendError):
            DiscordWebhookSender("")

    def test_split_for_discord(self):
        text = "\n".join(f"line{i}" for i in range(500))
        chunks = _split_for_discord(text, limit=100)
        self.assertTrue(all(len(c) <= 100 for c in chunks))
        self.assertGreater(len(chunks), 1)


class TestDryRunEndToEnd(unittest.TestCase):
    def test_full_dry_run(self):
        with tempfile.TemporaryDirectory() as d:
            dd = Path(d)
            csv = write_cp932_csv(dd / "report.csv", ROWS_DAY1)
            cfg = dd / "config.ini"
            cfg.write_text(
                "[report]\ntitle = テストレポート\n"
                "[output]\nsender = stdout\n"
                f"[state]\npath = {dd / 'state.json'}\n"
                f"[log]\npath = {dd / 'log.txt'}\n",
                encoding="utf-8",
            )
            buf = io.StringIO()
            with redirect_stdout(buf):
                rc = run(
                    ["--config", str(cfg), "--csv", str(csv),
                     "--date", "2026-09-01", "--dry-run"]
                )
            out = buf.getvalue()
        self.assertEqual(rc, 0)
        self.assertIn("報酬合計", out)
        self.assertIn("dry-run", out)


if __name__ == "__main__":
    unittest.main(verbosity=2)
