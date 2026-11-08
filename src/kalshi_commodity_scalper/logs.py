"""Logging: one console stream plus a small rotating file."""

from __future__ import annotations

import logging
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path

_quiet = False
_configured = False


def setup(path: str | Path, quiet: bool = False) -> None:
    global _quiet, _configured
    _quiet = quiet
    if _configured:
        return
    handler = RotatingFileHandler(
        Path(path), mode="a", maxBytes=2 * 1024 * 1024, backupCount=2
    )
    handler.setFormatter(logging.Formatter("[%(asctime)s] %(message)s", datefmt="%H:%M:%S"))
    logging.basicConfig(
        level=logging.INFO,
        handlers=[logging.StreamHandler(sys.stdout), handler],
        force=True,
    )
    _configured = True


def log(message: str) -> None:
    logging.info(message)


def tick(message: str) -> None:
    if not _quiet:
        logging.info(message)
