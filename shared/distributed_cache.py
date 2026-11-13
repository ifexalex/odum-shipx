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
            raise RuntimeError("redis package is not installed. It is a pinned runtime dep in pyproject.toml.") from exc

        host = os.environ.get("REDIS_HOST", "localhost")
        port = int(os.environ.get("REDIS_PORT", "6379"))
        # Azure Cache for Redis (Basic/Standard) mandates TLS + an access key;
        # AWS ElastiCache here is in-VPC plain TCP with no auth. Both are env-
        # driven and default to the AWS/local posture (no password, no TLS).
        password = os.environ.get("REDIS_PASSWORD") or None
        use_ssl = os.environ.get("REDIS_SSL", "").lower() == "true"
        self._client = redis.Redis(
            host=host,
            port=port,
            password=password,
            ssl=use_ssl,
            decode_responses=True,
            socket_connect_timeout=_CONNECT_TIMEOUT,
            socket_timeout=_SOCKET_TIMEOUT,
            health_check_interval=30,
            # Pin RESP2 explicitly. redis-py <=5 defaulted to RESP2; redis-py 8
            # defaults connections to RESP3, which negotiates with `HELLO 3` and
            # needs a Redis server >= 6.0. Leaving it implicit would make a
            # library upgrade silently change the wire protocol — and because
            # every method here fails OPEN (returns None / logs a warning so the
            # caller falls back to the database), a server that rejected the
            # handshake would not raise: the cache would just stop working, and
            # the only symptom would be extra database load. RESP3 is worth
            # adopting deliberately, after confirming the server version in each
            # environment — not as a side effect of a version bump.
            protocol=2,
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

    def incr(self, key: str, ttl: int | None = None) -> int | None:
        """Atomically increment a counter, setting its TTL on first write.

        Returns the new count, or **None** when Redis is unreachable — the
        caller decides what an unknown count means. Separate from get/set
        because a read-modify-write across two round trips is not atomic, and a
        rate limiter built on one would undercount exactly when it matters: a
        burst of concurrent requests.

        The TTL is applied only when the counter is created (count == 1), so a
        fixed window starts at the first request and is not extended by later
        ones — otherwise a steady trickle would hold the window open forever
        and never reset.
        """
        try:
            client = self._get_client()
            full_key = self._key(key)
            count = int(client.incr(full_key))
            if count == 1:
                client.expire(full_key, ttl if ttl is not None else self._default_ttl)
            return count
        except Exception as exc:
            logger.warning("Redis INCR failed for key=%s: %s", key, exc)
            return None

    def clear(self) -> None:
        """No-op for distributed cache — flushing the whole keyspace is unsafe
        in a shared Redis instance. Call delete() per key instead."""
        logger.warning("DistributedCache.clear() is a no-op — delete keys individually.")
