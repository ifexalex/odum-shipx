"""Resolve a platform caller to their ``platform_user`` row and role (platform audit Phase 1, C-28).

Membership of the identity provider's ``platform_admin`` group gets a token to the platform routes; the directory
decides who that person is and what they may do. ``shared.auth.get_tenant_context`` calls
:func:`resolve_platform_caller` on every platform request, and denies the request when the lookup fails (fail-closed).

How a row is found for a subject:

1. A row already bound to the token's subject. ``active`` passes; ``invited`` (created by a console invite, which
   creates the identity-provider account and so knows the subject) becomes ``active``; ``disabled`` is refused.
2. An ``invited`` row with no subject yet (seeded by ``scripts/platform_admins.py``) whose email matches the token's
   email is bound to the subject and becomes ``active``.
3. Bootstrap: while the directory holds no active or invited owner, the first platform admin to sign in becomes the
   owner. Before Phase 1 every member of the group had full power, so this grants nothing new; after it, everyone else
   needs an invite. ``scripts/platform_admins.py`` seeds an invited owner ahead of a deploy to skip bootstrap.
"""

import logging
from typing import Any

from shared.distributed_cache import DistributedCache
from shared.exceptions import LogisticsBaseError, PlatformAdminNotEnrolledError, ServiceUnavailableError
from shared.platform_roles import PlatformRole
from shared.tenant_context import PLATFORM_TENANT_ID

logger = logging.getLogger(__name__)

# subject → "{platform_user_id}:{role}", or "-" for a subject that is disabled. Short TTL: a disabled admin or a role
# change takes effect within this window even if the eviction below is missed; the directory writes evict at once.
_caller_cache: DistributedCache = DistributedCache(default_ttl=30, key_prefix="platform_caller:")
_DISABLED = "-"


class PlatformAdminDisabledError(PlatformAdminNotEnrolledError):
    """403 for a platform admin whose directory row is disabled."""

    def __init__(self) -> None:
        LogisticsBaseError.__init__(
            self,
            message="Your platform admin access has been disabled.",
            error_code="PLATFORM_ADMIN_DISABLED",
            status_code=403,
        )


def resolve_platform_caller(subject: str, email: str | None, name: str | None) -> tuple[str, str]:
    """Return ``(platform_user_id, role)`` for an active platform admin.

    Args:
        subject: The verified identity-provider subject (Cognito ``sub`` / Entra ``oid``).
        email: The token's email claim, used only to bind an invited row on first sign-in.
        name: The token's display name, used only when bootstrapping the first owner.

    Raises:
        PlatformAdminNotEnrolledError: No directory row for this person, and the directory already has an owner.
        PlatformAdminDisabledError: The person's row is disabled.
        ServiceUnavailableError: The directory could not be read (fail-closed).
    """
    cached = _caller_cache.get(subject)
    if cached == _DISABLED:
        raise PlatformAdminDisabledError()
    if cached:
        user_id, _, role = cached.partition(":")
        if user_id and role:
            return user_id, role

    try:
        resolved = _lookup(subject, email, name)
    except LogisticsBaseError:
        raise
    except Exception as exc:
        logger.error("Platform directory lookup failed — denying request (fail-closed): %s", exc)
        raise ServiceUnavailableError("Platform directory unavailable") from exc

    if resolved is None:
        _caller_cache.set(subject, _DISABLED)
        raise PlatformAdminDisabledError()
    _caller_cache.set(subject, f"{resolved[0]}:{resolved[1]}")
    return resolved


def evict_platform_caller(subject: str | None) -> None:
    """Forget a cached caller at once, after their role or status changes."""
    if subject:
        _caller_cache.delete(subject)


def _lookup(subject: str, email: str | None, name: str | None) -> tuple[str, str] | None:
    """Return ``(id, role)`` for an active row, ``None`` for a disabled one; raise when there is no row at all."""
    from shared.db import execute_with_tenant, execute_write_with_tenant

    rows = execute_with_tenant(
        PLATFORM_TENANT_ID,
        "SELECT id, role, status FROM platform_user WHERE subject = %(subject)s",
        {"subject": subject},
    )
    if rows:
        row = rows[0]
        if row["status"] == "invited":
            # Invited through the console: the identity provider account (and so the subject) was created then.
            activated = execute_write_with_tenant(
                PLATFORM_TENANT_ID,
                """
                UPDATE platform_user SET status = 'active', last_seen_at = NOW(), updated_at = NOW()
                WHERE id = %(id)s AND status = 'invited'
                RETURNING id, role
                """,
                {"id": row["id"]},
            )
            if activated:
                _audit_enrolled(subject, str(activated["id"]), str(activated["role"]), bootstrap=False)
                return str(activated["id"]), str(activated["role"])
        if row["status"] != "active":
            return None
        # last_seen_at is written at most every 5 minutes per admin, so the directory read stays a read.
        execute_write_with_tenant(
            PLATFORM_TENANT_ID,
            """
            UPDATE platform_user SET last_seen_at = NOW()
            WHERE id = %(id)s AND (last_seen_at IS NULL OR last_seen_at < NOW() - INTERVAL '5 minutes')
            RETURNING id
            """,
            {"id": row["id"]},
        )
        return str(row["id"]), str(row["role"])

    if email:
        bound = execute_write_with_tenant(
            PLATFORM_TENANT_ID,
            """
            UPDATE platform_user
            SET subject = %(subject)s, status = 'active', last_seen_at = NOW(), updated_at = NOW()
            WHERE lower(email) = lower(%(email)s) AND status = 'invited' AND subject IS NULL
            RETURNING id, role
            """,
            {"subject": subject, "email": email},
        )
        if bound:
            _audit_enrolled(subject, str(bound["id"]), str(bound["role"]), bootstrap=False)
            return str(bound["id"]), str(bound["role"])

    created = _bootstrap_owner(subject, email, name)
    if created is None:
        raise PlatformAdminNotEnrolledError()
    _audit_enrolled(subject, created, PlatformRole.OWNER.value, bootstrap=True)
    return created, PlatformRole.OWNER.value


def _bootstrap_owner(subject: str, email: str | None, name: str | None) -> str | None:
    """Create the first owner while the directory has none; return its id, or None when an owner exists.

    A transaction-scoped advisory lock serialises concurrent first sign-ins, so two people cannot both become owner.
    """
    from shared.db import tenant_transaction

    with tenant_transaction(PLATFORM_TENANT_ID) as cur:
        cur.execute("SELECT pg_advisory_xact_lock(hashtext('platform_owner_bootstrap'))")
        cur.execute("SELECT 1 FROM platform_user WHERE role = 'owner' AND status IN ('active', 'invited') LIMIT 1")
        if cur.fetchone():
            return None
        cur.execute(
            """
            INSERT INTO platform_user (subject, email, name, role, status, last_seen_at)
            VALUES (%(subject)s, %(email)s, %(name)s, 'owner', 'active', NOW())
            RETURNING id
            """,
            {"subject": subject, "email": email or subject, "name": (name or email or "Platform owner")[:200]},
        )
        row: Any = cur.fetchone()
    logger.warning("Platform directory bootstrapped: the first platform admin to sign in is now the owner")
    return str(row["id"])


def _audit_enrolled(subject: str, platform_user_id: str, role: str, *, bootstrap: bool) -> None:
    from shared.platform_audit import PlatformAuditAction, insert_platform_audit

    try:
        insert_platform_audit(
            action=PlatformAuditAction.PLATFORM_ADMIN_ENROLLED,
            actor_id=subject,
            target_tenant_id=None,
            details={"platform_user_id": platform_user_id, "role": role, "bootstrap": bootstrap},
        )
    except Exception as exc:
        logger.warning("Platform audit insert failed for directory enrolment: %s", exc)
