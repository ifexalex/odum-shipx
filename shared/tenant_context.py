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
    is_platform_admin: bool = field(init=False)

    def __post_init__(self) -> None:
        object.__setattr__(self, "is_platform_admin", self.tenant_id == PLATFORM_TENANT_ID)
        if not self.roles:
            object.__setattr__(self, "roles", frozenset({self.role}))

    def assert_role(self, *allowed_roles: UserRole) -> None:
        """Raise InsufficientPermissionsError if none of the user's roles are allowed."""
        from shared.exceptions import InsufficientPermissionsError

        if not (self.roles & set(allowed_roles)):
            raise InsufficientPermissionsError(
                action="this operation",
                required_role=" or ".join(r.value for r in allowed_roles),
            )

    def assert_tenant_scope(self, target_tenant_id: str) -> None:
        """Verify user can access data for the given tenant."""
        from shared.exceptions import InsufficientPermissionsError

        if not self.is_platform_admin and self.tenant_id != target_tenant_id:
            raise InsufficientPermissionsError(
                action="cross-tenant access",
                required_role=UserRole.PLATFORM_ADMIN.value,
            )
