"""Regression tests for shared/db.py's connection self-heal.

Found live via e2e testing: shared/metering.py's record_usage() hit a
duplicate-key race on rapid requests, and — for reasons not fully pinned
down, but observed directly — the connection was left in a failed-transaction
state that then broke *every subsequent unrelated request* on the same
process with `psycopg2.errors.InFailedSqlTransaction: current transaction is
aborted`. In production this is a warm Lambda container reusing the same
module-level connection across invocations, so one such failure would break
every request on that container until AWS recycles it.
"""

from unittest.mock import MagicMock, patch

import psycopg2.extensions

import shared.db as db_module


class TestConnectionSelfHeal:
    def setup_method(self) -> None:
        """Reset the module-level connection singleton before each test.

        setup_function/teardown_function (module-level hooks) silently do not
        apply to methods inside a test class — the first version of this file
        used those, so the previous test's mock connection leaked into the
        next one via shared.db's module-global `_connection`, making
        test_creates_a_new_connection_when_none_exists fail only when run
        alongside its sibling tests, never in isolation.
        """
        db_module._connection = None  # noqa: SLF001 — test needs a clean slate

    def teardown_method(self) -> None:
        db_module._connection = None  # noqa: SLF001

    def test_rolls_back_a_connection_left_in_a_failed_transaction(self) -> None:
        """A reused connection stuck INERROR is healed before being handed out,
        not left to fail every query until something else notices."""
        stuck_conn = MagicMock()
        stuck_conn.closed = False
        stuck_conn.get_transaction_status.return_value = psycopg2.extensions.TRANSACTION_STATUS_INERROR
        db_module._connection = stuck_conn

        result = db_module.get_connection()

        assert result is stuck_conn
        stuck_conn.rollback.assert_called_once()

    def test_healthy_connection_is_returned_untouched(self) -> None:
        """No unnecessary rollback on a connection that isn't broken."""
        healthy_conn = MagicMock()
        healthy_conn.closed = False
        healthy_conn.get_transaction_status.return_value = psycopg2.extensions.TRANSACTION_STATUS_IDLE
        db_module._connection = healthy_conn

        result = db_module.get_connection()

        assert result is healthy_conn
        healthy_conn.rollback.assert_not_called()

    def test_creates_a_new_connection_when_none_exists(self) -> None:
        with (
            patch.object(db_module.psycopg2, "connect") as mock_connect,
            patch.dict(
                "os.environ",
                {
                    "DATABASE_HOST": "localhost",
                    "DATABASE_PORT": "5432",
                    "DATABASE_NAME": "test",
                    "DATABASE_USER": "test",
                    "DATABASE_PASSWORD": "test",
                    "DB_SECRET_ARN": "",  # forces the local-mode password path, not Secrets Manager
                },
                clear=False,
            ),
        ):
            db_module._cached_password = None  # noqa: SLF001 — avoid leaking a cached prod password
            mock_connect.return_value = MagicMock(closed=False)
            result = db_module.get_connection()

        mock_connect.assert_called_once()
        assert result is mock_connect.return_value


class TestSslMode:
    """sslmode selection (added for Azure Postgres, which mandates TLS)."""

    def setup_method(self) -> None:
        db_module._connection = None  # noqa: SLF001
        db_module._cached_password = None  # noqa: SLF001

    def teardown_method(self) -> None:
        db_module._connection = None  # noqa: SLF001

    def _connect_with_env(self, env: dict[str, str]) -> str:
        base = {
            "DATABASE_HOST": "localhost",
            "DATABASE_PORT": "5432",
            "DATABASE_NAME": "test",
            "DATABASE_USER": "test",
            "DATABASE_PASSWORD": "test",
            "DB_SECRET_ARN": "",
            "DATABASE_SSLMODE": "",
        }
        base.update(env)
        with (
            patch.object(db_module.psycopg2, "connect") as mock_connect,
            patch.object(db_module, "_get_db_password", return_value="test"),
            patch.dict("os.environ", base, clear=False),
        ):
            mock_connect.return_value = MagicMock(closed=False)
            db_module.get_connection()
        return mock_connect.call_args.kwargs["sslmode"]

    def test_explicit_sslmode_wins(self) -> None:
        # Azure path: DATABASE_SSLMODE=require overrides everything.
        assert self._connect_with_env({"DATABASE_SSLMODE": "require"}) == "require"

    def test_aws_production_defaults_to_require(self) -> None:
        assert self._connect_with_env({"DB_SECRET_ARN": "arn:aws:secretsmanager:x"}) == "require"

    def test_local_defaults_to_prefer(self) -> None:
        assert self._connect_with_env({}) == "prefer"
