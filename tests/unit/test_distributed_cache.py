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
