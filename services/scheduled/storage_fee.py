"""Storage Fee Accrual — runs daily at 00:00 UTC.

BR-SF-001 / BR-SF-002 / BR-SF-003:
  For each tenant with storage_fee.enabled = true:
    For each active release_note past the grace period:
      Charge daily_fee_per_carton_ngn × unreleased carton count.
      Insert storage_fee_log (idempotent via UNIQUE(billing_id, accrual_date)).
      Add fee to billing.total_ngn.
      Publish StorageFeeAccrued event.
"""

import logging
from datetime import date
from decimal import Decimal
from typing import Any

from aws_xray_sdk.core import patch_all

from shared.db import execute_with_tenant, execute_write_with_tenant
from shared.events import publish_event
from shared.logging_config import setup_logging
from shared.tenant_context import PLATFORM_TENANT_ID

setup_logging()
patch_all()

logger = logging.getLogger(__name__)

_DEFAULT_GRACE_PERIOD = 14
_DEFAULT_DAILY_RATE_NGN = Decimal("500")


# ---------------------------------------------------------------------------
# Lambda entry point
# ---------------------------------------------------------------------------


def lambda_handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
    tenants = _get_active_tenants()
    processed = skipped = errors = 0

    for tenant in tenants:
        tenant_id = str(tenant["id"])
        try:
            fees_accrued = _process_tenant(tenant_id)
            processed += 1
            if fees_accrued:
                logger.info(
                    "Storage fee accrual complete",
                    extra={"tenant_id": tenant_id, "fees_accrued": fees_accrued},
                )
        except Exception:
            logger.exception("Storage fee accrual failed for tenant %s", tenant_id)
            errors += 1

    logger.info(
        "Storage fee job done: processed=%d skipped=%d errors=%d",
        processed,
        skipped,
        errors,
    )
    return {"processed": processed, "skipped": skipped, "errors": errors}


# ---------------------------------------------------------------------------
# Per-tenant processing
# ---------------------------------------------------------------------------


def _process_tenant(tenant_id: str) -> int:
    config = _get_storage_fee_config(tenant_id)
    if not config.get("enabled"):
        return 0

    grace_period = int(config.get("grace_period_days", _DEFAULT_GRACE_PERIOD))
    daily_rate = Decimal(str(config.get("daily_fee_per_carton_ngn", _DEFAULT_DAILY_RATE_NGN)))
    today = date.today()

    active_notes = _get_active_release_notes(tenant_id)
    fees_accrued = 0

    for note in active_notes:
        try:
            accrued = _accrue_for_note(tenant_id, note, grace_period, daily_rate, today)
            fees_accrued += 1 if accrued else 0
        except Exception:
            logger.exception(
                "Storage fee error for release_note %s",
                note["id"],
                extra={"tenant_id": tenant_id},
            )

    return fees_accrued


def _accrue_for_note(
    tenant_id: str,
    note: dict[str, Any],
    grace_period: int,
    daily_rate: Decimal,
    today: date,
) -> bool:
    """Accrue one day's storage fee for a release note, if applicable.

    Returns True if a fee was inserted, False otherwise.
    """
    created_at = note["created_at"]
    created_date = created_at.date() if hasattr(created_at, "date") else created_at

    days_since = (today - created_date).days
    if days_since <= grace_period:
        return False

    note_id = str(note["id"])
    billing_id = str(note["billing_id"])

    cartons_picked = _sum_cartons_picked(tenant_id, note_id)
    unreleased = note["total_cartons"] - cartons_picked
    if unreleased <= 0:
        return False

    fee = unreleased * daily_rate
    day_number = days_since - grace_period

    inserted = execute_write_with_tenant(
        tenant_id,
        """
        INSERT INTO storage_fee_log (
            tenant_id, billing_id, customer_id, container_id,
            accrual_date, cartons_in_storage, daily_rate_ngn, amount_ngn,
            grace_period_days, days_in_storage
        ) VALUES (
            %(tenant_id)s, %(billing_id)s, %(customer_id)s, %(container_id)s,
            %(accrual_date)s, %(cartons_in_storage)s, %(daily_rate_ngn)s, %(amount_ngn)s,
            %(grace_period_days)s, %(days_in_storage)s
        )
        ON CONFLICT (billing_id, accrual_date) DO NOTHING
        RETURNING id
        """,
        {
            "tenant_id": tenant_id,
            "billing_id": billing_id,
            "customer_id": str(note["customer_id"]),
            "container_id": str(note["container_id"]),
            "accrual_date": today,
            "cartons_in_storage": unreleased,
            "daily_rate_ngn": daily_rate,
            "amount_ngn": fee,
            "grace_period_days": grace_period,
            "days_in_storage": day_number,
        },
    )

    if not inserted:
        # Conflict — fee already accrued today for this billing
        return False

    # Add fee to billing total
    execute_write_with_tenant(
        tenant_id,
        """
        UPDATE billing
        SET total_ngn  = total_ngn + %(fee)s,
            updated_at = NOW()
        WHERE tenant_id = %(tenant_id)s AND id = %(billing_id)s
        RETURNING id
        """,
        {"fee": fee, "tenant_id": tenant_id, "billing_id": billing_id},
    )

    publish_event(
        source="logistics.scheduled",
        detail_type="StorageFeeAccrued",
        tenant_id=tenant_id,
        payload={
            "release_note_id": str(note["id"]),
            "billing_id": billing_id,
            "customer_id": str(note["customer_id"]),
            "accrual_date": str(today),
            "cartons_in_storage": unreleased,
            "daily_rate_ngn": str(daily_rate),
            "amount_ngn": str(fee),
            "day_number": day_number,
        },
    )

    logger.info(
        "Storage fee accrued: billing=%s date=%s cartons=%d fee=%s",
        billing_id,
        today,
        unreleased,
        fee,
        extra={"tenant_id": tenant_id},
    )
    return True


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _get_active_tenants() -> list[dict[str, Any]]:
    return execute_with_tenant(
        PLATFORM_TENANT_ID,
        "SELECT id FROM tenant WHERE status = 'active'",
    )


def _get_storage_fee_config(tenant_id: str) -> dict[str, Any]:
    rows = execute_with_tenant(
        tenant_id,
        """
        SELECT config_value FROM tenant_config
        WHERE tenant_id = %s AND config_key = 'storage_fee'
        LIMIT 1
        """,
        (tenant_id,),
    )
    return rows[0]["config_value"] if rows else {}


def _get_active_release_notes(tenant_id: str) -> list[dict[str, Any]]:
    return execute_with_tenant(
        tenant_id,
        """
        SELECT id, billing_id, customer_id, container_id,
               total_cartons, created_at
        FROM release_note
        WHERE tenant_id = %s AND status = 'active'
        """,
        (tenant_id,),
    )


def _sum_cartons_picked(tenant_id: str, release_note_id: str) -> int:
    rows = execute_with_tenant(
        tenant_id,
        """
        SELECT COALESCE(SUM(cartons_count), 0) AS total_picked
        FROM pickup_record
        WHERE tenant_id = %s AND release_note_id = %s
        """,
        (tenant_id, release_note_id),
    )
    return int(rows[0]["total_picked"]) if rows else 0
