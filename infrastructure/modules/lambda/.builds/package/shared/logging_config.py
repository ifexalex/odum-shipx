"""Structured JSON logging configuration.

See 00_CROSS_CUTTING_STANDARDS.md §3 for the logging standard.
"""
import json
import logging
import os
from datetime import datetime, timezone


class StructuredFormatter(logging.Formatter):
    """Emit logs as single-line JSON for CloudWatch Insights queries."""

    def format(self, record: logging.LogRecord) -> str:
        log_entry = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "service": os.environ.get("SERVICE_NAME", "unknown"),
            "environment": os.environ.get("ENVIRONMENT", "unknown"),
            "request_id": getattr(record, "request_id", None),
            "tenant_id": getattr(record, "tenant_id", None),
            "message": record.getMessage(),
            "logger": record.name,
        }
        if record.exc_info:
            log_entry["exception"] = self.formatException(record.exc_info)
        return json.dumps(log_entry, default=str)


def setup_logging() -> logging.Logger:
    """Configure the root logger with structured JSON output."""
    logger = logging.getLogger()
    logger.setLevel(os.environ.get("LOG_LEVEL", "INFO"))

    # Remove default Lambda handler if present
    for handler in logger.handlers[:]:
        logger.removeHandler(handler)

    handler = logging.StreamHandler()
    handler.setFormatter(StructuredFormatter())
    logger.addHandler(handler)
    return logger
