"""Logging helpers for UncommonRhymesV2."""
from __future__ import annotations

import logging
import os


def setup_logging() -> None:
    """Configure root logging from the LOG_LEVEL environment variable."""
    level = os.getenv("LOG_LEVEL", "INFO").upper()
    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )


__all__ = ["setup_logging"]
