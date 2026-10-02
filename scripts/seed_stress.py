"""Volume-simulation seed — adds ~200 containers across ~50 customers to the
Acme Shipping Ltd dev tenant, spanning the full container lifecycle and every
billing status, so the container/customer/billing list UIs can be exercised
under realistic production-scale volume (not just the 2-container curated
seed from scripts/seed.py).

Additive, not a replacement: run `python scripts/seed.py` (or `make stack`)
first. Targets Acme specifically because both LocalAuthProvider.tsx's dev
role-switcher and local_server.py's DEFAULT_TENANT_ID are hardcoded to it —
so the bulk data is immediately visible via the role switcher with no extra
Cognito setup.

Bumps Acme's subscription_tier to 'enterprise' so the metering container-cap
check (starter = 5/month) doesn't block further container creation from the
UI after this runs — see shared/tier_limits.py.

Safe to re-run: no-ops if the marker container (ACME9001) already exists.

Usage:
    DATABASE_HOST=localhost DATABASE_NAME=logistics \\
    DATABASE_USER=postgres DATABASE_PASSWORD=secret \\
    python scripts/seed_stress.py
"""

import random
import sys
from datetime import date, timedelta
from decimal import Decimal

from seed import (
    ACME_ADMIN_ID,
    ACME_CHINA_ID,
    ACME_NIGERIA_ID,
    ACME_TENANT_ID,
    _connect,
    _exec,
    create_billing,
    create_container,
    create_customer,
    create_manifest,
    create_packing_list,
    create_packing_list_item,
    create_payment,
    create_shipment_tracking,
)

random.seed(42)  # reproducible across re-runs (though re-runs no-op anyway)

CBM_RATE_USD = 45.0
EXCHANGE_RATE_NGN = 1550.0

FIRST_NAMES = [
    "Adaeze",
    "Bola",
    "Chinedu",
    "Damilola",
    "Efe",
    "Folake",
    "Gbenga",
    "Hauwa",
    "Ikechukwu",
    "Jumoke",
    "Kelechi",
    "Lola",
    "Muyiwa",
    "Ngozi",
    "Obinna",
    "Peace",
    "Quadri",
    "Rasheed",
    "Segun",
    "Tolu",
    "Uche",
    "Vivian",
    "Wale",
    "Yemisi",
    "Zainab",
    "Amara",
    "Bayo",
    "Chidinma",
    "Dapo",
    "Ebele",
    "Femi",
    "Gift",
    "Habiba",
    "Ifeoma",
    "Junaid",
    "Kemi",
    "Lekan",
    "Maryam",
    "Nnamdi",
    "Olamide",
    "Precious",
    "Qasim",
    "Ruth",
    "Sade",
    "Tobi",
    "Umar",
    "Victor",
    "Wumi",
    "Yakubu",
    "Zubair",
]
LAST_NAMES = [
    "Okafor",
    "Adeyemi",
    "Musa",
    "Eze",
    "Bello",
    "Suleiman",
    "Okoro",
    "Bakare",
    "Yusuf",
    "Chukwu",
    "Obi",
    "Nwankwo",
    "Nwosu",
    "Dada",
    "Asante",
    "Kalu",
    "Ibrahim",
    "Danjuma",
    "Okonkwo",
    "Balogun",
    "Onyekwere",
    "Abubakar",
    "Uduak",
    "Ojo",
    "Alabi",
    "Nnamani",
    "Okpara",
    "Idris",
    "Osei",
    "Etim",
    "Effiong",
    "Adisa",
    "Mohammed",
    "Chikodi",
    "Adeoye",
    "Nkemdirim",
    "Garba",
    "Anyanwu",
    "Ogundele",
    "Sanni",
    "Ekong",
    "Chukwuma",
    "Aliyu",
    "Owolabi",
    "Umeh",
    "Fashola",
    "Adebisi",
    "Ndukwe",
    "Tanko",
    "Igwe",
]
CITIES = [
    "Lagos",
    "Aba",
    "Kano",
    "Kaduna",
    "Enugu",
    "Onitsha",
    "Ibadan",
    "Port Harcourt",
    "Abuja",
    "Uyo",
    "Benin City",
    "Owerri",
]

GOODS = [
    "Electronic goods",
    "Clothing items",
    "Kitchen appliances",
    "Auto parts",
    "Fabric rolls",
    "Shoes",
    "Machinery parts",
    "Electronics",
    "Textiles",
    "Furniture",
    "Building materials",
    "Cosmetics",
    "Toys",
    "Phone accessories",
    "Generators",
    "Bags and luggage",
    "Plastic goods",
    "Hair products",
]

# (status, count) — sums to 200. Weighted toward the mid-pipeline stages so
# the list views show a realistic operational spread rather than a uniform one.
STATUS_COUNTS = [
    ("loading", 24),
    ("sealed", 16),
    ("in_transit", 40),
    ("arrived", 16),
    ("customs_clearance", 20),
    ("cleared", 30),
    ("at_warehouse", 34),
    ("fully_released", 16),
    ("cancelled", 4),
]

# Container statuses that have already "shipped" — eligible for billing.
_BILLABLE_STATUSES = {
    "in_transit",
    "arrived",
    "customs_clearance",
    "cleared",
    "at_warehouse",
    "fully_released",
}

_BILLING_WEIGHTS: dict[str, dict[str, float]] = {
    "in_transit": {"unpaid": 55, "partially_paid": 35, "paid": 10},
    "arrived": {"unpaid": 55, "partially_paid": 35, "paid": 10},
    "customs_clearance": {"unpaid": 50, "partially_paid": 35, "paid": 15},
    "cleared": {"unpaid": 20, "partially_paid": 40, "paid": 35, "overpaid": 3, "waived": 2},
    "at_warehouse": {"unpaid": 20, "partially_paid": 40, "paid": 35, "overpaid": 3, "waived": 2},
    "fully_released": {
        "paid": 55,
        "released_with_outstanding": 20,
        "partially_paid": 10,
        "overpaid": 8,
        "waived": 7,
    },
}

_invoice_seq = 0
_tracking_seq = 0


def _next_invoice_number() -> str:
    global _invoice_seq
    _invoice_seq += 1
    return f"INV-S-{_invoice_seq:04d}"


def _next_tracking_code() -> str:
    global _tracking_seq
    _tracking_seq += 1
    return f"TRKS{_tracking_seq:05d}"


def _dates_for_status(status: str, today: date) -> tuple[date | None, date | None, date | None]:
    """Return (ship_date, eta, actual_arrival) plausible for the given stage."""
    if status in ("loading", "cancelled"):
        return None, None, None
    if status == "sealed":
        ship = today - timedelta(days=random.randint(0, 3))
        return ship, ship + timedelta(days=random.randint(20, 30)), None
    if status == "in_transit":
        ship = today - timedelta(days=random.randint(5, 25))
        return ship, today + timedelta(days=random.randint(3, 20)), None
    if status == "arrived":
        ship = today - timedelta(days=random.randint(25, 35))
        arrival = today - timedelta(days=random.randint(0, 2))
        return ship, arrival - timedelta(days=random.randint(0, 2)), arrival
    if status == "customs_clearance":
        ship = today - timedelta(days=random.randint(28, 40))
        arrival = today - timedelta(days=random.randint(2, 6))
        return ship, arrival, arrival
    if status == "cleared":
        ship = today - timedelta(days=random.randint(30, 45))
        arrival = today - timedelta(days=random.randint(6, 12))
        return ship, arrival, arrival
    if status == "at_warehouse":
        ship = today - timedelta(days=random.randint(35, 55))
        arrival = today - timedelta(days=random.randint(12, 25))
        return ship, arrival, arrival
    if status == "fully_released":
        ship = today - timedelta(days=random.randint(60, 120))
        arrival = today - timedelta(days=random.randint(30, 55))
        return ship, arrival, arrival
    raise ValueError(f"unhandled status: {status}")


def _weighted_billing_status(container_status: str) -> str:
    weights = _BILLING_WEIGHTS[container_status]
    return random.choices(list(weights), weights=list(weights.values()), k=1)[0]


def _apply_payment(cur, billing: dict, billing_status: str, tid: str, recorded_by: str, payment_date: date) -> None:
    """Set amount_paid_ngn / released_with_outstanding and insert payment_record(s)
    consistent with billing_status, mirroring the pattern in scripts/seed.py."""
    total = billing["total_ngn"]
    if billing_status == "unpaid":
        return
    if billing_status == "partially_paid":
        amount = round(total * Decimal(str(round(random.uniform(0.2, 0.75), 2))), 2)
    elif billing_status == "paid":
        amount = total
    elif billing_status == "overpaid":
        amount = round(total * Decimal(str(round(random.uniform(1.05, 1.2), 2))), 2)
    elif billing_status == "waived":
        return  # status already set by the caller; no payment collected
    elif billing_status == "released_with_outstanding":
        amount = round(total * Decimal(str(round(random.uniform(0.3, 0.7), 2))), 2)
        cur.execute("UPDATE billing SET released_with_outstanding = TRUE WHERE id = %s", (billing["id"],))
    else:
        raise ValueError(f"unhandled billing status: {billing_status}")

    method = random.choice(["bank_transfer", "cash", "pos", "online"])
    create_payment(
        cur,
        str(billing["id"]),
        tid,
        amount,
        method,
        f"REF-S-{billing['invoice_number']}",
        payment_date,
        recorded_by,
    )
    cur.execute("UPDATE billing SET amount_paid_ngn = %s WHERE id = %s", (amount, billing["id"]))


def _build_customer_pool(cur, tid: str) -> list[dict]:
    names = list(zip(FIRST_NAMES, LAST_NAMES, strict=True))
    random.shuffle(names)
    customers = []
    for i, (first, last) in enumerate(names, start=1):
        name = f"{first} {last}"
        city = random.choice(CITIES)
        cust = create_customer(
            cur,
            tid,
            name,
            f"+2348090{i:06d}",
            f"cust{i:03d}@acmeshipping.com",
            f"{random.randint(1, 99)} {last} Street, {city}",
        )
        customers.append(cust)
    return customers


def _build_containers(cur, tid: str, china_id: str, nigeria_id: str, customers: list[dict]) -> dict[str, int]:
    today = date.today()
    statuses = []
    for status, count in STATUS_COUNTS:
        statuses.extend([status] * count)
    random.shuffle(statuses)

    tally: dict[str, int] = {}
    for idx, status in enumerate(statuses, start=1):
        tally[status] = tally.get(status, 0) + 1
        ship_date, eta, arrival = _dates_for_status(status, today)
        container = create_container(
            cur,
            tid,
            f"ACME9{idx:03d}",
            status,
            china_id,
            ship_date=ship_date,
            eta=eta,
            arrival=arrival,
        )
        cid = str(container["id"])

        if status == "cancelled":
            continue  # voided before cargo assigned — no manifest/packing lists

        num_customers = 1 if status in ("loading", "sealed") else random.randint(1, 3)
        picked = random.sample(customers, k=num_customers)
        pl_status = "pending_approval" if status in ("loading", "sealed") else "approved"
        verified_by = None if status in ("loading", "sealed") else nigeria_id

        total_cartons = 0
        total_weight = 0.0
        total_cbm = 0.0
        packing_lists = []
        for cust in picked:
            n_items = random.randint(1, 2)
            cartons = random.randint(2, 15)
            cbm = round(random.uniform(0.5, 4.0), 2)
            total_cartons += cartons
            total_cbm += cbm
            packing_lists.append((cust, cartons, cbm, n_items))
            total_weight += cbm * 180  # rough density for a plausible weight figure

        manifest = create_manifest(
            cur,
            tid,
            cid,
            len(picked),
            total_cartons,
            round(total_weight, 1),
            round(total_cbm, 2),
            verified_by,
        )
        mid = str(manifest["id"])

        for cust, cartons, cbm, n_items in packing_lists:
            pl = create_packing_list(cur, tid, cid, mid, str(cust["id"]), pl_status, china_id)
            per_item_cbm = round(cbm / n_items, 3)
            for item_idx in range(n_items):
                item = create_packing_list_item(
                    cur,
                    str(pl["id"]),
                    random.choice(GOODS),
                    f"ACME9{idx:03d}-{item_idx + 1}",
                    _next_tracking_code(),
                    round(random.uniform(10.0, 90.0), 1),
                    per_item_cbm,
                )
                tracking_status = {
                    "in_transit": "in_transit",
                    "arrived": "arrived_port",
                    "customs_clearance": "customs_clearance",
                    "cleared": "at_warehouse",
                    "at_warehouse": "ready_for_pickup",
                    "fully_released": "released",
                }.get(status, "at_warehouse")
                create_shipment_tracking(cur, tid, str(item["id"]), item["tracking_code"], tracking_status)

            if status in _BILLABLE_STATUSES:
                due_date = (eta or arrival or today) + timedelta(days=7)
                billing = create_billing(
                    cur,
                    tid,
                    str(cust["id"]),
                    cid,
                    str(pl["id"]),
                    _next_invoice_number(),
                    cartons,
                    cbm,
                    CBM_RATE_USD,
                    EXCHANGE_RATE_NGN,
                    "unpaid",
                    nigeria_id,
                    due_date=due_date,
                )
                billing_status = _weighted_billing_status(status)
                if billing_status != "unpaid":
                    cur.execute("UPDATE billing SET status = %s WHERE id = %s", (billing_status, billing["id"]))
                payment_date = min(today, due_date) - timedelta(days=random.randint(0, 5))
                _apply_payment(cur, billing, billing_status, tid, nigeria_id, payment_date)

    return tally


def main() -> None:
    print("Connecting to database...")
    conn = _connect()
    try:
        with conn.cursor() as cur:
            existing = _exec(
                cur,
                "SELECT id FROM container WHERE tenant_id = %s AND container_number = %s",
                (ACME_TENANT_ID, "ACME9001"),
            )
            if existing:
                print(
                    "Stress data already present (ACME9001 exists) — skipping. "
                    "Run `make stack` first if you want a clean re-seed."
                )
                return

            admin_rows = _exec(cur, "SELECT id FROM tenant_user WHERE id = %s", (ACME_ADMIN_ID,))
            if not admin_rows:
                print("Acme Shipping Ltd not seeded yet — run `python scripts/seed.py` first.", file=sys.stderr)
                sys.exit(1)

            print(
                "Bumping Acme to 'enterprise' tier so the container-cap metering "
                "check doesn't block further UI-driven container creation..."
            )
            cur.execute("UPDATE tenant SET subscription_tier = 'enterprise' WHERE id = %s", (ACME_TENANT_ID,))

            print("Creating 50 customers...")
            customers = _build_customer_pool(cur, ACME_TENANT_ID)

            print("Creating 200 containers across the full lifecycle + billing states...")
            tally = _build_containers(cur, ACME_TENANT_ID, ACME_CHINA_ID, ACME_NIGERIA_ID, customers)

        conn.commit()
        print("\n=== Stress seed complete ===")
        print(f"Customers: {len(customers)}")
        print("Containers by status:")
        for status, _ in STATUS_COUNTS:
            print(f"  {status:20s} {tally.get(status, 0)}")
        print(
            "\nLog into Acme Shipping Ltd via the dev role switcher "
            "(tenant_admin / china_office_staff / nigeria_office_staff / warehouse_attendant) "
            "to browse the populated container, customer, and billing list views."
        )

    except Exception as exc:
        conn.rollback()
        print(f"\nStress seed FAILED: {exc}", file=sys.stderr)
        raise
    finally:
        conn.close()


if __name__ == "__main__":
    main()
