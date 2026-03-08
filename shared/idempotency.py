"""Idempotency key management for POST endpoints.

Prevents duplicate resource creation when clients retry failed requests.
The key is stored in a lightweight `idempotency_key` table and expires
after 24 hours.

See 00_CROSS_CUTTING_STANDARDS.md §1.2 for the idempotency contract.

Usage in a handler:
    idempotency_key = (event.get("headers") or {}).get("idempotency-key")
    cached = check_idempotency(idempotency_key)
    if cached:
        return cached          # return the original response unchanged

    response = _handle_create(...)

    store_idempotency(idempotency_key, response)
    return response
"""

import json
import logging

from shared.db import get_connection

logger = logging.getLogger(__name__)

# Sentinel to avoid redundant DDL on warm invocations
_TABLE_CREATED: bool = False

_DDL = """
CREATE TABLE IF NOT EXISTS idempotency_key (
    tenant_id     VARCHAR(100) NOT NULL,
    key           VARCHAR(100) NOT NULL,
    response_body JSONB        NOT NULL,
    created_at    TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    PRIMARY KEY (tenant_id, key)
)
"""

_EXPIRY_INTERVAL = "24 hours"


def _ensure_table() -> None:
    """Create the idempotency_key table if it does not already exist.

    Called once per Lambda container lifetime via the _TABLE_CREATED flag.
    Safe to call concurrently — CREATE TABLE IF NOT EXISTS is idempotent.
    """
    global _TABLE_CREATED
    if _TABLE_CREATED:
        return
    conn = get_connection()
    with conn.cursor() as cur:
        cur.execute(_DDL)
    conn.commit()
    _TABLE_CREATED = True


def check_idempotency(key: str | None, tenant_id: str = "") -> dict | None:
    """Look up a previously stored response by idempotency key, scoped to tenant.

    Args:
        key: The value of the `Idempotency-Key` request header, or None.
        tenant_id: The caller's tenant ID for isolation. Empty string is treated
            as no-op (returns None) to preserve backward-compat for platform-admin
            paths that don't use idempotency.

    Returns:
        The original Lambda response dict if the key exists and has not expired,
        otherwise None (meaning the request should be processed normally).
    """
    if not key or not tenant_id:
        return None
    if len(key) > 100:
        # Silently ignore oversized keys — do not process as idempotent, let the request through.
        logger.warning("Idempotency key exceeds 100-char limit (len=%d) — bypassing idempotency", len(key))
        return None
    try:
        _ensure_table()
        conn = get_connection()
        with conn.cursor() as cur:
            cur.execute(
                "SELECT response_body FROM idempotency_key"
                " WHERE tenant_id = %s AND key = %s AND created_at > NOW() - INTERVAL %s",
                (tenant_id, key, _EXPIRY_INTERVAL),
            )
            row = cur.fetchone()
        if row:
            logger.info("Idempotency hit for key '%s' tenant '%s' — returning cached response",
                        key, tenant_id)
            return dict(row["response_body"])
        return None
    except Exception as exc:
        # Fail-open: if the DB is unavailable, process the request normally
        logger.warning("Idempotency check failed for key '%s': %s", key, exc)
        return None


def store_idempotency(key: str | None, response: dict, tenant_id: str = "") -> None:
    """Persist a response under the given idempotency key, scoped to tenant.

    Uses ON CONFLICT DO NOTHING so a race between concurrent identical
    requests doesn't fail — the first write wins.

    Args:
        key: The idempotency key string, or None (no-op).
        response: The complete Lambda response dict to cache.
        tenant_id: The caller's tenant ID. Required to prevent cross-tenant
            key collisions. No-op when empty.
    """
    if not key or not tenant_id:
        return
    if len(key) > 100:
        logger.warning("Idempotency key exceeds 100-char limit (len=%d) — skipping store", len(key))
        return
    try:
        _ensure_table()
        conn = get_connection()
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO idempotency_key (tenant_id, key, response_body)"
                " VALUES (%s, %s, %s::jsonb)"
                " ON CONFLICT (tenant_id, key) DO NOTHING",
                (tenant_id, key, json.dumps(response)),
            )
        conn.commit()
        logger.debug("Idempotency key stored: '%s' tenant '%s'", key, tenant_id)
    except Exception as exc:
        logger.warning("Idempotency store failed for key '%s': %s", key, exc)
