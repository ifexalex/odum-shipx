"""Dispute Auto-Escalation — runs every 6 hours.

For each tenant with dispute_escalation.enabled = true:
  For each cbm_dispute with status = 'under_review':
    If (NOW() - updated_at).days >= auto_escalate_days:
      Set status = 'escalated', publish DisputeEscalated event,
      notify China Office Staff + Tenant Admin.
"""

import logging
from datetime import UTC, datetime
from typing import Any

from shared.db import execute_with_tenant, execute_write_with_tenant
from shared.events import publish_event
from shared.logging_config import bind_log_context, clear_log_context, setup_logging
from shared.notifications import enqueue_notification
from shared.observability import init_tracing, record_failure
from shared.staff_notifications import notify_staff
from shared.tenant_context import PLATFORM_TENANT_ID

setup_logging()
init_tracing()

logger = logging.getLogger(__name__)

_DEFAULT_ESCALATE_DAYS = 5


# ---------------------------------------------------------------------------
# Lambda entry point
# ---------------------------------------------------------------------------


def lambda_handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
    clear_log_context()
    bind_log_context(request_id=getattr(context, "aws_request_id", None))
    tenants = _get_active_tenants()
    escalated = errors = 0

    for tenant in tenants:
        tenant_id = str(tenant["id"])
        bind_log_context(tenant_id=tenant_id)
        try:
            count = _process_tenant(tenant_id)
            escalated += count
        except Exception:
            logger.exception("Dispute escalation failed for tenant %s", tenant_id)
            record_failure("scheduled_job_step")
            errors += 1

    logger.info(
        "Dispute escalation job done: escalated=%d errors=%d",
        escalated,
        errors,
    )
    return {"escalated": escalated, "errors": errors}


# ---------------------------------------------------------------------------
# Per-tenant processing
# ---------------------------------------------------------------------------


def _process_tenant(tenant_id: str) -> int:
    config = _get_dispute_escalation_config(tenant_id)
    if not config.get("enabled"):
        return 0

    auto_escalate_days = int(config.get("auto_escalate_days", _DEFAULT_ESCALATE_DAYS))
    now = datetime.now(UTC)

    disputes = _get_investigating_disputes(tenant_id)
    escalated = 0

    for dispute in disputes:
        try:
            updated_at = dispute["updated_at"]
            if updated_at.tzinfo is None:
                updated_at = updated_at.replace(tzinfo=UTC)
            days_investigating = (now - updated_at).days

            if days_investigating >= auto_escalate_days and _escalate_dispute(tenant_id, dispute) is not False:
                escalated += 1
        except Exception:
            logger.exception(
                "Escalation error for dispute %s",
                dispute["id"],
                extra={"tenant_id": tenant_id},
            )
            record_failure("scheduled_job_step")

    return escalated


def _escalate_dispute(tenant_id: str, dispute: dict[str, Any]) -> bool:
    dispute_id = str(dispute["id"])

    updated = execute_write_with_tenant(
        tenant_id,
        """
        UPDATE cbm_dispute
        SET status     = 'escalated_china',
             updated_at = NOW()
        WHERE tenant_id = %(tenant_id)s
          AND id = %(id)s
          AND status IN ('investigating', 'under_review')
        RETURNING id
        """,
        {"tenant_id": tenant_id, "id": dispute_id},
    )
    if not updated:
        return False

    publish_event(
        source="logistics.scheduled",
        detail_type="DisputeEscalated",
        tenant_id=tenant_id,
        payload={
            "dispute_id": dispute_id,
            "billing_id": str(dispute["billing_id"]),
            "customer_id": str(dispute["customer_id"]),
            "disputed_cbm": str(dispute["disputed_cbm"]),
        },
    )

    # Notify admin channels — phone/email not known at job level, use event-driven channel
    _notify_escalation(tenant_id, dispute)

    logger.info(
        "Dispute escalated: %s",
        dispute_id,
        extra={"tenant_id": tenant_id},
    )
    return True


def _notify_escalation(tenant_id: str, dispute: dict[str, Any]) -> None:
    """Enqueue notifications to admin-level recipients via platform SQS."""
    # Fetch tenant admin contact info for notification routing (including multi-role assignments)
    admins = execute_with_tenant(
        tenant_id,
        """
        SELECT DISTINCT tu.email, tu.locale
        FROM tenant_user tu
        LEFT JOIN tenant_user_role tur
          ON tur.tenant_user_id = tu.id AND tur.tenant_id = tu.tenant_id
        WHERE tu.tenant_id = %s
          AND (
              tu.role IN ('tenant_admin', 'china_office_staff')
              OR tur.role IN ('tenant_admin', 'china_office_staff')
          )
          AND tu.status = 'active'
        LIMIT 10
        """,
        (tenant_id,),
    )

    template_vars = {
        "dispute_id": str(dispute["id"]),
        "reference_number": str(dispute.get("reference_number") or dispute["id"]),
        "status": "escalated_china",
        "disputed_cbm": str(dispute["disputed_cbm"]),
    }

    for admin in admins:
        if admin.get("email"):
            try:
                enqueue_notification(
                    tenant_id=tenant_id,
                    channel="email",
                    recipient=admin["email"],
                    template_id="cbm_dispute_update",
                    template_vars=template_vars,
                    locale=admin.get("locale", "en"),
                )
            except Exception:
                logger.warning(
                    "Failed to enqueue escalation email for dispute %s",
                    dispute["id"],
                    extra={"tenant_id": tenant_id},
                )

    # In-app bell, alongside the email above.
    for role in ("china_office_staff", "tenant_admin"):
        notify_staff(
            tenant_id=tenant_id,
            event_type="cbm_dispute_escalated",
            entity_type="cbm_dispute",
            entity_id=str(dispute["id"]),
            title="CBM dispute escalated",
            body=f"Dispute {dispute['id']} was auto-escalated after no action.",
            target_role=role,
        )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _get_active_tenants() -> list[dict[str, Any]]:
    return execute_with_tenant(
        PLATFORM_TENANT_ID,
        "SELECT id FROM tenant WHERE status = 'active'",
    )


def _get_dispute_escalation_config(tenant_id: str) -> dict[str, Any]:
    rows = execute_with_tenant(
        tenant_id,
        """
        SELECT config_value FROM tenant_config
        WHERE tenant_id = %s AND config_key = 'dispute_escalation'
        LIMIT 1
        """,
        (tenant_id,),
    )
    return rows[0]["config_value"] if rows else {}


def _get_investigating_disputes(tenant_id: str) -> list[dict[str, Any]]:
    return execute_with_tenant(
        tenant_id,
        """
        SELECT id, billing_id, customer_id, disputed_cbm, updated_at
        FROM cbm_dispute
        WHERE tenant_id = %s AND status IN ('investigating', 'under_review')
        ORDER BY updated_at ASC
        """,
        (tenant_id,),
    )
