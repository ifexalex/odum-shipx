"""Audit logging helper.

Writes immutable audit records to the `audit_log` table (defined in Task 05b).
Audit failures are swallowed and logged as WARNING so they never break primary
business operations.
"""

import logging
import uuid
from datetime import datetime, timezone
from typing import Any

logger = logging.getLogger(__name__)


def log_audit(
    tenant_id: str,
    entity_type: str,
    entity_id: str,
    action: str,
    actor_id: str,
    actor_role: str,
    before_state: dict | None = None,
    after_state: dict | None = None,
    ip_address: str | None = None,
) -> None:
    """Insert an audit record into the audit_log table.

    This function is designed to be called after a successful write operation.
    It will NOT raise exceptions — any failure is logged as a warning.

    Args:
        tenant_id: Tenant that owns the entity.
        entity_type: e.g. "packing_list", "claim", "tenant".
        entity_id: UUID of the affected entity.
        action: One of CREATE, UPDATE, DELETE, STATUS_CHANGE.
        actor_id: Cognito sub of the user performing the action.
        actor_role: Role string of the actor.
        before_state: Dict snapshot of the entity before the change (optional).
        after_state: Dict snapshot of the entity after the change (optional).
        ip_address: Source IP address from the request (optional).
    """
    try:
        import json

        from shared.db import execute_write_with_tenant
        from shared.tenant_context import PLATFORM_TENANT_ID

        audit_id = str(uuid.uuid4())
        created_at = datetime.now(timezone.utc).isoformat()

        query = """
            INSERT INTO audit_log (
                id, tenant_id, entity_type, entity_id, action,
                actor_id, actor_role, before_state, after_state,
                ip_address, created_at
            ) VALUES (
                %(id)s, %(tenant_id)s, %(entity_type)s, %(entity_id)s, %(action)s,
                %(actor_id)s, %(actor_role)s, %(before_state)s::jsonb, %(after_state)s::jsonb,
                %(ip_address)s, %(created_at)s
            )
        """
        params: dict[str, Any] = {
            "id": audit_id,
            "tenant_id": tenant_id,
            "entity_type": entity_type,
            "entity_id": entity_id,
            "action": action,
            "actor_id": actor_id,
            "actor_role": actor_role,
            "before_state": json.dumps(before_state, default=str) if before_state else None,
            "after_state": json.dumps(after_state, default=str) if after_state else None,
            "ip_address": ip_address,
            "created_at": created_at,
        }

        # Use PLATFORM scope so audit records are written regardless of tenant RLS
        execute_write_with_tenant(PLATFORM_TENANT_ID, query, params)

        logger.info(
            "Audit record written",
            extra={
                "audit_id": audit_id,
                "tenant_id": tenant_id,
                "entity_type": entity_type,
                "entity_id": entity_id,
                "action": action,
                "actor_id": actor_id,
            },
        )

    except Exception as exc:
        # Audit must never break primary operations
        logger.warning(
            "Failed to write audit record: %s",
            exc,
            extra={
                "tenant_id": tenant_id,
                "entity_type": entity_type,
                "entity_id": entity_id,
                "action": action,
            },
        )
