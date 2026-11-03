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
    """Owner/superuser connection, used only to set the fixture up."""
    try:
        return psycopg2.connect(**_dsn())
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
                    "SELECT polname, pg_get_expr(polqual, polrelid) FROM pg_policy " "WHERE polrelid = %s::regclass",
                    (table,),
                )
                policies = cur.fetchall()
                assert policies, f"{table} has RLS enabled but no policy — that denies everything"
                for name, qual in policies:
                    assert "app.current_tenant_id" in (
                        qual or ""
                    ), f"{table}.{name} does not reference app.current_tenant_id: {qual}"
                    assert "'app.tenant_id'" not in (qual or ""), f"{table}.{name} still reads the setting name nothing ever sets"
        finally:
            conn.close()
