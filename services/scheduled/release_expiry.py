"""Release Note Expiry — runs daily at 00:00 UTC.

For each release_note with:
  status = 'active'
  AND valid_until IS NOT NULL
  AND valid_until < CURRENT_DATE
→ Mark status = 'expired'
→ Notify customer (SMS + email)
"""

import logging
from datetime import date
from typing import Any

from aws_xray_sdk.core import patch_all

from shared.db import execute_with_tenant, execute_write_with_tenant
from shared.logging_config import setup_logging
from shared.notifications import enqueue_notification
from shared.tenant_context import PLATFORM_TENANT_ID

setup_logging()
patch_all()

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Lambda entry point
# ---------------------------------------------------------------------------


def lambda_handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
    tenants = _get_active_tenants()
    expired = errors = 0

    for tenant in tenants:
        tenant_id = str(tenant["id"])
        try:
            count = _process_tenant(tenant_id)
            expired += count
        except Exception:
            logger.exception("Release expiry failed for tenant %s", tenant_id)
            errors += 1

    logger.info(
        "Release expiry job done: expired=%d errors=%d",
        expired,
        errors,
    )
    return {"expired": expired, "errors": errors}


# ---------------------------------------------------------------------------
# Per-tenant processing
# ---------------------------------------------------------------------------


def _process_tenant(tenant_id: str) -> int:
    today = date.today()
    notes = _get_expired_notes(tenant_id, today)
    expired_count = 0

    for note in notes:
        try:
            _expire_note(tenant_id, note)
            expired_count += 1
        except Exception:
            logger.exception(
                "Failed to expire release_note %s",
                note["id"],
                extra={"tenant_id": tenant_id},
            )

    return expired_count


def _expire_note(tenant_id: str, note: dict[str, Any]) -> None:
    note_id = str(note["id"])

    execute_write_with_tenant(
        tenant_id,
        """
        UPDATE release_note
        SET status     = 'expired',
            updated_at = NOW()
        WHERE tenant_id = %(tenant_id)s AND id = %(id)s
        RETURNING id
        """,
        {"tenant_id": tenant_id, "id": note_id},
    )

    logger.info(
        "Release note expired: %s valid_until=%s",
        note_id,
        note.get("valid_until"),
        extra={"tenant_id": tenant_id},
    )

    _notify_customer(tenant_id, note)


def _notify_customer(tenant_id: str, note: dict[str, Any]) -> None:
    customer = _get_customer_contact(tenant_id, str(note["customer_id"]))
    if not customer:
        return

    template_vars = {
        "reference_number": note.get("reference_number", ""),
        "valid_until": str(note.get("valid_until", "")),
    }
    locale = customer.get("locale", "en")

    if customer.get("phone"):
        try:
            enqueue_notification(
                tenant_id=tenant_id,
                channel="sms",
                recipient=customer["phone"],
                template_id="release_note_generated",
                template_vars=template_vars,
                locale=locale,
            )
        except Exception:
            logger.warning(
                "Failed to send expiry SMS for note %s",
                note["id"],
                extra={"tenant_id": tenant_id},
            )

    if customer.get("email"):
        try:
            enqueue_notification(
                tenant_id=tenant_id,
                channel="email",
                recipient=customer["email"],
                template_id="release_note_generated",
                template_vars=template_vars,
                locale=locale,
            )
        except Exception:
            logger.warning(
                "Failed to send expiry email for note %s",
                note["id"],
                extra={"tenant_id": tenant_id},
            )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _get_active_tenants() -> list[dict[str, Any]]:
    return execute_with_tenant(
        PLATFORM_TENANT_ID,
        "SELECT id FROM tenant WHERE status = 'active'",
    )


def _get_expired_notes(tenant_id: str, today: date) -> list[dict[str, Any]]:
    return execute_with_tenant(
        tenant_id,
        """
        SELECT id, customer_id, reference_number, valid_until
        FROM release_note
        WHERE tenant_id  = %s
          AND status     = 'active'
          AND valid_until IS NOT NULL
          AND valid_until < %s
        ORDER BY valid_until ASC
        """,
        (tenant_id, today),
    )


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
