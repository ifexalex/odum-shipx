"""Release Note Expiry — runs daily at 00:00 UTC.

For each release_note with:
  status = 'active'
  AND valid_until IS NOT NULL
  AND valid_until < CURRENT_DATE
→ Mark status = 'expired'
→ Notify customer (SMS + email)
"""

import logging
from datetime import UTC, date, datetime
from typing import Any

from shared.db import execute_with_tenant, execute_write_with_tenant
from shared.job_runs import tracked_job
from shared.logging_config import bind_log_context, clear_log_context, setup_logging
from shared.notifications import enqueue_notification
from shared.observability import init_tracing, record_failure
from shared.tenant_context import PLATFORM_TENANT_ID

setup_logging()
init_tracing()

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Lambda entry point
# ---------------------------------------------------------------------------


@tracked_job("release_expiry")
def lambda_handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
    clear_log_context()
    bind_log_context(request_id=getattr(context, "aws_request_id", None))
    tenants = _get_active_tenants()
    expired = errors = 0

    for tenant in tenants:
        tenant_id = str(tenant["id"])
        bind_log_context(tenant_id=tenant_id)
        try:
            count = _process_tenant(tenant_id)
            expired += count
        except Exception:
            logger.exception("Release expiry failed for tenant %s", tenant_id)
            record_failure("scheduled_job_step")
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
    today = datetime.now(UTC).date()
    notes = _get_expired_notes(tenant_id, today)
    expired_count = 0

    for note in notes:
        try:
            if _expire_note(tenant_id, note) is not False:
                expired_count += 1
        except Exception:
            logger.exception(
                "Failed to expire release_note %s",
                note["id"],
                extra={"tenant_id": tenant_id},
            )
            record_failure("scheduled_job_step")

    return expired_count


def _expire_note(tenant_id: str, note: dict[str, Any]) -> bool:
    note_id = str(note["id"])

    updated = execute_write_with_tenant(
        tenant_id,
        """
        UPDATE release_note
        SET status     = 'expired',
            updated_at = NOW()
        WHERE tenant_id = %(tenant_id)s
          AND id = %(id)s
          AND status = 'active'
        RETURNING id
        """,
        {"tenant_id": tenant_id, "id": note_id},
    )
    if not updated:
        return False

    logger.info(
        "Release note expired: %s valid_until=%s",
        note_id,
        note.get("valid_until"),
        extra={"tenant_id": tenant_id},
    )

    _notify_customer(tenant_id, note)
    return True


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
                template_id="release_note_expired",
                template_vars=template_vars,
                locale=locale,
                customer_id=str(note["customer_id"]),
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
                template_id="release_note_expired",
                template_vars=template_vars,
                locale=locale,
                customer_id=str(note["customer_id"]),
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
        SELECT rn.id, rn.customer_id, rn.reference_number, rn.valid_until
        FROM release_note rn
        WHERE rn.tenant_id  = %s
          AND rn.status     = 'active'
          AND rn.valid_until IS NOT NULL
          AND rn.valid_until < %s
          AND COALESCE((
              SELECT SUM(pr.cartons_count)
              FROM pickup_record pr
              WHERE pr.tenant_id = rn.tenant_id AND pr.release_note_id = rn.id
          ), 0) < rn.total_cartons
        ORDER BY rn.valid_until ASC
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
