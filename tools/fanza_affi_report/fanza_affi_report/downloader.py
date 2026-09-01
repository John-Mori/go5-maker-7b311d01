"""CSV取得口の抽象。裁定#1確定=完全自動化(ブラウザでDMMアフィ管理画面からCSVを自動DL)。
手動フォルダ配置への逃げ(半自動案)は不可、との裁定を受けての境界。

自動DLが失敗しても「無言の欠測」にしない: DownloadError を投げ、
呼び元(cli.py)が売上ゼロ日の通常レポートとは別文面の【取得失敗】を送信口へ出す。
"""
from __future__ import annotations

import glob
from abc import ABC, abstractmethod
from pathlib import Path


class DownloadError(RuntimeError):
    """CSV取得(ログイン/画面遷移/DL)に失敗した。売上ゼロと混同させないための専用例外。"""


class Downloader(ABC):
    @abstractmethod
    def fetch(self, dest_dir: Path, date: str) -> Path:
        """dest_dir にCSVを用意し、そのパスを返す。取れなければ DownloadError。"""


class LocalFolderDownloader(Downloader):
    """dest_dir 直下の csv_glob 最新ファイルをそのまま使う(取得方式=local)。

    ブラウザ自動化(裁定#1の本番方式)に切り替わるまでの検証用、および
    --dry-run での動作確認用に残す。本番運用は PlaywrightDMMDownloader を使う。
    """

    def __init__(self, csv_glob: str = "*.csv"):
        self.csv_glob = csv_glob

    def fetch(self, dest_dir: Path, date: str) -> Path:
        matches = sorted(glob.glob(str(Path(dest_dir) / self.csv_glob)))
        if not matches:
            raise DownloadError(f"フォルダにCSVが見つかりません: {dest_dir}")
        return Path(matches[-1])  # 最新(名前順末尾)を使う


class PlaywrightDMMDownloader(Downloader):
    """DMMアフィ管理画面へログインしCSVを自動DLする(裁定#1=確定方式)。

    ★実装未完了: ログインURL・フォーム項目のセレクタ・CSVエクスポート導線は
    実物の管理画面(ログイン画面/レポート画面のURLとDOM)を見ないと分からない。
    ここでは絶対に当て推量で埋めない。config [download] の各セレクタが
    揃っていない限り DownloadError で明確に止まる(黙って偽の成功を返さない)。
    値は 🐧さん または発注元(イージス研究室GL)が実物の管理画面を見て
    config.ini に入れる想定。
    """

    REQUIRED_KEYS = (
        "login_url",
        "username_selector",
        "password_selector",
        "login_submit_selector",
        "report_url",
        "csv_export_selector",
    )

    def __init__(self, dl_config: dict, username: str, password: str, timeout_ms: int = 30000):
        self.dl_config = dl_config
        self.username = username
        self.password = password
        self.timeout_ms = timeout_ms

    def fetch(self, dest_dir: Path, date: str) -> Path:
        missing = [k for k in self.REQUIRED_KEYS if not self.dl_config.get(k)]
        if missing:
            raise DownloadError(
                "ブラウザ自動化の設定が未完了です(config.ini [download] に "
                f"{', '.join(missing)} が必要)。DMMアフィ管理画面の実物"
                "(ログイン画面/レポート画面)を見ないとセレクタは分からないため、"
                "当て推量では埋めていません。"
            )
        if not self.username or not self.password:
            raise DownloadError(
                "DMMログイン情報が未設定です(config.ini [download] username/password)"
            )

        try:
            from playwright.sync_api import sync_playwright
        except ImportError as e:
            raise DownloadError(
                "playwright が未インストールです。"
                "`pip install playwright` の後 `playwright install chromium` を実行してください。"
            ) from e

        dest_dir = Path(dest_dir)
        dest_dir.mkdir(parents=True, exist_ok=True)
        cfg = self.dl_config
        try:
            with sync_playwright() as p:
                browser = p.chromium.launch(headless=True)
                page = browser.new_page(accept_downloads=True)
                try:
                    page.goto(cfg["login_url"], timeout=self.timeout_ms)
                    page.fill(cfg["username_selector"], self.username)
                    page.fill(cfg["password_selector"], self.password)
                    page.click(cfg["login_submit_selector"])
                    page.wait_for_load_state("networkidle", timeout=self.timeout_ms)

                    report_url = cfg.get("report_url") or ""
                    if report_url and report_url != page.url:
                        page.goto(report_url, timeout=self.timeout_ms)

                    with page.expect_download(timeout=self.timeout_ms) as dl_info:
                        page.click(cfg["csv_export_selector"])
                    download = dl_info.value
                    dest = dest_dir / f"{date}_{download.suggested_filename}"
                    download.save_as(dest)
                    return dest
                finally:
                    browser.close()
        except DownloadError:
            raise
        except Exception as e:  # ログイン失敗/画面変更/タイムアウト等、原因を問わず取得失敗として扱う
            raise DownloadError(f"自動DLに失敗しました: {e}") from e


def build_downloader(config: dict) -> Downloader:
    mode = (config.get("download_mode") or "local").strip().lower()
    if mode == "local":
        return LocalFolderDownloader(csv_glob=config.get("csv_glob", "*.csv"))
    if mode == "playwright":
        return PlaywrightDMMDownloader(
            dl_config=config.get("download", {}),
            username=config.get("dmm_username", ""),
            password=config.get("dmm_password", ""),
        )
    raise DownloadError(f"未対応の取得方式: {mode!r}(対応=local/playwright)")
