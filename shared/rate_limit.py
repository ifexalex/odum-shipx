"""Per-caller throttling for public, unauthenticated endpoints.

Why this exists
---------------
`POST /v1/register/{slug}` creates a real account — a Cognito user, a
`tenant_user` row and a `customer` row — and requires no credentials to call.
It had no throttle of any kind. That was survivable while the signup link was
effectively undiscoverable; it stops being survivable the moment companies put
that link on a QR code and a poster, which is exactly what the feature this
ships alongside is for.

Fixed window, not a token bucket
--------------------------------
A fixed window is one `INCR` plus one `EXPIRE` on first write — atomic, and
cheap enough to sit in front of every public request. Its known weakness is the
boundary: a caller can send a full allowance at the end of one window and
another at the start of the next, so the true worst case is 2x the limit over a
short span. That is acceptable here. The purpose is to stop scripted bulk
signup, not to meter an API, and the limits are set well below what a human
filling in a form could reach.

Fails OPEN
----------
When Redis is unreachable the limiter allows the request and logs a warning.
This matches `shared/auth.py`'s tenant-status cache, which also falls through
on Redis failure, and it is a deliberate trade: a Redis blip should not stop
every customer in the world from signing up. The cost is that an attacker who
can take Redis down also removes the throttle — which is why this is one layer,
not the only one. Email uniqueness, Cognito's own protections and the tenant
toggle sit beside it.
"""

import logging

from shared.distributed_cache import DistributedCache
from shared.exceptions import LogisticsBaseError

logger = logging.getLogger(__name__)

# Attempts allowed per window, per caller, per action.
#
# Ten is far above what a person completing a signup form reaches — including
# validation failures and a retry or two — and far below what a script needs to
# be useful. A shared office NAT could plausibly produce several genuine
# signups in fifteen minutes, which is why it is not tighter.
DEFAULT_LIMIT = 10
DEFAULT_WINDOW_SECONDS = 15 * 60

_cache: DistributedCache = DistributedCache(default_ttl=DEFAULT_WINDOW_SECONDS, key_prefix="ratelimit:")


class RateLimitExceededError(LogisticsBaseError):
    """Raised when a caller has exhausted its allowance for this window.

    A `LogisticsBaseError` rather than a bare Exception so it maps to 429
    through the same path as every other domain error — the handler needs no
    special case, and the RFC 7807 body comes out consistent with the rest of
    the API.

    The message deliberately names no identifier. It is returned to an
    unauthenticated caller, so it must not confirm whether a slug, a company or
    an email exists.
    """

    def __init__(self, action: str, limit: int, window_seconds: int) -> None:
        super().__init__(
            message=f"Too many attempts. Try again in {window_seconds // 60} minutes.",
            error_code="RATE_LIMIT_EXCEEDED",
            status_code=429,
        )
        self.action = action
        self.limit = limit
        self.window_seconds = window_seconds


def check_rate_limit(
    action: str,
    caller: str | None,
    *,
    limit: int = DEFAULT_LIMIT,
    window_seconds: int = DEFAULT_WINDOW_SECONDS,
) -> None:
    """Count this attempt and raise once the caller is over the limit.

    Args:
        action: What is being limited, e.g. ``"self_register"``. Namespaces the
            counter so one throttled action cannot exhaust another's budget.
        caller: The IP address, or None when it could not be determined.
        limit: Attempts permitted per window.
        window_seconds: Window length.

    Raises:
        RateLimitExceededError: The caller is over the limit.
    """
    if not caller:
        # No IP means no key to count against. Allowing it is the lesser evil:
        # a single shared bucket for every unidentified caller would let one
        # script lock out everyone whose address we also failed to read.
        logger.warning("Rate limit skipped for action=%s — no caller address", action)
        return

    count = _cache.incr(f"{action}:{caller}", ttl=window_seconds)
    if count is None:
        # Redis unreachable — see the module docstring on failing open.
        return

    if count > limit:
        # Logged at WARNING with the action and count but WITHOUT the address:
        # an IP is personal data under GDPR, and the project forbids PII in
        # CloudWatch. The count alone is what tells an operator this is
        # happening.
        logger.warning("Rate limit exceeded for action=%s (attempt %d of %d allowed)", action, count, limit)
        raise RateLimitExceededError(action, limit, window_seconds)
