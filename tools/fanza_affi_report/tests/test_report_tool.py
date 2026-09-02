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
from fanza_affi_report.downloader import (
    DownloadError,
    LocalFolderDownloader,
    SessionDownloader,
    SessionExpired,
    build_downloader,
)
from fanza_affi_report.notify import FailureKind, classify
from fanza_affi_report.parser import ReportFormatError, load_report_csv, parse_report_text
from fanza_affi_report.report import format_report
from fanza_affi_report.senders import (
    DiscordWebhookSender,
    MailSender,
    SendError,
    StdoutSender,
    build_sender,
    _split_for_discord,
)
from fanza_affi_report.state import StateStore

from tests.fixtures import (
    ROWS_DAY1,
    ROWS_DAY2,
    write_bad_csv,
    write_cp932_csv,
    write_header_only_csv,
    write_html_login_csv,
    write_zero_byte_csv,
)


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

    def test_login_html_raises(self):
        """セッション失効時にログイン画面のHTMLがCSVの体で返るケースを弾く。"""
        html = (
            "<!DOCTYPE html><html><head><title>ログイン</title></head>"
            "<body>ログインしてください</body></html>"
        )
        with self.assertRaises(ReportFormatError) as ctx:
            parse_report_text(html)
        self.assertIn("HTML", str(ctx.exception))

    def test_zero_byte_file_raises(self):
        """0バイトファイル(DL途中断)はCSV異常として明確に弾く。"""
        with tempfile.TemporaryDirectory() as d:
            p = write_zero_byte_csv(Path(d) / "empty.csv")
            with self.assertRaises(ReportFormatError):
                load_report_csv(p)

    def test_header_only_is_zero_sales_not_error(self):
        """ヘッダ行だけ(明細0行)は正常な「売上ゼロ」。取得失敗と混同してはいけない。"""
        with tempfile.TemporaryDirectory() as d:
            p = write_header_only_csv(Path(d) / "zero.csv")
            rows = load_report_csv(p)
        self.assertEqual(rows, [])

    def test_html_mixed_file_raises_via_load_report_csv(self):
        """ログイン画面が200でCSVの体で返ってきたファイルをファイル経由でも弾く。"""
        with tempfile.TemporaryDirectory() as d:
            p = write_html_login_csv(Path(d) / "login.csv")
            with self.assertRaises(ReportFormatError) as ctx:
                load_report_csv(p)
        self.assertIn("HTML", str(ctx.exception))

    def test_cp932_decode_failure_falls_back_or_raises_clearly(self):
        """cp932で復号できないバイト列は utf-8系へフォールバックし、それも失敗すれば
        「文字コードを判定できない」で明確に止まる(黙って文字化けCSVを通さない)。"""
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "broken.csv"
            # 0x81 単独は cp932 として不正、かつ utf-8としても不正なバイト列。
            p.write_bytes(b"\x81\xff\x00\x01\x02")
            with self.assertRaises(ReportFormatError) as ctx:
                load_report_csv(p)
        self.assertIn("文字コード", str(ctx.exception))


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


class TestDownloader(unittest.TestCase):
    def test_local_missing_raises_download_error(self):
        with tempfile.TemporaryDirectory() as d:
            with self.assertRaises(DownloadError):
                LocalFolderDownloader().fetch(Path(d), "2026-09-01")

    def test_local_returns_latest(self):
        with tempfile.TemporaryDirectory() as d:
            dd = Path(d)
            write_cp932_csv(dd / "a_2026-09-01.csv", ROWS_DAY1)
            write_cp932_csv(dd / "b_2026-09-02.csv", ROWS_DAY2)
            got = LocalFolderDownloader().fetch(dd, "2026-09-02")
        self.assertEqual(got.name, "b_2026-09-02.csv")

    def test_build_downloader_unknown_mode_raises(self):
        with self.assertRaises(DownloadError):
            build_downloader({"download_mode": "fax"})

    def test_build_downloader_local_default(self):
        d = build_downloader({})
        self.assertIsInstance(d, LocalFolderDownloader)

    def test_session_without_wiring_raises_without_touching_network(self):
        # export_url_template/report_page_url 未設定なら playwright を import する前に止まる
        # (=当て推量のURLで実際に接続しにいかない)。資格情報は一切渡さない(二層方式)。
        d = SessionDownloader(session_dir="sessions", affiliate_id="")
        with self.assertRaises(DownloadError) as ctx:
            d.fetch(Path("."), "2026-09-01")
        self.assertIn("実配線", str(ctx.exception))

    def test_session_holds_no_credentials(self):
        # 二層方式: username/password はコンストラクタにもconfigにも存在しない。
        d = SessionDownloader(session_dir="sessions", affiliate_id="af-1")
        self.assertFalse(hasattr(d, "username"))
        self.assertFalse(hasattr(d, "password"))

    def test_build_downloader_session_mode_wires_browser_channel(self):
        d = build_downloader(
            {
                "download_mode": "session",
                "session_dir": "sessions",
                "browser_channel": "msedge",
                "export_url_template": "https://example.invalid/export",
            }
        )
        self.assertIsInstance(d, SessionDownloader)
        self.assertEqual(d.browser_channel, "msedge")

    def test_build_downloader_legacy_playwright_mode_still_accepted(self):
        # 旧設定値 mode=playwright は後方互換で SessionDownloader を返す。
        d = build_downloader({"download_mode": "playwright", "session_dir": "sessions"})
        self.assertIsInstance(d, SessionDownloader)


class _FakeResponse:
    def __init__(self, status: int, url: str = "", body: bytes = b""):
        self.status = status
        self.url = url
        self._body = body

    def body(self) -> bytes:
        return self._body


class _FakeRequestContext:
    """context.request の代わり(直叩き第1層)。"""

    def __init__(self, response=None, exc: Exception | None = None):
        self._response = response
        self._exc = exc
        self.calls: list[str] = []

    def get(self, url: str, timeout=None):
        self.calls.append(url)
        if self._exc:
            raise self._exc
        return self._response


class _FakeDownload:
    def __init__(self, path: str):
        self._path = path

    def path(self) -> str:
        return self._path


class _FakeDownloadInfo:
    def __init__(self, download):
        self.value = download


class _FakeExpectDownload:
    """page.expect_download() の代わり(with文で使うコンテキストマネージャ)。"""

    def __init__(self, download):
        self._download = download

    def __enter__(self):
        return _FakeDownloadInfo(self._download)

    def __exit__(self, *exc):
        return False


class _FakePage:
    def __init__(self, goto_response=None, goto_exc=None, download_path: str | None = None, url: str = ""):
        self._goto_response = goto_response
        self._goto_exc = goto_exc
        self._download_path = download_path
        self.url = url
        self.clicked: list[str] = []

    def goto(self, url, wait_until=None, timeout=None):
        if self._goto_exc:
            raise self._goto_exc
        return self._goto_response

    def expect_download(self, timeout=None):
        return _FakeExpectDownload(_FakeDownload(self._download_path))

    def click(self, selector):
        self.clicked.append(selector)


class _FakeContext:
    def __init__(self, request=None, page=None):
        self.request = request
        self.pages = [page] if page else []
        self._new_page = page

    def new_page(self):
        return self._new_page


class TestSessionDownloaderFallback(unittest.TestCase):
    """設計メモ§6-1: 直叩き→クリックのフォールバック選択ロジックをオフラインで検証。
    実playwright/実ネットワークには一切触れない(フェイクの context/page を注入)。
    """

    def test_direct_hit_success_uses_direct_body(self):
        d = SessionDownloader(
            session_dir="sessions",
            export_url_template="https://example.invalid/export?date={date}",
            report_page_url="https://example.invalid/report",
            csv_export_selector="button.export",
        )
        ctx = _FakeContext(
            request=_FakeRequestContext(_FakeResponse(200, body=b"csv-direct-body")),
            page=_FakePage(),  # クリック側は呼ばれないはず
        )
        body = d._fetch_body(ctx, "2026-09-01")
        self.assertEqual(body, b"csv-direct-body")
        self.assertEqual(ctx.request.calls, ["https://example.invalid/export?date=2026-09-01"])

    def test_direct_hit_session_expired_does_not_fallback(self):
        """401/403は失効なので、クリック方式が設定されていてもフォールバックしない。"""
        d = SessionDownloader(
            session_dir="sessions",
            export_url_template="https://example.invalid/export?date={date}",
            report_page_url="https://example.invalid/report",
            csv_export_selector="button.export",
        )
        page = _FakePage()
        ctx = _FakeContext(
            request=_FakeRequestContext(_FakeResponse(401)),
            page=page,
        )
        with self.assertRaises(SessionExpired):
            d._fetch_body(ctx, "2026-09-01")
        self.assertEqual(page.clicked, [])  # クリック側に触れていない

    def test_direct_hit_structural_failure_falls_back_to_click(self):
        """直叩きが構造変化などで200以外(401/403以外)を返したら、クリック方式へ
        フォールバックし、そちらが成功すればそれを使う。"""
        d = SessionDownloader(
            session_dir="sessions",
            export_url_template="https://example.invalid/export?date={date}",
            report_page_url="https://example.invalid/report",
            csv_export_selector="button.export",
        )
        with tempfile.TemporaryDirectory() as td:
            dl_path = Path(td) / "downloaded.csv"
            dl_path.write_bytes(b"csv-via-click")
            page = _FakePage(goto_response=_FakeResponse(200), download_path=str(dl_path))
            ctx = _FakeContext(
                request=_FakeRequestContext(_FakeResponse(500)),
                page=page,
            )
            body = d._fetch_body(ctx, "2026-09-01")
        self.assertEqual(body, b"csv-via-click")
        self.assertEqual(page.clicked, ["button.export"])

    def test_direct_unset_goes_straight_to_click(self):
        d = SessionDownloader(
            session_dir="sessions",
            export_url_template="",
            report_page_url="https://example.invalid/report",
            csv_export_selector="button.export",
        )
        with tempfile.TemporaryDirectory() as td:
            dl_path = Path(td) / "downloaded.csv"
            dl_path.write_bytes(b"csv-via-click-only")
            page = _FakePage(goto_response=_FakeResponse(200), download_path=str(dl_path))
            ctx = _FakeContext(request=None, page=page)
            body = d._fetch_body(ctx, "2026-09-01")
        self.assertEqual(body, b"csv-via-click-only")

    def test_click_path_session_expired_via_login_redirect(self):
        d = SessionDownloader(
            session_dir="sessions",
            export_url_template="",
            report_page_url="https://example.invalid/report",
            csv_export_selector="button.export",
        )
        page = _FakePage(goto_response=_FakeResponse(200, url="https://example.invalid/login"), url="https://example.invalid/login")
        ctx = _FakeContext(request=None, page=page)
        with self.assertRaises(SessionExpired):
            d._fetch_body(ctx, "2026-09-01")


class TestDownloadFailureNotice(unittest.TestCase):
    def test_download_failure_is_distinct_from_zero_sales(self):
        """自動DL失敗の通知は、売上ゼロ日の通常レポートと本文だけで区別できること。"""
        with tempfile.TemporaryDirectory() as d:
            dd = Path(d)
            (dd / "empty_csv_dir").mkdir()
            cfg = dd / "config.ini"
            cfg.write_text(
                "[report]\ntitle = テストレポート\n"
                f"[input]\ncsv_dir = {dd / 'empty_csv_dir'}\n"
                "[output]\nsender = stdout\n"
                f"[state]\npath = {dd / 'state.json'}\n"
                f"[log]\npath = {dd / 'log.txt'}\n"
                "[download]\nmode = local\n",
                encoding="utf-8",
            )
            buf = io.StringIO()
            with redirect_stdout(buf):
                rc = run(["--config", str(cfg), "--date", "2026-09-01"])
            out = buf.getvalue()
        self.assertEqual(rc, 1)
        self.assertIn("取得失敗", out)
        self.assertIn("売上ゼロではありません", out)
        self.assertNotIn("報酬合計", out)


class TestFailureClassification(unittest.TestCase):
    def test_login_html_classified_as_session_expired(self):
        self.assertIs(
            classify(ReportFormatError("CSVでなくHTMLが返っている(ログイン画面/セッション失効の可能性)")),
            FailureKind.SESSION_EXPIRED,
        )

    def test_missing_column_classified_as_structure_changed(self):
        self.assertIs(
            classify(ReportFormatError("必須列が欠けています")), FailureKind.STRUCTURE_CHANGED
        )

    def test_bad_numeric_value_classified_as_csv_invalid(self):
        self.assertIs(classify(ReportFormatError("数値として読めない値: 'abc'")), FailureKind.CSV_INVALID)

    def test_end_to_end_failure_notice_names_the_classification(self):
        """壊れたCSV(ログインHTML)を実際に流し、通知本文に分類が出ることを確認する。"""
        with tempfile.TemporaryDirectory() as d:
            dd = Path(d)
            html_csv = dd / "report.csv"
            html_csv.write_text("<!DOCTYPE html><html><body>ログイン</body></html>", encoding="utf-8")
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
                rc = run(["--config", str(cfg), "--csv", str(html_csv), "--date", "2026-09-01"])
            out = buf.getvalue()
        self.assertEqual(rc, 1)
        self.assertIn(FailureKind.SESSION_EXPIRED.value, out)
        self.assertIn("relogin", out)

    def test_session_expired_exception_classified_directly(self):
        # 文字列一致より先に型で SESSION_EXPIRED に確定する(SessionDownloaderの例外)。
        self.assertIs(classify(SessionExpired("失効")), FailureKind.SESSION_EXPIRED)


def _write_min_config(dd: Path, csv_dir: Path | None = None, sender: str = "stdout") -> Path:
    cfg = dd / "config.ini"
    lines = [
        "[report]\ntitle = テストレポート\n",
        f"[output]\nsender = {sender}\n",
        f"[state]\npath = {dd / 'state.json'}\n",
        f"[log]\npath = {dd / 'log.txt'}\n",
    ]
    if csv_dir is not None:
        lines.insert(1, f"[input]\ncsv_dir = {csv_dir}\n")
        lines.append("[download]\nmode = local\n")
    cfg.write_text("".join(lines), encoding="utf-8")
    return cfg


class TestIdempotency(unittest.TestCase):
    """設計メモ§6-6: 同日冪等性(タスク二重起動/手動再実行で二重送信しない)。"""

    def test_second_run_same_day_is_skipped(self):
        with tempfile.TemporaryDirectory() as d:
            dd = Path(d)
            csv = write_cp932_csv(dd / "report.csv", ROWS_DAY1)
            cfg = _write_min_config(dd)

            buf1 = io.StringIO()
            with redirect_stdout(buf1):
                rc1 = run(["--config", str(cfg), "--csv", str(csv), "--date", "2026-09-01"])
            self.assertEqual(rc1, 0)
            self.assertIn("報酬合計", buf1.getvalue())

            buf2 = io.StringIO()
            with redirect_stdout(buf2):
                rc2 = run(["--config", str(cfg), "--csv", str(csv), "--date", "2026-09-01"])
            self.assertEqual(rc2, 0)
            self.assertIn("スキップ", buf2.getvalue())
            self.assertNotIn("報酬合計", buf2.getvalue())

    def test_force_bypasses_idempotency(self):
        with tempfile.TemporaryDirectory() as d:
            dd = Path(d)
            csv = write_cp932_csv(dd / "report.csv", ROWS_DAY1)
            cfg = _write_min_config(dd)

            with redirect_stdout(io.StringIO()):
                run(["--config", str(cfg), "--csv", str(csv), "--date", "2026-09-01"])

            buf = io.StringIO()
            with redirect_stdout(buf):
                rc = run(
                    ["--config", str(cfg), "--csv", str(csv), "--date", "2026-09-01", "--force"]
                )
            self.assertEqual(rc, 0)
            self.assertIn("報酬合計", buf.getvalue())

    def test_dry_run_never_skipped_and_never_records_state(self):
        with tempfile.TemporaryDirectory() as d:
            dd = Path(d)
            csv = write_cp932_csv(dd / "report.csv", ROWS_DAY1)
            cfg = _write_min_config(dd)
            for _ in range(2):
                buf = io.StringIO()
                with redirect_stdout(buf):
                    rc = run(
                        ["--config", str(cfg), "--csv", str(csv),
                         "--date", "2026-09-01", "--dry-run"]
                    )
                self.assertEqual(rc, 0)
                self.assertIn("報酬合計", buf.getvalue())
            self.assertFalse((dd / "state.json").exists())


class TestAttachmentPlumbing(unittest.TestCase):
    """設計メモ§6-5: 送信時に元CSVを添付する導線(送信口の抽象を通す)。"""

    def test_stdout_sender_notes_attachment(self):
        with tempfile.TemporaryDirectory() as d:
            csv = write_cp932_csv(Path(d) / "report.csv", ROWS_DAY1)
            buf = io.StringIO()
            with redirect_stdout(buf):
                StdoutSender().send("件名", "本文", attachment_path=csv)
            self.assertIn("添付予定", buf.getvalue())
            self.assertIn(str(csv), buf.getvalue())

    def test_dry_run_end_to_end_shows_attachment_note(self):
        with tempfile.TemporaryDirectory() as d:
            dd = Path(d)
            csv = write_cp932_csv(dd / "report.csv", ROWS_DAY1)
            cfg = _write_min_config(dd)
            buf = io.StringIO()
            with redirect_stdout(buf):
                run(["--config", str(cfg), "--csv", str(csv), "--date", "2026-09-01", "--dry-run"])
            self.assertIn("添付予定", buf.getvalue())

    def test_discord_sender_requires_existing_attachment(self):
        sender = DiscordWebhookSender("https://discord.invalid/webhook/x")
        with tempfile.TemporaryDirectory() as d:
            missing = Path(d) / "does_not_exist.csv"
            with self.assertRaises(SendError):
                sender._post_multipart("content", missing)


class TestMailSenderPlaceholder(unittest.TestCase):
    """設計メモ§6-5: メール配送は裁定が返ってから実装できるよう境界だけ用意。
    ★未検証(プレースホルダ)。実SMTP資格情報での送信確認はしていない。
    """

    def test_build_sender_mail_without_config_raises_clear_error(self):
        with self.assertRaises(SendError) as ctx:
            build_sender({"sender": "mail"})
        self.assertIn("smtp_host", str(ctx.exception))

    def test_build_sender_mail_with_minimum_config_constructs(self):
        sender = build_sender(
            {
                "sender": "mail",
                "smtp_host": "smtp.example.invalid",
                "smtp_port": "587",
                "mail_from": "from@example.invalid",
                "mail_to": "to@example.invalid",
            }
        )
        self.assertIsInstance(sender, MailSender)


if __name__ == "__main__":
    unittest.main(verbosity=2)
