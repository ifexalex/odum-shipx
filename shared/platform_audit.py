"""The platform's own audit trail (``platform_audit_log``): what platform admins and platform jobs did.

Distinct from ``shared.audit.log_audit``, which writes a tenant's own trail. Platform scope.
"""

import json
from enum import StrEnum
from typing import Any

from shared.audit import _mask_sensitive
from shared.db import execute_write_with_tenant
from shared.logging_config import current_request_id
from shared.observability import record_failure
from shared.tenant_context import PLATFORM_TENANT_ID


class PlatformAuditAction(StrEnum):
    """Every ``action`` value written to ``platform_audit_log``.

    The platform console's audit filter offers exactly these (``frontend/src/api/platformAuditActions.ts``);
    ``tests/unit/test_platform_audit_actions.py`` fails when the code writes a value missing here, or when the two lists
    differ. Before 2026-11-28 three filter options matched nothing (audit PA-05).
    """

    TENANT_CREATED = "TENANT_CREATED"
    TENANT_UPDATED = "TENANT_UPDATED"
    TENANT_SUSPENDED = "TENANT_SUSPENDED"
    TENANT_ACTIVATED = "TENANT_ACTIVATED"
    TENANT_OFFBOARDED = "TENANT_OFFBOARDED"
    TENANT_REACTIVATED = "TENANT_REACTIVATED"
    TENANT_EXPORT_QUEUED = "TENANT_EXPORT_QUEUED"
    TENANT_DATA_EXPORTED = "TENANT_DATA_EXPORTED"
    TENANT_EXPORT_LINK_ISSUED = "TENANT_EXPORT_LINK_ISSUED"
    IMPERSONATION_START = "IMPERSONATION_START"
    IMPERSONATION_END = "IMPERSONATION_END"
    QUOTA_OVERRIDE_SET = "QUOTA_OVERRIDE_SET"
    QUOTA_OVERRIDE_CLEARED = "QUOTA_OVERRIDE_CLEARED"
    PLAN_LIMITS_UPDATED = "PLAN_LIMITS_UPDATED"
    SETTINGS_UPDATED = "SETTINGS_UPDATED"
    GATEWAY_SETTINGS_UPDATED = "GATEWAY_SETTINGS_UPDATED"
    ONBOARDING_REQUEST_UPDATED = "ONBOARDING_REQUEST_UPDATED"
    # Platform admin directory (Phase 1, C-28)
    PLATFORM_ADMIN_ENROLLED = "PLATFORM_ADMIN_ENROLLED"
    PLATFORM_ADMIN_INVITED = "PLATFORM_ADMIN_INVITED"
    PLATFORM_ADMIN_ROLE_CHANGED = "PLATFORM_ADMIN_ROLE_CHANGED"
    PLATFORM_ADMIN_DISABLED = "PLATFORM_ADMIN_DISABLED"
    PLATFORM_ADMIN_ENABLED = "PLATFORM_ADMIN_ENABLED"
    STEP_UP_VERIFIED = "STEP_UP_VERIFIED"
    # Two-person approvals (Phase 1, C-30)
    APPROVAL_REQUESTED = "APPROVAL_REQUESTED"
    APPROVAL_APPROVED = "APPROVAL_APPROVED"
    APPROVAL_REJECTED = "APPROVAL_REJECTED"
    APPROVAL_CANCELLED = "APPROVAL_CANCELLED"
    APPROVAL_SCHEDULED = "APPROVAL_SCHEDULED"
    APPROVAL_EXECUTED = "APPROVAL_EXECUTED"
    APPROVAL_FAILED = "APPROVAL_FAILED"
    APPROVAL_EXPIRED = "APPROVAL_EXPIRED"


def insert_platform_audit(
    action: str,
    actor_id: str | None,
    target_tenant_id: str | None,
    details: dict[str, Any] | None = None,
    ip_address: str | None = None,
    *,
    before_state: dict[str, Any] | None = None,
    after_state: dict[str, Any] | None = None,
) -> None:
    """Record one platform action. ``actor_id`` is ``None`` for a platform job.

    ``before_state`` / ``after_state`` are what changed, with secrets already masked by the caller. The request id is
    taken from the bound log context, so no caller threads it.

    Raises on failure (a caller such as the export download link must not proceed without the record); the failure is
    counted here, once, as ``audit_write`` (audit OPS-04), whatever the caller then does with it.
    """
    try:
        execute_write_with_tenant(
            PLATFORM_TENANT_ID,
            """
            INSERT INTO platform_audit_log
                (action, actor_id, target_tenant_id, details, ip_address, before_state, after_state, request_id)
            VALUES (%(action)s, %(actor_id)s, %(target_tenant_id)s, %(details)s::jsonb, %(ip_address)s,
                    %(before_state)s::jsonb, %(after_state)s::jsonb, %(request_id)s)
            RETURNING id
            """,
            {
                "action": str(action),
                "actor_id": actor_id,
                "target_tenant_id": target_tenant_id,
                "details": _json(details),
                "ip_address": ip_address,
                "before_state": _json(before_state),
                "after_state": _json(after_state),
                "request_id": current_request_id(),
            },
        )
    except Exception:
        record_failure("audit_write")
        raise


def _json(value: dict[str, Any] | None) -> str | None:
    """Serialise with sensitive fields masked (``shared.audit._mask_sensitive``, #195): details and both states."""
    masked = _mask_sensitive(value) if value else None
    return json.dumps(masked, default=str) if masked else None
