"""Unit tests for shared/distributed_cache.py client construction — the
REDIS_PASSWORD / REDIS_SSL support added for Azure Cache for Redis (TLS + key),
while AWS/local stays plain TCP with no auth. The redis package is faked so no
server is needed."""

import sys
from unittest.mock import MagicMock, patch

from shared.distributed_cache import DistributedCache


def _construct_client_with_env(env: dict[str, str]) -> dict:
    """Build a DistributedCache client with `env` applied and return the kwargs
    passed to redis.Redis(...)."""
    fake_redis = MagicMock()
    cache = DistributedCache()
    cache._client = None  # noqa: SLF001 — force a fresh build
    base = {"REDIS_HOST": "localhost", "REDIS_PORT": "6379", "REDIS_PASSWORD": "", "REDIS_SSL": ""}
    base.update(env)
    with patch.dict(sys.modules, {"redis": fake_redis}), patch.dict("os.environ", base, clear=False):
        cache._get_client()  # noqa: SLF001
    return fake_redis.Redis.call_args.kwargs


class TestRedisClientConstruction:
    def test_aws_local_default_no_auth_no_tls(self):
        kwargs = _construct_client_with_env({"REDIS_HOST": "localhost", "REDIS_PORT": "6379"})
        assert kwargs["host"] == "localhost"
        assert kwargs["port"] == 6379
        assert kwargs["password"] is None
        assert kwargs["ssl"] is False

    def test_azure_tls_and_password(self):
        kwargs = _construct_client_with_env(
            {
                "REDIS_HOST": "shipx.redis.cache.windows.net",
                "REDIS_PORT": "6380",
                "REDIS_PASSWORD": "secret-key",
                "REDIS_SSL": "true",
            }
        )
        assert kwargs["port"] == 6380
        assert kwargs["password"] == "secret-key"
        assert kwargs["ssl"] is True

    def test_ssl_flag_is_case_insensitive_and_defaults_off(self):
        assert _construct_client_with_env({"REDIS_SSL": "TRUE"})["ssl"] is True
        assert _construct_client_with_env({"REDIS_SSL": "false"})["ssl"] is False
        assert _construct_client_with_env({})["ssl"] is False


class TestWireProtocolIsPinned:
    """redis-py 8 changed the DEFAULT wire protocol; this cache must not follow.

    redis-py <= 5 defaulted connections to RESP2. redis-py 8 defaults them to
    RESP3, which negotiates with `HELLO 3` and requires a Redis server >= 6.0.

    That would be a silent change, which is why it is pinned and tested: every
    method on DistributedCache fails OPEN (logs a warning, returns None, and the
    caller falls back to the database), so a server rejecting the handshake would
    not raise anything. The cache would simply stop working and the only symptom
    would be extra database load — the hardest kind of regression to notice.
    """

    def test_resp2_is_requested_explicitly(self) -> None:
        kwargs = _construct_client_with_env({})
        assert kwargs["protocol"] == 2, (
            "RESP2 must stay explicit — relying on the redis-py default is what changed between 5.x and 8.x"
        )

    def test_protocol_is_pinned_regardless_of_environment(self) -> None:
        # Azure (TLS + key) and AWS (plain TCP) must agree on the protocol.
        azure = _construct_client_with_env(
            {"REDIS_HOST": "shipx.redis.cache.windows.net", "REDIS_PORT": "6380", "REDIS_SSL": "true"}
        )
        aws = _construct_client_with_env({"REDIS_HOST": "localhost", "REDIS_PORT": "6379"})
        assert azure["protocol"] == aws["protocol"] == 2


class TestRedisOutageIsFastNotSlow:
    """A Redis outage must cost one fast failure, not seconds per call.

    redis-py's default retries a failed command with exponential backoff, which made every operation against
    an unreachable Redis take about four seconds. A request makes several (tenant status, identity, rate
    limits), so an outage was a multi-second delay on every authenticated request: not fail-soft at all.
    """

    def test_the_client_does_not_retry_a_failed_command(self) -> None:
        client = DistributedCache()._get_client()  # noqa: SLF001 — real redis-py; it connects lazily, so no server is needed
        assert client.get_retry().get_retries() == 0

    @staticmethod
    def _cache_with(client: MagicMock) -> DistributedCache:
        cache = DistributedCache(key_prefix="t:")
        cache._client = client  # noqa: SLF001
        return cache

    def test_after_a_failure_redis_is_left_alone_for_a_while(self) -> None:
        client = MagicMock()
        client.get.side_effect = ConnectionError("down")
        cache = self._cache_with(client)

        assert cache.get("a") is None
        assert cache.get("b") is None
        cache.set("c", "v")
        cache.delete("d")
        assert cache.incr_window("e", 60) is None
        assert cache.window_state("f") is None

        client.get.assert_called_once()  # only the first call reached Redis
        client.setex.assert_not_called()
        client.delete.assert_not_called()
        client.eval.assert_not_called()

    def test_redis_is_tried_again_after_the_cooldown(self) -> None:
        client = MagicMock()
        client.get.side_effect = [ConnectionError("down"), "active"]
        cache = self._cache_with(client)

        assert cache.get("a") is None
        cache._down_until = 0.0  # noqa: SLF001 — the cooldown has passed
        assert cache.get("a") == "active"

    def test_a_working_redis_is_never_skipped(self) -> None:
        client = MagicMock()
        client.get.return_value = "active"
        cache = self._cache_with(client)

        assert [cache.get("a") for _ in range(20)] == ["active"] * 20
        assert client.get.call_count == 20

    def test_every_operation_fails_open_during_an_outage(self) -> None:
        client = MagicMock()
        for method in (client.get, client.setex, client.delete, client.eval):
            method.side_effect = ConnectionError("down")
        cache = self._cache_with(client)

        assert cache.get("a") is None
        cache._down_until = 0.0  # noqa: SLF001
        cache.set("a", "v")
        cache._down_until = 0.0  # noqa: SLF001
        cache.delete("a")
        cache._down_until = 0.0  # noqa: SLF001
        assert cache.incr_window("a", 60) is None

    def test_the_outage_is_logged_once_not_per_call(self, caplog) -> None:
        import logging

        client = MagicMock()
        client.get.side_effect = ConnectionError("down")
        cache = self._cache_with(client)

        with caplog.at_level(logging.WARNING, logger="shared.distributed_cache"):
            for _ in range(50):
                cache.get("a")
        assert len([r for r in caplog.records if "Redis GET failed" in r.getMessage()]) == 1
