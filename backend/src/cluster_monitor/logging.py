"""Application logging helpers.

Uvicorn configures ``uvicorn.error`` with a visible handler at INFO level. Using
its child namespace keeps application and transport metadata visible without
installing global logging handlers when the package is imported elsewhere.
"""

from __future__ import annotations

import logging

_APPLICATION_LOGGER = "uvicorn.error.cluster_monitor"


def get_logger(component: str) -> logging.Logger:
    """Return a logger that is visible with Uvicorn's default configuration."""

    return logging.getLogger(f"{_APPLICATION_LOGGER}.{component}")
