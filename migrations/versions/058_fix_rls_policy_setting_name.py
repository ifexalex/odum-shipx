"""058 — repair the RLS policies on four tables, and make them PLATFORM-aware.

Four tables added after migration 005 carry policies that **can never match a
row**, so their row-level security has never done anything:

    container_document     (022)
    notification_template  (024)
    rate_history           (025)
    warehouse              (041)

Each was written as::

    USING (tenant_id::text = current_setting('app.tenant_id', TRUE))

but `shared/db.py::_set_tenant` sets **`app.current_tenant_id`**, not
`app.tenant_id`. `current_setting('app.tenant_id', TRUE)` therefore returns
NULL, `tenant_id::text = NULL` evaluates to NULL, and NULL is not TRUE — so the
policy denies every row.

That outage never surfaced because of a *second* defect: unlike migration 005's
21 core tables, none of the four ran `FORCE ROW LEVEL SECURITY`. Postgres exempts
a table's owner from non-forced RLS, and the application connects as the owner,
so the broken policies were simply bypassed.

The two defects masked each other, which is why this survived four migrations:
correcting only the setting name would have changed nothing observable (still
bypassed), and adding only FORCE would have taken those four tables offline
(zero rows). Both are fixed here, together.

PLATFORM scope
--------------
The policies are also made explicitly PLATFORM-aware, which the originals were
not. `_set_tenant` sets the sentinel string `'PLATFORM'`
(`shared/tenant_context.PLATFORM_TENANT_ID`) for deliberate cross-tenant reads —
public shipment tracking, `find_user_across_tenants`, activation lookups,
`resolve_identity_from_db`. A policy that compares that sentinel against a uuid
column cannot work: migration 005's core policies cast with
`current_setting(...)::uuid`, and `'PLATFORM'::uuid` **raises** rather than
returning false. Comparing `tenant_id::text` to the raw setting, plus an explicit
PLATFORM branch, keeps both access patterns working once enforcement is real.

Note on the four-layer isolation model
--------------------------------------
This repairs the policies; it does not by itself make RLS *enforced* in the
deployed environments. The application connects as the database owner, and on
Azure Flexible Server that role also bypasses RLS — which is demonstrable:
`resolve_identity_from_db` reads `tenant_user` (one of migration 005's FORCE'd
tables) under PLATFORM scope and succeeds, where an enforced
`current_setting('app.current_tenant_id')::uuid` policy would have raised on
`'PLATFORM'::uuid`. Real enforcement additionally requires the app to connect as
a non-owner, non-BYPASSRLS role — migration 005 already creates `logistics_app`
for exactly that purpose, and nothing uses it. Tracked separately; see
`docs/project docs/05c_database_rls_indexes_seed.md`.
"""

from alembic import op

revision = "058"
down_revision = "057"

# Tables whose policy referenced the wrong setting name, with the policy name
# each migration used. Kept explicit rather than discovered at runtime so this
# migration cannot silently widen to a table it was never reviewed against.
_BROKEN_POLICIES: tuple[tuple[str, str], ...] = (
    ("container_document", "container_document_tenant_isolation"),
    ("notification_template", "notif_template_tenant_isolation"),
    ("rate_history", "rate_history_tenant_isolation"),
    ("warehouse", "warehouse_tenant_isolation"),
)

# Compared as text, not cast to uuid: the PLATFORM sentinel is not a uuid, and
# casting it raises instead of evaluating false. `TRUE` on current_setting makes
# a missing setting return NULL rather than erroring, so a connection that never
# called _set_tenant is denied rather than blowing up.
_PREDICATE = (
    "current_setting('app.current_tenant_id', TRUE) = 'PLATFORM' "
    "OR tenant_id::text = current_setting('app.current_tenant_id', TRUE)"
)


def upgrade() -> None:
    for table, policy in _BROKEN_POLICIES:
        op.execute(f"DROP POLICY IF EXISTS {policy} ON {table}")
        # FOR ALL with both USING and WITH CHECK: USING governs
        # SELECT/UPDATE/DELETE visibility, WITH CHECK governs the rows an
        # INSERT/UPDATE may write. The originals supplied only USING, which
        # Postgres also applies as the INSERT check — stated explicitly here so
        # the write path is not an accident of that default.
        op.execute(
            f"""
            CREATE POLICY {policy} ON {table}
                FOR ALL
                USING ({_PREDICATE})
                WITH CHECK ({_PREDICATE})
            """
        )
        # Match migration 005's 21 core tables: without FORCE the policy does
        # not apply to the table owner, which is what hid the broken predicate.
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")


def downgrade() -> None:
    # Restores the original (non-functional) policies verbatim, including the
    # wrong setting name and the absent FORCE. A downgrade should return the
    # schema to what it was, not to what it should have been.
    for table, policy in _BROKEN_POLICIES:
        op.execute(f"ALTER TABLE {table} NO FORCE ROW LEVEL SECURITY")
        op.execute(f"DROP POLICY IF EXISTS {policy} ON {table}")
        op.execute(
            f"""
            CREATE POLICY {policy} ON {table}
                USING (tenant_id::text = current_setting('app.tenant_id', TRUE))
            """
        )
