"""Platform admin roles and what each may do (platform audit C-28, decision D2).

Every platform admin holds exactly one role from ``platform_user.role``. Routes ask for a permission, never a role, so
the matrix below is the single place that says who can do what.
"""

from enum import StrEnum


class PlatformRole(StrEnum):
    """A platform admin's role, as stored in ``platform_user.role``."""

    OWNER = "owner"
    ADMIN = "admin"
    SUPPORT = "support"
    FINANCE = "finance"


class PlatformPermission(StrEnum):
    """One thing a platform route needs its caller to be allowed to do."""

    READ = "read"  # every GET: tenants, usage, audit, settings (secrets masked), approvals
    TENANT_LIFECYCLE = "tenant_lifecycle"  # create, edit, suspend, activate, reactivate, offboard, exports
    SUPPORT = "support"  # impersonate a tenant (read-only), end a session, work onboarding leads
    PLANS = "plans"  # plan limits and per-tenant quota overrides
    SETTINGS = "settings"  # general settings, maintenance mode, provider gateways
    ADMINS = "admins"  # invite, re-role, disable and re-enable platform admins
    APPROVE = "approve"  # decide another admin's two-person request


_ALL = frozenset(PlatformPermission)

ROLE_PERMISSIONS: dict[PlatformRole, frozenset[PlatformPermission]] = {
    PlatformRole.OWNER: _ALL,
    PlatformRole.ADMIN: _ALL - {PlatformPermission.ADMINS},
    PlatformRole.SUPPORT: frozenset({PlatformPermission.READ, PlatformPermission.SUPPORT}),
    PlatformRole.FINANCE: frozenset({PlatformPermission.READ}),
}

# Roles that count as a second pair of hands for a two-person approval (decision D4).
APPROVER_ROLES: frozenset[PlatformRole] = frozenset(
    role for role, perms in ROLE_PERMISSIONS.items() if PlatformPermission.APPROVE in perms
)


def permissions_for(role: str | None) -> frozenset[PlatformPermission]:
    """Return the permissions a role grants; an unknown or missing role grants none."""
    try:
        return ROLE_PERMISSIONS[PlatformRole(role)] if role else frozenset()
    except ValueError:
        return frozenset()
