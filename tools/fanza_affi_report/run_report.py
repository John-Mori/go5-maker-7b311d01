#!/usr/bin/env python3
"""起動スクリプト。タスクスケジューラ/cron からはこれを叩く。

例:
    python run_report.py --dry-run --csv sample.csv
    python run_report.py            # config.ini の設定で送信
"""
from fanza_affi_report.cli import main

if __name__ == "__main__":
    main()
