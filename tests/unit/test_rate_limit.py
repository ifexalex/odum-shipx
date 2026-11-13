"""Unit tests for the public-endpoint throttle.

The thing being protected is `POST /v1/register/{slug}`: it creates a Cognito
user and two database rows, needs no credentials, and had no limit of any kind.
That was tolerable while the signup link was effectively undiscoverable. It
stops being tolerable the moment companies put the link on a QR poster, which
is what it now ships alongside.
"""

import contextlib

import pytest

from shared.exceptions import LogisticsBaseError
from shared.rate_limit import DEFAULT_LIMIT, RateLimitExceededError, check_rate_limit


class _FakeCache:
    """Stands in for Redis, counting per key like INCR does."""

    def __init__(self, *, unreachable: bool = False) -> None:
        self.counts: dict[str, int] = {}
        self.ttls: dict[str, int] = {}
        self.unreachable = unreachable

    def incr(self, key: str, ttl: int | None = None) -> int | None:
        if self.unreachable:
            return None
        self.counts[key] = self.counts.get(key, 0) + 1
        if self.counts[key] == 1 and ttl is not None:
            self.ttls[key] = ttl
        return self.counts[key]


@pytest.fixture
def cache(monkeypatch: pytest.MonkeyPatch) -> _FakeCache:
    fake = _FakeCache()
    monkeypatch.setattr("shared.rate_limit._cache", fake)
    return fake


class TestRateLimit:
    def test_allows_attempts_up_to_the_limit(self, cache: _FakeCache) -> None:
        for _ in range(DEFAULT_LIMIT):
            check_rate_limit("self_register", "203.0.113.5")

    def test_raises_once_over_the_limit(self, cache: _FakeCache) -> None:
        for _ in range(DEFAULT_LIMIT):
            check_rate_limit("self_register", "203.0.113.5")

        with pytest.raises(RateLimitExceededError):
            check_rate_limit("self_register", "203.0.113.5")

    def test_counts_per_caller_not_globally(self, cache: _FakeCache) -> None:
        """One abusive address must not lock out everyone else."""
        for _ in range(DEFAULT_LIMIT + 1):
            with contextlib.suppress(RateLimitExceededError):
                check_rate_limit("self_register", "203.0.113.5")

        check_rate_limit("self_register", "198.51.100.9")

    def test_counts_per_action_not_across_them(self, cache: _FakeCache) -> None:
        """Exhausting one action must not spend another's budget."""
        for _ in range(DEFAULT_LIMIT):
            check_rate_limit("self_register", "203.0.113.5")

        check_rate_limit("password_reset", "203.0.113.5")

    def test_the_window_ttl_is_set_once_on_creation(self, cache: _FakeCache) -> None:
        """A TTL refreshed on every hit would hold the window open forever."""
        for _ in range(3):
            check_rate_limit("self_register", "203.0.113.5", window_seconds=900)

        assert cache.ttls == {"self_register:203.0.113.5": 900}

    def test_an_unknown_caller_is_allowed_rather_than_shared(self, cache: _FakeCache) -> None:
        """One bucket for every unidentified caller would let one script lock
        out everyone whose address also failed to resolve."""
        for _ in range(DEFAULT_LIMIT * 3):
            check_rate_limit("self_register", None)

    def test_fails_open_when_redis_is_unreachable(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """A Redis blip must not stop the world from signing up.

        The cost is explicit: an attacker who can take Redis down also removes
        the throttle. That is why this is one layer and not the only one.
        """
        monkeypatch.setattr("shared.rate_limit._cache", _FakeCache(unreachable=True))

        for _ in range(DEFAULT_LIMIT * 2):
            check_rate_limit("self_register", "203.0.113.5")

    def test_the_error_maps_to_429_like_every_other_domain_error(self, cache: _FakeCache) -> None:
        for _ in range(DEFAULT_LIMIT):
            check_rate_limit("self_register", "203.0.113.5")

        with pytest.raises(RateLimitExceededError) as exc:
            check_rate_limit("self_register", "203.0.113.5")

        assert isinstance(exc.value, LogisticsBaseError)
        assert exc.value.status_code == 429
        assert exc.value.error_code == "RATE_LIMIT_EXCEEDED"

    def test_the_message_names_no_identifier(self, cache: _FakeCache) -> None:
        """It is returned to an unauthenticated caller, so it must not confirm
        that a slug, a company or an email exists."""
        for _ in range(DEFAULT_LIMIT):
            check_rate_limit("self_register", "203.0.113.5")

        with pytest.raises(RateLimitExceededError) as exc:
            check_rate_limit("self_register", "203.0.113.5")

        assert "203.0.113.5" not in str(exc.value)
        assert "self_register" not in str(exc.value)
