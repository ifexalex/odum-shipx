"""Idempotency key management for POST endpoints.

Prevents duplicate resource creation when clients retry failed requests.
The key is stored in a lightweight `idempotency_key` table and expires
after 24 hours.

Security & correctness invariants:
  - Keys are scoped to `(tenant_id, actor_id, method, path, key)` (hashed to
    fit VARCHAR(100)) whenever caller/route context is passed, so one user or
    role can never replay another user's cached response across endpoints.
  - Secret-minting / one-time-token endpoints (webhook secret rotation,
    impersonation, offboarding export links, pickup-code reissue) are never
    cached.
  - Reusing the same key with a different request payload raises 422
    `IDEMPOTENCY_KEY_CONFLICT` when `body` is supplied.
  - Expired entries (>24h) are overwritten cleanly on conflict rather than
    deadlocking permanently.
  - Every DB read/write ends its transaction cleanly (commit/rollback).

See 00_CROSS_CUTTING_STANDARDS.md §1.2 for the idempotency contract.
"""

import hashlib
import json
import logging
from typing import Any

from shared.db import get_connection
from shared.exceptions import BusinessRuleViolationError

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

# Endpoints whose responses contain one-time secrets, signed tokens, or
# short-lived download URLs must never be cached in the idempotency table.
_NON_CACHEABLE_SUFFIXES = (
    "/rotate-secret",
    "/impersonate",
    "/offboarding-export/link",
    "/pickup-code",
)

_ENVELOPE_MARKER = "__shipx_idem_v2__"


def get_idempotency_key(event: dict[str, Any]) -> str | None:
    """Extract the `Idempotency-Key` header case-insensitively."""
    headers = event.get("headers") or {}
    for k, v in headers.items():
        if str(k).lower() == "idempotency-key":
            val = str(v).strip() if v is not None else ""
            return val or None
    return None


def _is_non_cacheable_path(path: str) -> bool:
    norm = "/" + path.strip("/")
    return any(norm.endswith(suffix) for suffix in _NON_CACHEABLE_SUFFIXES)


def _scoped_storage_key(key: str, actor_id: str, method: str, path: str) -> str:
    """Build a tenant-internal storage key scoped to actor + method + path.

    When actor/route metadata is absent (legacy callers / unit tests), returns
    the raw key unchanged. When present, hashes the tuple into a fixed 67-char
    `v2:<sha256>` token so distinct users or endpoints can never collide.
    """
    if not (actor_id or method or path):
        return key
    norm_path = "/" + path.strip("/") if path else ""
    digest = hashlib.sha256(f"{actor_id}|{method.upper()}|{norm_path}|{key}".encode()).hexdigest()
    return f"v2:{digest}"


def _body_hash(body: str | None) -> str | None:
    if body is None:
        return None
    return hashlib.sha256(body.encode("utf-8")).hexdigest()


def _ensure_table() -> None:
    """Create the idempotency_key table if it does not already exist.

    Called once per Lambda container lifetime via the _TABLE_CREATED flag.
    Safe to call concurrently — CREATE TABLE IF NOT EXISTS is idempotent.
    """
    global _TABLE_CREATED
    if _TABLE_CREATED:
        return
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(_DDL)
        conn.commit()
        _TABLE_CREATED = True
    except Exception:
        conn.rollback()
        raise


def check_idempotency(
    key: str | None,
    tenant_id: str = "",
    *,
    actor_id: str = "",
    method: str = "",
    path: str = "",
    body: str | None = None,
) -> dict[str, Any] | None:
    """Look up a previously stored response by idempotency key, scoped to tenant & actor/route.

    Args:
        key: The value of the `Idempotency-Key` request header, or None.
        tenant_id: The caller's tenant ID for isolation.
        actor_id: Authenticated caller's user_id (prevents cross-user replay).
        method: HTTP method (e.g. "POST").
        path: HTTP path (prevents cross-endpoint replay).
        body: Raw request body for payload-consistency verification (optional).

    Returns:
        The original Lambda response dict if the key exists and has not expired,
        otherwise None (meaning the request should be processed normally).

    Raises:
        BusinessRuleViolationError: If the same key is reused with a different payload.
    """
    if not key or not tenant_id:
        return None
    if len(key) > 100:
        logger.warning("Idempotency key exceeds 100-char limit (len=%d) — bypassing idempotency", len(key))
        return None
    if path and _is_non_cacheable_path(path):
        return None

    storage_key = _scoped_storage_key(key, actor_id, method, path)
    req_body_hash = _body_hash(body)
    conn = None
    try:
        _ensure_table()
        conn = get_connection()
        with conn.cursor() as cur:
            cur.execute(
                "SELECT response_body FROM idempotency_key"
                " WHERE tenant_id = %s AND key = %s AND created_at > NOW() - INTERVAL %s",
                (tenant_id, storage_key, _EXPIRY_INTERVAL),
            )
            row = cur.fetchone()
        conn.commit()
        if not row:
            return None
        stored = dict(row["response_body"])
        if stored.get(_ENVELOPE_MARKER):
            stored_hash = stored.get("body_hash")
            if req_body_hash is not None and stored_hash is not None and req_body_hash != stored_hash:
                raise BusinessRuleViolationError(
                    "Idempotency-Key was already used with a different request payload",
                    rule_id="IDEMPOTENCY_KEY_CONFLICT",
                )
            logger.info("Idempotency hit for key '%s' tenant '%s' — returning cached response", key, tenant_id)
            return dict(stored["response"])
        logger.info("Idempotency hit for key '%s' tenant '%s' — returning cached response", key, tenant_id)
        return stored
    except BusinessRuleViolationError:
        raise
    except Exception as exc:
        if conn is not None:
            try:
                conn.rollback()
            except Exception:
                logger.debug("Idempotency rollback after check failure failed", exc_info=True)
        # Fail-open: if the DB is unavailable, process the request normally
        logger.warning("Idempotency check failed for key '%s': %s", key, exc)
        return None


def store_idempotency(
    key: str | None,
    response: dict[str, Any],
    tenant_id: str = "",
    *,
    actor_id: str = "",
    method: str = "",
    path: str = "",
    body: str | None = None,
) -> None:
    """Persist a response under the given idempotency key, scoped to tenant & actor/route.

    Overwrites expired entries (>24h) on conflict so keys never deadlock after expiry;
    active unexpired entries keep the first response written.
    """
    if not key or not tenant_id:
        return
    if len(key) > 100:
        logger.warning("Idempotency key exceeds 100-char limit (len=%d) — skipping store", len(key))
        return
    if path and _is_non_cacheable_path(path):
        return

    storage_key = _scoped_storage_key(key, actor_id, method, path)
    req_body_hash = _body_hash(body)
    payload: dict[str, Any] = (
        {_ENVELOPE_MARKER: True, "body_hash": req_body_hash, "response": response} if req_body_hash is not None else response
    )
    conn = None
    try:
        _ensure_table()
        conn = get_connection()
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO idempotency_key (tenant_id, key, response_body)"
                " VALUES (%s, %s, %s::jsonb)"
                " ON CONFLICT (tenant_id, key) DO UPDATE"
                " SET response_body = EXCLUDED.response_body, created_at = NOW()"
                " WHERE idempotency_key.created_at <= NOW() - INTERVAL %s",
                (tenant_id, storage_key, json.dumps(payload), _EXPIRY_INTERVAL),
            )
        conn.commit()
        logger.debug("Idempotency key stored: '%s' tenant '%s'", key, tenant_id)
    except Exception as exc:
        if conn is not None:
            try:
                conn.rollback()
            except Exception:
                logger.debug("Idempotency rollback after store failure failed", exc_info=True)
        logger.warning("Idempotency store failed for key '%s': %s", key, exc)
