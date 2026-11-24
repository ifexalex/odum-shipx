"""Per-client rate limits for public endpoints, and a per-tenant limit for authenticated traffic (audit SEC-03).

Before this the only limit was one stage-wide API Gateway throttle shared by every tenant, so one script could
flood sign-ups and onboarding leads, guess tracking-code and phone pairs, try passwords through the login proxy,
or use up the shared budget for everyone.

Each limit is a fixed window counted in Redis, keyed by who is being limited and what for. A *policy* names one
(`LOGIN_IP`, `TRACKING_FAILURES`, ...). Two shapes:

* `hit` counts every request and refuses the one that passes the limit. For flood limits (per IP, per tenant).
* `peek` + `record_failure` + `clear` count only failures. For guessing limits, where a user who gets it right
  must not be punished for typos: `peek` refuses a client already at its limit, `record_failure` counts a wrong
  guess, `clear` forgets the count after a success.

When refused, the request gets 429 with `Retry-After` (`RateLimitExceededError`).

**Fail open.** If Redis cannot be reached the request goes through, and `rate_limiter_unavailable` is logged at
ERROR (a log metric filter on that string is the alarm, OPS-04). The alternative, failing closed, would make
Redis an availability dependency of sign-in: a Redis blip would be a full outage. A limiter that is briefly off
costs protection for that long; it never takes the product down.

**Where it does not run.** A Lambda outside the VPC cannot reach ElastiCache, and trying would add a connection
timeout to every request, so Terraform sets `RATE_LIMIT_ENABLED=false` there (the auth Lambda, which only talks
to Cognito). Those routes are throttled per route at API Gateway instead.

Configuration, all by environment variable:

    RATE_LIMIT_ENABLED         "false" turns the limiter off entirely (default on).
    RATE_LIMIT_<POLICY>        "limit/window_seconds", e.g. RATE_LIMIT_LOGIN_IP=20/60. "off" disables one policy.

Keys never contain a raw email, tracking code or address: identifiers are hashed, so Redis (and anything that
dumps it) holds no personal data, only opaque counters that expire within the policy's window.
"""

import hashlib
import logging
import os
import time
from dataclasses import dataclass
from typing import Any

from shared.client_ip import client_ip
from shared.distributed_cache import DistributedCache
from shared.exceptions import RateLimitExceededError

logger = logging.getLogger(__name__)

ENABLED_ENV = "RATE_LIMIT_ENABLED"
_cache: DistributedCache = DistributedCache(default_ttl=60, key_prefix="ratelimit:")

# An outage is logged at most this often per process, so a Redis outage is one alarm and not a flood of lines.
_UNAVAILABLE_LOG_INTERVAL_SECONDS = 30.0
_last_unavailable_log = 0.0


@dataclass(frozen=True)
class RateLimit:
    """A named limit: `limit` events per fixed window of `window_seconds`."""

    name: str
    limit: int
    window_seconds: int


# The defaults the owner approved (2026-11-15). Each can be overridden by RATE_LIMIT_<NAME>.
LOGIN_IP = RateLimit("login_ip", 10, 60)  # login attempts per client address
LOGIN_FAILURES = RateLimit("login_failures", 5, 900)  # wrong passwords per username
REGISTER_IP = RateLimit("register_ip", 5, 3600)  # customer self-registrations per address
ONBOARDING_IP = RateLimit("onboarding_ip", 5, 3600)  # company onboarding requests per address
TRACKING_IP = RateLimit("tracking_ip", 30, 60)  # public tracking lookups per address
TRACKING_FAILURES = RateLimit("tracking_failures", 10, 3600)  # wrong-phone guesses per tracking code
SESSION_IP = RateLimit("session_ip", 60, 60)  # refresh / session / logout / sign-in redirect calls per address
TENANT = RateLimit("tenant", 600, 60)  # authenticated requests per tenant


def enabled() -> bool:
    """False when the limiter is switched off for this process."""
    return os.environ.get(ENABLED_ENV, "true").strip().lower() not in {"false", "0", "off", "no"}


def _effective(policy: RateLimit) -> RateLimit | None:
    """The policy with any environment override applied, or None if it is switched off."""
    raw = os.environ.get(f"RATE_LIMIT_{policy.name.upper()}", "").strip().lower()
    if not raw:
        return policy
    if raw == "off":
        return None
    try:
        limit_text, _, window_text = raw.partition("/")
        limit, window = int(limit_text), int(window_text)
        if limit < 1 or window < 1:
            raise ValueError("limit and window must be positive")
    except ValueError:
        logger.warning("Ignoring RATE_LIMIT_%s=%r: expected 'limit/window_seconds'", policy.name.upper(), raw)
        return policy
    return RateLimit(policy.name, limit, window)


def _key(policy: RateLimit, identifier: str) -> str:
    digest = hashlib.sha256(identifier.strip().lower().encode()).hexdigest()[:32]
    return f"{policy.name}:{digest}"


def _log_unavailable(policy: RateLimit) -> None:
    global _last_unavailable_log
    now = time.monotonic()
    if now - _last_unavailable_log >= _UNAVAILABLE_LOG_INTERVAL_SECONDS:
        _last_unavailable_log = now
        logger.error("rate_limiter_unavailable: Redis could not be reached, allowing requests (policy=%s)", policy.name)


def hit(policy: RateLimit, identifier: str) -> None:
    """Count one request against `identifier`; raise RateLimitExceededError once it is past the limit."""
    if not enabled() or not identifier:
        return
    effective = _effective(policy)
    if effective is None:
        return
    state = _cache.incr_window(_key(effective, identifier), effective.window_seconds)
    if state is None:
        _log_unavailable(effective)
        return
    count, retry_after = state
    if count > effective.limit:
        logger.warning("Rate limit exceeded (policy=%s, key=%s)", effective.name, _key(effective, identifier)[-8:])
        raise RateLimitExceededError(retry_after)


def peek(policy: RateLimit, identifier: str) -> None:
    """Raise RateLimitExceededError if `identifier` has already used up the limit, without counting."""
    if not enabled() or not identifier:
        return
    effective = _effective(policy)
    if effective is None:
        return
    state = _cache.window_state(_key(effective, identifier))
    if state is None:
        _log_unavailable(effective)
        return
    count, retry_after = state
    if count >= effective.limit:
        logger.warning("Rate limit exceeded (policy=%s, key=%s)", effective.name, _key(effective, identifier)[-8:])
        raise RateLimitExceededError(retry_after or effective.window_seconds)


def record_failure(policy: RateLimit, identifier: str) -> None:
    """Count one failure against `identifier`. Never raises: the request that failed has already been answered."""
    if not enabled() or not identifier:
        return
    effective = _effective(policy)
    if effective is None:
        return
    if _cache.incr_window(_key(effective, identifier), effective.window_seconds) is None:
        _log_unavailable(effective)


def clear(policy: RateLimit, identifier: str) -> None:
    """Forget `identifier`'s count, for after a success."""
    if not enabled() or not identifier:
        return
    effective = _effective(policy)
    if effective is not None:
        _cache.delete(_key(effective, identifier))


def hit_for_client(policy: RateLimit, event: dict[str, Any]) -> None:
    """`hit` keyed by the request's client address.

    An unknown address is not limited: lumping every request with no address into one bucket would
    let a handful of them lock everybody out.
    """
    address = client_ip(event)
    if address:
        hit(policy, address)
