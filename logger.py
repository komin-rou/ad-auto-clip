"""Logging configuration without import-time filesystem writes."""
from __future__ import annotations

import logging
import sys
from datetime import datetime
from pathlib import Path


LOG_FORMAT = "%(asctime)s [%(levelname)s] %(message)s"
DATE_FORMAT = "%Y-%m-%d %H:%M:%S"

logger = logging.getLogger("ad_auto")
logger.setLevel(logging.DEBUG)
logger.propagate = False
logger.addHandler(logging.NullHandler())


def configure_logging(base_dir: str) -> Path:
    """Create console/file handlers after application bootstrap."""
    log_dir = Path(base_dir) / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    log_path = log_dir / f"run_{datetime.now().strftime('%Y%m%d_%H%M%S_%f')}.log"

    logger.handlers.clear()
    formatter = logging.Formatter(LOG_FORMAT, DATE_FORMAT)

    console = logging.StreamHandler(sys.stdout)
    console.setLevel(logging.INFO)
    console.setFormatter(formatter)
    logger.addHandler(console)

    file_handler = logging.FileHandler(log_path, encoding="utf-8")
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)
    return log_path


def get_logger():
    return logger


def info(msg: str):
    logger.info(msg)


def debug(msg: str):
    logger.debug(msg)


def warning(msg: str):
    logger.warning(msg)


def error(msg: str):
    logger.error(msg)
