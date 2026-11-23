"""The platform's own audit trail (``platform_audit_log``): what platform admins and platform jobs did to a tenant.

Distinct from ``shared.audit.log_audit``, which writes a tenant's own trail. Platform scope.
"""

import json
from typing import Any

from shared.db import execute_write_with_tenant
from shared.observability import record_failure
from shared.tenant_context import PLATFORM_TENANT_ID


def insert_platform_audit(
    action: str,
    actor_id: str | None,
    target_tenant_id: str | None,
    details: dict[str, Any] | None = None,
    ip_address: str | None = None,
) -> None:
    """Record one platform action. ``actor_id`` is ``None`` for a platform job.

    Raises on failure (a caller such as the export download link must not proceed without the record); the failure is
    counted here, once, as ``audit_write`` (audit OPS-04), whatever the caller then does with it.
    """
    try:
        _insert(action, actor_id, target_tenant_id, details, ip_address)
    except Exception:
        record_failure("audit_write")
        raise


def _insert(
    action: str,
    actor_id: str | None,
    target_tenant_id: str | None,
    details: dict[str, Any] | None,
    ip_address: str | None,
) -> None:
    execute_write_with_tenant(
        PLATFORM_TENANT_ID,
        """
        INSERT INTO platform_audit_log (action, actor_id, target_tenant_id, details, ip_address)
        VALUES (%(action)s, %(actor_id)s, %(target_tenant_id)s, %(details)s::jsonb, %(ip_address)s)
        RETURNING id
        """,
        {
            "action": action,
            "actor_id": actor_id,
            "target_tenant_id": target_tenant_id,
            "details": json.dumps(details) if details else None,
            "ip_address": ip_address,
        },
    )
