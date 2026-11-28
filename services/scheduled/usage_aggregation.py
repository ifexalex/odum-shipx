"""Usage Aggregation — runs hourly.

Aggregates raw usage_record rows into per-day summaries.

The `record_usage` helper in shared/metering.py inserts one row per event.
This job consolidates them: for each (tenant_id, metric_type, period_start)
group it sums the values, deletes the individual rows, and re-inserts a
single aggregated row. This keeps the table lean and makes billing
aggregation fast.

Idempotent: safe to re-run (only one aggregated row per group will exist
after each run).
"""

import logging
from datetime import UTC, date, datetime, timedelta
from typing import Any

from shared.db import execute_with_tenant, execute_write_with_tenant, tenant_transaction
from shared.job_runs import tracked_job
from shared.logging_config import bind_log_context, clear_log_context, setup_logging
from shared.observability import init_tracing, record_failure
from shared.tenant_context import PLATFORM_TENANT_ID

from . import tenant_metrics

setup_logging()
init_tracing()

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Lambda entry point
# ---------------------------------------------------------------------------


@tracked_job("usage_aggregation")
def lambda_handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
    clear_log_context()
    bind_log_context(request_id=getattr(context, "aws_request_id", None))
    # Aggregate all completed days (yesterday and earlier) — never today,
    # since today's records are still accumulating.
    yesterday = datetime.now(UTC).date() - timedelta(days=1)

    tenants = _get_active_tenants()
    aggregated = errors = 0

    for tenant in tenants:
        tenant_id = str(tenant["id"])
        bind_log_context(tenant_id=tenant_id)
        try:
            count = _aggregate_tenant(tenant_id, up_to=yesterday)
            aggregated += count
        except Exception:
            logger.exception("Usage aggregation failed for tenant %s", tenant_id)
            record_failure("scheduled_job_step")
            errors += 1

    # Daily tenant metrics (platform audit Phase 1c): yesterday's and today's rows, after the usage records above are
    # consolidated, then the job-run history beyond its retention window.
    metrics = tenant_metrics.refresh_recent()
    pruned = 0
    try:
        pruned = tenant_metrics.prune_job_runs()
    except Exception:
        logger.exception("Pruning old job_run rows failed")
        errors += 1

    logger.info(
        "Usage aggregation job done: groups_aggregated=%d errors=%d metric_rows=%d metric_errors=%d job_runs_pruned=%d",
        aggregated,
        errors,
        metrics["metric_rows"],
        metrics["metric_errors"],
        pruned,
    )
    return {"groups_aggregated": aggregated, "errors": errors, **metrics, "job_runs_pruned": pruned}


# ---------------------------------------------------------------------------
# Per-tenant aggregation
# ---------------------------------------------------------------------------


def _aggregate_tenant(tenant_id: str, up_to: date) -> int:
    """Consolidate usage_record rows for all completed periods up to `up_to`.

    Returns the number of (metric_type, period_start) groups processed.
    """
    groups = execute_with_tenant(
        tenant_id,
        """
        SELECT metric_type,
               period_start,
               MAX(period_end)     AS period_end,
               SUM(value)::DECIMAL AS total_value,
               COUNT(*)            AS row_count
        FROM usage_record
        WHERE tenant_id    = %s
          AND period_start <= %s
          AND period_end   = period_start
        GROUP BY metric_type, period_start
        HAVING COUNT(*) > 1
        ORDER BY period_start ASC, metric_type ASC
        """,
        (tenant_id, up_to),
    )

    if not groups:
        return 0

    consolidated = 0
    for group in groups:
        try:
            _consolidate_group(
                tenant_id=tenant_id,
                metric_type=group["metric_type"],
                period_start=group["period_start"],
                total_value=group["total_value"],
                period_end=group.get("period_end"),
            )
            consolidated += 1
        except Exception:
            logger.exception(
                "Failed to consolidate usage group tenant=%s metric=%s period=%s",
                tenant_id,
                group["metric_type"],
                group["period_start"],
            )
            record_failure("scheduled_job_step")

    logger.info(
        "Aggregated %d usage groups for tenant %s up to %s",
        consolidated,
        tenant_id,
        up_to,
        extra={"tenant_id": tenant_id},
    )
    return consolidated


def _consolidate_group(
    tenant_id: str,
    metric_type: str,
    period_start: date,
    total_value: Any,
    period_end: date | None = None,
) -> None:
    """Delete individual rows for a group and insert one aggregated row atomically."""
    resolved_period_end = period_end if period_end is not None else period_start
    with tenant_transaction(tenant_id):
        execute_write_with_tenant(
            tenant_id,
            """
            DELETE FROM usage_record
            WHERE tenant_id    = %(tenant_id)s
              AND metric_type  = %(metric_type)s
              AND period_start = %(period_start)s
              AND period_end   = %(period_end)s
            RETURNING id
            """,
            {
                "tenant_id": tenant_id,
                "metric_type": metric_type,
                "period_start": period_start,
                "period_end": resolved_period_end,
            },
        )

        execute_write_with_tenant(
            tenant_id,
            """
            INSERT INTO usage_record (
                tenant_id, metric_type, value, period_start, period_end
            ) VALUES (
                %(tenant_id)s, %(metric_type)s, %(value)s,
                %(period_start)s, %(period_end)s
            )
            RETURNING id
            """,
            {
                "tenant_id": tenant_id,
                "metric_type": metric_type,
                "value": total_value,
                "period_start": period_start,
                "period_end": resolved_period_end,
            },
        )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _get_active_tenants() -> list[dict[str, Any]]:
    return execute_with_tenant(
        PLATFORM_TENANT_ID,
        "SELECT id FROM tenant WHERE status = 'active'",
    )
