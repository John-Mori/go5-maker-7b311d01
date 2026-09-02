"""設定の読み込み。★資格情報は持たない(取得は保存済みセッションの二層方式。[download]参照)。"""
from __future__ import annotations

import configparser
from pathlib import Path


class ConfigError(RuntimeError):
    pass


def load_config(path: str | Path) -> dict:
    p = Path(path)
    if not p.exists():
        raise ConfigError(
            f"設定ファイルが見つかりません: {p}  "
            f"(config.example.ini をコピーして config.ini を作ってください)"
        )
    cp = configparser.ConfigParser()
    cp.read(p, encoding="utf-8")

    def get(section: str, key: str, default: str = "") -> str:
        return cp.get(section, key, fallback=default).strip()

    return {
        # [report]
        "title": get("report", "title", "FANZAアフィ売上レポート"),
        # [input]
        "csv_dir": get("input", "csv_dir", ""),
        "csv_glob": get("input", "csv_glob", "*.csv"),
        "encoding": get("input", "encoding", "cp932"),
        # [output]
        "sender": get("output", "sender", "stdout"),
        "webhook_url": get("output", "webhook_url", ""),
        # [output] sender = mail のときだけ使う雛形(未検証・実資格情報は書かない)
        "smtp_host": get("output", "smtp_host", ""),
        "smtp_port": get("output", "smtp_port", "587"),
        "smtp_user": get("output", "smtp_user", ""),
        "smtp_password": get("output", "smtp_password", ""),
        "mail_from": get("output", "mail_from", ""),
        "mail_to": get("output", "mail_to", ""),
        # [state]
        "state_path": get("state", "path", "state/daily_summary.json"),
        # [log]
        "log_path": get("log", "path", "logs/fanza_affi_report.log"),
        # [schedule] 対象期間。腕A確定=毎朝「昨日分」を送る。
        "schedule_period": get("schedule", "period", "yesterday"),
        # [download] 取得方式。★採用は腕Aのみ=mode=session(保存済みセッションで完全自動)。
        # 腕B(毎朝手作業)は不採用/未実装。mode=local は検証用の「フォルダから拾う」だけ。
        # ★資格情報は持たない(二層方式=保存済みセッションのみで取得する。
        # 失効時は relogin.py を手で1回実行してセッションを保存し直す)。
        "download_mode": get("download", "mode", "local"),
        "session_dir": get("download", "session_dir", "sessions"),
        "affiliate_id": get("download", "affiliate_id", ""),
        "report_page_url": get("download", "report_page_url", ""),
        "export_url_template": get("download", "export_url_template", ""),
        "login_url": get("download", "login_url", ""),
        "csv_export_selector": get("download", "csv_export_selector", ""),
        # browser_channel: chrome / msedge (🐧さんの既存ブラウザに合わせて切替)
        "browser_channel": get("download", "browser_channel", "chrome"),
    }
