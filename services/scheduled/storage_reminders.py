"""Storage Reminders — runs daily at 08:00 UTC.

For each tenant with storage_fee.enabled = true:
  For each active release_note with unreleased cartons:
    days_since = (today - release_note.created_at).days
    if days_since == storage_first_reminder (default 7):
      Send "goods ready for pickup, X days free storage remaining"
    if days_since == storage_final_reminder (default 13):
      Send "storage fees begin tomorrow"
"""

import logging
from datetime import date
from typing import Any

from shared.db import execute_with_tenant
from shared.logging_config import bind_log_context, clear_log_context, setup_logging
from shared.notifications import enqueue_notification
from shared.observability import init_tracing
from shared.tenant_context import PLATFORM_TENANT_ID

setup_logging()
init_tracing()

logger = logging.getLogger(__name__)

_DEFAULT_FIRST_REMINDER = 7
_DEFAULT_FINAL_REMINDER = 13
_DEFAULT_GRACE_PERIOD = 14


# ---------------------------------------------------------------------------
# Lambda entry point
# ---------------------------------------------------------------------------


def lambda_handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
    clear_log_context()
    bind_log_context(request_id=getattr(context, "aws_request_id", None))
    tenants = _get_active_tenants()
    sent = errors = 0

    for tenant in tenants:
        tenant_id = str(tenant["id"])
        bind_log_context(tenant_id=tenant_id)
        try:
            count = _process_tenant(tenant_id)
            sent += count
        except Exception:
            logger.exception("Storage reminders failed for tenant %s", tenant_id)
            errors += 1

    logger.info(
        "Storage reminders job done: sent=%d errors=%d",
        sent,
        errors,
    )
    return {"sent": sent, "errors": errors}


# ---------------------------------------------------------------------------
# Per-tenant processing
# ---------------------------------------------------------------------------


def _process_tenant(tenant_id: str) -> int:
    storage_config = _get_storage_fee_config(tenant_id)
    if not storage_config.get("enabled"):
        return 0

    reminder_config = _get_reminder_config(tenant_id)
    first_reminder_day = int(reminder_config.get("storage_first_reminder", _DEFAULT_FIRST_REMINDER))
    final_reminder_day = int(reminder_config.get("storage_final_reminder", _DEFAULT_FINAL_REMINDER))
    grace_period = int(storage_config.get("grace_period_days", _DEFAULT_GRACE_PERIOD))
    today = date.today()

    active_notes = _get_active_release_notes(tenant_id)
    sent = 0

    for note in active_notes:
        try:
            sent += _maybe_send_reminder(
                tenant_id,
                note,
                today,
                first_reminder_day,
                final_reminder_day,
                grace_period,
            )
        except Exception:
            logger.exception(
                "Reminder error for release_note %s",
                note["id"],
                extra={"tenant_id": tenant_id},
            )

    return sent


def _maybe_send_reminder(
    tenant_id: str,
    note: dict[str, Any],
    today: date,
    first_reminder_day: int,
    final_reminder_day: int,
    grace_period: int,
) -> int:
    created_at = note["created_at"]
    created_date = created_at.date() if hasattr(created_at, "date") else created_at
    days_since = (today - created_date).days

    if days_since not in (first_reminder_day, final_reminder_day):
        return 0

    note_id = str(note["id"])
    cartons_picked = _sum_cartons_picked(tenant_id, note_id)
    unreleased = note["total_cartons"] - cartons_picked
    if unreleased <= 0:
        return 0

    days_remaining = grace_period - days_since
    customer = _get_customer_contact(tenant_id, str(note["customer_id"]))
    if not customer:
        return 0

    if days_since == first_reminder_day:
        template_id = "storage_first_reminder"
        template_vars = {
            "reference_number": note.get("reference_number", ""),
            "carton_count": unreleased,
            "days_remaining": max(days_remaining, 0),
        }
    else:  # final reminder
        template_id = "storage_final_reminder"
        template_vars = {
            "reference_number": note.get("reference_number", ""),
            "carton_count": unreleased,
        }

    sent = 0
    locale = customer.get("locale", "en")

    if customer.get("phone"):
        try:
            enqueue_notification(
                tenant_id=tenant_id,
                channel="sms",
                recipient=customer["phone"],
                template_id=template_id,
                template_vars=template_vars,
                locale=locale,
                customer_id=str(note["customer_id"]),
            )
            sent += 1
        except Exception:
            logger.warning(
                "Failed to enqueue SMS reminder for note %s",
                note_id,
                extra={"tenant_id": tenant_id},
            )

    if customer.get("email"):
        try:
            enqueue_notification(
                tenant_id=tenant_id,
                channel="email",
                recipient=customer["email"],
                template_id=template_id,
                template_vars=template_vars,
                locale=locale,
                customer_id=str(note["customer_id"]),
            )
            sent += 1
        except Exception:
            logger.warning(
                "Failed to enqueue email reminder for note %s",
                note_id,
                extra={"tenant_id": tenant_id},
            )

    if sent:
        logger.info(
            "Storage reminder sent: note=%s days=%d type=%s",
            note_id,
            days_since,
            template_id,
            extra={"tenant_id": tenant_id},
        )

    return sent


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


def _get_reminder_config(tenant_id: str) -> dict[str, Any]:
    rows = execute_with_tenant(
        tenant_id,
        """
        SELECT config_value FROM tenant_config
        WHERE tenant_id = %s AND config_key = 'reminder_days'
        LIMIT 1
        """,
        (tenant_id,),
    )
    return rows[0]["config_value"] if rows else {}


def _get_active_release_notes(tenant_id: str) -> list[dict[str, Any]]:
    return execute_with_tenant(
        tenant_id,
        """
        SELECT id, customer_id, reference_number, total_cartons, created_at
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


def _get_customer_contact(tenant_id: str, customer_id: str) -> dict[str, Any] | None:
    rows = execute_with_tenant(
        tenant_id,
        """
        SELECT id, email, phone, locale
        FROM customer
        WHERE tenant_id = %s AND id = %s AND anonymised_at IS NULL
        LIMIT 1
        """,
        (tenant_id, customer_id),
    )
    return rows[0] if rows else None
