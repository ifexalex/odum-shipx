"""Customer account-creation invites — DB access + token primitives.

Issued when a customer is created without a login (manifest import, which
only ever supplies name + phone). The token is a random opaque string, never
a JWT: single-use revocation needs a server-side row regardless (to flip
`consumed_at`), so a JWT would buy nothing while adding claims that can't be
withdrawn once issued. Only the SHA-256 hash of the token is stored — a
leaked `customer_invite` table gives no working links.

Mirrors the shape of `services/tenant_management/impersonation.py`'s
session-row pattern (`get_active_session` / `_create_session`), minus JWT
signing.
"""

import hashlib
import secrets
from datetime import UTC, datetime, timedelta
from typing import Any

from shared.db import execute_with_tenant, execute_write_with_tenant

INVITE_TTL_HOURS = 48
_TOKEN_BYTES = 32


def mint_token() -> str:
    """Return a new random, URL-safe invite token. Never stored — only its hash is."""
    return secrets.token_urlsafe(_TOKEN_BYTES)


def hash_token(token: str) -> str:
    """Return the SHA-256 hex digest of a token, as stored in `token_hash`."""
    return hashlib.sha256(token.encode()).hexdigest()


def delete_unconsumed_invites(tenant_id: str, customer_id: str) -> None:
    """Delete any unconsumed invite for a customer — a resend invalidates the old link."""
    execute_write_with_tenant(
        tenant_id,
        """
        DELETE FROM customer_invite
        WHERE tenant_id = %(tenant_id)s AND customer_id = %(customer_id)s AND consumed_at IS NULL
        RETURNING id
        """,
        {"tenant_id": tenant_id, "customer_id": customer_id},
    )


def create_invite(
    tenant_id: str,
    customer_id: str,
    token_hash: str,
    sent_channel: str | None,
    sent_to_masked: str | None,
    created_by: str | None,
) -> dict[str, Any] | None:
    """Insert a new invite row with a 48-hour expiry."""
    expires_at = datetime.now(UTC) + timedelta(hours=INVITE_TTL_HOURS)
    return execute_write_with_tenant(
        tenant_id,
        """
        INSERT INTO customer_invite (
            tenant_id, customer_id, token_hash, expires_at,
            sent_channel, sent_to_masked, created_by
        ) VALUES (
            %(tenant_id)s, %(customer_id)s, %(token_hash)s, %(expires_at)s,
            %(sent_channel)s, %(sent_to_masked)s, %(created_by)s
        ) RETURNING *
        """,
        {
            "tenant_id": tenant_id,
            "customer_id": customer_id,
            "token_hash": token_hash,
            "expires_at": expires_at.isoformat(),
            "sent_channel": sent_channel,
            "sent_to_masked": sent_to_masked,
            "created_by": created_by,
        },
    )


def get_invite_by_token(token: str) -> dict[str, Any] | None:
    """Look up an invite by raw token (hashed before querying), across all tenants.

    Invite lookups happen on the public claim page, before the caller's
    tenant is known — bypasses RLS via PLATFORM scope, matching the pattern
    `impersonation.get_active_session` uses for its cross-tenant lookups.
    Callers must still check `is_invite_valid()` before trusting the result.
    """
    from shared.tenant_context import PLATFORM_TENANT_ID

    token_hash = hash_token(token)
    rows = execute_with_tenant(
        PLATFORM_TENANT_ID,
        "SELECT * FROM customer_invite WHERE token_hash = %s LIMIT 1",
        (token_hash,),
    )
    return rows[0] if rows else None


def is_invite_valid(invite: dict[str, Any] | None) -> bool:
    """Return True if `invite` exists, is unconsumed, and has not expired."""
    if invite is None:
        return False
    if invite.get("consumed_at") is not None:
        return False
    expires_at = invite["expires_at"]
    if isinstance(expires_at, str):
        expires_at = datetime.fromisoformat(expires_at)
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=UTC)
    return bool(expires_at > datetime.now(UTC))


def consume_invite(tenant_id: str, invite_id: str) -> dict[str, Any] | None:
    """Stamp `consumed_at` on an invite. Only succeeds if it is still unconsumed and unexpired."""
    return execute_write_with_tenant(
        tenant_id,
        """
        UPDATE customer_invite
        SET consumed_at = NOW()
        WHERE tenant_id = %(tenant_id)s
          AND id = %(id)s
          AND consumed_at IS NULL
          AND expires_at > NOW()
        RETURNING *
        """,
        {"tenant_id": tenant_id, "id": invite_id},
    )
