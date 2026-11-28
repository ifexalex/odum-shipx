"""Daily tenant metrics (``tenant_metrics_daily``, platform audit Phase 1c, decision D7).

One row per tenant per UTC day, counts only. What each column means:

* ``customers_total``: customers created by the end of the day and not erased; ``customers_new``: created that day.
* ``containers_created``: containers created that day; ``containers_processed``: the metered ``containers_processed``.
* ``api_calls``: the metered API calls that day; ``storage_bytes``: metered storage up to the end of the day.
* ``{sms,whatsapp,email}_sent`` / ``_failed``: notifications logged that day by channel (sent, delivered and read
  count as sent).
* ``staff_seats``: staff seats in use when the row was computed (``shared/seats.py``).
* ``last_activity_at``: the tenant's newest audit-log entry by the end of the day.

The hourly usage job refreshes yesterday's and today's rows for every active or suspended tenant (an upsert, so it is
idempotent), and prunes ``job_run`` rows older than 180 days. ``scripts/backfill_tenant_metrics.py`` fills earlier
days from history. Each tenant's figures are read in that tenant's own RLS scope.
"""

import logging
from datetime import UTC, date, datetime, time, timedelta
from typing import Any

from shared.db import execute_with_tenant, execute_write_with_tenant, execute_write_with_tenant_many
from shared.seats import staff_seat_condition
from shared.tenant_context import PLATFORM_TENANT_ID

logger = logging.getLogger(__name__)

JOB_RUN_RETENTION_DAYS = 180
_SENT = "('sent', 'delivered', 'read')"

# Module constants only are spliced in (the seat rule and the sent statuses); every value is a parameter.
_COMPUTE_SQL = f"""
    SELECT
        (SELECT COUNT(*) FROM customer
          WHERE tenant_id = %(tenant_id)s AND created_at < %(end)s AND anonymised_at IS NULL) AS customers_total,
        (SELECT COUNT(*) FROM customer
          WHERE tenant_id = %(tenant_id)s AND created_at >= %(start)s AND created_at < %(end)s) AS customers_new,
        (SELECT COUNT(*) FROM container
          WHERE tenant_id = %(tenant_id)s AND created_at >= %(start)s AND created_at < %(end)s) AS containers_created,
        (SELECT COALESCE(SUM(value), 0) FROM usage_record
          WHERE tenant_id = %(tenant_id)s AND metric_type = 'containers_processed' AND period_start = %(day)s)
          AS containers_processed,
        (SELECT COALESCE(SUM(value), 0) FROM usage_record
          WHERE tenant_id = %(tenant_id)s AND metric_type = 'api_calls' AND period_start = %(day)s) AS api_calls,
        (SELECT COALESCE(SUM(value), 0) FROM usage_record
          WHERE tenant_id = %(tenant_id)s AND metric_type = 'storage_bytes' AND period_start <= %(day)s) AS storage_bytes,
        n.sms_sent, n.sms_failed, n.whatsapp_sent, n.whatsapp_failed, n.email_sent, n.email_failed,
        (SELECT COUNT(*) FROM tenant_user
          WHERE tenant_id = %(tenant_id)s AND {staff_seat_condition("tenant_user")}) AS staff_seats,
        (SELECT MAX(created_at) FROM audit_log
          WHERE tenant_id = %(tenant_id)s AND created_at < %(end)s) AS last_activity_at
    FROM (
        SELECT
            COUNT(*) FILTER (WHERE channel = 'sms' AND status IN {_SENT})      AS sms_sent,
            COUNT(*) FILTER (WHERE channel = 'sms' AND status = 'failed')      AS sms_failed,
            COUNT(*) FILTER (WHERE channel = 'whatsapp' AND status IN {_SENT}) AS whatsapp_sent,
            COUNT(*) FILTER (WHERE channel = 'whatsapp' AND status = 'failed') AS whatsapp_failed,
            COUNT(*) FILTER (WHERE channel = 'email' AND status IN {_SENT})    AS email_sent,
            COUNT(*) FILTER (WHERE channel = 'email' AND status = 'failed')    AS email_failed
        FROM notification_log
        WHERE tenant_id = %(tenant_id)s AND created_at >= %(start)s AND created_at < %(end)s
    ) n
"""

_COLUMNS = (
    "customers_total",
    "customers_new",
    "containers_created",
    "containers_processed",
    "api_calls",
    "storage_bytes",
    "sms_sent",
    "sms_failed",
    "whatsapp_sent",
    "whatsapp_failed",
    "email_sent",
    "email_failed",
    "staff_seats",
    "last_activity_at",
)

_UPSERT_SQL = f"""
    INSERT INTO tenant_metrics_daily (tenant_id, metric_date, {", ".join(_COLUMNS)}, computed_at)
    VALUES (%(tenant_id)s, %(day)s, {", ".join(f"%({c})s" for c in _COLUMNS)}, NOW())
    ON CONFLICT (tenant_id, metric_date) DO UPDATE SET
        {", ".join(f"{c} = EXCLUDED.{c}" for c in _COLUMNS)}, computed_at = NOW()
    RETURNING tenant_id
"""


def _bounds(day: date) -> tuple[datetime, datetime]:
    start = datetime.combine(day, time.min, tzinfo=UTC)
    return start, start + timedelta(days=1)


def compute_day(tenant_id: str, day: date) -> dict[str, Any]:
    """Read one tenant's figures for one UTC day, in the tenant's own scope."""
    start, end = _bounds(day)
    rows = execute_with_tenant(tenant_id, _COMPUTE_SQL, {"tenant_id": tenant_id, "day": day, "start": start, "end": end})
    row = rows[0] if rows else {}
    figures: dict[str, Any] = {c: row.get(c) for c in _COLUMNS}
    for column in _COLUMNS:
        if column != "last_activity_at":
            figures[column] = int(figures[column] or 0)
    return figures


def store_day(tenant_id: str, day: date, figures: dict[str, Any]) -> None:
    """Upsert one tenant-day row."""
    execute_write_with_tenant(PLATFORM_TENANT_ID, _UPSERT_SQL, {"tenant_id": tenant_id, "day": day, **figures})


def tracked_tenants() -> list[str]:
    """Tenants whose metrics are kept: active and suspended (an offboarded tenant's history stays until deletion)."""
    rows = execute_with_tenant(PLATFORM_TENANT_ID, "SELECT id FROM tenant WHERE status IN ('active', 'suspended')")
    return [str(r["id"]) for r in rows]


def refresh(days: list[date]) -> dict[str, int]:
    """Compute and store ``days`` for every tracked tenant; one tenant's failure does not stop the rest."""
    rows = errors = 0
    for tenant_id in tracked_tenants():
        for day in days:
            try:
                store_day(tenant_id, day, compute_day(tenant_id, day))
                rows += 1
            except Exception:
                logger.exception("Tenant metrics failed for tenant %s on %s", tenant_id, day)
                errors += 1
    return {"metric_rows": rows, "metric_errors": errors}


def refresh_recent(now: datetime | None = None) -> dict[str, int]:
    """Yesterday (now complete) and today (so far): what the hourly job keeps current."""
    today = (now or datetime.now(UTC)).date()
    return refresh([today - timedelta(days=1), today])


def backfill(days: int, now: datetime | None = None) -> dict[str, int]:
    """Fill the last ``days`` complete days (oldest first). Re-running overwrites with the same figures."""
    today = (now or datetime.now(UTC)).date()
    return refresh([today - timedelta(days=n) for n in range(days, 0, -1)])


def prune_job_runs() -> int:
    """Delete ``job_run`` rows older than the retention window; return how many."""
    deleted = execute_write_with_tenant_many(
        PLATFORM_TENANT_ID,
        "DELETE FROM job_run WHERE started_at < NOW() - make_interval(days => %(days)s) RETURNING id",
        {"days": JOB_RUN_RETENTION_DAYS},
    )
    return len(deleted)
