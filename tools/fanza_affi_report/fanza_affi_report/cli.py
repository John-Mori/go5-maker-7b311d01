"""エントリポイント。parse → aggregate → 前日比 → 整形 → 送信。

失敗は握り潰さない: 例外はローカルログへ残し、可能なら送信口へ
「レポート生成に失敗」を出してから非0で終了する(黙って止まらない)。
"""
from __future__ import annotations

import argparse
import datetime as dt
import sys
import traceback
from pathlib import Path

from . import __version__
from .aggregate import summarize
from .config import ConfigError, load_config
from .downloader import DownloadError, build_downloader
from .logging_setup import setup_logging
from .notify import classify, remediation_hint
from .parser import ReportFormatError, load_report_csv
from .report import format_report
from .senders import SendError, StdoutSender, build_sender
from .state import StateStore


def _obtain_csv(args, config: dict, date: str, logger) -> Path:
    """CSVを用意する。--csv指定があればそれを使う(手動検証用)。
    無ければ取得方式(config [download] mode)に従って取得する
    (裁定#1=本番は自動DL。手動フォルダ配置には逃げない)。
    """
    if args.csv:
        return Path(args.csv)
    if not config.get("csv_dir", ""):
        raise ConfigError("CSVの置き場所が指定されていません(--csv か config [input] csv_dir)")
    downloader = build_downloader(config)
    logger.info("CSV取得方式=%s", config.get("download_mode", "local"))
    return downloader.fetch(Path(config["csv_dir"]), date)


def build_argparser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(
        prog="fanza_affi_report",
        description="FANZA/DMMアフィ売上レポートの日次集計と送信",
    )
    ap.add_argument("--config", default="config.ini", help="設定ファイル(既定 config.ini)")
    ap.add_argument("--csv", default="", help="対象CSV(省略時は config の csv_dir から最新)")
    ap.add_argument(
        "--date", default="",
        help="レポート日付 YYYY-MM-DD(既定=config [schedule] period。既定値はyesterday)",
    )
    ap.add_argument("--clicks", type=int, default=None, help="クリック数(別ソースがあれば)")
    ap.add_argument("--dry-run", action="store_true", help="送信せず標準出力へ整形結果")
    ap.add_argument(
        "--force", action="store_true",
        help="同日冪等性チェックを無視して再送する(タスク二重起動対策の手動解除用)",
    )
    ap.add_argument("--verbose", action="store_true")
    ap.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    return ap


def _resolve_date(args, config: dict) -> str:
    """--date優先。無ければ config [schedule] period から決める(既定=yesterday)。"""
    if args.date:
        return args.date
    period = (config.get("schedule_period") or "yesterday").strip().lower()
    today = dt.date.today()
    if period == "today":
        return today.isoformat()
    if period == "yesterday":
        return (today - dt.timedelta(days=1)).isoformat()
    # 未知の値は既定(yesterday)にフォールバックしつつ黙らせない
    return (today - dt.timedelta(days=1)).isoformat()


def run(argv: list[str] | None = None) -> int:
    args = build_argparser().parse_args(argv)

    # 設定・ログの初期化。ここで失敗したら送信口も無いので stderr だけ。
    try:
        config = load_config(args.config)
    except ConfigError as e:
        print(f"[設定エラー] {e}", file=sys.stderr)
        return 2

    date = _resolve_date(args, config)
    logger = setup_logging(config["log_path"], verbose=args.verbose)
    logger.info("開始 v%s date=%s dry_run=%s", __version__, date, args.dry_run)

    try:
        return _run_body(args, config, date, logger)
    finally:
        # ファイルハンドラを閉じてログファイルのロックを解放する
        # (Windowsで開いたままだと呼び出し側の後片付けが PermissionError になる)。
        for h in list(logger.handlers):
            try:
                h.close()
            finally:
                logger.removeHandler(h)


def _run_body(args, config: dict, date: str, logger) -> int:
    try:
        store = StateStore(config["state_path"])

        # 同日冪等性: タスクスケジューラの二重起動/手動再実行で同じ日を二重送信しない。
        # --dry-run と --force は常にスキップしない(検証・手動解除のため)。
        if not args.dry_run and not args.force and store.already_reported(date):
            logger.info("スキップ: %s は既に送信済み(--force で強制再送可)", date)
            print(f"[スキップ] {date} は既に送信済みです(--force で再送できます)")
            return 0

        csv_path = _obtain_csv(args, config, date, logger)
        logger.info("CSV=%s", csv_path)
        rows = load_report_csv(csv_path, encoding=config["encoding"])
        summary = summarize(rows, date=date, clicks=args.clicks)

        delta = store.delta_against_previous(summary)
        body = format_report(
            summary, delta, title=config["title"],
            last_success_date=store.last_success_date(),
        )
        sender = build_sender(config, dry_run=args.dry_run)
        sender.send(f"{config['title']} {date}", body, attachment_path=csv_path)

        # 送信できてから状態を記録(送れなかった日を「前日」にしない)
        if not args.dry_run:
            store.record(summary)
        logger.info(
            "完了 報酬合計=%s円 件数=%s 明細=%s行",
            summary.total_amount, summary.total_count, summary.n_rows,
        )
        return 0

    except DownloadError as e:
        # 裁定#1(完全自動化)の代償: 取得失敗を黙らせない。売上ゼロ日の通常レポートとは
        # 別文面で送り、受け取った側が本文だけで「取得できなかった日」と分かるようにする。
        logger.error("取得失敗: %s", e)
        _notify_download_failure(config, args, date, e, logger)
        return 1
    except (ReportFormatError, ConfigError, SendError) as e:
        logger.error("失敗: %s", e)
        _notify_failure(config, args, date, e, logger)
        return 1
    except Exception as e:  # 想定外も黙らせない
        logger.error("想定外の失敗: %s\n%s", e, traceback.format_exc())
        _notify_failure(config, args, date, e, logger, prefix="想定外: ")
        return 1


def _notify_failure(config: dict, args, date: str, exc: Exception, logger, prefix: str = "") -> None:
    """失敗を送信口へも出す(ログだけに埋もれさせない)。分類を付け、受け手が
    「何をすれば閉じるか」を本文だけで判断できるようにする。
    """
    try:
        sender = build_sender(config, dry_run=args.dry_run)
    except Exception:
        sender = StdoutSender()
    kind = classify(exc)
    msg = (
        f"【失敗】{config.get('title','レポート')} の生成に失敗しました({date})\n"
        f"分類: {kind.value}\n"
        f"理由: {prefix}{exc}\n"
        f"{remediation_hint(kind)}"
    )
    try:
        sender.send(f"[失敗] {config.get('title','レポート')} {date}", msg)
    except Exception as e:
        logger.error("失敗通知の送信も失敗: %s", e)


def _notify_download_failure(config: dict, args, date: str, exc: Exception, logger) -> None:
    """自動DL失敗を送信口へ出す。売上ゼロ日の通常レポート(報酬合計 0円)とは
    件名・本文とも明確に分け、金額の記載自体を出さない(誤読=ゼロ円確定と混同させない)。
    """
    try:
        sender = build_sender(config, dry_run=args.dry_run)
    except Exception:
        sender = StdoutSender()
    kind = classify(exc)
    msg = (
        f"【取得失敗】{config.get('title','レポート')} のCSVを自動取得できませんでした({date})\n"
        f"※これは売上ゼロではありません。取得エラーのため金額は不明です。\n"
        f"分類: {kind.value}\n"
        f"理由: {exc}\n"
        f"{remediation_hint(kind)}"
    )
    try:
        sender.send(f"[取得失敗] {config.get('title','レポート')} {date}", msg)
    except Exception as e:
        logger.error("取得失敗通知の送信も失敗: %s", e)


def main() -> None:
    raise SystemExit(run())


if __name__ == "__main__":
    main()
