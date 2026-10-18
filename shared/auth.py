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
from shared.logging_config import bind_log_context
from shared.providers import get_claims_mapper
from shared.tenant_context import PLATFORM_TENANT_ID, TenantContext, UserRole

logger = logging.getLogger(__name__)

# Role values that are valid (used for parsing cognito:groups)
_VALID_ROLES: set[str] = {r.value for r in UserRole}

# Distributed Redis cache for tenant status — consistent across all Lambda instances.
# TTL 60s. On Redis failure, get() returns None and the caller falls through to DB.
_tenant_status_cache: DistributedCache = DistributedCache(default_ttl=15, key_prefix="tenant_status:")
# Subject (IdP oid/sub) → "{tenant_id}:{role}", for tokens that carry no tenant
# claim. See _resolve_identity_from_db.
_identity_cache: DistributedCache = DistributedCache(default_ttl=60, key_prefix="identity:")


def get_tenant_context(event: dict[str, Any]) -> TenantContext:
    """Extract and validate tenant context from an API Gateway proxy event.

    Reads JWT claims injected by the authorizer at:
        event["requestContext"]["authorizer"]["claims"]   (REST API v1 / local)
        event["requestContext"]["authorizer"]["jwt"]["claims"]  (HTTP API v2 JWT)
        event["requestContext"]["authorizer"]["<key>"]   (REQUEST authorizer context)

    Cognito JWT claim structure:
        sub               → user_id
        custom:tenant_id  → tenant_id
        cognito:groups    → comma-separated list of "{tenant_id}:{role}" strings

    Impersonation tokens additionally carry:
        impersonated_by   → platform_admin user_id
        session_id        → impersonation_session.id
        read_only         → "true"
    """
    try:
        authorizer: dict[str, Any] = event.get("requestContext", {}).get("authorizer", {})
        # HTTP API v2 JWT authorizer: requestContext.authorizer.jwt.claims
        # REST API v1 / local simulation: requestContext.authorizer.claims
        # REQUEST authorizer: context fields are at requestContext.authorizer directly
        claims: dict[str, Any] = (
            authorizer.get("jwt", {}).get("claims", {})
            or authorizer.get("claims", {})
            or (authorizer if authorizer.get("sub") else {})
        )
        if not claims:
            raise AuthenticationRequiredError()

        mapper = get_claims_mapper()
        user_id: str = mapper.user_id(claims)
        tenant_id: str = mapper.tenant_id(claims)

        if not user_id:
            raise AuthenticationRequiredError()

        # No tenant claim in the token → resolve it from tenant_user by subject.
        # Entra External ID does not emit the custom-claims provider's output
        # (see resolve_identity_from_db), so for tenant-scoped users the claim is
        # simply absent; the DB holds the same authoritative answer. A platform
        # admin never reaches here — mapper.tenant_id derives PLATFORM from the
        # group claim.
        db_role: str | None = None
        if not tenant_id:
            resolved = resolve_identity_from_db(user_id)
            if resolved is None:
                raise AuthenticationRequiredError()
            tenant_id, db_role = resolved

        roles = _parse_roles(claims, tenant_id)
        role = _parse_primary_role(claims, roles)
        # The token carried no role either, so the group-derived default
        # ('customer') is meaningless — trust the DB row instead.
        if db_role is not None and db_role in _VALID_ROLES:
            role = UserRole(db_role)
            roles = frozenset({role}) if roles == frozenset({UserRole.CUSTOMER}) else roles | {role}

    except AuthenticationRequiredError:
        raise
    except Exception as exc:
        logger.warning("Failed to parse JWT claims: %s", exc)
        raise AuthenticationRequiredError() from exc

    # Tenant suspension check with 60s in-memory cache
    if tenant_id != PLATFORM_TENANT_ID:
        _check_tenant_active(tenant_id)

    impersonated_by: str | None = claims.get("impersonated_by") or None
    imp_session_id: str | None = claims.get("session_id") or None
    read_only_raw = str(claims.get("read_only", "false")).lower()
    read_only = read_only_raw == "true" and bool(impersonated_by)

    ctx = TenantContext(
        tenant_id=tenant_id,
        user_id=user_id,
        role=role,
        roles=roles,
        impersonated_by=impersonated_by,
        session_id=imp_session_id,
        read_only=read_only,
    )

    # Bind trace context the moment identity is known, from this single
    # chokepoint, so every downstream log line carries tenant_id/user_id
    # without each handler wiring it. request_id is bound separately at the
    # handler entry point, which also calls clear_log_context() first so a
    # reused Lambda execution environment cannot leak the previous request.
    bind_log_context(tenant_id=ctx.tenant_id, user_id=ctx.user_id)

    # Central read-only enforcement for impersonation sessions.
    # Checked here — the single chokepoint — so individual write handlers never
    # need to call assert_not_read_only() and cannot accidentally omit it.
    # EventBridge/SQS events have no requestContext.http.method and never carry
    # impersonation tokens, so ctx.read_only is always False for those paths.
    if ctx.read_only:
        http_method = event.get("requestContext", {}).get("http", {}).get("method", "") or event.get("httpMethod", "")
        assert_not_read_only(ctx, http_method)

    return ctx


def assert_not_read_only(ctx: Any, method: str) -> None:
    """Raise BusinessRuleViolationError if this is a read-only impersonation session
    and the HTTP method is mutating.

    Call this at the top of any handler that performs writes, before business logic.
    This is the safety net for impersonated sessions that bypass per-endpoint checks.
    """
    if getattr(ctx, "read_only", False) and method not in ("GET", "HEAD", "OPTIONS"):
        from shared.exceptions import BusinessRuleViolationError

        raise BusinessRuleViolationError(
            "Impersonation sessions are read-only — mutating requests are not allowed",
            rule_id="IMPERSONATION_READ_ONLY",
        )


def _parse_roles(claims: dict[str, Any], tenant_id: str) -> frozenset[UserRole]:
    """Extract every assigned role from the identity provider's group claim.

    Groups format: "{tenant_id}:{role}" e.g. "abc-123:tenant_admin"
    Platform admins belong to the "platform_admin" group (no tenant prefix).
    Falls back to {UserRole.CUSTOMER} if no matching group is found. Unlike
    the single-role parsing this replaces, every matching group is kept —
    not just the first — so staff can hold more than one role at once.

    The raw claim shape is read by the cloud's `ClaimsMapper`; this function
    keeps the cloud-agnostic `{tenant_id}:{role}` interpretation.
    """
    groups = get_claims_mapper().groups(claims)

    # Platform admin group has no tenant prefix
    if "platform_admin" in groups:
        return frozenset({UserRole.PLATFORM_ADMIN})

    # Collect every group that matches "{tenant_id}:{role}"
    prefix = f"{tenant_id}:"
    roles = {
        UserRole(group[len(prefix) :]) for group in groups if group.startswith(prefix) and group[len(prefix) :] in _VALID_ROLES
    }

    return frozenset(roles) if roles else frozenset({UserRole.CUSTOMER})


def _parse_primary_role(claims: dict[str, Any], roles: frozenset[UserRole]) -> UserRole:
    """Determine the user's primary/active role.

    Read from the primary-role claim (kept in sync with `tenant_user.role`
    by the tenant management service on every role change). Falls back to a
    deterministic member of `roles` if the claim is absent, stale, or names a
    role the user no longer holds — the group claim carries no ordering
    guarantee, so "first matching group" (the pre-multi-role behavior) is
    replaced with a stable, reproducible choice.
    """
    primary_claim = get_claims_mapper().primary_role(claims)
    if primary_claim in _VALID_ROLES:
        primary = UserRole(primary_claim)
        if primary in roles:
            return primary
    return min(roles)


def resolve_identity_from_db(user_id: str) -> tuple[str, str] | None:
    """Resolve (tenant_id, role) for an IdP subject straight from `tenant_user`.

    The authoritative source for a user's tenant and role is their `tenant_user`
    row — `tenant_user.id` IS the IdP subject, so the `oid`/`sub` in the token is
    enough to find it. This is the fallback for tokens that carry no tenant
    claim.

    Why this exists: on Entra External ID (CIAM) the custom-claims provider
    returns `tenant_id`/`role` correctly, but Entra does not emit them into the
    token — the documented app-registration `optionalClaims` route is silently
    ignored there (CIAM honours a service-principal surface instead). Rather than
    depend on that, we resolve the same data server-side from the same table the
    provider reads. One source of truth either way.

    Cached for 60s per subject, mirroring `_check_tenant_active`, so this costs
    at most one DB round trip per user per minute on the auth path. Returns None
    when no active row matches (e.g. a platform admin, who legitimately has no
    `tenant_user` row and resolves from the group claim instead).
    """
    cached = _identity_cache.get(user_id)
    if cached is not None:
        if cached == "":  # negative result cached — do not re-query every request
            return None
        tenant_id, _, role = str(cached).partition(":")
        return (tenant_id, role) if tenant_id and role else None

    try:
        from shared.db import execute_with_tenant

        rows = execute_with_tenant(
            tenant_id=PLATFORM_TENANT_ID,  # spans tenants, like the status check
            query="SELECT tenant_id, role FROM tenant_user WHERE id = %s AND status = 'active' LIMIT 1",
            params=(user_id,),
        )
    except Exception as exc:
        # Do NOT cache a failure, and do not fail the request here: the caller
        # raises AuthenticationRequiredError if the identity stays unresolved.
        logger.warning("Identity resolution failed for subject %s: %s", user_id, exc)
        return None

    if not rows:
        _identity_cache.set(user_id, "")
        return None
    tenant_id = str(rows[0]["tenant_id"])
    role = str(rows[0]["role"])
    _identity_cache.set(user_id, f"{tenant_id}:{role}")
    return tenant_id, role


def _check_tenant_active(tenant_id: str) -> None:
    """Check whether a tenant is active. Raises TenantSuspendedError or
    TenantOffboardedError if not.

    Results are cached for 60 seconds per tenant to avoid a DB hit on every
    request. Raises ServiceUnavailableError if the DB is unavailable (fail-closed).
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
