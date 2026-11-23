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
  - No client retries, and a circuit breaker. redis-py's default retries a failed
    command with exponential backoff, which made EVERY operation against an
    unreachable Redis take about four seconds, and a request makes several. So a
    Redis outage was a multi-second delay on every authenticated request, which
    is the opposite of fail-soft. Retries are off, and after one failure Redis is
    not tried again for a few seconds: an outage costs one fast failure, not one
    per call.
  - decode_responses=True: values are stored and returned as plain strings
    (status values are always strings: "active", "suspended", etc.).

See 00_CROSS_CUTTING_STANDARDS.md §4 for the caching strategy.
"""

import logging
import os
import time
from typing import Any

logger = logging.getLogger(__name__)

# Counts one event in a fixed window: INCR, and start the expiry on the first one. The expiry is set in the
# same script as the INCR so a crash between the two cannot leave a counter that never expires (which would
# lock a client out forever). Returns {count, seconds left}; the TTL is re-armed if it is somehow missing.
_INCR_WINDOW_SCRIPT = """
local count = redis.call('INCR', KEYS[1])
if count == 1 then redis.call('EXPIRE', KEYS[1], ARGV[1]) end
local ttl = redis.call('TTL', KEYS[1])
if ttl < 0 then
  redis.call('EXPIRE', KEYS[1], ARGV[1])
  ttl = tonumber(ARGV[1])
end
return {count, ttl}
"""

_CONNECT_TIMEOUT = 0.5  # seconds
_SOCKET_TIMEOUT = 0.5  # seconds
# After a failure, how long Redis is left alone before the next attempt.
_COOLDOWN_SECONDS = 5.0


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
        self._down_until = 0.0  # time.monotonic() before which Redis is not tried (circuit breaker)

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

        try:
            from redis.backoff import NoBackoff
            from redis.retry import Retry

            # redis-py retries a failed command with exponential backoff by default; see the module docstring.
            # Held as Any: redis-py's Retry/NoBackoff have untyped constructors, which strict mode refuses to call.
            retry_class: Any = Retry
            backoff_class: Any = NoBackoff
            retry_options: dict[str, Any] = {"retry": retry_class(backoff_class(), 0)}
        except ImportError:  # a stand-in `redis` module, as in tests of client construction
            retry_options = {}

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
            **retry_options,
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

    def _tripped(self) -> bool:
        """True while Redis is being left alone after a failure."""
        return time.monotonic() < self._down_until

    def _trip(self, operation: str, key: str, exc: Exception) -> None:
        """Note a failure: log it once, then skip Redis for a few seconds."""
        self._down_until = time.monotonic() + _COOLDOWN_SECONDS
        logger.warning("Redis %s failed for key=%s: %s — not retrying for %.0fs", operation, key, exc, _COOLDOWN_SECONDS)

    # ------------------------------------------------------------------
    # Public interface (mirrors shared.cache.Cache)
    # ------------------------------------------------------------------

    def get(self, key: str) -> str | None:
        """Return the cached string value, or None on miss or error."""
        if self._tripped():
            return None
        try:
            result: str | None = self._get_client().get(self._key(key))
            return result
        except Exception as exc:
            self._trip("GET", key, exc)
            return None

    def set(self, key: str, value: str, ttl: int | None = None) -> None:
        """Store value with SETEX. Silently drops on error."""
        if self._tripped():
            return
        try:
            effective_ttl = ttl if ttl is not None else self._default_ttl
            self._get_client().setex(self._key(key), effective_ttl, value)
        except Exception as exc:
            self._trip("SET", key, exc)

    def delete(self, key: str) -> None:
        """Remove a key. Silently drops on error."""
        if self._tripped():
            return
        try:
            self._get_client().delete(self._key(key))
        except Exception as exc:
            self._trip("DELETE", key, exc)

    def incr_window(self, key: str, window_seconds: int) -> tuple[int, int] | None:
        """Count one event in a fixed window.

        Returns:
            ``(count so far, seconds until the window ends)``, or None if Redis could not be reached. The
            caller decides what an uncountable event means; a rate limiter fails open.
        """
        if self._tripped():
            return None
        try:
            count, ttl = self._get_client().eval(_INCR_WINDOW_SCRIPT, 1, self._key(key), window_seconds)
            return int(count), int(ttl)
        except Exception as exc:
            self._trip("INCR window", key, exc)
            return None

    def window_state(self, key: str) -> tuple[int, int] | None:
        """Read a window counter without counting: ``(count, seconds left)``, ``(0, 0)`` if there is none.

        Returns None if Redis could not be reached.
        """
        if self._tripped():
            return None
        try:
            client = self._get_client()
            raw = client.get(self._key(key))
            if raw is None:
                return 0, 0
            return int(raw), max(int(client.ttl(self._key(key))), 0)
        except Exception as exc:
            self._trip("window read", key, exc)
            return None

    def clear(self) -> None:
        """No-op for distributed cache — flushing the whole keyspace is unsafe
        in a shared Redis instance. Call delete() per key instead."""
        logger.warning("DistributedCache.clear() is a no-op — delete keys individually.")
