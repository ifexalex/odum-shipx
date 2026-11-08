"""Row-level security, exercised against a real database as a NON-OWNER role.

Why this file exists
--------------------
Everything else under `tests/tenant_isolation/` tests the *application* layer:
that services pass `tenant_id` and that handlers reject the wrong role. Those are
layer 2 of the four-layer model. Nothing tested layer 3 — the Postgres policies
themselves — and the gap was not theoretical. Four tables
(`container_document`, `notification_template`, `rate_history`, `warehouse`)
shipped with policies reading `app.tenant_id` while `shared/db.py::_set_tenant`
sets `app.current_tenant_id`, so those policies could never match a row. Migration
058 repairs them.

The crucial detail is **who connects**. Postgres exempts a table's owner from
non-forced RLS, and exempts any `BYPASSRLS`/superuser role from RLS entirely. CI's
Postgres service runs as `POSTGRES_USER=test_user`, which is a superuser — so a
test connecting the normal way would pass whether or not RLS worked at all. Each
test here therefore creates a deliberately unprivileged role and connects as it.
Run as `test_user`, every assertion below would pass vacuously.

These tests skip when no database is reachable, so a local run without the stack
up stays green; CI always has one (the `postgres:15` service, migrated before the
suite runs).
"""

import os
import uuid

import pytest

psycopg2 = pytest.importorskip("psycopg2", reason="psycopg2 is required for the real-database RLS tests")

# The tables migration 058 repairs. `rate_history` is omitted: it has no
# tenant-scoped INSERT path that is safe to exercise without its FK parents.
RLS_TABLES = ("warehouse", "container_document", "notification_template")

PROBE_ROLE = "rls_probe"
PROBE_PASSWORD = "rls_probe_pw"  # noqa: S105 — throwaway role inside the test database


def _dsn(user: str | None = None, password: str | None = None) -> dict[str, object]:
    return {
        "host": os.environ.get("DATABASE_HOST", "localhost"),
        "port": int(os.environ.get("DATABASE_PORT", "5432")),
        "dbname": os.environ.get("DATABASE_NAME", "logistics_test"),
        "user": user or os.environ.get("DATABASE_USER", "test_user"),
        "password": password or os.environ.get("DATABASE_PASSWORD", "test_pass"),
        "connect_timeout": 5,
    }


def _admin_conn():
    """Owner/superuser connection, used only to set the fixtures up.

    Must be the OWNER, not whatever `DATABASE_USER` happens to be. Since the
    RLS credential switchover (migration 060) `DATABASE_USER` is normally
    `logistics_app`, which is subject to the policies these tests measure — the
    cross-tenant fixture inserts below would fail with "new row violates
    row-level security policy", which is correct behaviour and useless for
    setup. `shared/db_credentials.admin_db_params()` resolves
    `DATABASE_ADMIN_*` with a fallback to `DATABASE_*`.
    """
    from shared.db_credentials import admin_db_params

    try:
        return psycopg2.connect(**admin_db_params(), connect_timeout=5)
    except Exception as exc:  # pragma: no cover - environment dependent
        pytest.skip(f"no database reachable for RLS tests: {exc}")


@pytest.fixture(scope="module")
def probe_role():
    """A role with table privileges but no ownership and no BYPASSRLS.

    This is the whole point: RLS is invisible to the owner unless FORCE is set,
    and invisible to a superuser even then.
    """
    conn = _admin_conn()
    conn.autocommit = True
    with conn.cursor() as cur:
        cur.execute(
            """
            DO $$
            BEGIN
                IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = %(role)s) THEN
                    EXECUTE format('CREATE ROLE %%I LOGIN PASSWORD %%L', %(role)s, %(pw)s);
                END IF;
            END $$
            """,
            {"role": PROBE_ROLE, "pw": PROBE_PASSWORD},
        )
        # Explicitly NOT superuser and NOT bypassrls — assert it, rather than
        # trusting CREATE ROLE's defaults, because the test is worthless if the
        # probe can bypass what it is meant to measure.
        cur.execute(
            "SELECT rolsuper, rolbypassrls FROM pg_roles WHERE rolname = %s",
            (PROBE_ROLE,),
        )
        is_super, bypasses = cur.fetchone()
        assert not is_super and not bypasses, "the probe role must be subject to RLS"

        cur.execute(f"GRANT USAGE ON SCHEMA public TO {PROBE_ROLE}")
        for table in RLS_TABLES:
            cur.execute(f"GRANT SELECT, INSERT, UPDATE, DELETE ON {table} TO {PROBE_ROLE}")
    conn.close()
    yield PROBE_ROLE


@pytest.fixture()
def two_tenants():
    """Two tenants with one warehouse each, created as the owner."""
    conn = _admin_conn()
    conn.autocommit = True
    a, b = str(uuid.uuid4()), str(uuid.uuid4())
    with conn.cursor() as cur:
        for tid, name in ((a, "RLS-A"), (b, "RLS-B")):
            # primary_contact_email and subscription_tier are NOT NULL with a
            # CHECK (migration 001); slug arrived in 023.
            cur.execute(
                """
                INSERT INTO tenant (
                    id, company_name, primary_contact_email, subscription_tier, slug, status
                )
                VALUES (%s, %s, %s, 'starter', %s, 'active')
                ON CONFLICT (id) DO NOTHING
                """,
                (tid, name, f"rls-{tid[:8]}@example.test", f"rls-{tid[:8]}"),
            )
            cur.execute(
                "INSERT INTO warehouse (tenant_id, name) VALUES (%s, %s)",
                (tid, f"Warehouse {name}"),
            )
    conn.close()
    yield a, b
    cleanup = _admin_conn()
    cleanup.autocommit = True
    with cleanup.cursor() as cur:
        for tid in (a, b):
            cur.execute("DELETE FROM warehouse WHERE tenant_id = %s", (tid,))
            cur.execute("DELETE FROM tenant WHERE id = %s", (tid,))
    cleanup.close()


def _as_probe(tenant_id: str, sql: str, params: tuple = ()) -> list[tuple]:
    """Run `sql` as the probe role with `app.current_tenant_id` set."""
    conn = psycopg2.connect(**_dsn(PROBE_ROLE, PROBE_PASSWORD))
    try:
        with conn.cursor() as cur:
            cur.execute("SET LOCAL app.current_tenant_id = %s", (tenant_id,))
            cur.execute(sql, params)
            return cur.fetchall()
    finally:
        conn.rollback()
        conn.close()


class TestWarehouseRowLevelSecurity:
    """`warehouse` is the table the live bug was found on."""

    def test_a_tenant_sees_only_its_own_warehouses(self, probe_role, two_tenants) -> None:
        a, b = two_tenants
        rows = _as_probe(a, "SELECT tenant_id FROM warehouse")
        assert rows, "tenant A should see its own warehouse"
        assert {str(r[0]) for r in rows} == {a}, "RLS let another tenant's rows through"

    def test_the_other_tenant_is_invisible(self, probe_role, two_tenants) -> None:
        a, b = two_tenants
        rows = _as_probe(a, "SELECT id FROM warehouse WHERE tenant_id = %s", (b,))
        assert rows == [], "tenant A read tenant B's warehouse by asking for it directly"

    def test_platform_scope_sees_across_tenants(self, probe_role, two_tenants) -> None:
        """The PLATFORM sentinel must keep working under enforced RLS.

        `_set_tenant` sets the literal string 'PLATFORM' for deliberate
        cross-tenant reads. Migration 005's core policies cast the setting with
        `::uuid`, and `'PLATFORM'::uuid` RAISES rather than returning false — so a
        policy written that way cannot coexist with this access pattern. 058
        compares as text with an explicit PLATFORM branch.
        """
        a, b = two_tenants
        rows = _as_probe("PLATFORM", "SELECT tenant_id FROM warehouse WHERE tenant_id IN (%s, %s)", (a, b))
        assert {str(r[0]) for r in rows} == {a, b}

    def test_a_connection_that_never_set_a_tenant_sees_nothing(self, probe_role, two_tenants) -> None:
        """Fail closed. `current_setting(..., TRUE)` returns NULL when unset, and
        `tenant_id::text = NULL` is NULL — not TRUE — so no row qualifies."""
        conn = psycopg2.connect(**_dsn(PROBE_ROLE, PROBE_PASSWORD))
        try:
            with conn.cursor() as cur:
                cur.execute("SELECT id FROM warehouse")
                assert cur.fetchall() == []
        finally:
            conn.close()

    def test_a_tenant_cannot_insert_a_row_for_another_tenant(self, probe_role, two_tenants) -> None:
        """WITH CHECK governs writes. Without it, a scoped session could create
        rows it would then be unable to see."""
        a, b = two_tenants
        conn = psycopg2.connect(**_dsn(PROBE_ROLE, PROBE_PASSWORD))
        try:
            with conn.cursor() as cur:
                cur.execute("SET LOCAL app.current_tenant_id = %s", (a,))
                with pytest.raises(psycopg2.errors.InsufficientPrivilege):
                    cur.execute(
                        "INSERT INTO warehouse (tenant_id, name) VALUES (%s, %s)",
                        (b, "smuggled"),
                    )
        finally:
            conn.rollback()
            conn.close()


class TestEveryRepairedTableIsForced:
    """The second half of the 058 defect: a correct policy that is not FORCE'd
    is still bypassed by the table owner, which is how the broken predicate went
    unnoticed through four migrations."""

    @pytest.mark.parametrize("table", RLS_TABLES + ("rate_history",))
    def test_rls_is_enabled_and_forced(self, table: str) -> None:
        conn = _admin_conn()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT relrowsecurity, relforcerowsecurity FROM pg_class WHERE relname = %s",
                    (table,),
                )
                row = cur.fetchone()
                assert row is not None, f"{table} not found"
                enabled, forced = row
                assert enabled, f"RLS is not enabled on {table}"
                assert forced, f"RLS is not FORCED on {table} — the owner bypasses it"
        finally:
            conn.close()

    @pytest.mark.parametrize("table", RLS_TABLES + ("rate_history",))
    def test_no_policy_still_references_the_wrong_setting_name(self, table: str) -> None:
        """Guards the exact bug: `app.tenant_id` instead of `app.current_tenant_id`."""
        conn = _admin_conn()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT polname, pg_get_expr(polqual, polrelid) FROM pg_policy WHERE polrelid = %s::regclass",
                    (table,),
                )
                policies = cur.fetchall()
                assert policies, f"{table} has RLS enabled but no policy — that denies everything"
                for name, qual in policies:
                    assert "app.current_tenant_id" in (qual or ""), (
                        f"{table}.{name} does not reference app.current_tenant_id: {qual}"
                    )
                    assert "'app.tenant_id'" not in (qual or ""), f"{table}.{name} still reads the setting name nothing ever sets"
        finally:
            conn.close()


class TestEveryTenantScopedTableUsesTheCanonicalPredicate:
    """Catalog-driven, deliberately: a hardcoded table list is exactly how four
    tables drifted onto a broken predicate for four migrations.

    Migration 059 normalised every tenant-scoped policy onto one PLATFORM-aware
    predicate. These assertions read `pg_class`/`pg_policy` and will fail if a
    future migration introduces a table whose policy disagrees — including the
    three historical styles this schema accumulated:

        `= current_setting(...)::uuid`                raises on PLATFORM scope
        `current_setting('app.tenant_id', TRUE)`      setting nothing ever sets
        no PLATFORM branch                            denies platform-scoped reads
    """

    @staticmethod
    def _tenant_scoped_rls_tables(cur) -> list[str]:
        cur.execute(
            """
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
             ORDER BY c.relname
            """
        )
        return [r[0] for r in cur.fetchall()]

    def test_the_schema_actually_has_tenant_scoped_rls_tables(self) -> None:
        # Guards the query itself: every assertion below would pass vacuously on
        # an empty list.
        conn = _admin_conn()
        try:
            with conn.cursor() as cur:
                assert len(self._tenant_scoped_rls_tables(cur)) >= 20
        finally:
            conn.close()

    def test_every_one_is_forced(self) -> None:
        conn = _admin_conn()
        try:
            with conn.cursor() as cur:
                tables = self._tenant_scoped_rls_tables(cur)
                cur.execute(
                    "SELECT relname FROM pg_class WHERE relname = ANY(%s) AND NOT relforcerowsecurity",
                    (tables,),
                )
                unforced = [r[0] for r in cur.fetchall()]
                assert unforced == [], f"RLS is not FORCED (owner bypasses it) on: {unforced}"
        finally:
            conn.close()

    def test_every_policy_is_platform_aware_and_uuid_cast_free(self) -> None:
        conn = _admin_conn()
        try:
            with conn.cursor() as cur:
                offenders = []
                for table in self._tenant_scoped_rls_tables(cur):
                    cur.execute(
                        "SELECT polname, pg_get_expr(polqual, polrelid), "
                        "       pg_get_expr(polwithcheck, polrelid) "
                        "  FROM pg_policy WHERE polrelid = %s::regclass",
                        (table,),
                    )
                    policies = cur.fetchall()
                    if not policies:
                        offenders.append(f"{table}: RLS enabled but NO policy — denies everything")
                        continue
                    for name, using, check in policies:
                        for label, expr in (("USING", using), ("WITH CHECK", check)):
                            if expr is None:
                                continue
                            if "'PLATFORM'" not in expr:
                                offenders.append(f"{table}.{name} {label}: no PLATFORM branch")
                            if "::uuid" in expr:
                                offenders.append(f"{table}.{name} {label}: casts to uuid — raises on 'PLATFORM'")
                            if "app.tenant_id" in expr and "app.current_tenant_id" not in expr:
                                offenders.append(f"{table}.{name} {label}: wrong setting name")
                assert offenders == [], "non-canonical RLS policies:\n  " + "\n  ".join(offenders)
        finally:
            conn.close()

    def test_a_core_005_table_isolates_by_tenant(self, probe_role, two_tenants) -> None:
        """`customer` is one of migration 005's original 21 — the group whose
        uuid-cast predicate 059 replaced. Proves the rewrite works on them too,
        not just on the four 058 repaired."""
        a, b = two_tenants
        admin = _admin_conn()
        admin.autocommit = True
        try:
            with admin.cursor() as cur:
                cur.execute(f"GRANT SELECT, INSERT ON customer TO {PROBE_ROLE}")
                for tid in (a, b):
                    cur.execute(
                        "INSERT INTO customer (tenant_id, name, phone) VALUES (%s, %s, %s)",
                        (tid, f"Cust {tid[:8]}", f"+234800{tid[:7]}"),
                    )
        finally:
            admin.close()

        rows = _as_probe(a, "SELECT tenant_id FROM customer")
        assert rows, "tenant A should see its own customer"
        assert {str(r[0]) for r in rows} == {a}

        platform = _as_probe("PLATFORM", "SELECT tenant_id FROM customer WHERE tenant_id IN (%s, %s)", (a, b))
        assert {str(r[0]) for r in platform} == {a, b}, "PLATFORM scope must still cross tenants"

        cleanup = _admin_conn()
        cleanup.autocommit = True
        with cleanup.cursor() as cur:
            for tid in (a, b):
                cur.execute("DELETE FROM customer WHERE tenant_id = %s", (tid,))
        cleanup.close()


class TestLogisticsAppRole:
    """Migration 005 created `logistics_app` with the literal password
    'CHANGE_ME_IN_SECRETS_MANAGER', and nothing ever connected as it. 059 stripped
    LOGIN; 060 grants it back with a real credential from the environment.

    This class previously asserted the role *could not* log in, which was the
    correct invariant between 059 and 060. 060 inverts it deliberately, so the
    assertion now covers what actually matters: the role can authenticate, and it
    is subject to the policies it is meant to be subject to.
    """

    def test_it_has_grants_on_tables_added_after_migration_005(self) -> None:
        """005's `GRANT ... ON ALL TABLES` covered only the tables that existed
        then. Every table from 022 onward had no grant, so the switchover would
        have failed with "permission denied" on whichever newer table was touched
        first — a confusing way to find a 30-migration-old omission."""
        conn = _admin_conn()
        try:
            with conn.cursor() as cur:
                cur.execute("SELECT 1 FROM pg_roles WHERE rolname = 'logistics_app'")
                if cur.fetchone() is None:
                    pytest.skip("logistics_app not present in this database")
                missing = []
                # One table from each era after 005.
                for table in ("container_document", "warehouse", "payment_claim", "tenant_user_activation"):
                    cur.execute(
                        "SELECT has_table_privilege('logistics_app', %s, 'SELECT')",
                        (table,),
                    )
                    if not cur.fetchone()[0]:
                        missing.append(table)
                assert missing == [], f"logistics_app has no SELECT on: {missing}"
        finally:
            conn.close()

    def test_it_is_never_allowed_to_bypass_rls(self) -> None:
        """The one attribute that makes the whole switchover meaningful.

        BYPASSRLS overrides FORCE ROW LEVEL SECURITY, so a `logistics_app` that
        inherited it would leave every policy 059 installed inert while looking
        correct in the catalog — which is exactly the state the application was
        in while connecting as `postgres`.
        """
        conn = _admin_conn()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT rolsuper, rolbypassrls FROM pg_roles WHERE rolname = 'logistics_app'",
                )
                row = cur.fetchone()
                if row is None:
                    pytest.skip("logistics_app not present in this database")
                is_super, bypasses = row
                assert not is_super, "logistics_app must not be a superuser"
                assert not bypasses, "logistics_app must not have BYPASSRLS - RLS would be inert"
        finally:
            conn.close()

    def test_migration_060_gave_it_a_working_credential(self) -> None:
        """After 060 the role can authenticate; before it, it could not.

        Skipped rather than failed when `APP_DB_PASSWORD` is unset, because 060
        deliberately no-ops in an environment whose secret has not been
        provisioned yet.
        """
        if not os.environ.get("APP_DB_PASSWORD"):
            pytest.skip("APP_DB_PASSWORD unset - migration 060 leaves the role NOLOGIN by design")

        conn = _admin_conn()
        try:
            with conn.cursor() as cur:
                cur.execute("SELECT rolcanlogin FROM pg_roles WHERE rolname = 'logistics_app'")
                row = cur.fetchone()
                if row is None:
                    pytest.skip("logistics_app not present in this database")
                assert row[0] is True, "migration 060 should have granted LOGIN"
        finally:
            conn.close()


@pytest.mark.isolation
class TestTheRealApplicationCredentialIsSubjectToRls:
    """Isolation measured through the credential the application actually uses.

    Every other test here uses a synthetic `probe_role`, which proves the
    *policies* work but says nothing about whether production connects on a role
    those policies apply to. For most of this project's life it did not: the app
    connected as `postgres`, whose BYPASSRLS made all of it inert.

    Skipped unless `DATABASE_ADMIN_USER` is set, i.e. unless `DATABASE_USER` has
    genuinely been repointed off the owner.
    """

    @staticmethod
    def _app_conn():
        if not os.environ.get("DATABASE_ADMIN_USER"):
            pytest.skip("DATABASE_USER is still the owner - switchover not applied in this environment")
        return psycopg2.connect(**_dsn())

    def test_it_sees_only_the_scoped_tenant(self, two_tenants) -> None:
        a, _b = two_tenants
        conn = self._app_conn()
        try:
            with conn.cursor() as cur:
                cur.execute("SET app.current_tenant_id = %s", (a,))
                cur.execute("SELECT count(*), count(DISTINCT tenant_id) FROM warehouse")
                rows, tenants = cur.fetchone()
                assert rows >= 1, "the scoped tenant's own row must be visible"
                assert tenants == 1, "more than one tenant visible - isolation is not being enforced"
        finally:
            conn.close()

    def test_an_unscoped_connection_sees_nothing(self) -> None:
        """Fails closed: no `app.current_tenant_id` means no rows, not all rows."""
        conn = self._app_conn()
        try:
            with conn.cursor() as cur:
                cur.execute("SELECT count(*) FROM warehouse")
                assert cur.fetchone()[0] == 0
        finally:
            conn.close()

    def test_it_cannot_run_ddl(self) -> None:
        """DML only (059). An app role able to ALTER the schema could drop the
        very policies that constrain it."""
        conn = self._app_conn()
        try:
            with conn.cursor() as cur:
                with pytest.raises(psycopg2.Error):
                    cur.execute("CREATE TABLE rls_switchover_probe (id int)")
        finally:
            conn.close()
