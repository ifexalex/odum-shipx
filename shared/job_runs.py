"""Record every scheduled-job run in ``job_run`` (platform audit Phase 1c, decision D7).

Each scheduled handler is wrapped with :func:`tracked_job`. A run row is opened as ``running``, then closed as
``succeeded`` or ``failed`` with its duration, the handler's result counts and, on failure, the exception's class name.
The Operations area (Phase 3) reads these rows to show each job's last run, duration and failures.

Counts come from the dict the handler returns: integer values whose key names an error or failure (``errors``,
``failed``) are the run's failures; the other integers are its items. Only counts are stored, never record contents,
and the error summary is the exception class, not its message, which can carry customer details.

Recording is best effort: a database problem while writing the row is logged and never changes what the job does.
"""

import functools
import logging
from collections.abc import Callable
from typing import Any, TypeVar

from shared.logging_config import current_request_id

logger = logging.getLogger(__name__)

_F = TypeVar("_F", bound=Callable[..., Any])
_FAILURE_WORDS = ("error", "fail", "refused")


def count_result(result: Any) -> tuple[int, int]:
    """Split a handler's result dict into ``(items_processed, failures)``."""
    if not isinstance(result, dict):
        return 0, 0
    items = failures = 0
    for key, value in result.items():
        if isinstance(value, bool) or not isinstance(value, int):
            continue
        if any(word in key.lower() for word in _FAILURE_WORDS):
            failures += value
        else:
            items += value
    return items, failures


def _start(job: str, trigger: str) -> str | None:
    from shared.db import execute_write_with_tenant
    from shared.tenant_context import PLATFORM_TENANT_ID

    try:
        row = execute_write_with_tenant(
            PLATFORM_TENANT_ID,
            "INSERT INTO job_run (job, trigger, request_id) VALUES (%(job)s, %(trigger)s, %(request_id)s) RETURNING id",
            {"job": job, "trigger": trigger, "request_id": current_request_id()},
        )
        return str(row["id"]) if row else None
    except Exception as exc:
        logger.warning("Could not open a job_run row for %s: %s", job, type(exc).__name__)
        return None


def _finish(run_id: str | None, status: str, result: Any, error: BaseException | None) -> None:
    if run_id is None:
        return
    import json

    from shared.db import execute_write_with_tenant
    from shared.tenant_context import PLATFORM_TENANT_ID

    items, failures = count_result(result)
    if error is not None:
        failures = max(failures, 1)
    try:
        execute_write_with_tenant(
            PLATFORM_TENANT_ID,
            """
            UPDATE job_run
            SET finished_at = NOW(), status = %(status)s, items_processed = %(items)s, failures = %(failures)s,
                result = %(result)s::jsonb, error_summary = %(error)s
            WHERE id = %(id)s
            RETURNING id
            """,
            {
                "id": run_id,
                "status": status,
                "items": items,
                "failures": failures,
                "result": json.dumps(result, default=str) if isinstance(result, dict) else None,
                "error": type(error).__name__ if error is not None else None,
            },
        )
    except Exception as exc:
        logger.warning("Could not close job_run %s: %s", run_id, type(exc).__name__)


def tracked_job(job: str) -> Callable[[_F], _F]:
    """Decorate a scheduled ``lambda_handler(event, context)`` so each run is recorded under ``job``.

    An event with ``"trigger": "manual"`` (a re-run asked for from the console, Phase 3) is recorded as such.
    """

    def decorator(handler: _F) -> _F:
        @functools.wraps(handler)
        def wrapper(event: Any, context: Any) -> Any:
            trigger = "manual" if isinstance(event, dict) and event.get("trigger") == "manual" else "schedule"
            run_id = _start(job, trigger)
            try:
                result = handler(event, context)
            except BaseException as exc:
                _finish(run_id, "failed", None, exc)
                raise
            _finish(run_id, "succeeded", result, None)
            return result

        return wrapper  # type: ignore[return-value]

    return decorator
