"""The rate limiter's Redis script against a real Redis server (audit SEC-03).

An in-memory fake can show the limiter's logic but not what Redis does: that the INCR and the expiry happen
together, that the window does not slide, that concurrent callers are counted exactly, and that a counter
can never be left without an expiry (which would lock a client out for good). Every key lives under a prefix
unique to the test and is removed afterwards, so this is safe to run against a shared development Redis.
"""

import logging
import os
import threading
import time
import uuid

import pytest

from shared import rate_limit
from shared.distributed_cache import DistributedCache
from shared.exceptions import RateLimitExceededError

pytestmark = pytest.mark.db


@pytest.fixture
def cache():
    """A DistributedCache on the configured Redis under its own prefix, cleaned up afterwards."""
    prefix = f"test-{uuid.uuid4().hex[:10]}:"
    fake = DistributedCache(key_prefix=prefix)
    try:
        fake._get_client().ping()
    except Exception as exc:  # pragma: no cover - environment dependent
        pytest.skip(f"no Redis reachable (set REDIS_HOST/REDIS_PORT): {exc}")
    yield fake
    client = fake._get_client()
    for key in client.scan_iter(match=f"{prefix}*"):
        client.delete(key)


class TestIncrWindow:
    def test_the_first_event_starts_a_window_of_the_requested_length(self, cache):
        count, ttl = cache.incr_window("k", 60)
        assert count == 1
        assert 58 <= ttl <= 60

    def test_later_events_count_up_and_do_not_extend_the_window(self, cache):
        cache.incr_window("k", 60)
        time.sleep(1.1)
        count, ttl = cache.incr_window("k", 60)
        assert count == 2
        assert ttl <= 59, "the window is fixed; counting must not slide it"

    def test_the_window_ends_and_the_count_starts_again(self, cache):
        cache.incr_window("k", 1)
        cache.incr_window("k", 1)
        time.sleep(1.3)
        assert cache.incr_window("k", 1)[0] == 1

    def test_a_counter_that_somehow_has_no_expiry_gets_one(self, cache):
        """Otherwise a client could be locked out forever by a counter that never ends."""
        cache._get_client().set(cache._key("k"), 7)
        assert cache._get_client().ttl(cache._key("k")) == -1
        count, ttl = cache.incr_window("k", 60)
        assert count == 8
        assert 0 < ttl <= 60
        assert cache._get_client().ttl(cache._key("k")) > 0

    def test_concurrent_events_are_counted_exactly(self, cache):
        results: list[int] = []

        def work() -> None:
            for _ in range(25):
                results.append(cache.incr_window("k", 60)[0])

        threads = [threading.Thread(target=work) for _ in range(8)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert sorted(results) == list(range(1, 201)), "every event gets its own count: no two callers see the same number"

    def test_window_state_reads_without_counting(self, cache):
        assert cache.window_state("k") == (0, 0)
        cache.incr_window("k", 60)
        count, ttl = cache.window_state("k")
        assert (count, 0 < ttl <= 60) == (1, True)
        assert cache.window_state("k")[0] == 1


class TestLimiterOnRealRedis:
    @pytest.fixture(autouse=True)
    def _wire(self, cache, monkeypatch):
        monkeypatch.setenv("RATE_LIMIT_ENABLED", "true")
        monkeypatch.setattr(rate_limit, "_cache", cache)
        monkeypatch.setattr(rate_limit, "_last_unavailable_log", 0.0)
        self.cache = cache

    def test_a_flood_is_refused_after_the_limit_with_a_wait_inside_the_window(self, monkeypatch):
        monkeypatch.setenv("RATE_LIMIT_LOGIN_IP", "3/60")
        for _ in range(3):
            rate_limit.hit(rate_limit.LOGIN_IP, "203.0.113.9")
        with pytest.raises(RateLimitExceededError) as exc:
            rate_limit.hit(rate_limit.LOGIN_IP, "203.0.113.9")
        assert 1 <= exc.value.retry_after <= 60
        rate_limit.hit(rate_limit.LOGIN_IP, "203.0.113.10")

    def test_guesses_lock_out_and_a_success_lets_back_in(self, monkeypatch):
        monkeypatch.setenv("RATE_LIMIT_LOGIN_FAILURES", "2/60")
        for _ in range(2):
            rate_limit.peek(rate_limit.LOGIN_FAILURES, "ada@example.test")
            rate_limit.record_failure(rate_limit.LOGIN_FAILURES, "ada@example.test")
        with pytest.raises(RateLimitExceededError):
            rate_limit.peek(rate_limit.LOGIN_FAILURES, "ada@example.test")
        rate_limit.clear(rate_limit.LOGIN_FAILURES, "ada@example.test")
        rate_limit.peek(rate_limit.LOGIN_FAILURES, "ada@example.test")

    def test_redis_holds_no_raw_identifier(self):
        rate_limit.hit(rate_limit.LOGIN_IP, "203.0.113.9")
        rate_limit.record_failure(rate_limit.LOGIN_FAILURES, "ada@example.test")
        keys = " ".join(self.cache._get_client().scan_iter(match=f"{self.cache._key_prefix}*"))
        assert keys
        assert "203.0.113.9" not in keys
        assert "ada@example.test" not in keys

    def test_every_counter_expires(self):
        rate_limit.hit(rate_limit.TENANT, "tenant-a")
        client = self.cache._get_client()
        ttls = [client.ttl(key) for key in client.scan_iter(match=f"{self.cache._key_prefix}*")]
        assert ttls
        assert all(t > 0 for t in ttls)


class TestRealOutage:
    def test_an_unreachable_redis_lets_requests_through_and_raises_the_alarm(self, monkeypatch, caplog):
        """Fail open for real: a connection refused, not a stub that says it is down."""
        monkeypatch.setenv("RATE_LIMIT_ENABLED", "true")
        monkeypatch.setenv("REDIS_PORT", "1")  # nothing listens here
        dead = DistributedCache(key_prefix="dead:")
        monkeypatch.setattr(rate_limit, "_cache", dead)
        monkeypatch.setattr(rate_limit, "_last_unavailable_log", 0.0)

        started = time.monotonic()
        with caplog.at_level(logging.ERROR):
            for _ in range(rate_limit.LOGIN_IP.limit + 5):
                rate_limit.hit(rate_limit.LOGIN_IP, "203.0.113.9")
        elapsed = time.monotonic() - started

        assert any("rate_limiter_unavailable" in r.getMessage() for r in caplog.records)
        assert elapsed < 15, f"an outage must not turn every request into a long wait (took {elapsed:.1f}s)"


def test_the_redis_the_suite_talks_to_is_configured():
    """A guard so a skipped suite is noticed: in CI REDIS_HOST is always set."""
    if os.environ.get("CI") and not os.environ.get("REDIS_HOST"):
        pytest.fail("CI must provide Redis (REDIS_HOST) for the rate limiter tests")
