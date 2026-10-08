"""Database access layer for the Excel import/export service.

Pure SQL — no business logic.
All queries use parameterized statements (%s / %(name)s) — never f-strings on
user-supplied values.
"""
import logging
from typing import Any

from shared.db import execute_with_tenant, execute_write_with_tenant
from shared.tenant_context import PLATFORM_TENANT_ID

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Tenant / branding helpers
# ---------------------------------------------------------------------------


def get_tenant_display_name(tenant_id: str) -> str:
    """Return company_display_name from branding_config, else company_name."""
    rows = execute_with_tenant(
        PLATFORM_TENANT_ID,
        "SELECT company_name, branding_config FROM tenant WHERE id = %s LIMIT 1",
        (tenant_id,),
    )
    if not rows:
        return ""
    row = rows[0]
    branding = row.get("branding_config") or {}
    if isinstance(branding, dict):
        display = branding.get("company_display_name")
        if display:
            return str(display)
    return str(row.get("company_name") or "")


def get_tenant_short(tenant_id: str) -> str:
    rows = execute_with_tenant(
        PLATFORM_TENANT_ID,
        "SELECT company_name FROM tenant WHERE id = %s LIMIT 1",
        (tenant_id,),
    )
    if not rows:
        return "UNK"
    company_name = rows[0].get("company_name") or "UNK"
    short = "".join(c for c in company_name.upper() if c.isalpha())[:3]
    return short.ljust(3, "X")


def get_tenant_destination_country(tenant_id: str) -> str | None:
    """Return the tenant's destination_country, used to pick a phone dial code."""
    rows = execute_with_tenant(
        PLATFORM_TENANT_ID,
        "SELECT destination_country FROM tenant WHERE id = %s LIMIT 1",
        (tenant_id,),
    )
    return rows[0].get("destination_country") if rows else None


# ---------------------------------------------------------------------------
# Packing list export data
# ---------------------------------------------------------------------------


def get_packing_list_for_export(tenant_id: str, pl_id: str) -> dict[str, Any] | None:
    """Return packing list row with customer_name and container_number."""
    rows = execute_with_tenant(
        tenant_id,
        """
        SELECT pl.*,
               c.name              AS customer_name,
               co.container_number AS container_number
        FROM packing_list pl
        LEFT JOIN customer  c  ON c.id  = pl.customer_id  AND c.tenant_id  = pl.tenant_id
        LEFT JOIN container co ON co.id = pl.container_id AND co.tenant_id = pl.tenant_id
        WHERE pl.tenant_id = %s AND pl.id = %s
        LIMIT 1
        """,
        (tenant_id, pl_id),
    )
    return rows[0] if rows else None


def get_items_for_packing_list(tenant_id: str, pl_id: str) -> list[dict[str, Any]]:
    """Return all items for a packing list (join enforces tenant scope)."""
    return execute_with_tenant(
        tenant_id,
        """
        SELECT pli.*
        FROM packing_list_item pli
        JOIN packing_list pl ON pl.id = pli.packing_list_id
        WHERE pl.tenant_id = %s AND pl.id = %s
        ORDER BY pli.carton_tag ASC
        """,
        (tenant_id, pl_id),
    )


# ---------------------------------------------------------------------------
# Manifest export data
# ---------------------------------------------------------------------------


def get_manifest_for_export(tenant_id: str, manifest_id: str) -> dict[str, Any] | None:
    rows = execute_with_tenant(
        tenant_id,
        """
        SELECT m.*, co.container_number
        FROM manifest m
        LEFT JOIN container co ON co.id = m.container_id AND co.tenant_id = m.tenant_id
        WHERE m.tenant_id = %s AND m.id = %s
        LIMIT 1
        """,
        (tenant_id, manifest_id),
    )
    return rows[0] if rows else None


def get_items_for_manifest(tenant_id: str, container_id: str) -> list[dict[str, Any]]:
    """Return all packing list items for a container with customer_name."""
    return execute_with_tenant(
        tenant_id,
        """
        SELECT pli.*, c.name AS customer_name
        FROM packing_list_item pli
        JOIN packing_list pl ON pl.id = pli.packing_list_id
        JOIN customer c ON c.id = pl.customer_id AND c.tenant_id = pl.tenant_id
        WHERE pl.tenant_id = %s AND pl.container_id = %s
        ORDER BY c.name ASC, pli.carton_tag ASC
        """,
        (tenant_id, container_id),
    )


# ---------------------------------------------------------------------------
# Billing export data
# ---------------------------------------------------------------------------


def get_misc_charges_for_export(tenant_id: str, billing_id: str) -> list[dict[str, Any]]:
    """misc_charge has no RLS (no tenant_id column) — scoped via billing_id,
    same posture as services/billing/repository.py::get_misc_charges().
    """
    return execute_with_tenant(
        tenant_id,
        "SELECT description, amount_ngn FROM misc_charge WHERE billing_id = %s ORDER BY created_at ASC",
        (billing_id,),
    )


def get_billing_for_export(tenant_id: str, billing_id: str) -> dict[str, Any] | None:
    """Return billing row with customer_name, container_number, and aggregated extras."""
    rows = execute_with_tenant(
        tenant_id,
        """
        SELECT b.*,
               cu.name              AS customer_name,
               co.container_number  AS container_number,
               COALESCE((
                   SELECT SUM(cl.carryover_amount_ngn)
                   FROM carryover_ledger cl
                   WHERE cl.tenant_id         = b.tenant_id
                     AND cl.target_billing_id = b.id
                     AND cl.status            = 'applied'
               ), 0) AS carryover_ngn,
               COALESCE((
                   SELECT SUM(sfl.amount_ngn)
                   FROM storage_fee_log sfl
                   WHERE sfl.tenant_id  = b.tenant_id
                     AND sfl.billing_id = b.id
               ), 0) AS storage_fees_ngn
        FROM billing b
        LEFT JOIN customer  cu ON cu.id = b.customer_id  AND cu.tenant_id = b.tenant_id
        LEFT JOIN container co ON co.id = b.container_id AND co.tenant_id = b.tenant_id
        WHERE b.tenant_id = %s AND b.id = %s
        LIMIT 1
        """,
        (tenant_id, billing_id),
    )
    if rows:
        row = dict(rows[0])
        row["adjustments_ngn"] = 0
        return row
    return None


def get_billing_for_container_export(tenant_id: str, container_id: str) -> list[dict[str, Any]]:
    """Return all billing rows for a container with per-row aggregated extras."""
    rows = execute_with_tenant(
        tenant_id,
        """
        SELECT b.*,
               cu.name              AS customer_name,
               co.container_number  AS container_number,
               COALESCE((
                   SELECT SUM(cl.carryover_amount_ngn)
                   FROM carryover_ledger cl
                   WHERE cl.tenant_id         = b.tenant_id
                     AND cl.target_billing_id = b.id
                     AND cl.status            = 'applied'
               ), 0) AS carryover_ngn,
               COALESCE((
                   SELECT SUM(sfl.amount_ngn)
                   FROM storage_fee_log sfl
                   WHERE sfl.tenant_id  = b.tenant_id
                     AND sfl.billing_id = b.id
               ), 0) AS storage_fees_ngn
        FROM billing b
        LEFT JOIN customer  cu ON cu.id = b.customer_id  AND cu.tenant_id = b.tenant_id
        LEFT JOIN container co ON co.id = b.container_id AND co.tenant_id = b.tenant_id
        WHERE b.tenant_id    = %s
          AND b.container_id = %s
        ORDER BY cu.name ASC
        """,
        (tenant_id, container_id),
    )
    result = []
    for row in rows:
        r = dict(row)
        r["adjustments_ngn"] = 0
        result.append(r)
    return result


def get_container_by_id(tenant_id: str, container_id: str) -> dict[str, Any] | None:
    rows = execute_with_tenant(
        tenant_id,
        "SELECT id, container_number FROM container WHERE tenant_id = %s AND id = %s LIMIT 1",
        (tenant_id, container_id),
    )
    return rows[0] if rows else None


def get_release_note_for_pdf(tenant_id: str, note_id: str) -> dict[str, Any] | None:
    """Return a release_note row joined with customer, container, billing, and
    warehouse for PDF export.

    Ground-truth fix: aliases total_cartons AS carton_count too — the PDF
    generator (export_release_note_pdf.py) reads note["carton_count"], but
    this query previously only returned total_cartons, so the Carton Count
    row on every printed release note always rendered empty.

    Ground-truth fix: selects b.invoice_number (not b.reference_number). The
    billing table has never had a reference_number column, so this query
    raised UndefinedColumn on every call — GET /v1/release-notes/{id}/pdf
    has never worked. Same bug class as the storage_fees_ngn defect in
    services/payment_release/repository.py: a raw-SQL column that no test
    catches because the unit suite mocks execute_with_tenant entirely.
    """
    rows = execute_with_tenant(
        tenant_id,
        """
        SELECT rn.*,
               rn.total_cartons     AS carton_count,
               cu.name              AS customer_name,
               cu.phone             AS customer_phone,
               cont.container_number,
               b.invoice_number     AS billing_reference,
               b.total_ngn          AS billing_total_ngn,
               b.amount_paid_ngn    AS billing_amount_paid_ngn,
               b.balance_ngn        AS billing_balance_ngn,
               b.status             AS payment_status,
               w.name               AS warehouse_name,
               w.address            AS warehouse_address,
               w.city               AS warehouse_city,
               w.state              AS warehouse_state,
               pr.receipt_number    AS receipt_number
        FROM release_note rn
        LEFT JOIN customer  cu   ON cu.id   = rn.customer_id  AND cu.tenant_id  = rn.tenant_id
        LEFT JOIN container cont ON cont.id  = rn.container_id AND cont.tenant_id = rn.tenant_id
        LEFT JOIN billing   b    ON b.id     = rn.billing_id
        LEFT JOIN warehouse w    ON w.id     = rn.warehouse_id
        LEFT JOIN payment_record pr ON pr.id = rn.payment_record_id
        WHERE rn.tenant_id = %s AND rn.id = %s
        LIMIT 1
        """,
        (tenant_id, note_id),
    )
    return rows[0] if rows else None


def get_payment_for_receipt_pdf(tenant_id: str, payment_id: str) -> dict[str, Any] | None:
    """Return a payment_record row joined with billing, customer, and
    warehouse for the cash receipt PDF export.
    """
    rows = execute_with_tenant(
        tenant_id,
        """
        SELECT p.*,
               b.invoice_number    AS billing_reference,
               b.customer_id       AS billing_customer_id,
               cu.name             AS customer_name,
               cu.phone            AS customer_phone,
               cu.address          AS customer_address,
               w.name              AS warehouse_name,
               w.address           AS warehouse_address
        FROM payment_record p
        LEFT JOIN billing  b  ON b.id  = p.billing_id
        LEFT JOIN customer cu ON cu.id = b.customer_id AND cu.tenant_id = p.tenant_id
        LEFT JOIN warehouse w ON w.id  = p.warehouse_id
        WHERE p.tenant_id = %s AND p.id = %s
        LIMIT 1
        """,
        (tenant_id, payment_id),
    )
    return rows[0] if rows else None


def get_customer_id_for_user(tenant_id: str, user_id: str) -> str | None:
    """Return the customer.id (as str) for the given user_id, or None."""
    rows = execute_with_tenant(
        tenant_id,
        "SELECT id FROM customer WHERE tenant_id = %s AND user_id = %s LIMIT 1",
        (tenant_id, user_id),
    )
    return str(rows[0]["id"]) if rows else None


def get_tenant_branding(tenant_id: str) -> dict[str, Any]:
    """Return branding_config JSONB for a tenant (PLATFORM scope)."""
    rows = execute_with_tenant(
        PLATFORM_TENANT_ID,
        "SELECT company_name, branding_config FROM tenant WHERE id = %s LIMIT 1",
        (tenant_id,),
    )
    if not rows:
        return {}
    row = rows[0]
    branding: dict[str, Any] = row.get("branding_config") or {}
    branding.setdefault("company_name", row.get("company_name") or "")
    return branding


# ---------------------------------------------------------------------------
# Import helpers
# ---------------------------------------------------------------------------


def get_tenant_customers(tenant_id: str) -> list[dict[str, Any]]:
    """Return all customers for this tenant (id, name)."""
    return execute_with_tenant(
        tenant_id,
        "SELECT id, name FROM customer WHERE tenant_id = %s ORDER BY name ASC",
        (tenant_id,),
    )


def get_next_carton_sequence(tenant_id: str, container_id: str) -> int:
    rows = execute_with_tenant(
        tenant_id,
        """
        SELECT COUNT(*) AS cnt
        FROM packing_list_item pli
        JOIN packing_list pl ON pl.id = pli.packing_list_id
        WHERE pl.tenant_id = %s AND pl.container_id = %s
        """,
        (tenant_id, container_id),
    )
    return int(rows[0]["cnt"]) + 1 if rows else 1


def get_existing_tracking_code(tenant_id: str, customer_id: str, received_date: Any) -> str | None:
    rows = execute_with_tenant(
        tenant_id,
        """
        SELECT pli.tracking_code
        FROM packing_list_item pli
        JOIN packing_list pl ON pl.id = pli.packing_list_id
        WHERE pl.tenant_id = %s AND pl.customer_id = %s AND pli.received_date = %s
        LIMIT 1
        """,
        (tenant_id, customer_id, received_date),
    )
    return rows[0]["tracking_code"] if rows else None


def get_next_tracking_sequence(tenant_id: str, date_prefix: str) -> int:
    like_pattern = date_prefix + "%"
    rows = execute_with_tenant(
        tenant_id,
        """
        SELECT COUNT(DISTINCT pli.tracking_code) AS cnt
        FROM packing_list_item pli
        JOIN packing_list pl ON pl.id = pli.packing_list_id
        WHERE pl.tenant_id = %s AND pli.tracking_code LIKE %s
        """,
        (tenant_id, like_pattern),
    )
    return int(rows[0]["cnt"]) + 1 if rows else 1


def get_next_pl_reference(tenant_id: str) -> str:
    """Generate the next PL reference for this tenant in PL-YYYYMMDD-NNN format.

    `packing_list.reference` is NOT NULL (migration 031) — every INSERT must
    supply one. Mirrors `services/packing_list/repository.py`'s helper of
    the same name/format so references stay consistent regardless of which
    flow created the packing list.
    """
    from datetime import UTC, datetime

    date_str = datetime.now(tz=UTC).strftime("%Y%m%d")
    prefix = f"PL-{date_str}-"
    rows = execute_with_tenant(
        tenant_id,
        "SELECT COUNT(*) AS cnt FROM packing_list WHERE tenant_id = %s AND reference LIKE %s",
        (tenant_id, prefix + "%"),
    )
    seq = (int(rows[0]["cnt"]) + 1) if rows else 1
    return f"{prefix}{seq:03d}"


def create_packing_list(tenant_id: str, data: dict[str, Any]) -> dict[str, Any] | None:
    """Insert an imported packing list, ready for review.

    Imported lists land in `pending_approval`, not `draft`. `draft` means "still
    being typed up" — but an imported file is complete on arrival, so there is
    nothing to finish before submitting it. Landing in draft forced staff to
    submit every row one at a time (a real manifest creates 68+) before bulk
    approve would touch them, which is what `wrong_status:draft` was reporting.

    The review gate itself is unchanged: pending_approval -> approved still
    requires a second person (see bulk_approve_packing_lists' self-approval
    guard).
    """
    return execute_write_with_tenant(
        tenant_id,
        """
        INSERT INTO packing_list (tenant_id, container_id, customer_id, status, created_by, reference)
        VALUES (
            %(tenant_id)s, %(container_id)s, %(customer_id)s,
            'pending_approval', %(created_by)s, %(reference)s
        )
        RETURNING *
        """,
        data,
    )


def insert_packing_list_items(tenant_id: str, items: list[dict[str, Any]]) -> None:
    for item in items:
        execute_write_with_tenant(
            tenant_id,
            """
            INSERT INTO packing_list_item (
                packing_list_id, description, weight_dispatch_kg, weight_actual_kg,
                carton_tag, tracking_code, cbm, length_cm, width_cm, height_cm,
                received_date
            ) VALUES (
                %(packing_list_id)s, %(description)s, %(weight_dispatch_kg)s,
                %(weight_actual_kg)s, %(carton_tag)s, %(tracking_code)s, %(cbm)s,
                %(length_cm)s, %(width_cm)s, %(height_cm)s, %(received_date)s
            )
            RETURNING id
            """,
            item,
        )


# ---------------------------------------------------------------------------
# Manifest import — find-or-create helpers
# ---------------------------------------------------------------------------


def find_container_by_number(tenant_id: str, container_number: str) -> dict[str, Any] | None:
    """Return the container row matching container_number, or None."""
    rows = execute_with_tenant(
        tenant_id,
        "SELECT * FROM container WHERE tenant_id = %s AND container_number = %s LIMIT 1",
        (tenant_id, container_number),
    )
    return rows[0] if rows else None


def create_container(tenant_id: str, data: dict[str, Any]) -> dict[str, Any] | None:
    """Create a new container. Fields are set only at creation — never called on re-import."""
    return execute_write_with_tenant(
        tenant_id,
        """
        INSERT INTO container (
            tenant_id, container_number, parcel_number, destination,
            ship_date, departure_date, estimated_arrival_date, created_by
        ) VALUES (
            %(tenant_id)s, %(container_number)s, %(parcel_number)s, %(destination)s,
            %(ship_date)s, %(departure_date)s, %(estimated_arrival_date)s, %(created_by)s
        )
        RETURNING *
        """,
        data,
    )


def find_customer_by_phone(tenant_id: str, phone: str) -> dict[str, Any] | None:
    """Return a customer matching the given phone (already normalized), or None."""
    rows = execute_with_tenant(
        tenant_id,
        "SELECT id, name, phone FROM customer WHERE tenant_id = %s AND phone = %s LIMIT 1",
        (tenant_id, phone),
    )
    return rows[0] if rows else None


def find_customer_by_name(tenant_id: str, name: str) -> dict[str, Any] | None:
    """Return a customer matching the given name exactly (case-insensitive), or None."""
    rows = execute_with_tenant(
        tenant_id,
        "SELECT id, name, phone FROM customer WHERE tenant_id = %s AND LOWER(name) = LOWER(%s) LIMIT 1",
        (tenant_id, name),
    )
    return rows[0] if rows else None


def create_customer(tenant_id: str, name: str, phone: str | None) -> dict[str, Any] | None:
    """Create a new customer with just name + phone (manifest import auto-creation)."""
    return execute_write_with_tenant(
        tenant_id,
        """
        INSERT INTO customer (tenant_id, name, phone)
        VALUES (%s, %s, %s)
        RETURNING id, name, phone
        """,
        (tenant_id, name, phone),
    )


def find_packing_list(tenant_id: str, container_id: str, customer_id: str) -> dict[str, Any] | None:
    """Return the packing list for (container, customer), or None."""
    rows = execute_with_tenant(
        tenant_id,
        """
        SELECT * FROM packing_list
        WHERE tenant_id = %s AND container_id = %s AND customer_id = %s
        LIMIT 1
        """,
        (tenant_id, container_id, customer_id),
    )
    return rows[0] if rows else None


def find_existing_item_by_delivery_note(
    tenant_id: str, packing_list_id: str, delivery_note_number: str, bale_no: str | None = None
) -> dict[str, Any] | None:
    """Return an existing packing_list_item matching this parcel, or None.

    Dedupe key for manifest re-imports: (delivery_note_number, bale_no) within
    a packing list.

    The bale number is part of the key, not decoration. One delivery note
    routinely covers several physical bales, each its own manifest row with its
    own bale number and weight — in the real STL409 export, customer
    HM(UNIQUEWEARS) has three bales (5, 4, 3) under delivery note 0079283.
    Keying on the delivery note alone treated those as re-imports of one parcel
    and dropped all but the first, losing real cargo on the very first import.

    Carton/bag rows carry no bale number; there the delivery note alone is the
    key, matched with IS NULL so those rows still dedupe correctly.
    """
    rows = execute_with_tenant(
        tenant_id,
        """
        SELECT pli.id
        FROM packing_list_item pli
        JOIN packing_list pl ON pl.id = pli.packing_list_id
        WHERE pl.tenant_id = %(tenant_id)s
          AND pli.packing_list_id = %(packing_list_id)s
          AND pli.delivery_note_number = %(delivery_note_number)s
          AND pli.bale_no IS NOT DISTINCT FROM %(bale_no)s
        LIMIT 1
        """,
        {
            "tenant_id": tenant_id,
            "packing_list_id": packing_list_id,
            "delivery_note_number": delivery_note_number,
            "bale_no": bale_no,
        },
    )
    return rows[0] if rows else None


def insert_manifest_items(tenant_id: str, items: list[dict[str, Any]]) -> None:
    """Insert manifest-import packing_list_item rows (bulk-quantity model)."""
    for item in items:
        execute_write_with_tenant(
            tenant_id,
            """
            INSERT INTO packing_list_item (
                packing_list_id, description, weight_actual_kg,
                carton_tag, tracking_code, cbm, received_date,
                delivery_note_number, quantity, quantity_raw, package_unit,
                bale_type, bale_no,
                original_receipt_number, delivery_zone, on_hold, hold_reason
            ) VALUES (
                %(packing_list_id)s, %(description)s, %(weight_actual_kg)s,
                %(carton_tag)s, %(tracking_code)s, %(cbm)s, %(received_date)s,
                %(delivery_note_number)s, %(quantity)s, %(quantity_raw)s, %(package_unit)s,
                %(bale_type)s, %(bale_no)s,
                %(original_receipt_number)s, %(delivery_zone)s, %(on_hold)s, %(hold_reason)s
            )
            RETURNING id
            """,
            item,
        )
