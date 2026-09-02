"""失敗の分類。無言終了のコードパスを作らないための最後の砦。

cli.py の失敗通知(_notify_failure / _notify_download_failure)へ「何をすれば閉じるか」
が本文だけで分かるよう、分類ラベルと(必要なら)対処ヒントを付ける。
"""
from __future__ import annotations

import enum


class FailureKind(enum.Enum):
    SESSION_EXPIRED = "セッション失効(要再ログイン)"
    STRUCTURE_CHANGED = "構造変化疑い(管理画面が変わった)"
    CSV_INVALID = "CSV異常(取得内容がおかしい)"
    NETWORK = "ネットワーク障害"
    DELIVERY_FAILED = "配送失敗"
    UNKNOWN = "不明なエラー"


def classify(exc: Exception) -> FailureKind:
    """例外から失敗分類を推定する。"""
    from .downloader import DownloadError, SessionExpired
    from .parser import ReportFormatError
    from .senders import SendError

    if isinstance(exc, ReportFormatError):
        text = str(exc)
        if "HTML" in text or "セッション" in text or "ログイン" in text:
            return FailureKind.SESSION_EXPIRED
        if "列" in text or "ヘッダ" in text:
            return FailureKind.STRUCTURE_CHANGED
        return FailureKind.CSV_INVALID
    if isinstance(exc, SessionExpired):
        # 文字列一致より先に型で確定させる(SessionDownloaderが明示的に上げる例外)。
        return FailureKind.SESSION_EXPIRED
    if isinstance(exc, DownloadError):
        text = str(exc)
        if "セッション失効" in text or "ログイン" in text:
            return FailureKind.SESSION_EXPIRED
        if "実配線" in text or "応答が異常" in text:
            return FailureKind.STRUCTURE_CHANGED
        return FailureKind.NETWORK
    if isinstance(exc, SendError):
        return FailureKind.DELIVERY_FAILED
    name = type(exc).__name__
    if "URLError" in name or "Timeout" in name or "Connection" in name:
        return FailureKind.NETWORK
    return FailureKind.UNKNOWN


def remediation_hint(kind: FailureKind) -> str:
    if kind is FailureKind.SESSION_EXPIRED:
        return "→ `python -m fanza_affi_report.relogin --config config.ini` を一度実行してください。"
    if kind is FailureKind.STRUCTURE_CHANGED:
        return "→ DMMアフィ管理画面の構造/URLが変わっていないか確認してください(実配線の見直し要)。"
    if kind is FailureKind.NETWORK:
        return "→ ネットワーク接続を確認し、時間を置いて再実行してください。"
    if kind is FailureKind.DELIVERY_FAILED:
        return "→ 送信口(Webhook URL等)の設定を確認してください。"
    return "→ ログを確認してください。"
