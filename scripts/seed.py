"""Database seed script — populates dev/staging environments with initial data.

Creates three test tenants, each with a full staff set (tenant_admin,
china_office_staff, nigeria_office_staff, warehouse_attendant) and 5
customers — all sharing that tenant's own email domain, so real-Cognito
login testing (LOCAL_TESTING.md §14.2, via scripts/bootstrap_local.sh) can
sign in as any specific tenant, staff, or customer account. Acme additionally
gets one multi-role staff member (nigeria_office_staff + warehouse_attendant,
migration 039) to exercise the role-switch toggle and Cognito group-sync fix:
  - Tenant A: "Acme Shipping Ltd"   (starter tier,  @acmeshipping.com,  2 containers)
  - Tenant B: "Global Cargo Co"     (business tier, @globalcargo.com,   1 container)
  - Tenant C: "Demo Shipping Ltd"   (business tier, @demoshipping.com,  1 container)

Usage:
    DATABASE_HOST=localhost DATABASE_NAME=logistics \\
    DATABASE_USER=postgres DATABASE_PASSWORD=secret \\
    python scripts/seed.py
"""

import re
import sys
from datetime import date, timedelta
from decimal import Decimal

import psycopg2
import psycopg2.extras

from shared.db_credentials import admin_db_params

# ---------------------------------------------------------------------------
# Connection helpers
# ---------------------------------------------------------------------------


def _connect() -> psycopg2.extensions.connection:
    # The OWNER credential, not the application role: this script writes fixture
    # rows for several tenants in one connection, which an RLS-enforced role
    # cannot do without setting the tenant GUC before every statement. See
    # shared/db_credentials.py.
    conn = psycopg2.connect(**admin_db_params(), cursor_factory=psycopg2.extras.RealDictCursor)
    conn.autocommit = False
    return conn


def _exec(cur: psycopg2.extensions.cursor, sql: str, params=None) -> list[dict]:
    cur.execute(sql, params)
    if cur.description:
        return [dict(r) for r in cur.fetchall()]
    return []


def _one(cur, sql, params=None) -> dict:
    rows = _exec(cur, sql, params)
    return rows[0]


# ---------------------------------------------------------------------------
# Seed helpers
# ---------------------------------------------------------------------------


def create_tenant(cur, company_name: str, email: str, phone: str, tier: str, tenant_id: str | None = None) -> dict:
    # tenant.slug is NOT NULL + UNIQUE (migration 023) — mirror its backfill
    # logic (lowercase, non-alnum -> hyphen, trim) since there's no DB default.
    slug = re.sub(r"-+", "-", re.sub(r"[^a-z0-9]+", "-", company_name.lower())).strip("-")
    if tenant_id:
        return _one(
            cur,
            """
            INSERT INTO tenant (
                id, company_name, primary_contact_email, primary_contact_phone,
                subscription_tier, status, slug
            ) VALUES (%s, %s, %s, %s, %s, 'active', %s)
            RETURNING *
            """,
            (tenant_id, company_name, email, phone, tier, slug),
        )
    return _one(
        cur,
        """
        INSERT INTO tenant (
            company_name, primary_contact_email, primary_contact_phone,
            subscription_tier, status, slug
        ) VALUES (%s, %s, %s, %s, 'active', %s)
        RETURNING *
        """,
        (company_name, email, phone, tier, slug),
    )


def create_user(
    cur,
    tenant_id: str,
    email: str,
    name: str,
    role: str,
    created_by: str | None = None,
    user_id: str | None = None,
) -> dict:
    # user_id is set to a fixed UUID when known so that id = cognito_sub holds
    # for seeded users — TenantContext.user_id is the raw Cognito sub with no
    # resolution step, so any created_by / approved_by FK must use this id.
    if user_id:
        return _one(
            cur,
            """
            INSERT INTO tenant_user (id, tenant_id, email, full_name, role, status, created_by)
            VALUES (%s, %s, %s, %s, %s, 'active', %s)
            RETURNING *
            """,
            (user_id, tenant_id, email, name, role, created_by),
        )
    return _one(
        cur,
        """
        INSERT INTO tenant_user (tenant_id, email, full_name, role, status, created_by)
        VALUES (%s, %s, %s, %s, 'active', %s)
        RETURNING *
        """,
        (tenant_id, email, name, role, created_by),
    )


def create_user_role(
    cur,
    tenant_user_id: str,
    tenant_id: str,
    role: str,
    is_primary: bool,
    assigned_by: str | None = None,
) -> None:
    """Insert a tenant_user_role row (migration 039 — multi-role staff support).

    Only called explicitly for the one multi-role seed user below — every
    single-role seeded user relies on repository.py's COALESCE fallback to
    `ARRAY[tenant_user.role]` when it has no tenant_user_role rows, same as
    any pre-existing tenant_user row would after the migration's backfill.
    """
    cur.execute(
        """
        INSERT INTO tenant_user_role (tenant_user_id, tenant_id, role, is_primary, assigned_by)
        VALUES (%s, %s, %s, %s, %s)
        ON CONFLICT (tenant_user_id, role) DO NOTHING
        """,
        (tenant_user_id, tenant_id, role, is_primary, assigned_by),
    )


def create_config(cur, tenant_id: str, key: str, value: dict) -> None:
    import json

    cur.execute(
        """
        INSERT INTO tenant_config (tenant_id, config_key, config_value)
        VALUES (%s, %s, %s)
        ON CONFLICT (tenant_id, config_key) DO UPDATE SET config_value = EXCLUDED.config_value
        """,
        (tenant_id, key, json.dumps(value)),
    )


def create_customer(cur, tenant_id: str, name: str, phone: str, email: str, address: str, user_id: str | None = None) -> dict:
    # user_id links the customer row to a tenant_user login — required for every
    # customer-portal flow that resolves the caller via customer.user_id
    # (my-shipments, my-billing, pay-online initialize, claims). Without it the
    # local role-switcher customer sees an empty portal.
    return _one(
        cur,
        """
        INSERT INTO customer (tenant_id, name, phone, email, address, user_id)
        VALUES (%s, %s, %s, %s, %s, %s)
        RETURNING *
        """,
        (tenant_id, name, phone, email, address, user_id),
    )


def create_container(
    cur, tenant_id: str, number: str, status: str, created_by: str, ship_date=None, eta=None, arrival=None
) -> dict:
    return _one(
        cur,
        """
        INSERT INTO container (
            tenant_id, container_number, origin, destination,
            ship_date, estimated_arrival_date, actual_arrival_date,
            status, created_by
        ) VALUES (%s, %s, 'China', 'Nigeria', %s, %s, %s, %s, %s)
        RETURNING *
        """,
        (tenant_id, number, ship_date, eta, arrival, status, created_by),
    )


def create_manifest(
    cur,
    tenant_id: str,
    container_id: str,
    total_customers: int,
    total_cartons: int,
    weight_kg: float,
    total_cbm: float,
    verified_by: str | None = None,
) -> dict:
    vstatus = "verified" if verified_by else "pending"
    return _one(
        cur,
        """
        INSERT INTO manifest (
            tenant_id, container_id, total_customers, total_cartons,
            total_weight_kg, total_cbm, verification_status, verified_by
        ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
        RETURNING *
        """,
        (tenant_id, container_id, total_customers, total_cartons, weight_kg, total_cbm, vstatus, verified_by),
    )


def create_packing_list(
    cur,
    tenant_id: str,
    container_id: str,
    manifest_id: str,
    customer_id: str,
    status: str,
    created_by: str,
    reference: str | None = None,
) -> dict:
    if reference is None:
        # Derive a stable reference from the row count so far for this tenant.
        row = _one(cur, "SELECT COUNT(*) AS cnt FROM packing_list WHERE tenant_id = %s", (tenant_id,))
        seq = int(row["cnt"]) + 1
        from datetime import date as _date

        reference = f"PL-{_date.today().strftime('%Y%m%d')}-{seq:03d}"
    return _one(
        cur,
        """
        INSERT INTO packing_list (
            tenant_id, container_id, manifest_id, customer_id, status, created_by, reference
        ) VALUES (%s, %s, %s, %s, %s, %s, %s)
        RETURNING *
        """,
        (tenant_id, container_id, manifest_id, customer_id, status, created_by, reference),
    )


def create_packing_list_item(
    cur, packing_list_id: str, description: str, carton_tag: str, tracking_code: str, weight_kg: float, cbm: float
) -> dict:
    return _one(
        cur,
        """
        INSERT INTO packing_list_item (
            packing_list_id, description, carton_tag, tracking_code,
            weight_actual_kg, cbm, received_date
        ) VALUES (%s, %s, %s, %s, %s, %s, CURRENT_DATE)
        RETURNING *
        """,
        (packing_list_id, description, carton_tag, tracking_code, weight_kg, cbm),
    )


def create_shipment_tracking(cur, tenant_id: str, packing_list_item_id: str, tracking_code: str, status: str) -> dict:
    return _one(
        cur,
        """
        INSERT INTO shipment_tracking (tenant_id, packing_list_item_id, tracking_code, status)
        VALUES (%s, %s, %s, %s)
        RETURNING *
        """,
        (tenant_id, packing_list_item_id, tracking_code, status),
    )


def create_billing(
    cur,
    tenant_id: str,
    customer_id: str,
    container_id: str,
    packing_list_id: str,
    invoice_number: str,
    total_cartons: int,
    total_cbm: float,
    cbm_rate_usd: float,
    exchange_rate: float,
    status: str,
    created_by: str,
    due_date=None,
) -> dict:
    subtotal_usd = round(total_cbm * cbm_rate_usd, 2)
    subtotal_ngn = round(subtotal_usd * exchange_rate, 2)
    return _one(
        cur,
        """
        INSERT INTO billing (
            tenant_id, customer_id, container_id, packing_list_id,
            invoice_number, total_cartons, total_cbm,
            cbm_rate_usd, subtotal_usd, exchange_rate_ngn,
            subtotal_ngn, total_ngn, status, due_date, created_by
        ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        RETURNING *
        """,
        (
            tenant_id,
            customer_id,
            container_id,
            packing_list_id,
            invoice_number,
            total_cartons,
            total_cbm,
            cbm_rate_usd,
            subtotal_usd,
            exchange_rate,
            subtotal_ngn,
            subtotal_ngn,
            status,
            due_date,
            created_by,
        ),
    )


def create_payment(
    cur, billing_id: str, tenant_id: str, amount_ngn: float, method: str, reference: str, payment_date, recorded_by: str
) -> dict:
    return _one(
        cur,
        """
        INSERT INTO payment_record (
            billing_id, tenant_id, amount_ngn, payment_method,
            reference_number, payment_date, recorded_by
        ) VALUES (%s, %s, %s, %s, %s, %s, %s)
        RETURNING *
        """,
        (billing_id, tenant_id, amount_ngn, method, reference, payment_date, recorded_by),
    )


# ---------------------------------------------------------------------------
# Main seed logic
# ---------------------------------------------------------------------------


# Fixed well-known UUIDs for all three dev-seed tenants so that
# LocalAuthProvider.tsx's DEMO_TENANT_ID and local_server.py's
# DEFAULT_TENANT_ID always match, and so scripts/bootstrap_local.sh's
# Cognito users line up 1:1 with these tenant_user rows by email —
# regardless of how many times `make stack` is run.
#
# Uniform per-tenant numbering scheme (all three tenants follow this):
#   xx11 tenant_admin · xx12 china_office_staff · xx13 nigeria_office_staff
#   xx14 warehouse_attendant · xx21-xx25 customers 1-5
#
# Each tenant's staff + customers all share that tenant's own email
# domain (acmeshipping.com / globalcargo.com / demoshipping.com) so
# real-Cognito-login testing (LOCAL_TESTING.md §14.2) can log in as any
# specific tenant or customer account, all under one platform admin.
ACME_TENANT_ID = "10000000-0000-0000-0000-000000000001"
ACME_ADMIN_ID = "10000000-0000-0000-0000-000000000011"
ACME_CHINA_ID = "10000000-0000-0000-0000-000000000012"
ACME_NIGERIA_ID = "10000000-0000-0000-0000-000000000013"
ACME_WH_ID = "10000000-0000-0000-0000-000000000014"
# Multi-role staff (migration 039) — Nigeria office staff + warehouse attendant,
# so the role-switch toggle and Cognito group-sync fix have a real login to
# exercise beyond the local-only LocalAuthProvider 'nigeria_warehouse' identity.
ACME_NIGERIA_WH_ID = "10000000-0000-0000-0000-000000000015"
ACME_CUST1_ID = "10000000-0000-0000-0000-000000000021"
ACME_CUST2_ID = "10000000-0000-0000-0000-000000000022"
ACME_CUST3_ID = "10000000-0000-0000-0000-000000000023"
ACME_CUST4_ID = "10000000-0000-0000-0000-000000000024"
ACME_CUST5_ID = "10000000-0000-0000-0000-000000000025"

# Fixed UUIDs for Global Cargo Co — stable across make stack resets.
GCCO_TENANT_ID = "30000000-0000-0000-0000-000000000001"
GCCO_ADMIN_ID = "30000000-0000-0000-0000-000000000011"
GCCO_CHINA_ID = "30000000-0000-0000-0000-000000000012"
GCCO_NIGERIA_ID = "30000000-0000-0000-0000-000000000013"
GCCO_WH_ID = "30000000-0000-0000-0000-000000000014"
GCCO_CUST1_ID = "30000000-0000-0000-0000-000000000021"
GCCO_CUST2_ID = "30000000-0000-0000-0000-000000000022"
GCCO_CUST3_ID = "30000000-0000-0000-0000-000000000023"
GCCO_CUST4_ID = "30000000-0000-0000-0000-000000000024"
GCCO_CUST5_ID = "30000000-0000-0000-0000-000000000025"

# Fixed UUIDs for Demo Shipping Ltd — stable across make stack resets.
DEMO_TENANT_ID = "20000000-0000-0000-0000-000000000001"
DEMO_ADMIN_ID = "20000000-0000-0000-0000-000000000011"
DEMO_CHINA_ID = "20000000-0000-0000-0000-000000000012"
DEMO_NIGERIA_ID = "20000000-0000-0000-0000-000000000013"
DEMO_WH_ID = "20000000-0000-0000-0000-000000000014"
DEMO_CUST1_ID = "20000000-0000-0000-0000-000000000021"
DEMO_CUST2_ID = "20000000-0000-0000-0000-000000000022"
DEMO_CUST3_ID = "20000000-0000-0000-0000-000000000023"
DEMO_CUST4_ID = "20000000-0000-0000-0000-000000000024"
DEMO_CUST5_ID = "20000000-0000-0000-0000-000000000025"


def seed_tenant_a(cur) -> dict:
    """Acme Shipping Ltd — starter tier, 2 containers, varied billing states."""
    today = date.today()
    print("\n--- Tenant A: Acme Shipping Ltd ---")

    tenant = create_tenant(
        cur,
        company_name="Acme Shipping Ltd",
        email="admin@acmeshipping.com",
        phone="+2348011111111",
        tier="starter",
        tenant_id=ACME_TENANT_ID,
    )
    tid = str(tenant["id"])
    print(f"  tenant_id: {tid}")

    # Users — fixed IDs so local_server.py's _resolve_user_id always finds
    # these rows, and DEMO_TENANT_ID in LocalAuthProvider.tsx stays stable.
    admin = create_user(cur, tid, "admin@acmeshipping.com", "Chidi Okafor", "tenant_admin", user_id=ACME_ADMIN_ID)
    china_staff = create_user(
        cur, tid, "china@acmeshipping.com", "Li Wei", "china_office_staff", admin["id"], user_id=ACME_CHINA_ID
    )
    ng_staff = create_user(
        cur, tid, "lagos@acmeshipping.com", "Emeka Eze", "nigeria_office_staff", admin["id"], user_id=ACME_NIGERIA_ID
    )
    warehouse = create_user(
        cur, tid, "warehouse@acmeshipping.com", "Tunde Bello", "warehouse_attendant", admin["id"], user_id=ACME_WH_ID
    )
    # Multi-role staff member — primary role (mirrored to tenant_user.role) is
    # nigeria_office_staff, secondary is warehouse_attendant. See LOCAL_TESTING.md
    # §14 for how to log in as this user and exercise the role-switch toggle.
    ng_wh_staff = create_user(
        cur, tid, "amaka@acmeshipping.com", "Amaka Nwachukwu", "nigeria_office_staff", admin["id"], user_id=ACME_NIGERIA_WH_ID
    )
    create_user_role(cur, ng_wh_staff["id"], tid, "nigeria_office_staff", is_primary=True, assigned_by=admin["id"])
    create_user_role(cur, ng_wh_staff["id"], tid, "warehouse_attendant", is_primary=False, assigned_by=admin["id"])
    # 5 customer logins, all @acmeshipping.com — one tenant_user + one linked
    # customer row each (see create_customer below), so every one of them can
    # log in as a customer and see their own portal.
    cust1_user = create_user(cur, tid, "ngozi@acmeshipping.com", "Ngozi Adeyemi", "customer", admin["id"], user_id=ACME_CUST1_ID)
    cust2_user = create_user(cur, tid, "ibrahim@acmeshipping.com", "Ibrahim Musa", "customer", admin["id"], user_id=ACME_CUST2_ID)
    cust3_user = create_user(cur, tid, "chioma@acmeshipping.com", "Chioma Eze", "customer", admin["id"], user_id=ACME_CUST3_ID)
    cust4_user = create_user(cur, tid, "yusuf@acmeshipping.com", "Yusuf Musa", "customer", admin["id"], user_id=ACME_CUST4_ID)
    cust5_user = create_user(
        cur, tid, "blessing@acmeshipping.com", "Blessing Nwosu", "customer", admin["id"], user_id=ACME_CUST5_ID
    )
    print(
        f"  users: {admin['id']} (admin), {china_staff['id']} (china), {ng_staff['id']} (ng), {warehouse['id']} (wh), {ng_wh_staff['id']} (ng+wh multi-role)"
    )

    # Configs
    create_config(cur, tid, "dollar_rate", {"rate": 1550.00, "currency_pair": "USD_NGN", "effective_from": str(today)})
    create_config(cur, tid, "cbm_rate_per_unit", {"rate_usd": 45.00})
    create_config(cur, tid, "storage_fee", {"enabled": True, "grace_period_days": 14, "daily_fee_per_carton_ngn": 500})
    create_config(cur, tid, "warehouse_address", {"address": "1 Apapa Road", "city": "Lagos", "state": "Lagos"})
    create_config(cur, tid, "refund_threshold_usd", {"staff_limit": 50, "requires_manager_above": 50})
    create_config(cur, tid, "dispute_escalation", {"enabled": True, "auto_escalate_days": 5})
    create_config(cur, tid, "reminder_days", {"storage_first_reminder": 7, "storage_final_reminder": 13})

    # 5 customer profiles, all @acmeshipping.com, each linked via user_id to
    # the tenant_user row created above — every one of them is a real login.
    cust1 = create_customer(
        cur, tid, "Ngozi Adeyemi", "+2348022222222", "ngozi@acmeshipping.com", "5 Okonkwo Street, Aba", user_id=cust1_user["id"]
    )
    cust2 = create_customer(
        cur, tid, "Ibrahim Musa", "+2348033333333", "ibrahim@acmeshipping.com", "12 Kano Road, Kaduna", user_id=cust2_user["id"]
    )
    cust3 = create_customer(
        cur, tid, "Chioma Eze", "+2348034567890", "chioma@acmeshipping.com", "7 Eze Close, Enugu", user_id=cust3_user["id"]
    )
    cust4 = create_customer(
        cur, tid, "Yusuf Musa", "+2348023456789", "yusuf@acmeshipping.com", "22 Musa Avenue, Kano", user_id=cust4_user["id"]
    )
    cust5 = create_customer(
        cur,
        tid,
        "Blessing Nwosu",
        "+2348045678901",
        "blessing@acmeshipping.com",
        "31 Nwosu Crescent, Aba",
        user_id=cust5_user["id"],
    )
    print(
        f"  customers: {cust1['id']} (Ngozi), {cust2['id']} (Ibrahim), {cust3['id']} (Chioma), {cust4['id']} (Yusuf), {cust5['id']} (Blessing)"
    )

    # Container 1 — fully released (historical)
    ship1 = today - timedelta(days=90)
    arr1 = today - timedelta(days=30)
    con1 = create_container(
        cur, tid, "ACME001001", "fully_released", str(admin["id"]), ship_date=ship1, eta=arr1 - timedelta(days=5), arrival=arr1
    )
    man1 = create_manifest(cur, tid, str(con1["id"]), 2, 10, 210.5, 3.5, str(ng_staff["id"]))

    pl1 = create_packing_list(cur, tid, str(con1["id"]), str(man1["id"]), str(cust1["id"]), "approved", str(china_staff["id"]))
    item1a = create_packing_list_item(cur, str(pl1["id"]), "Electronic goods", "ACME-001-001", "TRK001001", 20.5, 0.8)
    item1b = create_packing_list_item(cur, str(pl1["id"]), "Clothing items", "ACME-001-002", "TRK001002", 18.0, 0.7)
    create_shipment_tracking(cur, tid, str(item1a["id"]), "TRK001001", "released")
    create_shipment_tracking(cur, tid, str(item1b["id"]), "TRK001002", "released")

    pl2 = create_packing_list(cur, tid, str(con1["id"]), str(man1["id"]), str(cust2["id"]), "approved", str(china_staff["id"]))
    item2a = create_packing_list_item(cur, str(pl2["id"]), "Kitchen appliances", "ACME-001-003", "TRK001003", 95.0, 1.2)
    item2b = create_packing_list_item(cur, str(pl2["id"]), "Auto parts", "ACME-001-004", "TRK001004", 77.0, 0.8)
    create_shipment_tracking(cur, tid, str(item2a["id"]), "TRK001003", "released")
    create_shipment_tracking(cur, tid, str(item2b["id"]), "TRK001004", "released")

    # Billing for container 1 — cust1 paid, cust2 partially_paid
    b1 = create_billing(
        cur,
        tid,
        str(cust1["id"]),
        str(con1["id"]),
        str(pl1["id"]),
        "INV-A-001",
        2,
        1.5,
        45.0,
        1550.0,
        "paid",
        str(ng_staff["id"]),
        due_date=arr1 + timedelta(days=7),
    )
    create_payment(
        cur, str(b1["id"]), tid, b1["total_ngn"], "bank_transfer", "REF001", arr1 + timedelta(days=3), str(ng_staff["id"])
    )
    # mark amount_paid_ngn
    cur.execute("UPDATE billing SET amount_paid_ngn = %s WHERE id = %s", (b1["total_ngn"], b1["id"]))

    b2 = create_billing(
        cur,
        tid,
        str(cust2["id"]),
        str(con1["id"]),
        str(pl2["id"]),
        "INV-A-002",
        4,
        2.0,
        45.0,
        1550.0,
        "partially_paid",
        str(ng_staff["id"]),
        due_date=arr1 + timedelta(days=7),
    )
    partial = round(b2["total_ngn"] * Decimal("0.6"), 2)
    create_payment(cur, str(b2["id"]), tid, partial, "cash", "CASH001", arr1 + timedelta(days=4), str(ng_staff["id"]))
    cur.execute("UPDATE billing SET amount_paid_ngn = %s WHERE id = %s", (partial, b2["id"]))

    # Container 2 — at_warehouse (active)
    ship2 = today - timedelta(days=20)
    arr2 = today - timedelta(days=5)
    con2 = create_container(
        cur, tid, "ACME001002", "at_warehouse", str(admin["id"]), ship_date=ship2, eta=arr2 + timedelta(days=2), arrival=arr2
    )
    man2 = create_manifest(cur, tid, str(con2["id"]), 1, 5, 110.0, 2.0)

    pl3 = create_packing_list(
        cur, tid, str(con2["id"]), str(man2["id"]), str(cust1["id"]), "pending_approval", str(china_staff["id"])
    )
    item3a = create_packing_list_item(cur, str(pl3["id"]), "Fabric rolls", "ACME-002-001", "TRK002001", 55.0, 1.0)
    item3b = create_packing_list_item(cur, str(pl3["id"]), "Shoes", "ACME-002-002", "TRK002002", 30.0, 0.6)
    create_shipment_tracking(cur, tid, str(item3a["id"]), "TRK002001", "at_warehouse")
    create_shipment_tracking(cur, tid, str(item3b["id"]), "TRK002002", "at_warehouse")

    # Unpaid billing for container 2
    create_billing(
        cur,
        tid,
        str(cust1["id"]),
        str(con2["id"]),
        str(pl3["id"]),
        "INV-A-003",
        2,
        1.6,
        45.0,
        1550.0,
        "unpaid",
        str(ng_staff["id"]),
        due_date=today + timedelta(days=14),
    )

    print(f"  containers: {con1['id']} (fully_released), {con2['id']} (at_warehouse)")
    return {"tenant": tenant, "admin": admin, "customers": [cust1, cust2]}


def seed_tenant_b(cur) -> dict:
    """Global Cargo Co — business tier, 1 container, no storage fee."""
    today = date.today()
    print("\n--- Tenant B: Global Cargo Co ---")

    tenant = create_tenant(
        cur,
        company_name="Global Cargo Co",
        email="admin@globalcargo.com",
        phone="+2348044444444",
        tier="business",
        tenant_id=GCCO_TENANT_ID,
    )
    tid = str(tenant["id"])
    print(f"  tenant_id: {tid}")

    # Users — full staff set (same shape as Acme/Demo) so every role is
    # testable against this tenant too.
    admin = create_user(cur, tid, "admin@globalcargo.com", "Aisha Suleiman", "tenant_admin", user_id=GCCO_ADMIN_ID)
    china1 = create_user(cur, tid, "china@globalcargo.com", "Zhang Wei", "china_office_staff", admin["id"], user_id=GCCO_CHINA_ID)
    ng_staff = create_user(
        cur, tid, "lagos@globalcargo.com", "Ade Bankole", "nigeria_office_staff", admin["id"], user_id=GCCO_NIGERIA_ID
    )
    warehouse = create_user(
        cur, tid, "warehouse@globalcargo.com", "Ngozi Kalu", "warehouse_attendant", admin["id"], user_id=GCCO_WH_ID
    )
    # 5 customer logins, all @globalcargo.com.
    cust1_user = create_user(
        cur, tid, "olumide@globalcargo.com", "Olumide Adebayo", "customer", admin["id"], user_id=GCCO_CUST1_ID
    )
    cust2_user = create_user(cur, tid, "chinwe@globalcargo.com", "Chinwe Okoro", "customer", admin["id"], user_id=GCCO_CUST2_ID)
    cust3_user = create_user(cur, tid, "tunji@globalcargo.com", "Tunji Bakare", "customer", admin["id"], user_id=GCCO_CUST3_ID)
    cust4_user = create_user(cur, tid, "grace@globalcargo.com", "Grace Eze", "customer", admin["id"], user_id=GCCO_CUST4_ID)
    cust5_user = create_user(cur, tid, "halima@globalcargo.com", "Halima Yusuf", "customer", admin["id"], user_id=GCCO_CUST5_ID)
    print(f"  users: {admin['id']} (admin), {china1['id']} (china), {ng_staff['id']} (ng), {warehouse['id']} (wh)")

    # Configs — higher rate, storage fee disabled
    create_config(cur, tid, "dollar_rate", {"rate": 1580.00, "currency_pair": "USD_NGN", "effective_from": str(today)})
    create_config(cur, tid, "cbm_rate_per_unit", {"rate_usd": 50.00})
    create_config(cur, tid, "storage_fee", {"enabled": False, "grace_period_days": 14, "daily_fee_per_carton_ngn": 0})
    create_config(cur, tid, "warehouse_address", {"address": "8 Broad Street", "city": "Lagos", "state": "Lagos"})
    create_config(cur, tid, "refund_threshold_usd", {"staff_limit": 100, "requires_manager_above": 100})

    # 5 customer profiles, all @globalcargo.com, each linked via user_id to
    # the tenant_user row created above.
    cust1 = create_customer(
        cur,
        tid,
        "Olumide Adebayo",
        "+2348055555555",
        "olumide@globalcargo.com",
        "3 Victoria Island, Lagos",
        user_id=cust1_user["id"],
    )
    cust2 = create_customer(
        cur, tid, "Chinwe Okoro", "+2348056666666", "chinwe@globalcargo.com", "18 Okoro Street, Onitsha", user_id=cust2_user["id"]
    )
    cust3 = create_customer(
        cur, tid, "Tunji Bakare", "+2348057777777", "tunji@globalcargo.com", "4 Bakare Close, Ibadan", user_id=cust3_user["id"]
    )
    cust4 = create_customer(
        cur, tid, "Grace Eze", "+2348058888888", "grace@globalcargo.com", "27 Eze Road, Enugu", user_id=cust4_user["id"]
    )
    cust5 = create_customer(
        cur, tid, "Halima Yusuf", "+2348059999999", "halima@globalcargo.com", "9 Yusuf Avenue, Kano", user_id=cust5_user["id"]
    )
    print(
        f"  customers: {cust1['id']} (Olumide), {cust2['id']} (Chinwe), {cust3['id']} (Tunji), {cust4['id']} (Grace), {cust5['id']} (Halima)"
    )

    # Container — in_transit
    ship_date = date.today() - timedelta(days=10)
    eta = date.today() + timedelta(days=15)
    con1 = create_container(cur, tid, "GCCO001001", "in_transit", str(admin["id"]), ship_date=ship_date, eta=eta)
    man1 = create_manifest(cur, tid, str(con1["id"]), 1, 8, 180.0, 4.0)

    pl1 = create_packing_list(cur, tid, str(con1["id"]), str(man1["id"]), str(cust1["id"]), "approved", str(china1["id"]))
    item1a = create_packing_list_item(cur, str(pl1["id"]), "Machinery parts", "GCCO-001-001", "TRK003001", 90.0, 2.0)
    item1b = create_packing_list_item(cur, str(pl1["id"]), "Electronics", "GCCO-001-002", "TRK003002", 50.0, 1.2)
    item1c = create_packing_list_item(cur, str(pl1["id"]), "Textiles", "GCCO-001-003", "TRK003003", 40.0, 0.8)
    create_shipment_tracking(cur, tid, str(item1a["id"]), "TRK003001", "in_transit")
    create_shipment_tracking(cur, tid, str(item1b["id"]), "TRK003002", "in_transit")
    create_shipment_tracking(cur, tid, str(item1c["id"]), "TRK003003", "in_transit")

    # Billing — sent (awaiting payment)
    create_billing(
        cur,
        tid,
        str(cust1["id"]),
        str(con1["id"]),
        str(pl1["id"]),
        "INV-B-001",
        3,
        4.0,
        50.0,
        1580.0,
        "unpaid",
        str(admin["id"]),
        due_date=eta + timedelta(days=7),
    )

    print(f"  container: {con1['id']} (in_transit)")
    return {"tenant": tenant, "admin": admin, "customers": [cust1, cust2, cust3, cust4, cust5]}


def seed_tenant_demo(cur) -> dict:
    """Demo Shipping Ltd — business tier, one loading container for testing."""
    today = date.today()
    print("\n--- Tenant C: Demo Shipping Ltd ---")

    tenant = create_tenant(
        cur,
        company_name="Demo Shipping Ltd",
        email="admin@demoshipping.com",
        phone="+2348099999999",
        tier="business",
        tenant_id=DEMO_TENANT_ID,
    )
    tid = str(tenant["id"])
    print(f"  tenant_id: {tid}")

    admin = create_user(cur, tid, "admin@demoshipping.com", "Amara Okafor", "tenant_admin", user_id=DEMO_ADMIN_ID)
    china = create_user(
        cur, tid, "china@demoshipping.com", "Kwame Asante", "china_office_staff", admin["id"], user_id=DEMO_CHINA_ID
    )
    nigeria = create_user(
        cur, tid, "lagos@demoshipping.com", "Fatima Bello", "nigeria_office_staff", admin["id"], user_id=DEMO_NIGERIA_ID
    )
    create_user(cur, tid, "warehouse@demoshipping.com", "Segun Dada", "warehouse_attendant", admin["id"], user_id=DEMO_WH_ID)
    # 5 customer logins, all @demoshipping.com.
    cust1_user = create_user(
        cur, tid, "funmi@demoshipping.com", "Funmilayo Adeyemi", "customer", admin["id"], user_id=DEMO_CUST1_ID
    )
    cust2_user = create_user(cur, tid, "emeka@demoshipping.com", "Emeka Obi", "customer", admin["id"], user_id=DEMO_CUST2_ID)
    cust3_user = create_user(cur, tid, "amaka@demoshipping.com", "Amaka Chukwu", "customer", admin["id"], user_id=DEMO_CUST3_ID)
    cust4_user = create_user(cur, tid, "david@demoshipping.com", "David Okon", "customer", admin["id"], user_id=DEMO_CUST4_ID)
    cust5_user = create_user(cur, tid, "zainab@demoshipping.com", "Zainab Bello", "customer", admin["id"], user_id=DEMO_CUST5_ID)
    print(f"  users: {admin['id']} (admin), {china['id']} (china), {nigeria['id']} (ng)")

    create_config(cur, tid, "dollar_rate", {"rate": 1600.00, "currency_pair": "USD_NGN", "effective_from": str(today)})
    create_config(cur, tid, "cbm_rate_per_unit", {"rate_usd": 48.00})
    create_config(cur, tid, "storage_fee", {"enabled": True, "grace_period_days": 14, "daily_fee_per_carton_ngn": 500})
    create_config(cur, tid, "warehouse_address", {"address": "3 Marina Road", "city": "Lagos", "state": "Lagos"})
    create_config(cur, tid, "refund_threshold_usd", {"staff_limit": 75, "requires_manager_above": 75})

    # 5 customer profiles, all @demoshipping.com, each linked via user_id to
    # the tenant_user row created above.
    cust1 = create_customer(
        cur,
        tid,
        "Funmilayo Adeyemi",
        "+2348011122233",
        "funmi@demoshipping.com",
        "14 Adeyemi Lane, Lagos",
        user_id=cust1_user["id"],
    )
    cust2 = create_customer(
        cur, tid, "Emeka Obi", "+2348044455566", "emeka@demoshipping.com", "9 Obi Street, Onitsha", user_id=cust2_user["id"]
    )
    cust3 = create_customer(
        cur, tid, "Amaka Chukwu", "+2348044455577", "amaka@demoshipping.com", "16 Chukwu Avenue, Aba", user_id=cust3_user["id"]
    )
    cust4 = create_customer(
        cur, tid, "David Okon", "+2348044455588", "david@demoshipping.com", "2 Okon Street, Uyo", user_id=cust4_user["id"]
    )
    cust5 = create_customer(
        cur, tid, "Zainab Bello", "+2348044455599", "zainab@demoshipping.com", "40 Bello Road, Kano", user_id=cust5_user["id"]
    )
    print(
        f"  customers: {cust1['id']} (Funmilayo), {cust2['id']} (Emeka), {cust3['id']} (Amaka), {cust4['id']} (David), {cust5['id']} (Zainab)"
    )

    # One container currently loading — so china staff can add packing lists immediately
    con1 = create_container(cur, tid, "DEMO001001", "loading", str(china["id"]))
    print(f"  container: {con1['id']} (loading)")

    return {"tenant": tenant, "admin": admin, "customers": [cust1, cust2, cust3, cust4, cust5]}


def main() -> None:
    print("Connecting to database...")
    conn = _connect()

    try:
        with conn.cursor() as cur:
            # Seed data is inserted as the superuser / DB owner, bypassing RLS.
            # In production, use the logistics_app role and set app.current_tenant_id.
            result_a = seed_tenant_a(cur)
            result_b = seed_tenant_b(cur)
            result_c = seed_tenant_demo(cur)

        conn.commit()
        print("\n=== Seed complete ===")
        print(f"Tenant A ({result_a['tenant']['company_name']}): {result_a['tenant']['id']}")
        print(f"Tenant B ({result_b['tenant']['company_name']}): {result_b['tenant']['id']}")
        print(f"Tenant C ({result_c['tenant']['company_name']}): {result_c['tenant']['id']}")
        print("\nTo test RLS cross-tenant isolation:")
        print("  SET app.current_tenant_id = '<tenant_a_id>';")
        print("  SELECT count(*) FROM customer;  -- should return only Tenant A rows")

    except Exception as exc:
        conn.rollback()
        print(f"\nSeed FAILED: {exc}", file=sys.stderr)
        raise
    finally:
        conn.close()


if __name__ == "__main__":
    main()
