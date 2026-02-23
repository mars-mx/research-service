"""JSON structured logging configuration."""

import logging
import sys

from pythonjsonlogger.json import JsonFormatter


def setup_logging(log_level: str = "INFO") -> None:
    """Configure root and uvicorn loggers for JSON output on stdout."""
    level = getattr(logging, log_level.upper(), logging.INFO)

    formatter = JsonFormatter(
        fmt="%(asctime)s %(levelname)s %(name)s %(message)s",
        rename_fields={
            "asctime": "timestamp",
            "levelname": "level",
            "name": "logger",
        },
        datefmt="%Y-%m-%dT%H:%M:%S%z",
    )

    # Configure root logger
    root = logging.getLogger()
    root.setLevel(level)
    root.handlers.clear()

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(formatter)
    root.addHandler(handler)

    # Reconfigure uvicorn loggers to use JSON formatter
    for name in ("uvicorn", "uvicorn.access", "uvicorn.error"):
        uv_logger = logging.getLogger(name)
        uv_logger.handlers.clear()
        uv_logger.addHandler(handler)
        uv_logger.propagate = False
