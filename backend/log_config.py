"""Single-source log configuration.

Why: stack traces and audit events come from a dozen modules
(routers, llm_audit, ledger_helpers, …). Each call site does its own
`logging.getLogger(__name__)` but no one configures handlers, so output
behaviour comes from uvicorn's defaults — different format in dev vs
production, no consistent timestamp, no easy grep.

This module installs:
- one StreamHandler on the root logger
- a structured single-line format that survives `tail -F`
- explicit levels for noisy upstream loggers (httpx, sqlalchemy)

Call `configure_logging()` once at startup (main.py does this). Safe to
call multiple times — the same handler isn't installed twice.
"""
from __future__ import annotations

import logging
import os
import sys

_FORMAT = (
    "%(asctime)s.%(msecs)03d "
    "[%(levelname).1s] "
    "%(name)s "
    "%(message)s"
)
_DATEFMT = "%Y-%m-%dT%H:%M:%S"


_INSTALLED = False


def configure_logging(level: str | int | None = None) -> None:
    """Install the project-wide log format on the root logger.

    `level` defaults to LOG_LEVEL env var, falling back to INFO. Repeat
    calls reuse the existing handler so reloads in --reload mode don't
    duplicate log lines.
    """
    global _INSTALLED
    root = logging.getLogger()
    desired_level = level if level is not None else os.getenv("LOG_LEVEL", "INFO")
    if isinstance(desired_level, str):
        desired_level = getattr(logging, desired_level.upper(), logging.INFO)
    root.setLevel(desired_level)

    if _INSTALLED:
        return

    handler = logging.StreamHandler(stream=sys.stdout)
    handler.setFormatter(logging.Formatter(fmt=_FORMAT, datefmt=_DATEFMT))
    handler.set_name("reactv3_root")
    # Skip if uvicorn / pytest already added a handler with the same name.
    if not any(h.get_name() == "reactv3_root" for h in root.handlers):
        root.addHandler(handler)

    # Tame chatty third-party loggers without losing their warnings.
    for noisy in ("httpx", "httpcore", "sqlalchemy.engine"):
        logging.getLogger(noisy).setLevel(logging.WARNING)

    _INSTALLED = True
