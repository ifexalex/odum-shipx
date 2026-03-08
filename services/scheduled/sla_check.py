"""SLA Breach Check — runs every 4 hours.

For each cbm_dispute with status = 'open':
  If (NOW() - created_at) > 24 hours AND dispute has not been acknowledged
  (i.e. updated_at == created_at — no staff action taken):
    Log SLA breach in audit_log (entity_type = 'sla_breach').
    Send reminder notification to Nigeria Office Staff.
"""

import logging
from datetime import UTC, datetime, timedelta

from aws_xray_sdk.core import patch_all

from shared.audit import log_audit
from shared.db import execute_with_tenant
from shared.logging_config import setup_logging
from shared.notifications import enqueue_notification
from shared.tenant_context import PLATFORM_TENANT_ID

setup_logging()
patch_all()

logger = logging.getLogger(__name__)

_SLA_WINDOW = timedelta(hours=24)
_SYSTEM_ACTOR = "system"
_SYSTEM_ROLE = "scheduler"


# ---------------------------------------------------------------------------
# Lambda entry point
# ---------------------------------------------------------------------------


def lambda_handler(event: dict, context) -> dict:
    tenants = _get_active_tenants()
    breaches = errors = 0

    for tenant in tenants:
        tenant_id = str(tenant["id"])
        try:
            count = _process_tenant(tenant_id)
            breaches += count
        except Exception:
            logger.exception(
                "SLA check failed for tenant %s", tenant_id
            )
            errors += 1

    logger.info(
        "SLA check job done: breaches=%d errors=%d",
        breaches, errors,
    )
    return {"breaches": breaches, "errors": errors}


# ---------------------------------------------------------------------------
# Per-tenant processing
# ---------------------------------------------------------------------------


def _process_tenant(tenant_id: str) -> int:
    now = datetime.now(UTC)
    threshold = now - _SLA_WINDOW

    # Disputes in 'open' status where updated_at == created_at (never acknowledged)
    # and created more than 24 hours ago
    breaching = _get_sla_breaching_disputes(tenant_id, threshold)
    breach_count = 0

    for dispute in breaching:
        try:
            _record_breach(tenant_id, dispute)
            breach_count += 1
        except Exception:
            logger.exception(
                "SLA breach record failed for dispute %s", dispute["id"],
                extra={"tenant_id": tenant_id},
            )

    return breach_count


def _record_breach(tenant_id: str, dispute: dict) -> None:
    dispute_id = str(dispute["id"])

    log_audit(
        tenant_id=tenant_id,
        entity_type="sla_breach",
        entity_id=dispute_id,
        action="STATUS_CHANGE",
        actor_id=_SYSTEM_ACTOR,
        actor_role=_SYSTEM_ROLE,
        after_state={
            "dispute_id":  dispute_id,
            "breach_type": "unacknowledged_24h",
            "created_at":  str(dispute["created_at"]),
        },
    )

    logger.warning(
        "SLA breach: dispute %s unacknowledged for > 24h",
        dispute_id,
        extra={"tenant_id": tenant_id},
    )

    # Notify Nigeria Office Staff
    _notify_nigeria_staff(tenant_id, dispute)


def _notify_nigeria_staff(tenant_id: str, dispute: dict) -> None:
    staff = execute_with_tenant(
        tenant_id,
        """
        SELECT tu.email, tu.phone_number
        FROM tenant_user tu
        WHERE tu.tenant_id = %s
          AND tu.role = 'nigeria_office_staff'
          AND tu.is_active = TRUE
        LIMIT 10
        """,
        (tenant_id,),
    )

    template_vars = {
        "dispute_id":   str(dispute["id"]),
        "disputed_cbm": str(dispute["disputed_cbm"]),
    }

    for staff_member in staff:
        if staff_member.get("email"):
            try:
                enqueue_notification(
                    tenant_id=tenant_id,
                    channel="email",
                    recipient=staff_member["email"],
                    template_id="cbm_dispute_update",
                    template_vars=template_vars,
                )
            except Exception:
                logger.warning(
                    "Failed to send SLA breach notification for dispute %s",
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


def _get_sla_breaching_disputes(tenant_id: str, threshold: datetime) -> list[dict]:
    """Return open disputes created before threshold that have never been touched."""
    return execute_with_tenant(
        tenant_id,
        """
        SELECT id, billing_id, customer_id, disputed_cbm, created_at, updated_at
        FROM cbm_dispute
        WHERE tenant_id  = %s
          AND status     = 'open'
          AND created_at < %s
          AND updated_at = created_at
        ORDER BY created_at ASC
        """,
        (tenant_id, threshold),
    )
