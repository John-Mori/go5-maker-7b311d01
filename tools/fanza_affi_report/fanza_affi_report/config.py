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
    }
