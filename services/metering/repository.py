"""Database access layer for the Metering service.

Pure SQL — no business logic.
All queries use parameterized statements (%s / %(name)s) — never f-strings on
user-supplied values.
"""

import logging
from datetime import date
from typing import Any

from shared.db import execute_with_tenant, execute_write_with_tenant
from shared.seats import staff_seat_condition
from shared.tenant_context import PLATFORM_TENANT_ID

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Tenant helpers (PLATFORM scope — tenant table is not RLS-isolated per tenant)
# ---------------------------------------------------------------------------


def get_tenant_info(tenant_id: str) -> dict[str, Any] | None:
    """Return tenant row (id, subscription_tier, status) using platform scope."""
    rows = execute_with_tenant(
        PLATFORM_TENANT_ID,
        "SELECT id, subscription_tier, status FROM tenant WHERE id = %s LIMIT 1",
        (tenant_id,),
    )
    return rows[0] if rows else None


# ---------------------------------------------------------------------------
# Limit-check helpers
# ---------------------------------------------------------------------------


def count_active_tenant_users(tenant_id: str) -> int:
    """Return the tenant's staff seats (``shared.seats``: customer portal accounts excluded, as in the quota check)."""
    rows = execute_with_tenant(
        tenant_id,
        f"SELECT COUNT(*) AS cnt FROM tenant_user WHERE tenant_id = %s AND {staff_seat_condition()}",
        (tenant_id,),
    )
    return int(rows[0]["cnt"]) if rows else 0


def count_containers_this_month(
    tenant_id: str,
    period_start: date | None = None,
    period_end: date | None = None,
) -> int:
    """Count non-cancelled containers created in the target calendar month (or current month)."""
    if period_start is not None and period_end is not None:
        rows = execute_with_tenant(
            tenant_id,
            """
            SELECT COUNT(*) AS cnt
            FROM container
            WHERE tenant_id = %s
              AND status <> 'cancelled'
              AND created_at >= %s::date
              AND created_at < (%s::date + INTERVAL '1 day')
            """,
            (tenant_id, period_start, period_end),
        )
        return int(rows[0]["cnt"]) if rows else 0

    rows = execute_with_tenant(
        tenant_id,
        """
        SELECT COUNT(*) AS cnt
        FROM container
        WHERE tenant_id = %s
          AND status <> 'cancelled'
          AND date_trunc('month', created_at) = date_trunc('month', NOW())
        """,
        (tenant_id,),
    )
    return int(rows[0]["cnt"]) if rows else 0


def get_latest_storage_bytes(tenant_id: str) -> float:
    """Return the cumulative storage_bytes value across usage_record rows, or 0."""
    rows = execute_with_tenant(
        tenant_id,
        """
        SELECT COALESCE(SUM(value), 0) AS value
        FROM usage_record
        WHERE tenant_id = %s AND metric_type = 'storage_bytes'
        """,
        (tenant_id,),
    )
    return float(rows[0]["value"] or 0.0) if rows else 0.0


# ---------------------------------------------------------------------------
# Usage record UPSERT (SQS consumer)
# ---------------------------------------------------------------------------


def upsert_usage_record(
    tenant_id: str,
    metric_type: str,
    value: float,
    period_start: date,
    period_end: date,
) -> None:
    """Increment usage record for (tenant, metric, period_start), inserting if absent."""
    execute_write_with_tenant(
        tenant_id,
        """
        INSERT INTO usage_record (
            tenant_id, metric_type, value, period_start, period_end, recorded_at
        ) VALUES (
            %(tenant_id)s, %(metric_type)s, %(value)s,
            %(period_start)s, %(period_end)s, NOW()
        )
        ON CONFLICT (tenant_id, metric_type, period_start)
        DO UPDATE SET
            value       = usage_record.value + EXCLUDED.value,
            recorded_at = NOW()
        RETURNING id
        """,
        {
            "tenant_id": tenant_id,
            "metric_type": metric_type,
            "value": value,
            "period_start": period_start,
            "period_end": period_end,
        },
    )


# ---------------------------------------------------------------------------
# Usage reads (API handler)
# ---------------------------------------------------------------------------


def get_usage_records(
    tenant_id: str,
    period_start: date,
    period_end: date,
) -> list[dict[str, Any]]:
    """Return all usage_record rows for a tenant within a period window."""
    return execute_with_tenant(
        tenant_id,
        """
        SELECT metric_type, SUM(value) AS total_value
        FROM usage_record
        WHERE tenant_id   = %s
          AND period_start >= %s
          AND period_end   <= %s
        GROUP BY metric_type
        """,
        (tenant_id, period_start, period_end),
    )
