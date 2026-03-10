"""Structured logging setup."""

import logging
import sys
from pathlib import Path


def setup(level="INFO", log_file=None):
    """Configure logging with console (stderr) and optional file output."""
    root = logging.getLogger()
    root.setLevel(level)

    if not root.handlers:
        console = logging.StreamHandler(sys.stderr)
        console.setFormatter(logging.Formatter("[%(name)s] %(message)s"))
        root.addHandler(console)

    if log_file:
        Path(log_file).parent.mkdir(parents=True, exist_ok=True)
        fh = logging.FileHandler(log_file, encoding="utf-8")
        fh.setFormatter(logging.Formatter(
            "%(asctime)s [%(name)s] %(levelname)s %(message)s"
        ))
        root.addHandler(fh)

    for lib in ("boto3", "botocore", "urllib3", "s3transfer"):
        logging.getLogger(lib).setLevel(logging.WARNING)
