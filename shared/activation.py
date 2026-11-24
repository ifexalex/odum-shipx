"""Tenant-user account activation — DB access + token primitives.

Issued when a staff member or the initial tenant admin is provisioned by an
operator (not self-registered). The user is created in the IdP with a random
password and no login; this backs the ShipX-branded "set your password" link
(`/activate/{token}`). Accepting it sets the user's chosen password in the IdP
and marks the row consumed.

Opaque single-use token (never a JWT — single-use revocation needs a server
row regardless); only its SHA-256 hash is stored, so a leaked
`tenant_user_activation` table yields no working links. Mirrors
`shared/invites.py` (customers), keyed to tenant_user.
"""

import hashlib
import secrets
from datetime import UTC, datetime, timedelta
from typing import Any

from shared.db import execute_with_tenant, execute_write_with_tenant
from shared.tenant_context import PLATFORM_TENANT_ID

ACTIVATION_TTL_HOURS = 48
_TOKEN_BYTES = 32


def mint_token() -> str:
    """Return a new random, URL-safe activation token. Never stored — only its hash."""
    return secrets.token_urlsafe(_TOKEN_BYTES)


def hash_token(token: str) -> str:
    """Return the SHA-256 hex digest of a token, as stored in `token_hash`."""
    return hashlib.sha256(token.encode()).hexdigest()


def delete_unconsumed(tenant_id: str, user_id: str) -> None:
    """Delete any unconsumed activation for a user — a resend invalidates the old link."""
    execute_write_with_tenant(
        tenant_id,
        """
        DELETE FROM tenant_user_activation
        WHERE tenant_id = %(tenant_id)s AND user_id = %(user_id)s AND consumed_at IS NULL
        RETURNING id
        """,
        {"tenant_id": tenant_id, "user_id": user_id},
    )


def create_activation(
    tenant_id: str,
    user_id: str,
    token_hash: str,
    sent_channel: str | None,
    sent_to_masked: str | None,
    created_by: str | None,
) -> dict[str, Any] | None:
    """Insert a new activation row with a 48-hour expiry."""
    expires_at = datetime.now(UTC) + timedelta(hours=ACTIVATION_TTL_HOURS)
    return execute_write_with_tenant(
        tenant_id,
        """
        INSERT INTO tenant_user_activation (
            tenant_id, user_id, token_hash, expires_at, sent_channel, sent_to_masked, created_by
        ) VALUES (
            %(tenant_id)s, %(user_id)s, %(token_hash)s, %(expires_at)s,
            %(sent_channel)s, %(sent_to_masked)s, %(created_by)s
        ) RETURNING *
        """,
        {
            "tenant_id": tenant_id,
            "user_id": user_id,
            "token_hash": token_hash,
            "expires_at": expires_at.isoformat(),
            "sent_channel": sent_channel,
            "sent_to_masked": sent_to_masked,
            "created_by": created_by,
        },
    )


def get_activation_by_token(token: str) -> dict[str, Any] | None:
    """Look up an activation by raw token (hashed before querying), across all tenants.

    The activation page is public — the caller's tenant is unknown — so this
    bypasses RLS via PLATFORM scope, matching `shared/invites.get_invite_by_token`.
    Callers must still check `is_activation_valid()` before trusting the result.
    """
    rows = execute_with_tenant(
        PLATFORM_TENANT_ID,
        "SELECT * FROM tenant_user_activation WHERE token_hash = %s LIMIT 1",
        (hash_token(token),),
    )
    return rows[0] if rows else None


def is_activation_valid(activation: dict[str, Any] | None) -> bool:
    """Return True if `activation` exists, is unconsumed, and has not expired."""
    if activation is None:
        return False
    if activation.get("consumed_at") is not None:
        return False
    expires_at = activation["expires_at"]
    if isinstance(expires_at, str):
        expires_at = datetime.fromisoformat(expires_at)
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=UTC)
    return bool(expires_at > datetime.now(UTC))


def consume_activation(tenant_id: str, activation_id: str) -> dict[str, Any] | None:
    """Stamp `consumed_at`. Only succeeds if still unconsumed and unexpired (single-use guard)."""
    return execute_write_with_tenant(
        tenant_id,
        """
        UPDATE tenant_user_activation
        SET consumed_at = NOW()
        WHERE tenant_id = %(tenant_id)s
          AND id = %(id)s
          AND consumed_at IS NULL
          AND expires_at > NOW()
        RETURNING *
        """,
        {"tenant_id": tenant_id, "id": activation_id},
    )
