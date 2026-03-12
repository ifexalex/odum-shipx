"""JWT authorizer claim extraction and role-based access control.

Extracts TenantContext from API Gateway event authorizer claims (Cognito JWT).
See 00_CROSS_CUTTING_STANDARDS.md §8 for security standards.
"""

import logging
from collections.abc import Callable
from functools import wraps
from typing import Any

from shared.distributed_cache import DistributedCache
from shared.exceptions import (
    AuthenticationRequiredError,
    ResourceNotFoundError,
    TenantOffboardedError,
    TenantSuspendedError,
)
from shared.tenant_context import PLATFORM_TENANT_ID, TenantContext, UserRole

logger = logging.getLogger(__name__)

# Role values that are valid (used for parsing cognito:groups)
_VALID_ROLES: set[str] = {r.value for r in UserRole}

# Distributed Redis cache for tenant status — consistent across all Lambda instances.
# TTL 60s. On Redis failure, get() returns None and the caller falls through to DB.
_tenant_status_cache: DistributedCache = DistributedCache(default_ttl=15, key_prefix="tenant_status:")


def get_tenant_context(event: dict[str, Any]) -> TenantContext:
    """Extract and validate tenant context from an API Gateway proxy event.

    Reads JWT claims injected by Cognito authorizer at:
        event["requestContext"]["authorizer"]["claims"]

    Cognito JWT claim structure:
        sub               → user_id
        custom:tenant_id  → tenant_id
        cognito:groups    → comma-separated list of "{tenant_id}:{role}" strings
    """
    try:
        authorizer: dict[str, Any] = event.get("requestContext", {}).get("authorizer", {})
        # HTTP API v2 JWT authorizer: requestContext.authorizer.jwt.claims
        # REST API v1 / local simulation: requestContext.authorizer.claims
        claims: dict[str, Any] = authorizer.get("jwt", {}).get("claims", {}) or authorizer.get("claims", {})
        if not claims:
            raise AuthenticationRequiredError()

        user_id: str = claims.get("sub", "")
        tenant_id: str = claims.get("custom:tenant_id", "")

        if not user_id or not tenant_id:
            raise AuthenticationRequiredError()

        role = _parse_role(claims, tenant_id)

    except AuthenticationRequiredError:
        raise
    except Exception as exc:
        logger.warning("Failed to parse JWT claims: %s", exc)
        raise AuthenticationRequiredError() from exc

    # Tenant suspension check with 60s in-memory cache
    if tenant_id != PLATFORM_TENANT_ID:
        _check_tenant_active(tenant_id)

    return TenantContext(tenant_id=tenant_id, user_id=user_id, role=role)


def _parse_role(claims: dict[str, Any], tenant_id: str) -> UserRole:
    """Extract role from cognito:groups claim.

    Groups format: "{tenant_id}:{role}" e.g. "abc-123:tenant_admin"
    Platform admins belong to the "platform_admin" group (no tenant prefix).
    Falls back to UserRole.CUSTOMER if no matching group is found.
    """
    groups_raw: str = claims.get("cognito:groups", "") or ""

    # Handle both comma-separated string and JSON array string
    if groups_raw.startswith("["):
        import json

        try:
            groups: list[str] = json.loads(groups_raw)
        except ValueError:
            groups = []
    else:
        groups = [g.strip() for g in groups_raw.split(",") if g.strip()]

    # Platform admin group has no tenant prefix
    if "platform_admin" in groups:
        return UserRole.PLATFORM_ADMIN

    # Find first group that matches "{tenant_id}:{role}"
    prefix = f"{tenant_id}:"
    for group in groups:
        if group.startswith(prefix):
            role_str = group[len(prefix) :]
            if role_str in _VALID_ROLES:
                return UserRole(role_str)

    return UserRole.CUSTOMER


def _check_tenant_active(tenant_id: str) -> None:
    """Check whether a tenant is active. Raises TenantSuspendedError or
    TenantOffboardedError if not.

    Results are cached for 60 seconds per tenant to avoid a DB hit on every
    request. Silently passes if the DB is unavailable (fail-open).
    """
    # Check cache first
    cached_status = _tenant_status_cache.get(tenant_id)
    if cached_status is not None:
        if cached_status == "suspended":
            raise TenantSuspendedError(tenant_id)
        if cached_status == "offboarded":
            raise TenantOffboardedError(tenant_id)
        if cached_status == "not_found":
            raise ResourceNotFoundError("tenant", tenant_id)
        return

    try:
        from shared.db import execute_with_tenant

        rows = execute_with_tenant(
            tenant_id=PLATFORM_TENANT_ID,  # admin scope to bypass RLS for status check
            query="SELECT status FROM tenant WHERE id = %s LIMIT 1",
            params=(tenant_id,),
        )
        if not rows:
            _tenant_status_cache.set(tenant_id, "not_found")
            raise ResourceNotFoundError("tenant", tenant_id)
        status: str = rows[0]["status"]
        _tenant_status_cache.set(tenant_id, status)
        if status == "suspended":
            raise TenantSuspendedError(tenant_id)
        if status == "offboarded":
            raise TenantOffboardedError(tenant_id)
    except (TenantSuspendedError, TenantOffboardedError, ResourceNotFoundError):
        raise
    except Exception as exc:
        # DB unavailable — fail-closed: deny the request rather than allowing
        # a suspended/offboarded tenant through during an outage.
        logger.error(
            "Tenant status check failed for %s — denying request (fail-closed): %s",
            tenant_id,
            exc,
        )
        from shared.exceptions import ServiceUnavailableError

        raise ServiceUnavailableError("Tenant status check unavailable") from exc


def require_roles(*roles: UserRole) -> Callable[..., Any]:
    """Decorator: validates the caller has one of the specified roles.

    Injects a `tenant_ctx` keyword argument into the decorated function.
    The decorated function MUST accept `event` as its first positional argument.

    Usage:
        @require_roles(UserRole.TENANT_ADMIN, UserRole.PLATFORM_ADMIN)
        def handler(event, context, *, tenant_ctx: TenantContext):
            ...
    """

    def decorator(func: Callable[..., Any]) -> Callable[..., Any]:
        @wraps(func)
        def wrapper(event: dict[str, Any], *args: Any, **kwargs: Any) -> Any:
            ctx = get_tenant_context(event)
            ctx.assert_role(*roles)
            return func(event, *args, tenant_ctx=ctx, **kwargs)

        return wrapper

    return decorator
