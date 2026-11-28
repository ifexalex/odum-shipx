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
from collections import defaultdict
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any

from shared.billing_money import adjust_billing
from shared.db import execute_with_tenant, execute_write_with_tenant, tenant_transaction
from shared.events import publish_event
from shared.job_runs import tracked_job
from shared.logging_config import bind_log_context, clear_log_context, setup_logging
from shared.observability import init_tracing, record_failure
from shared.tenant_context import PLATFORM_TENANT_ID

setup_logging()
init_tracing()

logger = logging.getLogger(__name__)

_DEFAULT_GRACE_PERIOD = 14
_DEFAULT_DAILY_RATE_NGN = Decimal("500")


# ---------------------------------------------------------------------------
# Lambda entry point
# ---------------------------------------------------------------------------


@tracked_job("storage_fee")
def lambda_handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
    clear_log_context()
    bind_log_context(request_id=getattr(context, "aws_request_id", None))
    tenants = _get_active_tenants()
    processed = skipped = errors = 0

    for tenant in tenants:
        tenant_id = str(tenant["id"])
        bind_log_context(tenant_id=tenant_id)
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
            record_failure("scheduled_job_step")
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
    today = datetime.now(UTC).date()

    active_notes = _get_active_release_notes(tenant_id)
    fees_accrued = 0

    # Group notes by billing_id so split release notes on the same invoice do not
    # shadow each other under UNIQUE(billing_id, accrual_date).
    notes_by_billing: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for note in active_notes:
        notes_by_billing[str(note["billing_id"])].append(note)

    for billing_id, billing_notes in notes_by_billing.items():
        if len(billing_notes) == 1:
            note = billing_notes[0]
            try:
                accrued = _accrue_for_note(tenant_id, note, grace_period, daily_rate, today)
                fees_accrued += 1 if accrued else 0
            except Exception:
                logger.exception(
                    "Storage fee error for release_note %s",
                    note["id"],
                    extra={"tenant_id": tenant_id},
                )
                record_failure("scheduled_job_step")
        else:
            try:
                overdue_notes = []
                for n in billing_notes:
                    created_at = n["created_at"]
                    created_date = created_at.date() if hasattr(created_at, "date") else created_at
                    if (today - created_date).days > grace_period:
                        overdue_notes.append(n)
                if not overdue_notes:
                    continue
                total_cartons = sum(int(n["total_cartons"]) for n in overdue_notes)
                total_picked = sum(_sum_cartons_picked(tenant_id, str(n["id"])) for n in overdue_notes)
                oldest = min(
                    overdue_notes,
                    key=lambda n: n["created_at"].date() if hasattr(n["created_at"], "date") else n["created_at"],
                )
                combined_note = {
                    **oldest,
                    "total_cartons": total_cartons,
                    "_precomputed_picked": total_picked,
                }
                accrued = _accrue_for_note(tenant_id, combined_note, grace_period, daily_rate, today)
                fees_accrued += 1 if accrued else 0
            except Exception:
                logger.exception(
                    "Storage fee error for billing %s",
                    billing_id,
                    extra={"tenant_id": tenant_id},
                )
                record_failure("scheduled_job_step")

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

    cartons_picked = (
        int(note["_precomputed_picked"]) if "_precomputed_picked" in note else _sum_cartons_picked(tenant_id, note_id)
    )
    unreleased = note["total_cartons"] - cartons_picked
    if unreleased <= 0:
        return False

    fee = unreleased * daily_rate
    day_number = days_since - grace_period

    # The fee-log row and the invoice total move together: if the invoice update
    # fails the log row rolls back with it, so the unique (billing, date) key never
    # blocks a retry and a fee is never logged without being charged. The status is
    # recomputed, so a 'paid' invoice that takes a fee becomes 'partially_paid'.
    with tenant_transaction(tenant_id):
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
        if adjust_billing(tenant_id, billing_id, fee) is None:
            raise RuntimeError(f"billing {billing_id} not found in tenant while accruing a storage fee")

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
        SELECT rn.id, rn.billing_id, rn.customer_id, rn.container_id,
               rn.total_cartons, rn.created_at
        FROM release_note rn
        JOIN billing b
          ON b.id = rn.billing_id AND b.tenant_id = rn.tenant_id
        WHERE rn.tenant_id = %s
          AND rn.status IN ('active', 'expired')
          AND b.status NOT IN ('cancelled', 'waived')
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
