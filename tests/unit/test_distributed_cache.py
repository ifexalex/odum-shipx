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
