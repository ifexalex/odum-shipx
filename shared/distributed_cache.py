"""Redis-backed distributed cache for tenant status.

Replaces the per-Lambda-instance in-memory Cache for tenant status checks so
that suspension and offboarding are enforced consistently across the entire
Lambda fleet — not just within a single warm instance.

Design decisions:
  - Lazy connection: client is created on first use and reused across warm
    invocations (same connection semantics as psycopg2 pool).
  - Fail-soft: Redis errors are logged and the operation returns None/no-op,
    so the caller falls through to the DB. Redis is an optimisation layer,
    not a hard dependency.
  - Socket timeouts: 500 ms connect + 500 ms operation — prevents Lambda from
    hanging if ElastiCache is temporarily unreachable.
  - decode_responses=True: values are stored and returned as plain strings
    (status values are always strings: "active", "suspended", etc.).

See 00_CROSS_CUTTING_STANDARDS.md §4 for the caching strategy.
"""

import logging
import os
from typing import Any

logger = logging.getLogger(__name__)

_CONNECT_TIMEOUT = 0.5  # seconds
_SOCKET_TIMEOUT = 0.5  # seconds


class DistributedCache:
    """Redis-backed cache with the same interface as shared.cache.Cache.

    Values are stored as raw strings with an expiry (SETEX). Suitable for
    short-lived status tokens like "active", "suspended", "not_found".

    Args:
        default_ttl: Default time-to-live in seconds (default: 60).
        key_prefix:  Optional namespace prefix to avoid key collisions.
    """

    def __init__(self, default_ttl: int = 60, key_prefix: str = "") -> None:
        self._default_ttl = default_ttl
        self._key_prefix = key_prefix
        self._client: Any = None  # redis.Redis, imported lazily

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _get_client(self) -> Any:
        """Return the Redis client, creating it on first call."""
        if self._client is not None:
            return self._client
        try:
            import redis
        except ImportError as exc:
            raise RuntimeError("redis package is not installed. Add redis>=5.0.0 to requirements-layer.txt.") from exc

        host = os.environ.get("REDIS_HOST", "localhost")
        port = int(os.environ.get("REDIS_PORT", "6379"))
        self._client = redis.Redis(
            host=host,
            port=port,
            decode_responses=True,
            socket_connect_timeout=_CONNECT_TIMEOUT,
            socket_timeout=_SOCKET_TIMEOUT,
            health_check_interval=30,
        )
        return self._client

    def _key(self, key: str) -> str:
        return f"{self._key_prefix}{key}" if self._key_prefix else key

    # ------------------------------------------------------------------
    # Public interface (mirrors shared.cache.Cache)
    # ------------------------------------------------------------------

    def get(self, key: str) -> str | None:
        """Return the cached string value, or None on miss or error."""
        try:
            result: str | None = self._get_client().get(self._key(key))
            return result
        except Exception as exc:
            logger.warning("Redis GET failed for key=%s: %s", key, exc)
            return None

    def set(self, key: str, value: str, ttl: int | None = None) -> None:
        """Store value with SETEX. Silently drops on error."""
        try:
            effective_ttl = ttl if ttl is not None else self._default_ttl
            self._get_client().setex(self._key(key), effective_ttl, value)
        except Exception as exc:
            logger.warning("Redis SET failed for key=%s: %s", key, exc)

    def delete(self, key: str) -> None:
        """Remove a key. Silently drops on error."""
        try:
            self._get_client().delete(self._key(key))
        except Exception as exc:
            logger.warning("Redis DELETE failed for key=%s: %s", key, exc)

    def clear(self) -> None:
        """No-op for distributed cache — flushing the whole keyspace is unsafe
        in a shared Redis instance. Call delete() per key instead."""
        logger.warning("DistributedCache.clear() is a no-op — delete keys individually.")
