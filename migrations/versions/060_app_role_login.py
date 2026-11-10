"""060 — give `logistics_app` LOGIN with a real credential, from the environment.

This is the database half of the RLS credential switchover that migration 059
was written to enable. 059 installed one canonical, PLATFORM-aware predicate on
every tenant-scoped table and turned on `FORCE ROW LEVEL SECURITY`, then noted
that none of it is *enforced* while the application connects as a role that
bypasses RLS — and stripped LOGIN from `logistics_app`, whose migration-005
password was the literal `'CHANGE_ME_IN_SECRETS_MANAGER'`.

Why RLS is currently inert
--------------------------
Verified against the local stack before writing this::

    SET app.current_tenant_id = '<tenant 1>';
    SELECT count(*), count(DISTINCT tenant_id) FROM billing;
    -> 4 rows across 2 distinct tenant_ids

`postgres` has `rolbypassrls`, and BYPASSRLS overrides FORCE ROW LEVEL SECURITY,
so the predicate never runs. Every bit of isolation in effect today comes from
the application's own `tenant_id` predicates — layer 3 of the documented
four-layer model is present in the catalog and doing nothing.

Where the password comes from
-----------------------------
`APP_DB_PASSWORD` in the environment of whatever runs this migration:

* AWS — the migrate Lambda, injected from the `logistics_app` Secrets Manager
  secret (`infrastructure/aws/modules/lambda/main.tf`).
* Local / CI — `.env.local`, read by `scripts/migrate.py`.

**Unset is not an error.** The migration logs a notice and leaves the role
NOLOGIN, so an environment that has not been cut over yet still migrates
cleanly. That matters because the alternative — failing the migration — would
block deploys on an environment whose secret has not been provisioned.

.. warning::

   **That no-op is permanent, and this migration is no longer the thing you
   rely on.** Alembic runs a migration exactly once per database. An
   environment that applied 060 *before* its secret existed got the notice
   below, a role left NOLOGIN, and `060` recorded as applied — and provisioning
   the secret afterwards changes nothing, because 060 never runs again.

   Azure dev hit exactly this: 060 shipped in #126 and deployed 2026-11-08, a
   day before #128 created the `db-app-password` secret. The phase-2 cutover
   then failed authentication on every request.

   An earlier version of this docstring said "Provision the secret and re-run to
   complete the RLS switchover." **Alembic makes that impossible**, and the
   sentence has been removed rather than left to mislead.

   The credential is now applied by ``shared.db_credentials.ensure_app_role_password``
   after *every* successful upgrade, from both migrate entrypoints
   (``scripts/migrate.py`` and ``services/migrate/handler.py``). That is
   idempotent and self-healing. This migration is kept for environments where it
   did work, and as the record of why the role exists.

Keeping the password out of SQL text
------------------------------------
The value is bound as a parameter into a `SET`, then read back inside the DO
block with `current_setting` and quoted by `format('%L', …)`. It is never
interpolated into a statement by Python, and `ALTER ROLE` cannot take a bind
parameter directly, so this is the route that satisfies the project's
no-interpolation rule.

`set_config(..., is_local => true)` scopes the value to this transaction, so it
does not linger on a pooled connection afterwards.

What this deliberately does NOT do
----------------------------------
It does not change which role the application connects as — that is
`DATABASE_USER`, set by Terraform (AWS) and `.env.local` (local), and is a
separate, revertible step. After this migration the role can log in; nothing
uses it until that variable is repointed. Splitting it this way means the
credential exists and is testable before anything depends on it, and rolling
back the cutover does not require a migration.

Migrations themselves keep running as the owner. DDL must be owner-run, and
`logistics_app` holds only SELECT/INSERT/UPDATE/DELETE (059) — so the migrate
Lambda stays on `postgres` by design, not by omission.
"""

import os

import sqlalchemy as sa
from alembic import op

revision = "060"
down_revision = "059"

# Grants and ALTER DEFAULT PRIVILEGES were applied by 059 and cover tables
# created later, so this migration only has to deal with the credential.
_GRANT_LOGIN = sa.text(
    """
    DO $outer$
    DECLARE
        pw TEXT := current_setting('shipx.app_db_password', TRUE);
    BEGIN
        IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'logistics_app') THEN
            RAISE NOTICE 'logistics_app does not exist - nothing to do';
            RETURN;
        END IF;

        IF pw IS NULL OR pw = '' THEN
            RAISE NOTICE
                'APP_DB_PASSWORD not set - leaving logistics_app NOLOGIN. '
                'This migration will NOT run again (alembic applies each once); '
                'the credential is applied after every upgrade by '
                'shared.db_credentials.ensure_app_role_password.';
            RETURN;
        END IF;

        -- format('%L') quotes and escapes; the value reached us as a bound
        -- parameter, so it is never part of a statement built by Python.
        EXECUTE format('ALTER ROLE logistics_app LOGIN PASSWORD %L', pw);

        -- The application role must never bypass the policies 059 installed.
        -- Asserted rather than assumed: an inherited BYPASSRLS would make the
        -- whole switchover silently pointless.
        ALTER ROLE logistics_app NOBYPASSRLS;

        RAISE NOTICE 'logistics_app can now log in';
    END $outer$
    """
)


def _warn_if_app_password_disagrees(app_password: str) -> None:
    """Shout when this migration is about to set a password the app won't use.

    The two values must agree: this migration sets `logistics_app`'s password
    from `APP_DB_PASSWORD`, while the application authenticates as
    `DATABASE_USER`/`DATABASE_PASSWORD`. Disagree, and the stack builds
    perfectly and then every single request dies with `FATAL: password
    authentication failed for user "logistics_app"` — a message that points at
    the database and says nothing about the env file that caused it.

    That is not hypothetical. `.env.local.sample` shipped the two as
    `paste-the-generated-value-here` and `paste-the-same-generated-value-here`,
    and both `make env` and the frontend-ci workflow copy that file unedited —
    so a fresh clone and CI both got a mismatch, and CI spent a full e2e run
    (25 failures across unrelated specs) before anything named the real cause.

    A notice, not an error: an environment that has not been cut over yet has
    no `APP_DB_PASSWORD` at all, which is a supported state, and a migration
    that refuses to run would block its deploy.
    """
    if not app_password:
        return
    if os.environ.get("DATABASE_USER") != "logistics_app":
        # Still connecting as the owner — the app password is being provisioned
        # ahead of the cutover, so there is nothing to disagree with yet.
        return
    if os.environ.get("DATABASE_PASSWORD") == app_password:
        return
    print(
        "WARNING: APP_DB_PASSWORD does not match DATABASE_PASSWORD while "
        "DATABASE_USER=logistics_app. This migration will set a password the "
        "application does not have, and every request will then fail with "
        "'password authentication failed for user \"logistics_app\"'. "
        "Set both to the same value."
    )


def upgrade() -> None:
    password = os.environ.get("APP_DB_PASSWORD", "")
    _warn_if_app_password_disagrees(password)

    # Bound as a parameter, transaction-local so it does not outlive this
    # migration on a pooled connection.
    op.get_bind().execute(
        sa.text("SELECT set_config('shipx.app_db_password', :pw, true)"),
        {"pw": password},
    )
    op.get_bind().execute(_GRANT_LOGIN)


def downgrade() -> None:
    """Strip LOGIN again, returning the role to its post-059 state.

    A faithful inverse: 059 left the role NOLOGIN, and this restores exactly
    that. Anything still configured to connect as `logistics_app` will start
    failing authentication, which is the honest consequence of undoing the
    credential half of the switchover — repoint `DATABASE_USER` back to the
    owner first.
    """
    op.execute(
        """
        DO $outer$
        BEGIN
            IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'logistics_app') THEN
                ALTER ROLE logistics_app NOLOGIN;
            END IF;
        END $outer$
        """
    )
