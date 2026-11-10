"""Which database credential a given job should connect with.

Two roles, deliberately:

``logistics_app``
    What the **application** connects as. It holds only
    SELECT/INSERT/UPDATE/DELETE (migration 059) and crucially does **not** have
    BYPASSRLS, so the canonical row-level-security predicate 059 installed is
    actually enforced. Service code reaches this through
    ``shared/db.py::get_connection``, which reads ``DATABASE_USER``.

the owner (``postgres``)
    What **schema and fixture work** connects as: Alembic migrations, the local
    DB reset, and the seed script. DDL has to be owner-run, and the seed writes
    across tenants, which an RLS-enforced role cannot do without setting the
    tenant GUC per statement.

This module resolves the second one. It exists so the rule lives in one place
instead of being re-derived in ``migrations/env.py``, ``scripts/reset_db.py``
and ``scripts/seed.py`` — three copies of a credential rule is how environments
drift apart.

``DATABASE_ADMIN_USER`` / ``DATABASE_ADMIN_PASSWORD`` are optional and fall back
to ``DATABASE_USER`` / ``DATABASE_PASSWORD``. That fallback is what keeps every
environment that has not been cut over working unchanged — including the AWS
migrate Lambda, which sets ``DATABASE_USER=postgres`` and no admin variables
because it is *already* the owner.
"""

import os


def admin_db_params() -> dict[str, str]:
    """Connection parameters for schema and fixture work, as the table owner.

    Returns:
        host / port / dbname / user / password, suitable for
        ``psycopg2.connect(**params)``.

    Raises:
        KeyError: A required variable is unset. Deliberately not defaulted —
            silently connecting somewhere unintended is worse than failing.
    """
    return {
        "host": os.environ["DATABASE_HOST"],
        "port": os.environ.get("DATABASE_PORT", "5432"),
        "dbname": os.environ["DATABASE_NAME"],
        "user": os.environ.get("DATABASE_ADMIN_USER") or os.environ["DATABASE_USER"],
        "password": os.environ.get("DATABASE_ADMIN_PASSWORD") or os.environ["DATABASE_PASSWORD"],
    }


def admin_sqlalchemy_url() -> str:
    """The same credential as :func:`admin_db_params`, as a SQLAlchemy URL.

    Used by ``migrations/env.py``. The password is URL-quoted so a credential
    containing ``@``, ``/`` or ``:`` — which a generated secret very often does
    — does not corrupt the URL.
    """
    from urllib.parse import quote_plus

    p = admin_db_params()
    return f"postgresql+psycopg2://{quote_plus(p['user'])}:{quote_plus(p['password'])}@{p['host']}:{p['port']}/{p['dbname']}"


def ensure_app_role_password() -> str:
    """Make ``logistics_app``'s password match ``APP_DB_PASSWORD``, every time.

    Why this is not (only) a migration
    ----------------------------------
    Migration 060 sets this password from the same variable — but Alembic runs a
    migration **exactly once per database**, and 060's effect depends on an
    environment variable rather than on the schema. An environment that applied
    060 *before* its secret existed got the no-op branch, a `NOTICE`, a role left
    NOLOGIN, and `060` permanently recorded as applied. Provisioning the secret
    afterwards changes nothing, because 060 will never run again.

    That is exactly what happened to Azure dev: 060 shipped in #126 and deployed
    on 2026-11-08, a day before #128 created the `db-app-password` secret. The
    phase-2 cutover then failed authentication, and 060's own docstring advised
    "provision the secret and re-run" — advice Alembic makes impossible.

    So the credential is applied **here**, after every successful upgrade. It is
    idempotent: re-setting the same password is a no-op in effect, and it
    repairs both failure modes without anyone diagnosing which one occurred —
    060 consumed as a no-op, *or* the role's password having drifted from the
    secret (a regenerated `random_password`, a restored database).

    Unset ``APP_DB_PASSWORD`` is not an error: an environment that has not been
    cut over has no such secret, and refusing to migrate would block its deploy.

    Returns:
        A short status string for logging: ``"set"``, ``"skipped-no-password"``,
        or ``"skipped-no-role"``.

    Raises:
        psycopg2.Error: The connection or the ``ALTER ROLE`` failed. Deliberately
            not swallowed — a credential that silently fails to apply is the
            whole bug this function exists to prevent.
    """
    import psycopg2

    password = os.environ.get("APP_DB_PASSWORD", "")
    if not password:
        return "skipped-no-password"

    with psycopg2.connect(**admin_db_params()) as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT 1 FROM pg_roles WHERE rolname = 'logistics_app'")
            if cur.fetchone() is None:
                return "skipped-no-role"

            # Same technique as migration 060: the value is bound as a parameter
            # into a transaction-local setting, then quoted by format('%L')
            # inside the DO block. ALTER ROLE cannot take a bind parameter, and
            # the project forbids interpolating values into SQL text.
            cur.execute("SELECT set_config('shipx.app_db_password', %s, true)", (password,))
            cur.execute(
                """
                DO $outer$
                DECLARE
                    pw TEXT := current_setting('shipx.app_db_password', TRUE);
                BEGIN
                    EXECUTE format('ALTER ROLE logistics_app LOGIN PASSWORD %L', pw);
                    ALTER ROLE logistics_app NOBYPASSRLS;
                END $outer$
                """
            )
    return "set"
