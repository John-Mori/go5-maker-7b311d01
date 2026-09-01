"""設定の読み込み。★資格情報は同梱せず、利用者が config.ini に入れる。"""
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
        # [state]
        "state_path": get("state", "path", "state/daily_summary.json"),
        # [log]
        "log_path": get("log", "path", "logs/fanza_affi_report.log"),
        # [download] 取得方式。裁定#1=本番は playwright(完全自動)。
        # ★username/password はここにしか置かない(ソース非埋め込み、🐧さんのPCの中だけ)。
        "download_mode": get("download", "mode", "local"),
        "dmm_username": get("download", "username", ""),
        "dmm_password": get("download", "password", ""),
        "download": {
            "login_url": get("download", "login_url", ""),
            "username_selector": get("download", "username_selector", ""),
            "password_selector": get("download", "password_selector", ""),
            "login_submit_selector": get("download", "login_submit_selector", ""),
            "report_url": get("download", "report_url", ""),
            "csv_export_selector": get("download", "csv_export_selector", ""),
        },
    }
