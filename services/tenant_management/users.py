"""Staff users.

Creation within the plan's user limit, reads, role and profile updates, deactivation, and the invite and password-reset
emails.

Split out of ``service.py`` (audit BE-13); ``service`` re-exports every public function, so callers are unchanged.
"""

import logging
from typing import TYPE_CHECKING, Any

from shared.audit import log_audit
from shared.auth import evict_identity_cache
from shared.exceptions import (
    BusinessRuleViolationError,
    DuplicateResourceError,
    ResourceNotFoundError,
    UsageLimitExceededError,
)
from shared.metering import record_usage
from shared.providers import get_identity_provider

from . import repository as repo
from .models import (
    CreateTenantUserRequest,
)

if TYPE_CHECKING:
    pass
from .activation import _audit_access_email, issue_activation
from .tenants import get_tenant

logger = logging.getLogger(__name__)


TIER_USER_LIMITS: dict[str, int] = {
    "starter": 10,
    "business": 50,
    "enterprise": 500,
}


# ---------------------------------------------------------------------------
# User management
# ---------------------------------------------------------------------------


def create_user(
    tenant_id: str,
    req: CreateTenantUserRequest,
    actor_id: str,
    request_id: str = "",
    ip_address: str | None = None,
) -> dict[str, Any]:
    from shared.tier_limits import get_effective_limits

    # Check effective plan + override limits (not hardcoded constants).
    tenant = get_tenant(tenant_id)
    tier = tenant["subscription_tier"]
    limit = int(get_effective_limits(tier, tenant_id)["users"])
    current_count = repo.count_active_users(tenant_id)
    if current_count >= limit:
        raise UsageLimitExceededError("users", current_count, limit)

    # Check duplicate email within tenant and across tenants (before touching IdP
    # so Entra conflict reuse cannot pollute another tenant's user's groups).
    if repo.get_user_by_email(tenant_id, req.email) or repo.find_user_across_tenants(email=req.email):
        raise DuplicateResourceError("user", req.email)

    role_values = [r.value for r in req.roles]
    primary_role_value = req.primary_role.value if req.primary_role is not None else role_values[0]

    # Provision Cognito
    cognito = get_identity_provider()
    cognito_sub = cognito.create_user(
        email=req.email,
        full_name=req.full_name,
        tenant_id=tenant_id,
        role=primary_role_value,
    )

    # `tenant_user.id` IS the IdP subject, so one identity belongs to exactly one
    # tenant. If the IdP resolved to an account already attached to a tenant_user
    # row, conflict clearly instead of violating tenant_user_pkey.
    if repo.find_user_across_tenants(user_id=cognito_sub):
        raise DuplicateResourceError("user", req.email)

    # Insert tenant_user (primary role only — tenant_user.role is the
    # single-role-shaped source of truth every existing query reads directly)
    user = repo.create_tenant_user(
        tenant_id,
        {
            "tenant_id": tenant_id,
            "cognito_sub": cognito_sub,
            "email": req.email,
            "full_name": req.full_name,
            "role": primary_role_value,
            "created_by": actor_id,
        },
    )
    if user is None:
        raise RuntimeError("create_tenant_user returned None unexpectedly")
    user_id = str(user["id"])

    # Populate tenant_user_role with the full assigned role set (N=1 for a
    # single-role invite) and reconcile Cognito group membership to match —
    # sync_user_groups replaces the old single create_group/add_user_to_group
    # pair and is the same "diff and reconcile" operation used by update_user.
    user = repo.set_user_roles(tenant_id, user_id, role_values, primary_role_value, assigned_by=actor_id) or user
    cognito.sync_user_groups(req.email, tenant_id, set(role_values))

    # Link customer record if customer is one of the assigned roles
    if "customer" in role_values:
        try:
            repo.link_customer_user(tenant_id, req.email, user_id)
        except Exception as exc:
            logger.warning("Customer link failed: %s", exc)

    log_audit(
        tenant_id=tenant_id,
        entity_type="tenant_user",
        entity_id=user_id,
        action="CREATE",
        actor_id=actor_id,
        actor_role="tenant_admin",
        after_state=user,
        ip_address=ip_address,
    )
    try:
        record_usage(tenant_id, "users_active", 1.0, request_id=request_id)
    except Exception as exc:
        logger.warning("Metering record failed: %s", exc)

    # Operator-provisioned users have a random IdP password and no login — send
    # the ShipX activation link so they set their own password (all roles).
    # Best-effort: the user is committed and the link can be resent.
    try:
        issue_activation(tenant_id, user_id, req.email, req.full_name, created_by=actor_id, request_id=request_id)
    except Exception as exc:
        logger.warning("Activation link issuance failed for user %s: %s", user_id, exc)

    return user


def list_users(tenant_id: str) -> list[dict[str, Any]]:
    return repo.list_users(tenant_id)


def get_user(tenant_id: str, user_id: str) -> dict[str, Any]:
    user = repo.get_user_by_id(tenant_id, user_id)
    if not user:
        raise ResourceNotFoundError("user", user_id)
    return user


def get_user_by_cognito_sub(tenant_id: str, cognito_sub: str) -> dict[str, Any]:
    """Return tenant_user by Cognito sub (used for self-service profile updates)."""
    user = repo.get_user_by_cognito_sub(tenant_id, cognito_sub)
    if user is None:
        raise ResourceNotFoundError("tenant_user", cognito_sub)
    return user


def update_user(
    tenant_id: str,
    user_id: str,
    updates: dict[str, Any],
    actor_id: str,
    ip_address: str | None = None,
    actor_role: str = "tenant_admin",
) -> dict[str, Any]:
    from services.tenant_management.repository import _SUPPORTED_LOCALES

    if "locale" in updates and updates["locale"] not in _SUPPORTED_LOCALES:
        raise BusinessRuleViolationError(
            f"Unsupported locale '{updates['locale']}' — must be one of: {sorted(_SUPPORTED_LOCALES)}",
            rule_id="UNSUPPORTED_LOCALE",
        )
    existing = get_user(tenant_id, user_id)
    if not updates:
        return existing

    # roles/primary_role touch tenant_user_role + Cognito group membership,
    # not a plain tenant_user column — handled separately from the generic
    # SET-clause update below (replaces the old dead-end
    # cognito.update_user_attributes(role=...)-only path that never actually
    # synced Cognito groups).
    roles = updates.pop("roles", None)
    primary_role = updates.pop("primary_role", None)
    new_primary: str | None = primary_role or (roles[0] if roles else None)

    # Guard against removing tenant_admin from the sole remaining active admin
    # (prevents permanent tenant lockout).
    if roles is not None:
        existing_roles = set(existing.get("roles") or [existing.get("role")])
        if (
            "tenant_admin" in existing_roles
            and "tenant_admin" not in set(roles)
            and repo.count_active_tenant_admins(tenant_id, exclude_user_id=user_id) < 1
        ):
            raise BusinessRuleViolationError(
                "Cannot remove tenant_admin from the sole remaining active administrator",
                rule_id="LAST_TENANT_ADMIN",
            )

    updated = existing
    if updates:
        result = repo.update_user(tenant_id, user_id, updates)
        if result is None:
            raise RuntimeError("update_user returned None unexpectedly")
        updated = result

    cognito = get_identity_provider()

    # Sync mutable Cognito attributes (name, primary role) — username/email is immutable
    if "full_name" in updates or new_primary is not None:
        cognito.update_user_attributes(
            username=existing["email"],
            full_name=updates.get("full_name"),
            role=new_primary,
        )

    if roles is not None and new_primary is not None:
        updated = repo.set_user_roles(tenant_id, user_id, roles, new_primary, assigned_by=actor_id) or updated
        # Reconcile Cognito group membership to match the new role set — the
        # actual fix for the bug where role changes never touched groups.
        cognito.sync_user_groups(existing["email"], tenant_id, set(roles))
        # Invalidate existing sessions so the new group membership / primary
        # role claim takes effect immediately rather than after JWT expiry.
        if existing.get("email"):
            try:
                cognito.global_sign_out(existing["email"])
            except Exception as exc:
                logger.warning("Session invalidation failed for user %s: %s", user_id, exc)
        # The identity cache holds the role for tokens that carry none.
        evict_identity_cache(user_id)

    log_audit(
        tenant_id=tenant_id,
        entity_type="tenant_user",
        entity_id=user_id,
        action="UPDATE",
        actor_id=actor_id,
        actor_role=actor_role,
        before_state=existing,
        after_state=updated,
        ip_address=ip_address,
    )
    return updated


def _revoke_login(tenant_id: str, user: dict[str, Any]) -> dict[str, Any]:
    """Cut a user's access off now and return their updated `tenant_user` row.

    Disables the identity-provider account, marks the row `deactivated`, ends their sessions
    and drops the cached identity. The row status is what denies a token that was already
    issued (`shared.auth._check_user_active` reads it on every request); the sign-out also
    revokes the refresh token so the session cannot be renewed, and is best effort because
    the status check does not depend on it.
    """
    user_id = str(user["id"])
    email = user.get("email")
    cognito = get_identity_provider()
    if email:
        cognito.disable_user(email)

    updated = repo.set_user_status(tenant_id, user_id, "deactivated")
    if updated is None:
        raise RuntimeError("set_user_status returned None unexpectedly")

    if email:
        try:
            cognito.global_sign_out(email)
        except Exception as exc:
            logger.warning("Session invalidation failed for user %s: %s", user_id, exc)
    # After the commit above, so the next request reads the new status instead of the old one.
    evict_identity_cache(user_id)
    return updated


def deactivate_user(
    tenant_id: str,
    user_id: str,
    actor_id: str,
    ip_address: str | None = None,
    actor_role: str = "tenant_admin",
) -> dict[str, Any]:
    existing = get_user(tenant_id, user_id)
    if existing["status"] == "deactivated":
        raise BusinessRuleViolationError("User is already deactivated")
    if str(existing["id"]) == str(actor_id):
        raise BusinessRuleViolationError("You cannot deactivate your own account", rule_id="SELF_DEACTIVATION_FORBIDDEN")
    existing_roles = set(existing.get("roles") or [existing.get("role")])
    if "tenant_admin" in existing_roles and repo.count_active_tenant_admins(tenant_id, exclude_user_id=user_id) < 1:
        raise BusinessRuleViolationError(
            "Cannot deactivate the sole remaining active tenant administrator",
            rule_id="LAST_TENANT_ADMIN",
        )

    updated = _revoke_login(tenant_id, existing)
    log_audit(
        tenant_id=tenant_id,
        entity_type="tenant_user",
        entity_id=user_id,
        action="STATUS_CHANGE",
        actor_id=actor_id,
        actor_role=actor_role,
        before_state={"status": "active"},
        after_state={"status": "deactivated"},
        ip_address=ip_address,
    )
    return updated


def reactivate_user(
    tenant_id: str,
    user_id: str,
    actor_id: str,
    ip_address: str | None = None,
    actor_role: str = "tenant_admin",
) -> dict[str, Any]:
    """Bring a deactivated staff user back, in both the directory and the database.

    Re-checks the tenant's seat limit before re-enabling the user in the identity
    provider or database so deactivation cannot be used to bypass plan limits.
    """
    existing = get_user(tenant_id, user_id)
    if existing["status"] != "deactivated":
        raise BusinessRuleViolationError(f"User is not deactivated (status: {existing['status']})")

    tenant = get_tenant(tenant_id)
    limit = TIER_USER_LIMITS.get(tenant["subscription_tier"], 10)
    current_count = repo.count_active_users(tenant_id)
    if current_count >= limit:
        raise UsageLimitExceededError("users", current_count, limit)

    cognito = get_identity_provider()
    if existing.get("email"):
        cognito.enable_user(existing["email"])

    updated = repo.set_user_status(tenant_id, user_id, "active")
    if updated is None:
        raise RuntimeError("set_user_status returned None unexpectedly")

    evict_identity_cache(user_id)

    log_audit(
        tenant_id=tenant_id,
        entity_type="tenant_user",
        entity_id=user_id,
        action="STATUS_CHANGE",
        actor_id=actor_id,
        actor_role=actor_role,
        before_state={"status": "deactivated"},
        after_state={"status": "active"},
        ip_address=ip_address,
    )
    return updated


def resend_user_invite(
    tenant_id: str,
    user_id: str,
    actor_id: str | None = None,
    actor_role: str = "tenant_admin",
    ip_address: str | None = None,
) -> None:
    """Resend the identity provider's temporary-password email for an active staff user, and audit it."""
    user = get_user(tenant_id, user_id)
    if user.get("status") != "active":
        raise BusinessRuleViolationError("Cannot resend invite for an inactive user", rule_id="USER_NOT_ACTIVE")
    get_identity_provider().resend_invite(user["email"])
    _audit_access_email(tenant_id, user_id, "INVITE_RESENT", actor_id, actor_role, ip_address)


def reset_user_password(
    tenant_id: str,
    user_id: str,
    actor_id: str | None = None,
    actor_role: str = "tenant_admin",
    ip_address: str | None = None,
) -> None:
    """Trigger the identity provider's password-reset email for an active staff user, and audit it."""
    user = get_user(tenant_id, user_id)
    if user.get("status") != "active":
        raise BusinessRuleViolationError("Cannot reset password for an inactive user", rule_id="USER_NOT_ACTIVE")
    get_identity_provider().reset_password(user["email"])
    _audit_access_email(tenant_id, user_id, "PASSWORD_RESET_SENT", actor_id, actor_role, ip_address)
