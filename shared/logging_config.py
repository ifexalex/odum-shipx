"""Structured JSON logging configuration.

Every log line is emitted as a single-line JSON object so it can be queried
with CloudWatch Logs Insights (e.g. ``filter tenant_id = "..." | sort @timestamp``).

Trace correlation is handled with request-scoped :mod:`contextvars`: a handler
calls :func:`bind_log_context` once per invocation and every subsequent log line
— across the handler, service and repository layers — automatically carries
``request_id``, ``tenant_id`` and ``user_id`` without each call site repeating
``extra={...}``. An explicit ``extra=`` on an individual call still wins over the
bound context for that line.

See 00_CROSS_CUTTING_STANDARDS.md §3 for the logging standard.
"""

import json
import logging
import os
from contextvars import ContextVar
from datetime import UTC, datetime
from typing import Any

# ---------------------------------------------------------------------------
# Request-scoped trace context
# ---------------------------------------------------------------------------
# Lambda reuses execution environments across invocations, so these are always
# reset in a handler's ``finally`` (via clear_log_context) to prevent one
# request's identifiers leaking into the logs of the next.
_request_id: ContextVar[str | None] = ContextVar("request_id", default=None)
_tenant_id: ContextVar[str | None] = ContextVar("tenant_id", default=None)
_user_id: ContextVar[str | None] = ContextVar("user_id", default=None)

# Standard LogRecord attributes — anything on a record that is NOT one of these
# (and not already surfaced as a top-level field) is a caller-supplied ``extra``
# and is passed through to the JSON output so it stays queryable.
_RESERVED_ATTRS = frozenset(
    {
        "args",
        "asctime",
        "created",
        "exc_info",
        "exc_text",
        "filename",
        "funcName",
        "levelname",
        "levelno",
        "lineno",
        "message",
        "module",
        "msecs",
        "msg",
        "name",
        "pathname",
        "process",
        "processName",
        "relativeCreated",
        "stack_info",
        "taskName",
        "thread",
        "threadName",
        # Surfaced explicitly below — not repeated in the passthrough block.
        "request_id",
        "tenant_id",
        "user_id",
    }
)


def diagnostics_enabled() -> bool:
    """Whether verbose diagnostic logging may run in this environment.

    Dev only. Debug logging around auth — token/claim shapes especially — must
    never run in staging or production: even claim *names* are more detail than
    those logs should retain, and anything written there outlives the debugging
    session. Genuine error logs are not gated by this; only verbose diagnostics.
    """
    return os.environ.get("ENVIRONMENT", "").strip().lower() in {"dev", "local"}


def bind_log_context(
    *,
    request_id: str | None = None,
    tenant_id: str | None = None,
    user_id: str | None = None,
) -> None:
    """Bind trace identifiers for the current execution context.

    Call once at the start of a Lambda invocation. Only non-None arguments are
    applied, so later calls (e.g. binding ``tenant_id``/``user_id`` after the
    tenant context resolves) refine the context without clearing the rest.

    Args:
        request_id: API Gateway request id (or a generated uuid) for this call.
        tenant_id: Tenant the request is scoped to, once known.
        user_id: Authenticated Cognito ``sub``, once known.
    """
    if request_id is not None:
        _request_id.set(request_id)
    if tenant_id is not None:
        _tenant_id.set(tenant_id)
    if user_id is not None:
        _user_id.set(user_id)


def clear_log_context() -> None:
    """Reset all bound trace identifiers.

    Must run in the ``finally`` of every handler so a reused Lambda execution
    environment does not leak identifiers into the next invocation's logs.
    """
    _request_id.set(None)
    _tenant_id.set(None)
    _user_id.set(None)


class ContextFilter(logging.Filter):
    """Inject the request-scoped trace context onto every log record.

    An explicit ``extra=`` on the log call takes precedence: the filter only
    fills a field the caller did not already set for that record.
    """

    def filter(self, record: logging.LogRecord) -> bool:
        if getattr(record, "request_id", None) is None:
            record.request_id = _request_id.get()
        if getattr(record, "tenant_id", None) is None:
            record.tenant_id = _tenant_id.get()
        if getattr(record, "user_id", None) is None:
            record.user_id = _user_id.get()
        return True


class StructuredFormatter(logging.Formatter):
    """Emit logs as single-line JSON for CloudWatch Insights queries."""

    def format(self, record: logging.LogRecord) -> str:
        log_entry: dict[str, Any] = {
            "timestamp": datetime.now(UTC).isoformat(),
            "level": record.levelname,
            "service": os.environ.get("SERVICE_NAME", "unknown"),
            "environment": os.environ.get("ENVIRONMENT", "unknown"),
            "request_id": getattr(record, "request_id", None),
            "tenant_id": getattr(record, "tenant_id", None),
            "user_id": getattr(record, "user_id", None),
            "message": record.getMessage(),
            "logger": record.name,
        }

        # Pass through any caller-supplied ``extra`` fields (e.g. duration_ms,
        # event_type) so they remain top-level and queryable rather than being
        # dropped. Reserved/standard attributes are skipped.
        for key, value in record.__dict__.items():
            if key not in _RESERVED_ATTRS and key not in log_entry:
                log_entry[key] = value

        if record.exc_info:
            log_entry["exception"] = self.formatException(record.exc_info)
        return json.dumps(log_entry, default=str)


def setup_logging() -> logging.Logger:
    """Configure the root logger with structured JSON output.

    Idempotent: safe to call on every Lambda cold start. Installs the
    :class:`StructuredFormatter` and the :class:`ContextFilter` so every record
    carries the bound trace context.
    """
    logger = logging.getLogger()
    logger.setLevel(os.environ.get("LOG_LEVEL", "INFO"))

    # Remove default Lambda handler if present
    for handler in logger.handlers[:]:
        logger.removeHandler(handler)

    handler = logging.StreamHandler()
    handler.setFormatter(StructuredFormatter())
    handler.addFilter(ContextFilter())
    logger.addHandler(handler)
    return logger
