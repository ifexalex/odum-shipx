"""TTL-based in-memory cache for Lambda functions.

Uses `time.monotonic()` for expiry tracking — immune to wall-clock skew.
Suitable for tenant config, tenant status, and notification preferences.

See 00_CROSS_CUTTING_STANDARDS.md §4 for the caching strategy.
"""

import logging
import time
from typing import Any

logger = logging.getLogger(__name__)


class Cache:
    """Per-key TTL cache backed by a plain dict.

    Safe for single-threaded Lambda execution. Module-level instances persist
    across warm invocations, providing effective in-process caching.

    Args:
        default_ttl: Default time-to-live in seconds (default: 60).
    """

    def __init__(self, default_ttl: int = 60) -> None:
        self._default_ttl = default_ttl
        # key → (value, expires_at_monotonic)
        self._cache: dict[str, tuple[Any, float]] = {}

    def get(self, key: str) -> Any | None:
        """Return the cached value for key, or None if missing or expired."""
        entry = self._cache.get(key)
        if entry is None:
            return None
        value, expires_at = entry
        if time.monotonic() > expires_at:
            del self._cache[key]
            return None
        return value

    def set(self, key: str, value: Any, ttl: int | None = None) -> None:
        """Store value under key with the given TTL (falls back to default_ttl)."""
        effective_ttl = ttl if ttl is not None else self._default_ttl
        self._cache[key] = (value, time.monotonic() + effective_ttl)

    def delete(self, key: str) -> None:
        """Remove a key from the cache (no-op if absent)."""
        self._cache.pop(key, None)

    def clear(self) -> None:
        """Evict all entries."""
        self._cache.clear()

    def __len__(self) -> int:
        return len(self._cache)
