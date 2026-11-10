"""Unit tests for the two-credential rule and the app-role password step.

The integration behaviour — that running the migrate entrypoint against a
database whose `logistics_app` is NOLOGIN actually repairs it — is covered by
`tests/tenant_isolation/test_rls_enforcement.py` and was verified by hand
against the reproduced Azure failure state. These tests cover the decision
logic, which is where the original bug lived: migration 060 chose to do nothing
and that choice was then recorded as permanent.
"""

import pytest

from shared.db_credentials import admin_db_params, admin_sqlalchemy_url, ensure_app_role_password

_BASE_ENV = {
    "DATABASE_HOST": "db.example.internal",
    "DATABASE_NAME": "logistics",
    "DATABASE_USER": "logistics_app",
    "DATABASE_PASSWORD": "app-pw",
}


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for key in (*_BASE_ENV, "DATABASE_PORT", "DATABASE_ADMIN_USER", "DATABASE_ADMIN_PASSWORD", "APP_DB_PASSWORD"):
        monkeypatch.delenv(key, raising=False)
    for key, value in _BASE_ENV.items():
        monkeypatch.setenv(key, value)


class TestAdminCredentialResolution:
    def test_prefers_the_admin_pair_when_present(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("DATABASE_ADMIN_USER", "postgres")
        monkeypatch.setenv("DATABASE_ADMIN_PASSWORD", "owner-pw")

        params = admin_db_params()

        assert params["user"] == "postgres"
        assert params["password"] == "owner-pw"

    def test_falls_back_to_the_app_pair(self) -> None:
        """An environment not yet cut over keeps working, running all as owner."""
        params = admin_db_params()

        assert params["user"] == "logistics_app"
        assert params["password"] == "app-pw"

    def test_missing_required_variable_raises_rather_than_defaulting(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Connecting somewhere unintended is worse than failing loudly."""
        monkeypatch.delenv("DATABASE_HOST")

        with pytest.raises(KeyError):
            admin_db_params()

    def test_sqlalchemy_url_quotes_a_password_with_url_metacharacters(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """A generated secret very often contains @ / or : — it must not corrupt the URL."""
        monkeypatch.setenv("DATABASE_ADMIN_USER", "postgres")
        monkeypatch.setenv("DATABASE_ADMIN_PASSWORD", "p@ss/w:rd")

        url = admin_sqlalchemy_url()

        assert "p%40ss%2Fw%3Ard" in url
        assert "@db.example.internal:5432/logistics" in url


class TestEnsureAppRolePassword:
    def test_unset_password_is_not_an_error(self) -> None:
        """An environment awaiting cutover has no such secret.

        Raising here would block its deploy, which is why migration 060 chose to
        no-op instead. The no-op was right; recording it as permanent was not.
        """
        assert ensure_app_role_password() == "skipped-no-password"

    def test_does_not_connect_when_there_is_no_password_to_set(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """The skip must come before the connection, not after a failed one."""
        import psycopg2

        def _explode(**_: object) -> object:
            raise AssertionError("connected despite having no password to apply")

        monkeypatch.setattr(psycopg2, "connect", _explode)

        assert ensure_app_role_password() == "skipped-no-password"

    def test_reports_skipped_when_the_role_does_not_exist(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """A database predating migration 005 has no such role; say so, don't crash."""
        import psycopg2

        monkeypatch.setenv("APP_DB_PASSWORD", "new-pw")
        monkeypatch.setattr(psycopg2, "connect", lambda **_: _FakeConn(role_exists=False))

        assert ensure_app_role_password() == "skipped-no-role"

    def test_binds_the_password_as_a_parameter_never_as_sql_text(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """The project forbids interpolating values into SQL; ALTER ROLE cannot bind."""
        import psycopg2

        conn = _FakeConn(role_exists=True)
        monkeypatch.setenv("APP_DB_PASSWORD", "s3cr3t-value")
        monkeypatch.setattr(psycopg2, "connect", lambda **_: conn)

        assert ensure_app_role_password() == "set"

        statements = [sql for sql, _ in conn.cursor_obj.executed]
        assert any("ALTER ROLE logistics_app LOGIN PASSWORD %L" in s for s in statements)
        assert not any("s3cr3t-value" in s for s in statements), "password reached SQL text"
        assert ("SELECT set_config('shipx.app_db_password', %s, true)", ("s3cr3t-value",)) in conn.cursor_obj.executed

    def test_strips_bypassrls_so_the_switchover_is_not_silently_pointless(self, monkeypatch: pytest.MonkeyPatch) -> None:
        import psycopg2

        conn = _FakeConn(role_exists=True)
        monkeypatch.setenv("APP_DB_PASSWORD", "pw")
        monkeypatch.setattr(psycopg2, "connect", lambda **_: conn)

        ensure_app_role_password()

        assert any("NOBYPASSRLS" in sql for sql, _ in conn.cursor_obj.executed)


class _FakeCursor:
    def __init__(self, role_exists: bool) -> None:
        self.role_exists = role_exists
        self.executed: list[tuple[str, object]] = []

    def execute(self, sql: str, params: object = None) -> None:
        self.executed.append((sql, params))

    def fetchone(self) -> tuple[int] | None:
        return (1,) if self.role_exists else None

    def __enter__(self) -> "_FakeCursor":
        return self

    def __exit__(self, *_: object) -> None:
        return None


class _FakeConn:
    def __init__(self, role_exists: bool) -> None:
        self.cursor_obj = _FakeCursor(role_exists)

    def cursor(self) -> _FakeCursor:
        return self.cursor_obj

    def __enter__(self) -> "_FakeConn":
        return self

    def __exit__(self, *_: object) -> None:
        return None
