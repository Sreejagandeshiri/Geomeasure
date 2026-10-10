"""
Structured JSON logging configuration for GeoMeasure.
All log output goes to stdout so it can be captured by process supervisors
and container log drivers without any extra configuration.
"""

import logging
import sys
from app.core.config import settings


def configure_logging() -> None:
    """Configure root logger with a human-readable format suitable for development.

    In a production deployment you might swap the formatter for a JSON formatter
    (e.g. python-json-logger) and add a file handler, but stdout is the right
    default for a containerised service.
    """
    log_level = getattr(logging, settings.LOG_LEVEL.upper(), logging.INFO)

    formatter = logging.Formatter(
        fmt="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
        datefmt="%Y-%m-%dT%H:%M:%S",
    )

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(formatter)

    root_logger = logging.getLogger()
    root_logger.setLevel(log_level)
    # Remove any handlers that may have been added before our configuration.
    root_logger.handlers.clear()
    root_logger.addHandler(handler)

    # Quieten noisy third-party libraries.
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)
    logging.getLogger("fiona").setLevel(logging.WARNING)
    logging.getLogger("shapely").setLevel(logging.WARNING)
