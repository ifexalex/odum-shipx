"""Unit tests for the two-credential rule and the app-role password step.

Every literal here is deliberately spelled ``fake_..._not_a_secret``. The
first version used realistic-looking passwords and GitGuardian failed the PR
with "3 secrets uncovered" — correctly, since a scanner cannot tell a fixture
from a leak. The project already uses this convention in ``.env.local.sample``
and ``ci.yml``; it keeps the scanner useful instead of training people to wave
it through.

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
    "DATABASE_PASSWORD": "fake_app_value_not_a_secret",
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
        monkeypatch.setenv("DATABASE_ADMIN_PASSWORD", "fake_owner_value_not_a_secret")

        params = admin_db_params()

        assert params["user"] == "postgres"
        assert params["password"] == "fake_owner_value_not_a_secret"

    def test_falls_back_to_the_app_pair(self) -> None:
        """An environment not yet cut over keeps working, running all as owner."""
        params = admin_db_params()

        assert params["user"] == "logistics_app"
        assert params["password"] == "fake_app_value_not_a_secret"

    def test_missing_required_variable_raises_rather_than_defaulting(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Connecting somewhere unintended is worse than failing loudly."""
        monkeypatch.delenv("DATABASE_HOST")

        with pytest.raises(KeyError):
            admin_db_params()

    def test_sqlalchemy_url_quotes_a_password_with_url_metacharacters(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """A generated secret very often contains @ / or : — it must not corrupt the URL."""
        monkeypatch.setenv("DATABASE_ADMIN_USER", "postgres")
        monkeypatch.setenv("DATABASE_ADMIN_PASSWORD", "fake@value/with:metachars")

        url = admin_sqlalchemy_url()

        assert "fake%40value%2Fwith%3Ametachars" in url
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

        monkeypatch.setenv("APP_DB_PASSWORD", "fake_value_not_a_secret")
        monkeypatch.setattr(psycopg2, "connect", lambda **_: _FakeConn(role_exists=False))

        assert ensure_app_role_password() == "skipped-no-role"

    def test_binds_the_password_as_a_parameter_never_as_sql_text(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """The project forbids interpolating values into SQL; ALTER ROLE cannot bind."""
        import psycopg2

        conn = _FakeConn()
        monkeypatch.setenv("APP_DB_PASSWORD", "fake_sentinel_not_a_secret")
        monkeypatch.setattr(psycopg2, "connect", lambda **_: conn)

        assert ensure_app_role_password() == "set"

        statements = [sql for sql, _ in conn.cursor_obj.executed]
        assert any("ALTER ROLE logistics_app LOGIN PASSWORD %L" in s for s in statements)
        assert not any("fake_sentinel_not_a_secret" in s for s in statements), "password reached SQL text"
        assert (
            "SELECT set_config('shipx.app_db_password', %s, true)",
            ("fake_sentinel_not_a_secret",),
        ) in conn.cursor_obj.executed

    def test_does_not_touch_bypassrls_when_it_is_already_correct(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Regression: ALTER ROLE ... NOBYPASSRLS requires SUPERUSER.

        A managed Postgres admin login is not one — Azure Flexible Server
        answers `must be superuser to change bypassrls attribute`. The first
        version issued it unconditionally and failed every Azure deploy while
        passing locally, because the local Docker superuser *can* run it.

        CREATE ROLE defaults to NOBYPASSRLS, so the common path must issue
        nothing and require no privilege.
        """
        import psycopg2

        conn = _FakeConn(has_bypassrls=False)
        monkeypatch.setenv("APP_DB_PASSWORD", "fake_value_not_a_secret")
        monkeypatch.setattr(psycopg2, "connect", lambda **_: conn)

        assert ensure_app_role_password() == "set"
        assert not any("BYPASSRLS" in sql for sql, _ in conn.cursor_obj.executed)

    def test_strips_bypassrls_when_the_role_really_has_it(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """An app role that bypasses RLS makes migration 059's policies inert."""
        import psycopg2

        conn = _FakeConn(has_bypassrls=True)
        monkeypatch.setenv("APP_DB_PASSWORD", "fake_value_not_a_secret")
        monkeypatch.setattr(psycopg2, "connect", lambda **_: conn)

        assert ensure_app_role_password() == "set-and-stripped-bypassrls"
        assert any("NOBYPASSRLS" in sql for sql, _ in conn.cursor_obj.executed)

    def test_commits_the_password_before_attempting_bypassrls(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """The two were one DO block, so a privilege error rolled back both.

        A failed deploy then ALSO left the credential unset — two problems
        reported as one. Confirmed against a real non-superuser: `rolcanlogin`
        goes false -> true even when the BYPASSRLS change raises.
        """
        import psycopg2

        conn = _FakeConn(has_bypassrls=True)
        monkeypatch.setenv("APP_DB_PASSWORD", "fake_value_not_a_secret")
        monkeypatch.setattr(psycopg2, "connect", lambda **_: conn)

        ensure_app_role_password()

        statements = [sql for sql, _ in conn.cursor_obj.executed]
        assert conn.commits >= 2, "password must be committed before the BYPASSRLS attempt"
        assert statements[-1] == "ALTER ROLE logistics_app NOBYPASSRLS"

    def test_closes_the_connection_even_when_bypassrls_fails(self, monkeypatch: pytest.MonkeyPatch) -> None:
        import psycopg2

        class _Boom(_FakeConn):
            def cursor(self) -> _FakeCursor:
                if self.commits:  # the post-commit BYPASSRLS cursor
                    raise RuntimeError("must be superuser to change bypassrls attribute")
                return self.cursor_obj

        conn = _Boom(has_bypassrls=True)
        monkeypatch.setenv("APP_DB_PASSWORD", "fake_value_not_a_secret")
        monkeypatch.setattr(psycopg2, "connect", lambda **_: conn)

        with pytest.raises(RuntimeError):
            ensure_app_role_password()

        assert conn.closed, "connection leaked on the error path"


class _FakeCursor:
    def __init__(self, role_exists: bool, has_bypassrls: bool) -> None:
        self.role_exists = role_exists
        self.has_bypassrls = has_bypassrls
        self.executed: list[tuple[str, object]] = []

    def execute(self, sql: str, params: object = None) -> None:
        self.executed.append((sql, params))

    def fetchone(self) -> tuple[bool] | None:
        """The first query selects `rolbypassrls`; None means no such role."""
        return (self.has_bypassrls,) if self.role_exists else None

    def __enter__(self) -> "_FakeCursor":
        return self

    def __exit__(self, *_: object) -> None:
        return None


class _FakeConn:
    def __init__(self, role_exists: bool = True, has_bypassrls: bool = False) -> None:
        self.cursor_obj = _FakeCursor(role_exists, has_bypassrls)
        self.commits = 0
        self.closed = False

    def cursor(self) -> _FakeCursor:
        return self.cursor_obj

    def commit(self) -> None:
        self.commits += 1

    def close(self) -> None:
        self.closed = True
