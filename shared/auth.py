"""JWT authorizer claim extraction and role-based access control.

Extracts TenantContext from API Gateway event authorizer claims (Cognito JWT).
See 00_CROSS_CUTTING_STANDARDS.md §8 for security standards.
"""

import logging
from collections.abc import Callable
from functools import wraps
from typing import Any

from shared import rate_limit
from shared.distributed_cache import DistributedCache
from shared.exceptions import (
    AuthenticationRequiredError,
    ResourceNotFoundError,
    ServiceUnavailableError,
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
# TTL 15s (see default_ttl below): this bounds how long a SUSPENDED tenant keeps
# being served, so it is a security window, not just a performance knob. Redis
# rather than an in-process cache precisely because an in-process one is
# per-instance — every warm Lambda would expire it independently.
# On Redis failure, get() returns None and the caller falls through to DB.
_tenant_status_cache: DistributedCache = DistributedCache(default_ttl=15, key_prefix="tenant_status:")
# Subject (IdP oid/sub) → "{tenant_id}:{primary_role}:{role1,role2,...}" for a user
# with an ACTIVE tenant_user row, or "" when there is none. Serves two callers:
# the identity fallback for tokens that carry no tenant claim, and the per-request
# active-user + authoritative-role check (_check_user_active).
_identity_cache: DistributedCache = DistributedCache(default_ttl=60, key_prefix="identity:")
# Companion cache storing comma-separated authoritative roles from `tenant_user_role`
# for the same subject (evicted alongside `_identity_cache` in `evict_identity_cache`).
_identity_roles_cache: DistributedCache = DistributedCache(default_ttl=60, key_prefix="identity_roles:")
# Platform-wide maintenance_mode flag (5s TTL, evicted on update).
_maintenance_cache: DistributedCache = DistributedCache(default_ttl=5, key_prefix="platform_maint:")


def _check_maintenance_mode() -> None:
    """Block non-platform-admin requests with 503 when platform maintenance_mode is enabled."""
    cached = _maintenance_cache.get("enabled")
    if cached is not None:
        if cached == "1":
            raise ServiceUnavailableError("ShipX is currently undergoing scheduled maintenance. Please try again shortly.")
        return

    try:
        from shared.db import execute_with_tenant

        rows = execute_with_tenant(
            tenant_id=PLATFORM_TENANT_ID,
            query="SELECT value FROM platform_settings WHERE key = 'maintenance_mode' LIMIT 1",
        )
    except Exception as exc:
        # Don't take down the entire platform if the optional maintenance_mode lookup
        # hits a transient issue — tenant/user status checks still fail closed below.
        logger.warning("Maintenance mode check failed: %s", exc)
        return

    raw_val = rows[0]["value"] if rows else False
    enabled = raw_val is True or str(raw_val).strip().lower() == "true"
    _maintenance_cache.set("enabled", "1" if enabled else "0")
    if enabled:
        raise ServiceUnavailableError("ShipX is currently undergoing scheduled maintenance. Please try again shortly.")


def evict_maintenance_cache() -> None:
    """Forget the cached maintenance_mode setting immediately after an admin toggles it."""
    _maintenance_cache.delete("enabled")


def get_tenant_context(event: dict[str, Any]) -> TenantContext:
    """Extract and validate tenant context from an API Gateway proxy event.

    Reads JWT claims injected by the authorizer at:
        event["requestContext"]["authorizer"]["claims"]        (REST API v1 / local)
        event["requestContext"]["authorizer"]["jwt"]["claims"] (HTTP API v2 JWT)
        event["requestContext"]["authorizer"]["lambda"]        (HTTP API v2 REQUEST authorizer)
        event["requestContext"]["authorizer"]["<key>"]         (REQUEST authorizer / flat context)

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
        # HTTP API v2 REQUEST authorizer (payload 2.0): requestContext.authorizer.lambda
        # REST API v1 / local simulation: requestContext.authorizer.claims
        # Direct/flat REQUEST authorizer context: requestContext.authorizer directly
        raw_lambda = authorizer.get("lambda")
        lambda_ctx: dict[str, Any] = raw_lambda if isinstance(raw_lambda, dict) else {}
        claims: dict[str, Any] = (
            authorizer.get("jwt", {}).get("claims", {})
            or authorizer.get("claims", {})
            or (lambda_ctx if lambda_ctx.get("sub") or lambda_ctx.get("oid") else {})
            or (authorizer if authorizer.get("sub") or authorizer.get("oid") else {})
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
        db_roles: frozenset[UserRole] | None = None
        if not tenant_id:
            resolved = resolve_identity_from_db(user_id)
            if resolved is None:
                raise AuthenticationRequiredError()
            tenant_id, db_role = resolved[0], resolved[1]
            db_roles = _cached_db_roles(user_id)

        roles = _parse_roles(claims, tenant_id)
        role = _parse_primary_role(claims, roles)
        # The token carried no tenant/role claims — trust the full DB role set.
        if db_roles:
            roles = db_roles
            role = UserRole(db_role) if (db_role in _VALID_ROLES and UserRole(db_role) in db_roles) else min(db_roles)
        elif db_role is not None and db_role in _VALID_ROLES:
            role = UserRole(db_role)
            roles = frozenset({role}) if roles == frozenset({UserRole.CUSTOMER}) else roles | {role}

    except AuthenticationRequiredError:
        raise
    except Exception as exc:
        logger.warning("Failed to parse JWT claims: %s", exc)
        raise AuthenticationRequiredError() from exc

    impersonated_by: str | None = claims.get("impersonated_by") or None
    imp_session_id: str | None = claims.get("session_id") or None
    # Fail closed: any impersonation session is strictly read-only regardless of
    # whether the `read_only` claim was explicitly set to "true".
    read_only = bool(impersonated_by)

    # Tenant suspension check, 15s distributed (Redis) cache — see
    # _tenant_status_cache; not in-memory, and not 60s.
    if tenant_id != PLATFORM_TENANT_ID:
        if not impersonated_by:
            _check_maintenance_mode()
        _check_tenant_active(tenant_id)
        # A token is a signed claim that was true when it was issued. Without this a
        # deactivated user, an erased customer, or a demoted admin keeps their old
        # access until the token expires.
        if db_role is None:
            checked = _check_user_active(user_id, tenant_id)
            if checked is not None and not impersonated_by:
                active_primary, active_roles = checked
                if active_roles:
                    roles = active_roles
                    role = (
                        UserRole(active_primary)
                        if (active_primary in _VALID_ROLES and UserRole(active_primary) in active_roles)
                        else min(active_roles)
                    )
        # One tenant's traffic must not be able to starve the others: API Gateway's throttle is shared by
        # all of them. Counted only for a request that got this far, so a revoked token costs the tenant nothing.
        rate_limit.hit(rate_limit.TENANT, tenant_id)

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


def _cached_db_roles(user_id: str) -> frozenset[UserRole] | None:
    """Return the cached authoritative DB role set for `user_id`, or None if unpopulated."""
    raw = _identity_roles_cache.get(user_id)
    if not raw:
        return None
    parsed = frozenset(UserRole(r) for r in str(raw).split(",") if r in _VALID_ROLES)
    return parsed or None


def _active_identity(user_id: str) -> tuple[str, str] | None:
    """Return (tenant_id, primary_role) from the user's ACTIVE `tenant_user` row, or None when there is none.

    Also populates `_identity_roles_cache` with the full assigned role set from
    `tenant_user_role` in the same query so multi-role staff on Azure Entra and
    role-downgrade revocations work without a second round-trip.
    """
    cached = _identity_cache.get(user_id)
    if cached is not None:
        if cached == "":  # negative result cached — do not re-query every request
            return None
        tenant_id, _, role = str(cached).partition(":")
        return (tenant_id, role) if tenant_id and role else None

    from shared.db import execute_with_tenant

    rows = execute_with_tenant(
        tenant_id=PLATFORM_TENANT_ID,  # spans tenants, like the status check
        query=(
            "SELECT tu.tenant_id, tu.role, "
            "COALESCE(ARRAY_AGG(tur.role) FILTER (WHERE tur.role IS NOT NULL), ARRAY[tu.role]) AS roles "
            "FROM tenant_user tu "
            "LEFT JOIN tenant_user_role tur ON tur.tenant_user_id = tu.id "
            "WHERE tu.id = %s AND tu.status = 'active' "
            "GROUP BY tu.id, tu.tenant_id, tu.role "
            "LIMIT 1"
        ),
        params=(user_id,),
    )
    if not rows:
        _identity_cache.set(user_id, "")
        _identity_roles_cache.delete(user_id)
        return None
    tenant_id = str(rows[0]["tenant_id"])
    role = str(rows[0]["role"])
    raw_roles = rows[0].get("roles") or [role]
    valid_role_strs = sorted({str(r) for r in raw_roles if str(r) in _VALID_ROLES})
    if role in _VALID_ROLES and role not in valid_role_strs:
        valid_role_strs.append(role)
    _identity_cache.set(user_id, f"{tenant_id}:{role}")
    if valid_role_strs:
        _identity_roles_cache.set(user_id, ",".join(valid_role_strs))
    return tenant_id, role


def resolve_identity_from_db(user_id: str) -> tuple[str, str] | None:
    """Resolve (tenant_id, primary_role) for an IdP subject straight from `tenant_user`."""
    try:
        return _active_identity(user_id)
    except Exception as exc:
        logger.warning("Identity resolution failed for subject %s: %s", user_id, exc)
        return None


def evict_identity_cache(user_id: str) -> None:
    """Forget the cached identity and roles of a user whose row just changed."""
    _identity_cache.delete(user_id)
    _identity_roles_cache.delete(user_id)


def _check_user_active(user_id: str, tenant_id: str) -> tuple[str, frozenset[UserRole]] | None:
    """Deny a token whose user has no active `tenant_user` row in the token's tenant.

    Returns `(primary_role, roles)` from the live DB row when available so
    `get_tenant_context` enforces immediate role downgrades rather than waiting
    for JWT expiry.
    """
    try:
        identity = _active_identity(user_id)
    except Exception as exc:
        logger.error("User status check failed for %s — denying request (fail-closed): %s", user_id, exc)
        raise ServiceUnavailableError("User status check unavailable") from exc
    if identity is None:
        logger.warning("Denied token for user %s: no active tenant_user row", user_id)
        raise AuthenticationRequiredError()
    if identity[0].lower() != tenant_id.lower():
        logger.warning("Denied token for user %s: the token's tenant is not the user's tenant", user_id)
        raise AuthenticationRequiredError()
    db_roles = _cached_db_roles(user_id)
    if db_roles:
        return identity[1], db_roles
    return None


def _check_tenant_active(tenant_id: str) -> None:
    """Check whether a tenant is active. Raises TenantSuspendedError or
    TenantOffboardedError if not.

    Results are cached for 15 seconds per tenant (``_tenant_status_cache``) to
    avoid a DB hit on every request. That TTL is the window in which a tenant
    suspended in the database is still served, so it is deliberately short.
    Raises ServiceUnavailableError if the DB is unavailable (fail-closed).
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
