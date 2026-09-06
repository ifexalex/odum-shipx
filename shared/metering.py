"""Usage metering — records API and resource usage per tenant.

Writes a row to `usage_record` and publishes a `UsageRecorded` event to
EventBridge so the scheduled metering Lambda can aggregate and bill.

Failures are swallowed — metering must never break primary business operations
(same fire-and-forget pattern as `audit.py`).

Usage:
    from shared.metering import record_usage

    record_usage(tenant_id, "api_calls", value=1, request_id=request_id)
"""

import logging
from datetime import date

from shared.db import execute_write_with_tenant
from shared.events import publish_event

logger = logging.getLogger(__name__)

# Allowlist matching the metric_type CHECK constraint in the usage_record table
VALID_METRIC_TYPES = frozenset(
    {
        "api_calls",
        "containers_processed",
        "storage_bytes",
        "users_active",
        "sms_sent",
        "whatsapp_sent",
        "emails_sent",
    }
)


def record_usage(
    tenant_id: str,
    metric_type: str,
    value: float = 1.0,
    request_id: str = "",
) -> None:
    """Record a usage metric for a tenant.

    Writes to the `usage_record` table (scoped to the tenant via RLS) and
    publishes a `UsageRecorded` event to EventBridge.

    Args:
        tenant_id: The tenant UUID.
        metric_type: One of the VALID_METRIC_TYPES values.
        value: Quantity to record (default: 1.0).
        request_id: Correlation ID from the originating request.
    """
    if metric_type not in VALID_METRIC_TYPES:
        logger.warning("Unknown metric_type '%s' — skipping metering record", metric_type)
        return

    from shared.tenant_context import PLATFORM_TENANT_ID

    if tenant_id == PLATFORM_TENANT_ID:
        # usage_record.tenant_id is a UUID column; the platform-admin sentinel
        # is the literal string "PLATFORM", which every write here failed on
        # with InvalidTextRepresentation — on every single platform-admin
        # request, since platform_admin has no tier limits to meter against
        # in the first place. Skip rather than let it fail (harmlessly, but
        # noisily and needlessly) every time.
        return

    today = date.today()

    try:
        # ON CONFLICT upsert, not a plain INSERT — migration 010's own
        # docstring documents this exact upsert as the reason
        # uq_usage_tenant_metric_period exists, but record_usage() never
        # actually used it. Every metering write past the first for a given
        # (tenant, metric, day) hit the unique constraint and was silently
        # dropped (this function fails open), so usage-based quota counting
        # only ever counted 1 per day per tenant per metric. Worse locally:
        # the resulting IntegrityError, while itself rolled back correctly,
        # was observed leaving the shared connection in a failed-transaction
        # state afterward — and since this constraint is hit on essentially
        # every request after the first each day, that wasn't a rare edge
        # case but the normal steady state (see get_connection()'s self-heal
        # in shared/db.py, added for the same reason).
        execute_write_with_tenant(
            tenant_id,
            """
            INSERT INTO usage_record (
                tenant_id, metric_type, value, period_start, period_end
            ) VALUES (
                %(tenant_id)s, %(metric_type)s, %(value)s, %(period_start)s, %(period_end)s
            )
            ON CONFLICT (tenant_id, metric_type, period_start)
            DO UPDATE SET value = usage_record.value + EXCLUDED.value
            RETURNING id
            """,
            {
                "tenant_id": tenant_id,
                "metric_type": metric_type,
                "value": value,
                "period_start": today,
                "period_end": today,
            },
        )
        logger.info(
            "Usage recorded",
            extra={
                "tenant_id": tenant_id,
                "metric_type": metric_type,
                "value": value,
                "period": str(today),
            },
        )
    except Exception as exc:
        logger.warning(
            "Usage DB write failed for tenant=%s metric=%s: %s",
            tenant_id,
            metric_type,
            exc,
        )

    try:
        publish_event(
            source="logistics.metering",
            detail_type="UsageRecorded",
            tenant_id=tenant_id,
            payload={
                "metric_type": metric_type,
                "value": value,
                "period": str(today),
            },
            request_id=request_id,
        )
    except Exception as exc:
        logger.warning(
            "Usage event publish failed for tenant=%s metric=%s: %s",
            tenant_id,
            metric_type,
            exc,
        )
