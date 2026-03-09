"""Business logic for the Metering service.

Provides:
- Inline tier-limit checks (called synchronously by other services).
- SQS event processing (upsert usage records from async events).
- Usage summary building for the Platform Admin API.
"""
import json
import logging
from calendar import monthrange
from datetime import UTC, date, datetime
from typing import Any

from shared.exceptions import UsageLimitExceededError

from . import repository as repo

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Tier limit definitions (spec §3.5)
# ---------------------------------------------------------------------------

TIER_LIMITS: dict[str, dict[str, Any]] = {
    "starter": {"users": 10, "containers_per_month": 5, "storage_gb": 5.0},
    "business": {"users": 50, "containers_per_month": 25, "storage_gb": 25.0},
    "enterprise": {"users": 999999, "containers_per_month": 999999, "storage_gb": 999999.0},
}

_DEFAULT_TIER = "starter"

# Metric types that aggregate daily (period = today → today)
_DAILY_METRICS = frozenset({"api_calls", "sms_sent", "whatsapp_sent", "emails_sent"})
# Metric types that aggregate monthly
_MONTHLY_METRICS = frozenset({"containers_processed", "storage_bytes", "users_active"})

_VALID_METRIC_TYPES = _DAILY_METRICS | _MONTHLY_METRICS


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _get_limits(tenant_id: str) -> dict[str, Any]:
    tenant = repo.get_tenant_info(tenant_id)
    tier = (tenant or {}).get("subscription_tier") or _DEFAULT_TIER
    return TIER_LIMITS.get(tier, TIER_LIMITS[_DEFAULT_TIER])


def _period_for_metric(metric_type: str, ref_date: date) -> tuple[date, date]:
    """Return (period_start, period_end) for the given metric and reference date."""
    if metric_type in _MONTHLY_METRICS:
        year, month = ref_date.year, ref_date.month
        last_day = monthrange(year, month)[1]
        return date(year, month, 1), date(year, month, last_day)
    # Daily metrics: period = just today
    return ref_date, ref_date


# ---------------------------------------------------------------------------
# Inline tier-limit checks (called by other services before performing actions)
# ---------------------------------------------------------------------------


def check_user_limit(tenant_id: str) -> None:
    """Raise UsageLimitExceededError if the tenant has reached its user cap."""
    limits = _get_limits(tenant_id)
    current = repo.count_active_tenant_users(tenant_id)
    if current >= limits["users"]:
        raise UsageLimitExceededError("users", current, limits["users"])


def check_container_limit(tenant_id: str) -> None:
    """Raise UsageLimitExceededError if the tenant has created too many containers this month."""
    limits = _get_limits(tenant_id)
    current = repo.count_containers_this_month(tenant_id)
    if current >= limits["containers_per_month"]:
        raise UsageLimitExceededError("containers_per_month", current, limits["containers_per_month"])


def check_storage_limit(tenant_id: str, additional_bytes: int) -> None:
    """Raise UsageLimitExceededError if adding additional_bytes would exceed the storage cap."""
    limits = _get_limits(tenant_id)
    current_bytes = repo.get_latest_storage_bytes(tenant_id)
    current_gb = current_bytes / (1024**3)
    new_total_gb = current_gb + (additional_bytes / (1024**3))
    if new_total_gb > limits["storage_gb"]:
        raise UsageLimitExceededError("storage_gb", round(current_gb, 2), limits["storage_gb"])


# ---------------------------------------------------------------------------
# SQS event processing
# ---------------------------------------------------------------------------


def process_usage_event(message_body: str) -> None:
    """Process a single SQS UsageRecorded message body string."""
    try:
        data = json.loads(message_body)
    except (json.JSONDecodeError, ValueError) as exc:
        raise ValueError(f"Invalid JSON in SQS message: {exc}") from exc

    tenant_id = data.get("tenant_id")
    metric_type = data.get("metric_type")
    value = float(data.get("value", 1))

    if not tenant_id:
        raise ValueError("Missing tenant_id in usage event")
    if metric_type not in _VALID_METRIC_TYPES:
        raise ValueError(f"Unknown metric_type '{metric_type}'")

    # Determine period from occurred_at or fall back to today
    occurred_at_raw = data.get("occurred_at")
    if occurred_at_raw:
        try:
            ref_date = datetime.fromisoformat(occurred_at_raw.replace("Z", "+00:00")).astimezone(UTC).date()
        except (ValueError, AttributeError):
            ref_date = date.today()
    else:
        ref_date = date.today()

    period_start, period_end = _period_for_metric(metric_type, ref_date)

    repo.upsert_usage_record(tenant_id, metric_type, value, period_start, period_end)
    logger.info(
        "Upserted usage: tenant=%s metric=%s value=%s period=%s",
        tenant_id,
        metric_type,
        value,
        period_start,
    )


# ---------------------------------------------------------------------------
# Usage summary for API
# ---------------------------------------------------------------------------


def get_tenant_usage(tenant_id: str, period: str | None = None) -> dict[str, Any]:
    """Build usage summary dict for GET /v1/platform/tenants/{id}/usage.

    period: "YYYY-MM" string; defaults to current month.
    """
    if period:
        try:
            year, month = int(period[:4]), int(period[5:7])
        except (ValueError, IndexError):
            year, month = date.today().year, date.today().month
    else:
        year, month = date.today().year, date.today().month

    last_day = monthrange(year, month)[1]
    period_start = date(year, month, 1)
    period_end = date(year, month, last_day)

    tenant = repo.get_tenant_info(tenant_id)
    tier = (tenant or {}).get("subscription_tier") or _DEFAULT_TIER
    limits = TIER_LIMITS.get(tier, TIER_LIMITS[_DEFAULT_TIER])

    records = repo.get_usage_records(tenant_id, period_start, period_end)
    metrics: dict[str, float] = {r["metric_type"]: float(r["total_value"]) for r in records}

    current_users = repo.count_active_tenant_users(tenant_id)
    current_containers = repo.count_containers_this_month(tenant_id)
    storage_bytes = repo.get_latest_storage_bytes(tenant_id)
    storage_gb = round(storage_bytes / (1024**3), 2)

    return {
        "tenant_id": tenant_id,
        "period": f"{year:04d}-{month:02d}",
        "subscription_tier": tier,
        "limits": {
            "users": {"used": current_users, "max": limits["users"]},
            "containers_per_month": {"used": current_containers, "max": limits["containers_per_month"]},
            "storage_gb": {"used": storage_gb, "max": limits["storage_gb"]},
        },
        "api_calls": int(metrics.get("api_calls", 0)),
        "notifications": {
            "sms_sent": int(metrics.get("sms_sent", 0)),
            "whatsapp_sent": int(metrics.get("whatsapp_sent", 0)),
            "emails_sent": int(metrics.get("emails_sent", 0)),
        },
    }
