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
