"""Fixtures for the real-database tests.

`admin` connects as the database owner, to set rows up and inspect results that the
application role is (correctly) not allowed to see across tenants. The code under
test always runs as the application role, so row-level security applies to it.
"""

import uuid

import pytest

psycopg2 = pytest.importorskip("psycopg2", reason="psycopg2 is required for the real-database tests")


@pytest.fixture(scope="module")
def admin():
    from shared.db_credentials import admin_db_params

    try:
        conn = psycopg2.connect(**admin_db_params(), connect_timeout=5)
    except Exception as exc:  # pragma: no cover - environment dependent
        pytest.skip(f"no database reachable: {exc}")
    conn.autocommit = True
    with conn.cursor() as cur:
        cur.execute("SELECT to_regclass('public.tenant_counter')")
        if cur.fetchone()[0] is None:
            pytest.skip("database is not migrated to 062 (tenant_counter missing)")
    yield conn
    conn.close()


@pytest.fixture
def world(admin):
    """A tenant with a pool of customers and containers, removed afterwards."""
    ids: dict = {"tenant": str(uuid.uuid4()), "customers": [], "containers": [], "user": str(uuid.uuid4())}
    with admin.cursor() as cur:
        cur.execute(
            "INSERT INTO tenant (id, company_name, primary_contact_email, subscription_tier, slug) "
            "VALUES (%s, %s, %s, 'starter', %s)",
            (ids["tenant"], "Money Test Ltd", "money@example.test", f"money-{ids['tenant'][:8]}"),
        )
        # A staff user: audit/approval columns reference tenant_user.
        cur.execute(
            "INSERT INTO tenant_user (id, tenant_id, email, full_name, role) VALUES (%s, %s, %s, 'Test Staff', 'nigeria_office_staff')",
            (ids["user"], ids["tenant"], f"staff-{ids['tenant'][:8]}@example.test"),
        )
        for i in range(12):
            cust, cont = str(uuid.uuid4()), str(uuid.uuid4())
            cur.execute("INSERT INTO customer (id, tenant_id, name) VALUES (%s, %s, %s)", (cust, ids["tenant"], f"Customer {i}"))
            cur.execute(
                "INSERT INTO container (id, tenant_id, container_number) VALUES (%s, %s, %s)",
                (cont, ids["tenant"], f"MNY{i:04d}"),
            )
            ids["customers"].append(cust)
            ids["containers"].append(cont)
    yield ids
    with admin.cursor() as cur:
        tenant = (ids["tenant"],)
        cur.execute("DELETE FROM misc_charge WHERE billing_id IN (SELECT id FROM billing WHERE tenant_id = %s)", tenant)
        cur.execute(
            "DELETE FROM packing_list_item WHERE packing_list_id IN (SELECT id FROM packing_list WHERE tenant_id = %s)", tenant
        )
        # Children before parents: items and resolutions reference refunds and claims.
        for table in (
            "storage_fee_log",
            "claim_resolution",
            "missing_item",
            "seized_item",
            "damage_claim",
            "refund_request",
            "payment_record",
            "carryover_ledger",
            "cbm_dispute",
            "billing",
            "packing_list",
            "manifest",
            "container",
            "customer",
            "tenant_user",
            "tenant_counter",
        ):
            cur.execute(f"DELETE FROM {table} WHERE tenant_id = %s", tenant)  # noqa: S608 - fixed table list
        cur.execute("DELETE FROM tenant WHERE id = %s", tenant)
