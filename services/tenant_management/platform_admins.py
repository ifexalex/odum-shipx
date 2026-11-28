"""The platform admin directory: who can run the console, and with which role (platform audit C-28, decision D2).

Owners invite, re-role, disable and re-enable admins. Two rules keep the console from locking itself out: nobody
changes or disables their own account here, and the last active owner cannot be demoted or disabled.
"""

import logging
from typing import Any

from shared.exceptions import (
    BusinessRuleViolationError,
    DuplicateResourceError,
    ResourceNotFoundError,
)
from shared.platform_audit import PlatformAuditAction, insert_platform_audit
from shared.platform_directory import evict_platform_caller
from shared.platform_roles import PlatformRole, permissions_for
from shared.providers import get_identity_provider
from shared.tenant_context import PLATFORM_TENANT_ID, TenantContext, UserRole

from . import platform_repository as prepo
from .models import InvitePlatformAdminRequest, UpdatePlatformAdminRequest

logger = logging.getLogger(__name__)

_PLATFORM_GROUP = "platform_admin"


def _public(row: dict[str, Any]) -> dict[str, Any]:
    """The admin as the console sees it: the identity-provider subject stays server-side."""
    return {k: v for k, v in row.items() if k != "subject"}


def get_me(ctx: TenantContext) -> dict[str, Any]:
    """The caller's own directory row and the permissions their role grants."""
    if not ctx.platform_user_id:
        raise ResourceNotFoundError("platform_user", ctx.user_id)
    row = prepo.get_platform_user(ctx.platform_user_id)
    if row is None:
        raise ResourceNotFoundError("platform_user", ctx.platform_user_id)
    return {**_public(row), "permissions": sorted(p.value for p in permissions_for(row["role"]))}


def list_admins() -> list[dict[str, Any]]:
    """Every platform admin, owners first."""
    return [_public(row) for row in prepo.list_platform_users()]


def invite_admin(ctx: TenantContext, req: InvitePlatformAdminRequest, ip_address: str | None = None) -> dict[str, Any]:
    """Create the identity-provider account in the platform group and an ``invited`` directory row.

    The identity provider emails the temporary password; the row becomes ``active`` on the person's first request.

    Raises:
        DuplicateResourceError: The email is already in the directory, or already has a ShipX sign-in (one identity
            is never both a tenant user and a platform admin).
    """
    if prepo.get_platform_user_by_email(req.email):
        raise DuplicateResourceError("platform admin", req.email)

    idp = get_identity_provider()
    subject = idp.create_user(email=req.email, full_name=req.name, tenant_id=PLATFORM_TENANT_ID, role=UserRole.PLATFORM_ADMIN)
    idp.create_group_if_not_exists(_PLATFORM_GROUP)
    idp.add_user_to_group(req.email, _PLATFORM_GROUP)

    row = prepo.insert_platform_user(subject, req.email, req.name, req.role.value, ctx.platform_user_id)
    _audit(
        PlatformAuditAction.PLATFORM_ADMIN_INVITED,
        ctx,
        ip_address,
        details={"platform_user_id": str(row["id"])},
        after={"email": req.email, "name": req.name, "role": req.role.value, "status": "invited"},
    )
    return _public(row)


def update_admin(
    ctx: TenantContext,
    platform_user_id: str,
    req: UpdatePlatformAdminRequest,
    ip_address: str | None = None,
) -> dict[str, Any]:
    """Change an admin's role, and/or disable or re-enable them.

    Raises:
        ResourceNotFoundError: No such admin.
        BusinessRuleViolationError: The change targets the caller, or would leave no active owner.
    """
    target = prepo.get_platform_user(platform_user_id)
    if target is None:
        raise ResourceNotFoundError("platform admin", platform_user_id)
    if str(target["id"]) == ctx.platform_user_id:
        raise BusinessRuleViolationError("You cannot change your own platform access.", rule_id="PLATFORM_ADMIN_SELF_CHANGE")

    new_role = req.role.value if req.role is not None else None
    new_status = _target_status(target, req.disabled)
    losing_owner = target["role"] == PlatformRole.OWNER and target["status"] == "active"
    demoting_owner = losing_owner and ((new_role and new_role != PlatformRole.OWNER) or new_status == "disabled")
    if demoting_owner and prepo.count_active_owners() <= 1:
        raise BusinessRuleViolationError(
            "This is the last active owner. Make someone else an owner first.", rule_id="PLATFORM_LAST_OWNER"
        )

    changes = {k: v for k, v in {"role": new_role, "status": new_status}.items() if v is not None and v != target[k]}
    if not changes:
        return _public(target)

    if changes.get("status") == "disabled":
        _cut_off(target)
    elif "status" in changes:
        get_identity_provider().enable_user(target["email"])

    updated = prepo.update_platform_user(platform_user_id, **changes)
    if updated is None:
        raise ResourceNotFoundError("platform admin", platform_user_id)
    evict_platform_caller(target.get("subject"))

    before = {k: target[k] for k in changes}
    if "role" in changes:
        _audit(
            PlatformAuditAction.PLATFORM_ADMIN_ROLE_CHANGED,
            ctx,
            ip_address,
            {"platform_user_id": platform_user_id},
            before={"role": target["role"]},
            after={"role": changes["role"]},
        )
    if "status" in changes:
        action = (
            PlatformAuditAction.PLATFORM_ADMIN_DISABLED
            if changes["status"] == "disabled"
            else PlatformAuditAction.PLATFORM_ADMIN_ENABLED
        )
        _audit(
            action,
            ctx,
            ip_address,
            {"platform_user_id": platform_user_id},
            before={"status": before["status"]},
            after={"status": changes["status"]},
        )
    return _public(updated)


def _target_status(target: dict[str, Any], disabled: bool | None) -> str | None:
    if disabled is None:
        return None
    if disabled:
        return "disabled"
    # Re-enabled: back to active if they had signed in before, else still waiting on their first sign-in.
    return "active" if target.get("last_seen_at") else "invited"


def _cut_off(target: dict[str, Any]) -> None:
    """Disable the identity-provider account and end its sessions. The directory status is what denies a live token;
    the sign-out stops the session being renewed, so it is best effort."""
    idp = get_identity_provider()
    idp.disable_user(target["email"])
    try:
        idp.global_sign_out(target["email"])
    except Exception as exc:
        logger.warning("Session sign-out failed for platform admin %s: %s", target["id"], exc)


def _audit(
    action: PlatformAuditAction,
    ctx: TenantContext,
    ip_address: str | None,
    details: dict[str, Any],
    *,
    before: dict[str, Any] | None = None,
    after: dict[str, Any] | None = None,
) -> None:
    try:
        insert_platform_audit(
            action=action,
            actor_id=ctx.user_id,
            target_tenant_id=None,
            details=details,
            ip_address=ip_address,
            before_state=before,
            after_state=after,
        )
    except Exception as exc:
        logger.warning("Platform audit insert failed for %s: %s", action, exc)
