"""059 — one canonical, PLATFORM-aware RLS predicate on every tenant-scoped table.

Migration 058 repaired four policies. Auditing the rest showed the problem was
not confined to them: **no table in the schema had a policy compatible with how
the application actually connects.** Three incompatible styles had accumulated:

    005 (21 core tables), 027, 039
        USING (tenant_id = current_setting('app.current_tenant_id')::uuid)
        -> RAISES on PLATFORM scope: 'PLATFORM'::uuid is not a valid uuid.

    022, 024, 025, 041                                      (fixed in 058)
        USING (tenant_id::text = current_setting('app.tenant_id', TRUE))
        -> Wrong setting name; denies every row.

    042, 044, 046, 048, 051, 055
        USING (tenant_id::text = current_setting('app.current_tenant_id', TRUE))
        -> Correct name, but no PLATFORM branch; denies every platform-scoped read.

`shared/db.py::_set_tenant` sets the literal sentinel `'PLATFORM'`
(`shared/tenant_context.PLATFORM_TENANT_ID`) for deliberate cross-tenant reads:
public shipment tracking, `find_user_across_tenants`, activation lookups,
`resolve_identity_from_db`. Under enforced RLS, every one of those paths would
either raise or silently return nothing. That is why RLS could never simply be
switched on — and why this migration has to come **before** the application is
moved off the owning database role.

What this does
--------------
Catalog-driven rather than a hardcoded table list, deliberately: a hardcoded list
is exactly how four tables drifted onto a broken predicate in the first place.
Every table in `public` that has RLS enabled **and** a `tenant_id` column gets its
policies replaced with one canonical `tenant_isolation` policy and
`FORCE ROW LEVEL SECURITY`.

Tables without a `tenant_id` column are untouched — `tenant`, `platform_settings`,
`platform_audit_log` and `tenant_onboarding_request` are platform-scoped by design
and have no tenant column to filter on.

The separate `tenant_isolation` (USING) + `tenant_insert` (WITH CHECK) pair that
005 created is consolidated into a single `FOR ALL` policy carrying both. Multiple
permissive policies are OR'd together, so stating both halves in one place is
equivalent and far easier to audit.

This changes nothing observable while the application still connects as the table
owner on a role that bypasses RLS. It is the prerequisite that makes enforcement
possible, not enforcement itself — see `05c_database_rls_indexes_seed.md`.

Also: `logistics_app` loses LOGIN
---------------------------------
Migration 005 created the intended application role with a literal password,
`'CHANGE_ME_IN_SECRETS_MANAGER'`, and nothing has ever connected as it. A login
role with a known password in every environment is a standing risk with no
upside, so LOGIN is stripped here. Granting it back with a real password from
Key Vault / Secrets Manager is part of the switchover, where the credential
actually belongs.
"""

from alembic import op

revision = "059"
down_revision = "058"

# The canonical predicate, for reference and for the test that asserts the
# catalog matches it. It is written inline in the SQL below rather than
# interpolated: a Python repr of it renders with DOUBLE quotes, which Postgres
# reads as a quoted identifier rather than a string literal.
#
# Compared as TEXT, never cast to uuid: the PLATFORM sentinel is not a uuid and
# casting it raises instead of evaluating false. `TRUE` on current_setting makes
# an unset variable return NULL rather than error, so a connection that never
# called _set_tenant matches nothing -> fails closed.
CANONICAL_PREDICATE = (
    "current_setting('app.current_tenant_id', TRUE) = 'PLATFORM' "
    "OR tenant_id::text = current_setting('app.current_tenant_id', TRUE)"
)


def upgrade() -> None:
    op.execute(
        """
        DO $outer$
        DECLARE
            tbl  TEXT;
            pol  TEXT;
            n    INT := 0;
        BEGIN
            FOR tbl IN
                SELECT c.relname
                  FROM pg_class c
                  JOIN pg_namespace ns ON ns.oid = c.relnamespace
                 WHERE ns.nspname = 'public'
                   AND c.relkind = 'r'
                   AND c.relrowsecurity
                   AND EXISTS (
                       SELECT 1
                         FROM pg_attribute a
                        WHERE a.attrelid = c.oid
                          AND a.attname  = 'tenant_id'
                          AND a.attnum   > 0
                          AND NOT a.attisdropped
                   )
                 ORDER BY c.relname
            LOOP
                -- Replace whatever is there. The three historical styles have
                -- different policy NAMES as well as different predicates, so
                -- dropping by name is not an option.
                FOR pol IN
                    SELECT polname FROM pg_policy WHERE polrelid = format('%I', tbl)::regclass
                LOOP
                    EXECUTE format('DROP POLICY %I ON %I', pol, tbl);
                END LOOP;

                EXECUTE format(
                    $sql$CREATE POLICY tenant_isolation ON %I FOR ALL
                         USING (
                             current_setting('app.current_tenant_id', TRUE) = 'PLATFORM'
                             OR tenant_id::text = current_setting('app.current_tenant_id', TRUE)
                         )
                         WITH CHECK (
                             current_setting('app.current_tenant_id', TRUE) = 'PLATFORM'
                             OR tenant_id::text = current_setting('app.current_tenant_id', TRUE)
                         )$sql$,
                    tbl
                );

                -- Without FORCE the policy does not apply to the table owner,
                -- which is how 022/024/025/041 hid a predicate that matched
                -- nothing for four migrations.
                EXECUTE format('ALTER TABLE %I FORCE ROW LEVEL SECURITY', tbl);
                n := n + 1;
            END LOOP;

            RAISE NOTICE 'canonical RLS policy applied to % tenant-scoped tables', n;
            IF n = 0 THEN
                RAISE EXCEPTION 'no tenant-scoped tables matched - refusing to report success';
            END IF;
        END $outer$
        """
    )

    # Bring `logistics_app`'s grants up to date, and make future ones automatic.
    #
    # Migration 005 ran `GRANT ... ON ALL TABLES IN SCHEMA public`, which applies
    # only to tables that existed at that moment. Every table added from 022
    # onward — container_document, warehouse, payment_claim, staff_notification,
    # tenant_user_activation and the rest — has no grant at all. Switching the
    # application onto this role without fixing that would fail with "permission
    # denied" on whichever newer table it touched first, which is a confusing way
    # to discover a 30-migration-old omission.
    #
    # ALTER DEFAULT PRIVILEGES covers tables created *later* by the owner (the
    # role migrations run as), so the next migration's table is granted without
    # anyone remembering to.
    #
    # Granting to a NOLOGIN role changes nothing today; it removes a step from
    # the switchover and a trap from the next migration.
    op.execute(
        """
        DO $outer$
        BEGIN
            IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'logistics_app') THEN
                RETURN;
            END IF;

            GRANT USAGE ON SCHEMA public TO logistics_app;
            GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO logistics_app;
            GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO logistics_app;

            ALTER DEFAULT PRIVILEGES IN SCHEMA public
                GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO logistics_app;
            ALTER DEFAULT PRIVILEGES IN SCHEMA public
                GRANT USAGE, SELECT ON SEQUENCES TO logistics_app;

            -- A LOGIN role whose password is a literal in version control
            -- ('CHANGE_ME_IN_SECRETS_MANAGER', migration 005) and that nothing
            -- has ever connected as. Revoked rather than rotated: the
            -- switchover sets a real credential, where it belongs.
            ALTER ROLE logistics_app NOLOGIN;
        END $outer$
        """
    )


def downgrade() -> None:
    """Restore the 005-style policy pair.

    Honest caveat: this is **not** a faithful inverse. Upgrade consolidated three
    different historical predicates and two policy shapes into one, and that
    information is not recoverable from the catalog. Downgrading returns every
    tenant-scoped table to 005's uuid-cast pair — which is the majority of what
    was there, and is uniformly broken for PLATFORM scope exactly as before.
    """
    op.execute(
        """
        DO $outer$
        DECLARE
            tbl TEXT;
            pol TEXT;
        BEGIN
            FOR tbl IN
                SELECT c.relname
                  FROM pg_class c
                  JOIN pg_namespace ns ON ns.oid = c.relnamespace
                 WHERE ns.nspname = 'public'
                   AND c.relkind = 'r'
                   AND c.relrowsecurity
                   AND EXISTS (
                       SELECT 1 FROM pg_attribute a
                        WHERE a.attrelid = c.oid AND a.attname = 'tenant_id'
                          AND a.attnum > 0 AND NOT a.attisdropped
                   )
            LOOP
                FOR pol IN
                    SELECT polname FROM pg_policy WHERE polrelid = format('%I', tbl)::regclass
                LOOP
                    EXECUTE format('DROP POLICY %I ON %I', pol, tbl);
                END LOOP;

                EXECUTE format(
                    $sql$CREATE POLICY tenant_isolation ON %I
                         USING (tenant_id = current_setting('app.current_tenant_id')::uuid)$sql$,
                    tbl
                );
                EXECUTE format(
                    $sql$CREATE POLICY tenant_insert ON %I FOR INSERT
                         WITH CHECK (tenant_id = current_setting('app.current_tenant_id')::uuid)$sql$,
                    tbl
                );
            END LOOP;
        END $outer$
        """
    )
    op.execute(
        """
        DO $outer$
        BEGIN
            IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'logistics_app') THEN
                ALTER ROLE logistics_app LOGIN;
            END IF;
        END $outer$
        """
    )
