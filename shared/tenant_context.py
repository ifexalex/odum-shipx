"""Tenant context extraction and validation."""

from dataclasses import dataclass, field
from enum import StrEnum


class UserRole(StrEnum):
    PLATFORM_ADMIN = "platform_admin"
    TENANT_ADMIN = "tenant_admin"
    CHINA_OFFICE_STAFF = "china_office_staff"
    NIGERIA_OFFICE_STAFF = "nigeria_office_staff"
    WAREHOUSE_ATTENDANT = "warehouse_attendant"
    CUSTOMER = "customer"


PLATFORM_TENANT_ID = "PLATFORM"


@dataclass(frozen=True)
class TenantContext:
    """Represents the authenticated user's tenant scope."""

    tenant_id: str
    user_id: str  # Cognito sub
    role: UserRole  # Primary role — used for nav/display and as the single-role fallback
    # Full set of roles assigned to this user (multi-role staff support).
    # Falls back to {role} in __post_init__ when left empty, so any code path
    # that constructs a TenantContext without populating it (e.g. tests) never
    # regresses to "no roles = no permissions".
    roles: frozenset[UserRole] = field(default_factory=frozenset)
    # Impersonation metadata — non-None only when a platform admin is impersonating
    impersonated_by: str | None = None
    session_id: str | None = None
    read_only: bool = False
    # Platform callers only: the caller's ``platform_user`` row id and role (owner, admin, support, finance), resolved
    # from the directory on every request (shared/platform_directory.py). None for tenant users.
    platform_user_id: str | None = None
    platform_role: str | None = None
    is_platform_admin: bool = field(init=False)

    def __post_init__(self) -> None:
        if not self.roles:
            object.__setattr__(self, "roles", frozenset({self.role}))
        object.__setattr__(
            self,
            "is_platform_admin",
            self.tenant_id == PLATFORM_TENANT_ID and UserRole.PLATFORM_ADMIN in self.roles,
        )

    def has_role(self, *allowed_roles: UserRole) -> bool:
        """Return True if any of the user's assigned roles is in `allowed_roles`."""
        return bool(self.roles & set(allowed_roles))

    @property
    def is_customer_only(self) -> bool:
        """True when the caller holds solely the CUSTOMER role (no staff or admin role)."""
        return self.roles == frozenset({UserRole.CUSTOMER})

    def must_scope_to_customer(self, *staff_roles: UserRole) -> bool:
        """True when the caller must be restricted to their own customer records on this endpoint.

        Prevents multi-role privilege escalation (e.g. ``{warehouse_attendant, customer}`` passing
        a route's ``assert_role(TENANT_ADMIN, NIGERIA_OFFICE_STAFF, CUSTOMER)`` via ``CUSTOMER``
        and then bypassing ownership because ``is_customer_only`` is ``False``).
        Pass no ``staff_roles`` on customer-only endpoints to scope unconditionally.
        """
        return not (bool(staff_roles) and self.has_role(*staff_roles))

    def assert_role(self, *allowed_roles: UserRole) -> None:
        """Raise InsufficientPermissionsError if none of the user's roles are allowed."""
        from shared.exceptions import InsufficientPermissionsError

        if not self.has_role(*allowed_roles):
            raise InsufficientPermissionsError(
                action="this operation",
                required_role=" or ".join(r.value for r in allowed_roles),
            )

    def has_platform_permission(self, permission: str) -> bool:
        """True when this is a platform admin whose directory role grants ``permission``."""
        from shared.platform_roles import PlatformPermission, permissions_for

        return self.is_platform_admin and PlatformPermission(permission) in permissions_for(self.platform_role)

    def assert_platform_permission(self, permission: str) -> None:
        """Raise InsufficientPermissionsError unless the platform role grants ``permission``."""
        from shared.exceptions import InsufficientPermissionsError

        if not self.has_platform_permission(permission):
            raise InsufficientPermissionsError(
                f"Your platform role ({self.platform_role or 'none'}) does not allow this ({permission})."
            )

    def assert_tenant_scope(self, target_tenant_id: str) -> None:
        """Verify user can access data for the given tenant."""
        from shared.exceptions import InsufficientPermissionsError

        if not self.is_platform_admin and self.tenant_id != target_tenant_id:
            raise InsufficientPermissionsError(
                action="cross-tenant access",
                required_role=UserRole.PLATFORM_ADMIN.value,
            )
