"""Dispute Auto-Escalation — runs every 6 hours.

For each tenant with dispute_escalation.enabled = true:
  For each cbm_dispute with status = 'under_review':
    If (NOW() - updated_at).days >= auto_escalate_days:
      Set status = 'escalated', publish DisputeEscalated event,
      notify China Office Staff + Tenant Admin.
"""

import logging
from datetime import UTC, datetime

from aws_xray_sdk.core import patch_all

from shared.db import execute_with_tenant, execute_write_with_tenant
from shared.events import publish_event
from shared.logging_config import setup_logging
from shared.notifications import enqueue_notification
from shared.tenant_context import PLATFORM_TENANT_ID

setup_logging()
patch_all()

logger = logging.getLogger(__name__)

_DEFAULT_ESCALATE_DAYS = 5


# ---------------------------------------------------------------------------
# Lambda entry point
# ---------------------------------------------------------------------------


def lambda_handler(event: dict, context) -> dict:
    tenants = _get_active_tenants()
    escalated = errors = 0

    for tenant in tenants:
        tenant_id = str(tenant["id"])
        try:
            count = _process_tenant(tenant_id)
            escalated += count
        except Exception:
            logger.exception(
                "Dispute escalation failed for tenant %s", tenant_id
            )
            errors += 1

    logger.info(
        "Dispute escalation job done: escalated=%d errors=%d",
        escalated, errors,
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

            if days_investigating >= auto_escalate_days:
                _escalate_dispute(tenant_id, dispute)
                escalated += 1
        except Exception:
            logger.exception(
                "Escalation error for dispute %s", dispute["id"],
                extra={"tenant_id": tenant_id},
            )

    return escalated


def _escalate_dispute(tenant_id: str, dispute: dict) -> None:
    dispute_id = str(dispute["id"])

    execute_write_with_tenant(
        tenant_id,
        """
        UPDATE cbm_dispute
        SET status     = 'escalated',
            updated_at = NOW()
        WHERE tenant_id = %(tenant_id)s AND id = %(id)s
        RETURNING id
        """,
        {"tenant_id": tenant_id, "id": dispute_id},
    )

    publish_event(
        source="logistics.scheduled",
        detail_type="DisputeEscalated",
        tenant_id=tenant_id,
        payload={
            "dispute_id":    dispute_id,
            "billing_id":    str(dispute["billing_id"]),
            "customer_id":   str(dispute["customer_id"]),
            "disputed_cbm":  str(dispute["disputed_cbm"]),
        },
    )

    # Notify admin channels — phone/email not known at job level, use event-driven channel
    _notify_escalation(tenant_id, dispute)

    logger.info(
        "Dispute escalated: %s", dispute_id,
        extra={"tenant_id": tenant_id},
    )


def _notify_escalation(tenant_id: str, dispute: dict) -> None:
    """Enqueue notifications to admin-level recipients via platform SQS."""
    # Fetch tenant admin contact info for notification routing
    admins = execute_with_tenant(
        tenant_id,
        """
        SELECT tu.email, tu.phone_number
        FROM tenant_user tu
        WHERE tu.tenant_id = %s
          AND tu.role IN ('tenant_admin', 'china_office_staff')
          AND tu.is_active = TRUE
        LIMIT 10
        """,
        (tenant_id,),
    )

    template_vars = {
        "dispute_id":   str(dispute["id"]),
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
                )
            except Exception:
                logger.warning(
                    "Failed to enqueue escalation email for dispute %s",
                    dispute["id"], extra={"tenant_id": tenant_id},
                )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _get_active_tenants() -> list[dict]:
    return execute_with_tenant(
        PLATFORM_TENANT_ID,
        "SELECT id FROM tenant WHERE status = 'active'",
    )


def _get_dispute_escalation_config(tenant_id: str) -> dict:
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


def _get_investigating_disputes(tenant_id: str) -> list[dict]:
    return execute_with_tenant(
        tenant_id,
        """
        SELECT id, billing_id, customer_id, disputed_cbm, updated_at
        FROM cbm_dispute
        WHERE tenant_id = %s AND status = 'under_review'
        ORDER BY updated_at ASC
        """,
        (tenant_id,),
    )
