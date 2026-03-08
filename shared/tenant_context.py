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
    role: UserRole
    is_platform_admin: bool = field(init=False)

    def __post_init__(self) -> None:
        object.__setattr__(self, "is_platform_admin", self.tenant_id == PLATFORM_TENANT_ID)

    def assert_role(self, *allowed_roles: UserRole) -> None:
        """Raise InsufficientPermissionsError if user doesn't have one of the allowed roles."""
        from shared.exceptions import InsufficientPermissionsError

        if self.role not in allowed_roles:
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
