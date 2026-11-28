"""SLA Breach Check — runs every 4 hours.

For each cbm_dispute with status = 'open':
  If (NOW() - created_at) > 24 hours AND dispute has not been acknowledged
  (i.e. updated_at == created_at — no staff action taken):
    Log SLA breach in audit_log (entity_type = 'sla_breach').
    Send reminder notification to Nigeria Office Staff.
"""

import logging
from datetime import UTC, datetime, timedelta
from typing import Any

from shared.audit import log_audit
from shared.db import execute_with_tenant, execute_write_with_tenant
from shared.job_runs import tracked_job
from shared.logging_config import bind_log_context, clear_log_context, setup_logging
from shared.notifications import enqueue_notification
from shared.observability import init_tracing, record_failure
from shared.staff_notifications import notify_staff
from shared.tenant_context import PLATFORM_TENANT_ID

setup_logging()
init_tracing()

logger = logging.getLogger(__name__)

_SLA_WINDOW = timedelta(hours=24)
_SYSTEM_ACTOR: str | None = None
_SYSTEM_ROLE = "scheduler"


# ---------------------------------------------------------------------------
# Lambda entry point
# ---------------------------------------------------------------------------


@tracked_job("sla_check")
def lambda_handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
    clear_log_context()
    bind_log_context(request_id=getattr(context, "aws_request_id", None))
    tenants = _get_active_tenants()
    breaches = errors = 0

    for tenant in tenants:
        tenant_id = str(tenant["id"])
        bind_log_context(tenant_id=tenant_id)
        try:
            count = _process_tenant(tenant_id)
            breaches += count
        except Exception:
            logger.exception("SLA check failed for tenant %s", tenant_id)
            record_failure("scheduled_job_step")
            errors += 1

    logger.info(
        "SLA check job done: breaches=%d errors=%d",
        breaches,
        errors,
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
            if _record_breach(tenant_id, dispute) is not False:
                breach_count += 1
        except Exception:
            logger.exception(
                "SLA breach record failed for dispute %s",
                dispute["id"],
                extra={"tenant_id": tenant_id},
            )
            record_failure("scheduled_job_step")

    return breach_count


def _record_breach(tenant_id: str, dispute: dict[str, Any]) -> bool:
    dispute_id = str(dispute["id"])

    stamped = execute_write_with_tenant(
        tenant_id,
        """
        UPDATE cbm_dispute
        SET sla_breached_at = NOW()
        WHERE tenant_id = %(tenant_id)s
          AND id = %(id)s
          AND status IN ('submitted', 'open')
          AND acknowledged_at IS NULL
          AND sla_breached_at IS NULL
        RETURNING id
        """,
        {"tenant_id": tenant_id, "id": dispute_id},
    )
    if not stamped:
        return False

    log_audit(
        tenant_id=tenant_id,
        entity_type="sla_breach",
        entity_id=dispute_id,
        action="STATUS_CHANGE",
        actor_id=_SYSTEM_ACTOR,
        actor_role=_SYSTEM_ROLE,
        after_state={
            "dispute_id": dispute_id,
            "breach_type": "unacknowledged_24h",
            "created_at": str(dispute["created_at"]),
        },
    )

    logger.warning(
        "SLA breach: dispute %s unacknowledged for > 24h",
        dispute_id,
        extra={"tenant_id": tenant_id},
    )

    # Notify Nigeria Office Staff
    _notify_nigeria_staff(tenant_id, dispute)
    return True


def _notify_nigeria_staff(tenant_id: str, dispute: dict[str, Any]) -> None:
    staff = execute_with_tenant(
        tenant_id,
        """
        SELECT DISTINCT tu.email, tu.locale
        FROM tenant_user tu
        LEFT JOIN tenant_user_role tur
          ON tur.user_id = tu.id AND tur.tenant_id = tu.tenant_id
        WHERE tu.tenant_id = %s
          AND (tu.role = 'nigeria_office_staff' OR tur.role = 'nigeria_office_staff')
          AND tu.status = 'active'
        LIMIT 10
        """,
        (tenant_id,),
    )

    template_vars = {
        "dispute_id": str(dispute["id"]),
        "reference_number": str(dispute.get("reference_number") or dispute["id"]),
        "status": "sla_breached",
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
                    locale=staff_member.get("locale", "en"),
                )
            except Exception:
                logger.warning(
                    "Failed to send SLA breach notification for dispute %s",
                    dispute["id"],
                    extra={"tenant_id": tenant_id},
                )

    # In-app bell, alongside the email above — a breach is exactly the kind
    # of "needs your attention now" moment the staff bell exists for.
    notify_staff(
        tenant_id=tenant_id,
        event_type="cbm_dispute_sla_breach",
        entity_type="cbm_dispute",
        entity_id=str(dispute["id"]),
        title="CBM dispute SLA breach",
        body=f"Dispute {dispute['id']} has been open over 24h with no action taken.",
        target_role="nigeria_office_staff",
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _get_active_tenants() -> list[dict[str, Any]]:
    return execute_with_tenant(
        PLATFORM_TENANT_ID,
        "SELECT id FROM tenant WHERE status = 'active'",
    )


def _get_sla_breaching_disputes(tenant_id: str, threshold: datetime) -> list[dict[str, Any]]:
    """Return submitted disputes created before threshold that have never been acknowledged."""
    return execute_with_tenant(
        tenant_id,
        """
        SELECT id, billing_id, customer_id, disputed_cbm, created_at, updated_at
        FROM cbm_dispute
        WHERE tenant_id        = %s
          AND status           IN ('submitted', 'open')
          AND created_at       < %s
          AND acknowledged_at  IS NULL
          AND sla_breached_at  IS NULL
        ORDER BY created_at ASC
        """,
        (tenant_id, threshold),
    )
