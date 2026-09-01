"""ローカルログ。相手のマシンで落ちた時に黙らないための足回り。"""
from __future__ import annotations

import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path


def setup_logging(log_path: str | Path, verbose: bool = False) -> logging.Logger:
    logger = logging.getLogger("fanza_affi_report")
    logger.setLevel(logging.DEBUG if verbose else logging.INFO)
    logger.handlers.clear()

    fmt = logging.Formatter("%(asctime)s %(levelname)s %(message)s")

    p = Path(log_path)
    p.parent.mkdir(parents=True, exist_ok=True)
    fh = RotatingFileHandler(p, maxBytes=1_000_000, backupCount=5, encoding="utf-8")
    fh.setFormatter(fmt)
    logger.addHandler(fh)

    sh = logging.StreamHandler()
    sh.setFormatter(fmt)
    logger.addHandler(sh)
    return logger
