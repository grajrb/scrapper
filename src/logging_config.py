"""Central logging setup: console + rotating file, no third-party deps."""
from __future__ import annotations

import logging
import os
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent
LOG_DIR = ROOT_DIR / "data" / "raw" / "logs"

_FORMAT = "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s"
_configured = False


def setup_logging(level: str | None = None, log_dir: Path | None = None) -> logging.Logger:
    """Configure the root ``jobsearch`` logger once and return it.

    ``level`` defaults to the ``JOB_SEARCH_LOG_LEVEL`` environment variable,
    then to INFO.
    """
    global _configured
    root = logging.getLogger("jobsearch")

    if _configured:
        return root

    resolved = (level or os.getenv("JOB_SEARCH_LOG_LEVEL") or "INFO").upper()
    root.setLevel(getattr(logging, resolved, logging.INFO))
    formatter = logging.Formatter(_FORMAT)

    console = logging.StreamHandler(sys.stdout)
    console.setFormatter(formatter)
    root.addHandler(console)

    target = Path(log_dir) if log_dir else LOG_DIR
    try:
        target.mkdir(parents=True, exist_ok=True)
        file_handler = RotatingFileHandler(
            target / "jobsearch.log", maxBytes=2_000_000, backupCount=3,
            encoding="utf-8",
        )
        file_handler.setFormatter(formatter)
        root.addHandler(file_handler)
    except OSError:  # pragma: no cover - log directory not writable
        root.warning("Cannot write log files to %s; console logging only.", target)

    root.propagate = False
    _configured = True
    return root


def get_logger(name: str = "") -> logging.Logger:
    """Get a child logger under the ``jobsearch`` namespace."""
    setup_logging()
    return logging.getLogger(f"jobsearch.{name}" if name else "jobsearch")
