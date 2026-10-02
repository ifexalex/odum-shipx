"""Staff-facing in-app notification helper.

Writes to `staff_notification` (migration 046) — a broadcast-or-targeted
event row the TopBar bell reads from. Modeled directly on
`shared/audit.py::log_audit`: this function never raises, so a failure to
write a staff notification can never break the primary business operation
that triggered it.

Usage:
    from shared.staff_notifications import notify_staff

    notify_staff(
        tenant_id=ctx.tenant_id,
        event_type="payment_claim_submitted",
        entity_type="payment_claim",
        entity_id=claim_id,
        title="New payment claim submitted",
        body=f"{customer_name} submitted a claim for NGN {amount}",
        target_role="nigeria_office_staff",
    )
"""

import logging
import uuid
from datetime import UTC, datetime
from typing import Any

logger = logging.getLogger(__name__)


def notify_staff(
    tenant_id: str,
    event_type: str,
    entity_type: str,
    title: str,
    body: str | None = None,
    entity_id: str | None = None,
    target_role: str | None = None,
    target_user_id: str | None = None,
) -> None:
    """Insert a staff_notification row.

    `target_user_id` set means "only this person"; `target_role` set (with
    `target_user_id` left None) means "every staff member with this role";
    both None means "every staff member in the tenant". Never raises — any
    failure is logged as a warning, same contract as `log_audit`.

    Args:
        tenant_id: Tenant that owns the notification.
        event_type: e.g. "payment_claim_submitted", "damage_claim_filed".
        entity_type: e.g. "payment_claim", "damage_claim".
        title: Short headline shown in the bell dropdown.
        body: Optional longer description.
        entity_id: UUID of the affected entity, for linking to its detail page.
        target_role: Role string (e.g. "nigeria_office_staff") to broadcast to.
        target_user_id: Specific tenant_user.id to target instead of a role.
    """
    try:
        from shared.db import execute_write_with_tenant

        notification_id = str(uuid.uuid4())
        query = """
            INSERT INTO staff_notification (
                id, tenant_id, target_role, target_user_id, event_type,
                entity_type, entity_id, title, body, created_at
            ) VALUES (
                %(id)s, %(tenant_id)s, %(target_role)s, %(target_user_id)s, %(event_type)s,
                %(entity_type)s, %(entity_id)s, %(title)s, %(body)s, %(created_at)s
            )
            RETURNING id
        """
        params: dict[str, Any] = {
            "id": notification_id,
            "tenant_id": tenant_id,
            "target_role": target_role,
            "target_user_id": target_user_id,
            "event_type": event_type,
            "entity_type": entity_type,
            "entity_id": entity_id,
            "title": title,
            "body": body,
            "created_at": datetime.now(UTC).isoformat(),
        }
        execute_write_with_tenant(tenant_id, query, params)
        logger.info(
            "Staff notification written",
            extra={"tenant_id": tenant_id, "event_type": event_type, "notification_id": notification_id},
        )
    except Exception as exc:
        logger.warning(
            "Failed to write staff notification (tenant=%s, event=%s): %s",
            tenant_id,
            event_type,
            exc,
        )
