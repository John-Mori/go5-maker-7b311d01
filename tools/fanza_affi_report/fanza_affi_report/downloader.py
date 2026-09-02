"""CSV取得口の抽象。★採用は腕A(mode=session)のみ(2026-09-02 設計メモ確定)。
毎朝の手作業(腕B/mode=local運用)は不採用。mode=local はここでは「検証用の
フォルダ読み取り」に限定して残す(--dry-run や単体テストのため)。

自動DLが失敗しても「無言の欠測」にしない: DownloadError を投げ、
呼び元(cli.py)が売上ゼロ日の通常レポートとは別文面の【取得失敗】を送信口へ出す。

★二層方式(セッション保持のみ・資格情報はどこにも保存しない):
- 日常運転(SessionDownloader): 保存済みセッション(Chromeの永続プロファイル)で
  `launch_persistent_context(session_dir, channel=browser_channel, headless=True)` により
  (a) export_url_template を直叩き(第1層)。
  (b) 直叩きが失敗/未設定なら、同セッションで report_page_url を開き
      csv_export_selector をクリックしてDL(第2層フォールバック)。
  セッション失効(401/403 or ログイン画面遷移)は SessionExpired として即座に上げる
  (フォールバックしても同じ結果になるため)。
- 失効時のみ(このモジュールの範囲外): `relogin.py` を人が一度手で実行し、
  可視ブラウザでログインし直してセッションを保存する。
"""
from __future__ import annotations

import glob
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any


class DownloadError(RuntimeError):
    """CSV取得(ログイン/画面遷移/DL)に失敗した。売上ゼロと混同させないための専用例外。"""


class SessionExpired(DownloadError):
    """保存済みセッションが失効している(401/403 またはログイン画面への遷移で検知)。

    再ログイン以外に打つ手が無いため、直叩き→クリックのフォールバックは行わず
    即座にこの例外を上げる(notify.classify が最優先で SESSION_EXPIRED に分類する)。
    """


class Downloader(ABC):
    @abstractmethod
    def fetch(self, dest_dir: Path, date: str) -> Path:
        """dest_dir にCSVを用意し、そのパスを返す。取れなければ DownloadError。"""


class LocalFolderDownloader(Downloader):
    """dest_dir 直下の csv_glob 最新ファイルをそのまま使う(取得方式=local)。

    ★腕B(監視フォルダ・毎朝手作業)は不採用。これは腕Bの実装ではなく、
    --dry-run・単体テスト・移行検証のためだけに残す薄いラッパ。
    """

    def __init__(self, csv_glob: str = "*.csv"):
        self.csv_glob = csv_glob

    def fetch(self, dest_dir: Path, date: str) -> Path:
        matches = sorted(glob.glob(str(Path(dest_dir) / self.csv_glob)))
        if not matches:
            raise DownloadError(f"フォルダにCSVが見つかりません: {dest_dir}")
        return Path(matches[-1])  # 最新(名前順末尾)を使う


class SessionDownloader(Downloader):
    """保存済みセッション(Chromeの永続プロファイル)でDMMアフィ管理画面からCSVを取得する。
    設計メモ「腕A」の心臓(config.ini [download] mode = session)。

    ★実配線未完了: `export_url_template` / `report_page_url` / `csv_export_selector` は
    CSVエクスポートの実URL・ボタンをDevToolsで1回キャプチャしないと分からない。
    ここでは絶対に当て推量で埋めない。どちらの方式も未設定のうちは DownloadError で
    明確に止まる(黙って偽の成功を返さない)。値は🐧さんまたは発注元が実物の管理画面を
    見て config.ini に埋める想定。

    ★資格情報はここにもconfig.iniにも持たない。セッションは session_dir の永続
    プロファイルにのみ存在する。失効時は `relogin.py` を1回手で実行する(このクラス自身は
    401/403/loginリダイレクトでの失効検知のみを行い、再ログイン操作はしない)。

    ★未検証(要🐧さん資格): 実サイトに対する動作確認はここでは行っていない。
    `_fetch_direct` / `_fetch_via_click` はテストではフェイクの context/page を注入して
    分岐ロジックのみをオフラインで検証している。
    """

    def __init__(
        self,
        session_dir: str,
        affiliate_id: str = "",
        report_page_url: str = "",
        export_url_template: str = "",
        csv_export_selector: str = "",
        browser_channel: str = "chrome",
        timeout_ms: int = 30000,
    ):
        self.session_dir = session_dir
        self.affiliate_id = affiliate_id
        self.report_page_url = report_page_url
        self.export_url_template = export_url_template
        self.csv_export_selector = csv_export_selector
        self.browser_channel = (browser_channel or "chrome").strip().lower()
        self.timeout_ms = timeout_ms

    # ------------------------------------------------------------------ #
    # 公開API
    # ------------------------------------------------------------------ #
    def fetch(self, dest_dir: Path, date: str) -> Path:
        if not self.export_url_template and not (self.report_page_url and self.csv_export_selector):
            raise DownloadError(
                "取得方式の実配線が未完了です(export_url_template も "
                "report_page_url + csv_export_selector も未設定)。"
                "DMMアフィ管理画面の実物をDevToolsで1回キャプチャしないとURLは分からないため、"
                "当て推量では埋めていません。"
            )

        try:
            from playwright.sync_api import sync_playwright
        except ImportError as e:
            raise DownloadError(
                "playwright が未インストールです。"
                "`pip install playwright` の後 `playwright install` を実行してください"
                "(mode=session は既定でご自身の Chrome/Edge を使うため、"
                "ブラウザ本体の追加インストールは基本不要です)。"
            ) from e

        dest_dir = Path(dest_dir)
        dest_dir.mkdir(parents=True, exist_ok=True)

        try:
            with sync_playwright() as p:
                context = p.chromium.launch_persistent_context(
                    self.session_dir, channel=self.browser_channel, headless=True
                )
                try:
                    body = self._fetch_body(context, date)
                finally:
                    context.close()
        except DownloadError:
            raise
        except Exception as e:  # 画面変更/タイムアウト等、原因を問わず取得失敗として扱う
            raise DownloadError(f"自動DLに失敗しました: {e}") from e

        dest = dest_dir / f"{date}_report.csv"
        dest.write_bytes(body)
        return dest

    # ------------------------------------------------------------------ #
    # フォールバック選択ロジック本体(テストではフェイク context を注入して検証する)
    # ------------------------------------------------------------------ #
    def _fetch_body(self, context: Any, date: str) -> bytes:
        """(a) export_url直叩き→成功ならそれを使う。
        (b) 直叩きが失敗/未設定なら、同セッションで report_page_url を開き
            csv_export_selector をクリックしてDL(第2層フォールバック)。
        セッション失効は即座に上げる(フォールバックしても失効は解消しないため)。
        """
        direct_error: DownloadError | None = None
        if self.export_url_template:
            try:
                return self._fetch_direct(context, date)
            except SessionExpired:
                raise
            except DownloadError as e:
                direct_error = e  # 構造変化等 → クリック方式へフォールバック

        if self.report_page_url and self.csv_export_selector:
            return self._fetch_via_click(context)

        if direct_error is not None:
            raise direct_error
        raise DownloadError("直叩き/クリックのどちらの取得方式も設定されていません")

    def _fetch_direct(self, context: Any, date: str) -> bytes:
        """第1層: context.request でエクスポートURLを直叩きする。"""
        url = self.export_url_template.format(date=date, affiliate_id=self.affiliate_id)
        try:
            response = context.request.get(url, timeout=self.timeout_ms)
        except Exception as e:
            raise DownloadError(f"直叩きに失敗しました: {e}") from e
        if response.status in (401, 403) or "login" in (response.url or "").lower():
            raise SessionExpired(
                "セッション失効(要再ログイン。relogin を実行してください)"
            )
        if response.status != 200:
            raise DownloadError(f"エクスポート応答が異常: HTTP {response.status}")
        return response.body()

    def _fetch_via_click(self, context: Any) -> bytes:
        """第2層フォールバック: レポート画面を開き、エクスポートボタンをクリックしてDLする。"""
        page = context.new_page() if not context.pages else context.pages[0]
        try:
            response = page.goto(
                self.report_page_url, wait_until="domcontentloaded", timeout=self.timeout_ms
            )
        except Exception as e:
            raise DownloadError(f"レポート画面を開けませんでした: {e}") from e

        final_url = getattr(page, "url", "") or ""
        status = getattr(response, "status", None) if response is not None else None
        if status in (401, 403) or "login" in final_url.lower():
            raise SessionExpired(
                "セッション失効(要再ログイン。relogin を実行してください)"
            )

        try:
            with page.expect_download(timeout=self.timeout_ms) as dl_info:
                page.click(self.csv_export_selector)
            download = dl_info.value
            tmp_path = download.path()
            if not tmp_path:
                raise DownloadError("ダウンロードに失敗しました(一時ファイルが得られません)")
            return Path(tmp_path).read_bytes()
        except DownloadError:
            raise
        except Exception as e:
            raise DownloadError(f"CSVエクスポートのクリック操作に失敗しました: {e}") from e


def build_downloader(config: dict) -> Downloader:
    mode = (config.get("download_mode") or "local").strip().lower()
    if mode == "local":
        return LocalFolderDownloader(csv_glob=config.get("csv_glob", "*.csv"))
    if mode in ("session", "playwright"):  # "playwright" は旧設定値の後方互換
        return SessionDownloader(
            session_dir=config.get("session_dir", "sessions"),
            affiliate_id=config.get("affiliate_id", ""),
            report_page_url=config.get("report_page_url", ""),
            export_url_template=config.get("export_url_template", ""),
            csv_export_selector=config.get("csv_export_selector", ""),
            browser_channel=config.get("browser_channel", "chrome"),
        )
    raise DownloadError(f"未対応の取得方式: {mode!r}(対応=local/session)")
