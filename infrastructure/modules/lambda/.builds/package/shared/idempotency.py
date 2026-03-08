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
    key          VARCHAR(100) PRIMARY KEY,
    response_body JSONB       NOT NULL,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT NOW()
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


def check_idempotency(key: str | None) -> dict | None:
    """Look up a previously stored response by idempotency key.

    Args:
        key: The value of the `Idempotency-Key` request header, or None.

    Returns:
        The original Lambda response dict if the key exists and has not expired,
        otherwise None (meaning the request should be processed normally).
    """
    if not key:
        return None
    try:
        _ensure_table()
        conn = get_connection()
        with conn.cursor() as cur:
            cur.execute(
                "SELECT response_body FROM idempotency_key"
                " WHERE key = %s AND created_at > NOW() - INTERVAL %s",
                (key, _EXPIRY_INTERVAL),
            )
            row = cur.fetchone()
        if row:
            logger.info("Idempotency hit for key '%s' — returning cached response", key)
            return dict(row["response_body"])
        return None
    except Exception as exc:
        # Fail-open: if the DB is unavailable, process the request normally
        logger.warning("Idempotency check failed for key '%s': %s", key, exc)
        return None


def store_idempotency(key: str | None, response: dict) -> None:
    """Persist a response under the given idempotency key.

    Uses ON CONFLICT DO NOTHING so a race between concurrent identical
    requests doesn't fail — the first write wins.

    Args:
        key: The idempotency key string, or None (no-op).
        response: The complete Lambda response dict to cache.
    """
    if not key:
        return
    try:
        _ensure_table()
        conn = get_connection()
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO idempotency_key (key, response_body)"
                " VALUES (%s, %s::jsonb)"
                " ON CONFLICT (key) DO NOTHING",
                (key, json.dumps(response)),
            )
        conn.commit()
        logger.debug("Idempotency key stored: '%s'", key)
    except Exception as exc:
        logger.warning("Idempotency store failed for key '%s': %s", key, exc)
