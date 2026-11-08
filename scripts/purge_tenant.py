#!/usr/bin/env python3
"""Hard-delete a tenant and every row that belongs to it.

Why this exists
---------------
`offboard_tenant` only sets a status — it never removes data, which is right for
a real customer. But test/abandoned tenants (e.g. the orphans left by a failed
provisioning run) need to actually go, and that cannot be done with a single
`DELETE FROM tenant`: 26 FKs reference `tenant(id)` with `ON DELETE RESTRICT`, so
the delete is refused until every dependent row is gone first.

Rather than hardcode a delete order (which silently rots as migrations land),
this derives the order from the live schema: it finds every table with a
`tenant_id` column, reads the real FK graph from `pg_constraint`, topologically
sorts it, and deletes dependents first. A table added by a future migration is
picked up automatically.

Safety
------
* Dry-run is the default — it only ever prints row counts. `--yes` is required
  to delete anything.
* All deletes run in ONE transaction, so a failure rolls the whole purge back.
* Targets are resolved and printed before anything is touched.

Usage
-----
    # inside the VNet (the DB is private) — e.g. via:
    #   az containerapp exec -g shipx-dev-rg -n shipx-dev-api \
    #     --command "python3 scripts/purge_tenant.py --email a@b.com --dry-run"

    python3 scripts/purge_tenant.py --email someone@example.com        # dry run
    python3 scripts/purge_tenant.py --tenant-id <uuid> --dry-run
    python3 scripts/purge_tenant.py --email someone@example.com --yes  # delete

Resolution: `--email` matches `tenant_user.email` OR `tenant.primary_contact_email`.
"""

import argparse
import os
import sys
from collections import defaultdict
from typing import Any

import psycopg2
import psycopg2.extras

from shared.db_credentials import admin_db_params

TENANT_TABLE = "tenant"

# Carries a tenant_id but is NOT tenant-owned data: an onboarding lead outlives
# the tenant it provisioned. Purging must reopen the lead (clear tenant_id, back
# to 'new') so it can be provisioned again — not delete the company's request.
SPECIAL_TABLES = {"tenant_onboarding_request"}


def _connect() -> Any:
    # The OWNER credential, and this one matters more than most: a purge run as
    # the RLS-enforced application role would match no rows outside whatever
    # tenant scope happened to be set, report success, and delete nothing.
    # A purge that silently does nothing is worse than one that fails.
    return psycopg2.connect(
        **admin_db_params(),
        sslmode=os.environ.get("DATABASE_SSLMODE", "require"),
    )


def resolve_tenant_ids(cur: Any, emails: list[str], tenant_ids: list[str]) -> list[dict[str, Any]]:
    """Return the tenant rows targeted by the given emails / ids."""
    ids: set[str] = set(tenant_ids)
    for email in emails:
        cur.execute(
            """
            SELECT tenant_id FROM tenant_user WHERE lower(email) = lower(%s)
            UNION
            SELECT id FROM tenant WHERE lower(primary_contact_email) = lower(%s)
            """,
            (email, email),
        )
        found = [str(r["tenant_id"]) for r in cur.fetchall()]
        if not found:
            print(f"  ! no tenant matched {email}")
        ids.update(found)
    if not ids:
        return []
    # `::uuid[]` is required throughout: psycopg2 sends these ids as a list of
    # Python str, and Postgres has no `uuid = text` operator.
    cur.execute(
        "SELECT id, company_name, slug, primary_contact_email, status, created_at "
        "FROM tenant WHERE id = ANY(%s::uuid[]) ORDER BY created_at",
        (list(ids),),
    )
    return list(cur.fetchall())


def tenant_scoped_tables(cur: Any) -> list[str]:
    """Every base table in `public` carrying a tenant_id column."""
    cur.execute(
        """
        SELECT c.table_name
        FROM information_schema.columns c
        JOIN information_schema.tables t
          ON t.table_schema = c.table_schema AND t.table_name = c.table_name
        WHERE c.table_schema = 'public'
          AND c.column_name = 'tenant_id'
          AND t.table_type = 'BASE TABLE'
        """
    )
    return sorted(r["table_name"] for r in cur.fetchall())


def fk_edges(cur: Any, tables: set[str]) -> dict[str, set[str]]:
    """child -> {parents} for FKs between the given tables (self-refs ignored)."""
    cur.execute(
        """
        SELECT src.relname AS child, tgt.relname AS parent
        FROM pg_constraint k
        JOIN pg_class src ON src.oid = k.conrelid
        JOIN pg_class tgt ON tgt.oid = k.confrelid
        WHERE k.contype = 'f'
        """
    )
    edges: dict[str, set[str]] = defaultdict(set)
    for row in cur.fetchall():
        child, parent = row["child"], row["parent"]
        if child in tables and parent in tables and child != parent:
            edges[child].add(parent)
    return edges


def deletion_order(tables: list[str], edges: dict[str, set[str]]) -> list[str]:
    """Children before parents. Kahn's algorithm; any cycle is appended last."""
    remaining = set(tables)
    order: list[str] = []
    while remaining:
        # A table is safe to delete once nothing left depends on it.
        free = [t for t in sorted(remaining) if not any(t in edges.get(o, set()) for o in remaining - {t})]
        if not free:  # FK cycle — emit the rest and let the transaction arbitrate
            order.extend(sorted(remaining))
            break
        order.extend(free)
        remaining -= set(free)
    return order


def main() -> None:
    ap = argparse.ArgumentParser(description="Hard-delete tenants and all their data.")
    ap.add_argument("--email", action="append", default=[], help="admin/contact email (repeatable)")
    ap.add_argument("--tenant-id", action="append", default=[], help="tenant id (repeatable)")
    group = ap.add_mutually_exclusive_group()
    group.add_argument("--dry-run", action="store_true", help="show what would be deleted (default)")
    group.add_argument("--yes", action="store_true", help="actually delete")
    args = ap.parse_args()

    if not args.email and not args.tenant_id:
        ap.error("give at least one --email or --tenant-id")

    conn = _connect()
    conn.autocommit = False
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

    print("Resolving targets…")
    targets = resolve_tenant_ids(cur, args.email, args.tenant_id)
    if not targets:
        print("Nothing matched — no changes.")
        conn.rollback()
        return

    print(f"\n{len(targets)} tenant(s) targeted:")
    for t in targets:
        print(
            f"  - {t['id']}  {t['company_name']!r}  slug={t['slug']}  "
            f"contact={t['primary_contact_email']}  status={t['status']}  created={t['created_at']}"
        )
    ids = [str(t["id"]) for t in targets]

    tables = [t for t in tenant_scoped_tables(cur) if t not in SPECIAL_TABLES]
    order = deletion_order(tables, fk_edges(cur, set(tables)))

    print("\nRows that belong to these tenants:")
    total = 0
    for table in order:
        cur.execute(f'SELECT count(*) AS n FROM "{table}" WHERE tenant_id = ANY(%s::uuid[])', (ids,))  # noqa: S608
        n = cur.fetchone()["n"]
        if n:
            print(f"  {n:>7}  {table}")
            total += n
    print(f"  {total:>7}  TOTAL (+ {len(targets)} tenant row(s))")

    if not args.yes:
        print("\nDRY RUN — nothing deleted. Re-run with --yes to delete.")
        conn.rollback()
        return

    print("\nDeleting (single transaction, children first)…")
    for table in order:
        cur.execute(f'DELETE FROM "{table}" WHERE tenant_id = ANY(%s::uuid[])', (ids,))  # noqa: S608
        if cur.rowcount:
            print(f"  -{cur.rowcount:<7} {table}")
    # Platform-level rows that point at the tenant but carry no tenant_id column.
    cur.execute("DELETE FROM platform_audit_log WHERE target_tenant_id = ANY(%s::uuid[])", (ids,))
    if cur.rowcount:
        print(f"  -{cur.rowcount:<7} platform_audit_log")
    cur.execute(
        "UPDATE tenant_onboarding_request SET tenant_id = NULL, status = 'new', "
        "reviewed_by = NULL, reviewed_at = NULL WHERE tenant_id = ANY(%s::uuid[]) RETURNING id",
        (ids,),
    )
    if cur.rowcount:
        print(f"  ~{cur.rowcount:<7} tenant_onboarding_request (lead reopened, can be re-provisioned)")
    cur.execute(f'DELETE FROM "{TENANT_TABLE}" WHERE id = ANY(%s::uuid[])', (ids,))
    print(f"  -{cur.rowcount:<7} {TENANT_TABLE}")

    conn.commit()
    print("\nDone — committed.")


if __name__ == "__main__":
    try:
        main()
    except KeyError as exc:
        sys.exit(f"Missing env var: {exc}. DATABASE_* must be set (run inside the VNet).")
