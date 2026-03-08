"""Database seed script — populates dev/staging environments with initial data.

Creates two test tenants with realistic cargo-shipping data:
  - Tenant A: "Acme Shipping Ltd"    (starter tier, 2 containers)
  - Tenant B: "Global Cargo Co"     (business tier, 1 container)

Usage:
    DATABASE_HOST=localhost DATABASE_NAME=logistics \\
    DATABASE_USER=postgres DATABASE_PASSWORD=secret \\
    python scripts/seed.py
"""

import os
import sys
import uuid
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path

import psycopg2
import psycopg2.extras

# ---------------------------------------------------------------------------
# Connection helpers
# ---------------------------------------------------------------------------


def _connect() -> psycopg2.extensions.connection:
    dsn = (
        f"host={os.environ['DATABASE_HOST']} "
        f"port={os.environ.get('DATABASE_PORT', '5432')} "
        f"dbname={os.environ['DATABASE_NAME']} "
        f"user={os.environ['DATABASE_USER']} "
        f"password={os.environ['DATABASE_PASSWORD']}"
    )
    conn = psycopg2.connect(dsn, cursor_factory=psycopg2.extras.RealDictCursor)
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


def create_tenant(cur, company_name: str, email: str, phone: str, tier: str) -> dict:
    return _one(
        cur,
        """
        INSERT INTO tenant (
            company_name, primary_contact_email, primary_contact_phone,
            subscription_tier, status
        ) VALUES (%s, %s, %s, %s, 'active')
        RETURNING *
        """,
        (company_name, email, phone, tier),
    )


def create_user(cur, tenant_id: str, email: str, name: str, role: str, created_by=None) -> dict:
    return _one(
        cur,
        """
        INSERT INTO tenant_user (tenant_id, email, full_name, role, status, created_by)
        VALUES (%s, %s, %s, %s, 'active', %s)
        RETURNING *
        """,
        (tenant_id, email, name, role, created_by),
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


def create_customer(cur, tenant_id: str, name: str, phone: str, email: str, address: str) -> dict:
    return _one(
        cur,
        """
        INSERT INTO customer (tenant_id, name, phone, email, address)
        VALUES (%s, %s, %s, %s, %s)
        RETURNING *
        """,
        (tenant_id, name, phone, email, address),
    )


def create_container(cur, tenant_id: str, number: str, status: str, created_by: str,
                     ship_date=None, eta=None, arrival=None) -> dict:
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


def create_manifest(cur, tenant_id: str, container_id: str, total_customers: int,
                    total_cartons: int, weight_kg: float, total_cbm: float,
                    verified_by: str | None = None) -> dict:
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
        (tenant_id, container_id, total_customers, total_cartons,
         weight_kg, total_cbm, vstatus, verified_by),
    )


def create_packing_list(cur, tenant_id: str, container_id: str, manifest_id: str,
                        customer_id: str, status: str, created_by: str) -> dict:
    return _one(
        cur,
        """
        INSERT INTO packing_list (
            tenant_id, container_id, manifest_id, customer_id, status, created_by
        ) VALUES (%s, %s, %s, %s, %s, %s)
        RETURNING *
        """,
        (tenant_id, container_id, manifest_id, customer_id, status, created_by),
    )


def create_packing_list_item(cur, packing_list_id: str, description: str,
                             carton_tag: str, tracking_code: str,
                             weight_kg: float, cbm: float) -> dict:
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


def create_shipment_tracking(cur, tenant_id: str, packing_list_item_id: str,
                              tracking_code: str, status: str) -> dict:
    return _one(
        cur,
        """
        INSERT INTO shipment_tracking (tenant_id, packing_list_item_id, tracking_code, status)
        VALUES (%s, %s, %s, %s)
        RETURNING *
        """,
        (tenant_id, packing_list_item_id, tracking_code, status),
    )


def create_billing(cur, tenant_id: str, customer_id: str, container_id: str,
                   packing_list_id: str, invoice_number: str, total_cartons: int,
                   total_cbm: float, cbm_rate_usd: float, exchange_rate: float,
                   status: str, created_by: str, due_date=None) -> dict:
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
        (tenant_id, customer_id, container_id, packing_list_id,
         invoice_number, total_cartons, total_cbm,
         cbm_rate_usd, subtotal_usd, exchange_rate,
         subtotal_ngn, subtotal_ngn, status, due_date, created_by),
    )


def create_payment(cur, billing_id: str, tenant_id: str, amount_ngn: float,
                   method: str, reference: str, payment_date, recorded_by: str) -> dict:
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
    )
    tid = str(tenant["id"])
    print(f"  tenant_id: {tid}")

    # Users
    admin = create_user(cur, tid, "admin@acmeshipping.com", "Chidi Okafor", "tenant_admin")
    china_staff = create_user(cur, tid, "china@acmeshipping.com", "Li Wei", "china_office_staff", admin["id"])
    ng_staff = create_user(cur, tid, "lagos@acmeshipping.com", "Emeka Eze", "nigeria_office_staff", admin["id"])
    warehouse = create_user(cur, tid, "warehouse@acmeshipping.com", "Tunde Bello", "warehouse_attendant", admin["id"])
    cust_user1 = create_user(cur, tid, "customer1@example.com", "Ngozi Adeyemi", "customer", admin["id"])
    cust_user2 = create_user(cur, tid, "customer2@example.com", "Ibrahim Musa", "customer", admin["id"])
    print(f"  users: {admin['id']} (admin), {china_staff['id']} (china), {ng_staff['id']} (ng), {warehouse['id']} (wh)")

    # Configs
    create_config(cur, tid, "dollar_rate", {"rate": 1550.00, "currency_pair": "USD_NGN", "effective_from": str(today)})
    create_config(cur, tid, "cbm_rate_per_unit", {"rate_usd": 45.00})
    create_config(cur, tid, "storage_fee", {"enabled": True, "grace_period_days": 14, "daily_fee_per_carton_ngn": 500})
    create_config(cur, tid, "warehouse_address", {"address": "1 Apapa Road", "city": "Lagos", "state": "Lagos"})
    create_config(cur, tid, "refund_threshold_usd", {"staff_limit": 50, "requires_manager_above": 50})
    create_config(cur, tid, "dispute_escalation", {"enabled": True, "auto_escalate_days": 5})
    create_config(cur, tid, "reminder_days", {"storage_first_reminder": 7, "storage_final_reminder": 13})

    # Customers
    cust1 = create_customer(cur, tid, "Ngozi Adeyemi", "+2348022222222", "ngozi@example.com", "5 Okonkwo Street, Aba")
    cust2 = create_customer(cur, tid, "Ibrahim Musa", "+2348033333333", "ibrahim@example.com", "12 Kano Road, Kaduna")
    print(f"  customers: {cust1['id']}, {cust2['id']}")

    # Container 1 — fully released (historical)
    ship1 = today - timedelta(days=90)
    arr1 = today - timedelta(days=30)
    con1 = create_container(cur, tid, "ACME001001", "fully_released", str(admin["id"]),
                            ship_date=ship1, eta=arr1 - timedelta(days=5), arrival=arr1)
    man1 = create_manifest(cur, tid, str(con1["id"]), 2, 10, 210.5, 3.5, str(ng_staff["id"]))

    pl1 = create_packing_list(cur, tid, str(con1["id"]), str(man1["id"]),
                               str(cust1["id"]), "approved", str(china_staff["id"]))
    item1a = create_packing_list_item(cur, str(pl1["id"]), "Electronic goods", "ACME-001-001", "TRK001001", 20.5, 0.8)
    item1b = create_packing_list_item(cur, str(pl1["id"]), "Clothing items", "ACME-001-002", "TRK001002", 18.0, 0.7)
    create_shipment_tracking(cur, tid, str(item1a["id"]), "TRK001001", "released")
    create_shipment_tracking(cur, tid, str(item1b["id"]), "TRK001002", "released")

    pl2 = create_packing_list(cur, tid, str(con1["id"]), str(man1["id"]),
                               str(cust2["id"]), "approved", str(china_staff["id"]))
    item2a = create_packing_list_item(cur, str(pl2["id"]), "Kitchen appliances", "ACME-001-003", "TRK001003", 95.0, 1.2)
    item2b = create_packing_list_item(cur, str(pl2["id"]), "Auto parts", "ACME-001-004", "TRK001004", 77.0, 0.8)
    create_shipment_tracking(cur, tid, str(item2a["id"]), "TRK001003", "released")
    create_shipment_tracking(cur, tid, str(item2b["id"]), "TRK001004", "released")

    # Billing for container 1 — cust1 paid, cust2 partially_paid
    b1 = create_billing(cur, tid, str(cust1["id"]), str(con1["id"]), str(pl1["id"]),
                        "INV-A-001", 2, 1.5, 45.0, 1550.0, "paid",
                        str(ng_staff["id"]), due_date=arr1 + timedelta(days=7))
    create_payment(cur, str(b1["id"]), tid, b1["total_ngn"], "bank_transfer", "REF001", arr1 + timedelta(days=3), str(ng_staff["id"]))
    # mark amount_paid_ngn
    cur.execute("UPDATE billing SET amount_paid_ngn = %s WHERE id = %s", (b1["total_ngn"], b1["id"]))

    b2 = create_billing(cur, tid, str(cust2["id"]), str(con1["id"]), str(pl2["id"]),
                        "INV-A-002", 4, 2.0, 45.0, 1550.0, "partially_paid",
                        str(ng_staff["id"]), due_date=arr1 + timedelta(days=7))
    partial = round(b2["total_ngn"] * Decimal("0.6"), 2)
    create_payment(cur, str(b2["id"]), tid, partial, "cash", "CASH001", arr1 + timedelta(days=4), str(ng_staff["id"]))
    cur.execute("UPDATE billing SET amount_paid_ngn = %s WHERE id = %s", (partial, b2["id"]))

    # Container 2 — at_warehouse (active)
    ship2 = today - timedelta(days=20)
    arr2 = today - timedelta(days=5)
    con2 = create_container(cur, tid, "ACME001002", "at_warehouse", str(admin["id"]),
                            ship_date=ship2, eta=arr2 + timedelta(days=2), arrival=arr2)
    man2 = create_manifest(cur, tid, str(con2["id"]), 1, 5, 110.0, 2.0)

    pl3 = create_packing_list(cur, tid, str(con2["id"]), str(man2["id"]),
                               str(cust1["id"]), "pending_approval", str(china_staff["id"]))
    item3a = create_packing_list_item(cur, str(pl3["id"]), "Fabric rolls", "ACME-002-001", "TRK002001", 55.0, 1.0)
    item3b = create_packing_list_item(cur, str(pl3["id"]), "Shoes", "ACME-002-002", "TRK002002", 30.0, 0.6)
    create_shipment_tracking(cur, tid, str(item3a["id"]), "TRK002001", "at_warehouse")
    create_shipment_tracking(cur, tid, str(item3b["id"]), "TRK002002", "at_warehouse")

    # Unpaid billing for container 2
    create_billing(cur, tid, str(cust1["id"]), str(con2["id"]), str(pl3["id"]),
                   "INV-A-003", 2, 1.6, 45.0, 1550.0, "unpaid",
                   str(ng_staff["id"]), due_date=today + timedelta(days=14))

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
    )
    tid = str(tenant["id"])
    print(f"  tenant_id: {tid}")

    # Users
    admin = create_user(cur, tid, "admin@globalcargo.com", "Aisha Suleiman", "tenant_admin")
    china1 = create_user(cur, tid, "china1@globalcargo.com", "Zhang Wei", "china_office_staff", admin["id"])
    china2 = create_user(cur, tid, "china2@globalcargo.com", "Wang Fang", "china_office_staff", admin["id"])
    cust_user = create_user(cur, tid, "customer@globalcargo.com", "Olumide Adebayo", "customer", admin["id"])
    print(f"  users: {admin['id']} (admin), {china1['id']}, {china2['id']} (china)")

    # Configs — higher rate, storage fee disabled
    create_config(cur, tid, "dollar_rate", {"rate": 1580.00, "currency_pair": "USD_NGN", "effective_from": str(today)})
    create_config(cur, tid, "cbm_rate_per_unit", {"rate_usd": 50.00})
    create_config(cur, tid, "storage_fee", {"enabled": False, "grace_period_days": 14, "daily_fee_per_carton_ngn": 0})
    create_config(cur, tid, "warehouse_address", {"address": "8 Broad Street", "city": "Lagos", "state": "Lagos"})
    create_config(cur, tid, "refund_threshold_usd", {"staff_limit": 100, "requires_manager_above": 100})

    # Customer
    cust1 = create_customer(cur, tid, "Olumide Adebayo", "+2348055555555", "olumide@example.com", "3 Victoria Island, Lagos")
    print(f"  customers: {cust1['id']}")

    # Container — in_transit
    ship_date = date.today() - timedelta(days=10)
    eta = date.today() + timedelta(days=15)
    con1 = create_container(cur, tid, "GCCO001001", "in_transit", str(admin["id"]),
                            ship_date=ship_date, eta=eta)
    man1 = create_manifest(cur, tid, str(con1["id"]), 1, 8, 180.0, 4.0)

    pl1 = create_packing_list(cur, tid, str(con1["id"]), str(man1["id"]),
                               str(cust1["id"]), "approved", str(china1["id"]))
    item1a = create_packing_list_item(cur, str(pl1["id"]), "Machinery parts", "GCCO-001-001", "TRK003001", 90.0, 2.0)
    item1b = create_packing_list_item(cur, str(pl1["id"]), "Electronics", "GCCO-001-002", "TRK003002", 50.0, 1.2)
    item1c = create_packing_list_item(cur, str(pl1["id"]), "Textiles", "GCCO-001-003", "TRK003003", 40.0, 0.8)
    create_shipment_tracking(cur, tid, str(item1a["id"]), "TRK003001", "in_transit")
    create_shipment_tracking(cur, tid, str(item1b["id"]), "TRK003002", "in_transit")
    create_shipment_tracking(cur, tid, str(item1c["id"]), "TRK003003", "in_transit")

    # Billing — sent (awaiting payment)
    b1 = create_billing(cur, tid, str(cust1["id"]), str(con1["id"]), str(pl1["id"]),
                        "INV-B-001", 3, 4.0, 50.0, 1580.0, "unpaid",
                        str(admin["id"]), due_date=eta + timedelta(days=7))

    print(f"  container: {con1['id']} (in_transit)")
    return {"tenant": tenant, "admin": admin, "customers": [cust1]}


def main() -> None:
    print("Connecting to database...")
    conn = _connect()

    try:
        with conn.cursor() as cur:
            # Seed data is inserted as the superuser / DB owner, bypassing RLS.
            # In production, use the logistics_app role and set app.current_tenant_id.
            result_a = seed_tenant_a(cur)
            result_b = seed_tenant_b(cur)

        conn.commit()
        print("\n=== Seed complete ===")
        print(f"Tenant A ({result_a['tenant']['company_name']}): {result_a['tenant']['id']}")
        print(f"Tenant B ({result_b['tenant']['company_name']}): {result_b['tenant']['id']}")
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
