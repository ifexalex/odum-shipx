"""Database access layer for the Excel import/export service.

Pure SQL — no business logic.
All queries use parameterized statements (%s / %(name)s) — never f-strings on
user-supplied values.
"""
import logging

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


# ---------------------------------------------------------------------------
# Packing list export data
# ---------------------------------------------------------------------------


def get_packing_list_for_export(tenant_id: str, pl_id: str) -> dict | None:
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


def get_items_for_packing_list(tenant_id: str, pl_id: str) -> list[dict]:
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


def get_manifest_for_export(tenant_id: str, manifest_id: str) -> dict | None:
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


def get_items_for_manifest(tenant_id: str, container_id: str) -> list[dict]:
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


def get_billing_for_export(tenant_id: str, billing_id: str) -> dict | None:
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


def get_billing_for_container_export(tenant_id: str, container_id: str) -> list[dict]:
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


def get_container_by_id(tenant_id: str, container_id: str) -> dict | None:
    rows = execute_with_tenant(
        tenant_id,
        "SELECT id, container_number FROM container WHERE tenant_id = %s AND id = %s LIMIT 1",
        (tenant_id, container_id),
    )
    return rows[0] if rows else None


# ---------------------------------------------------------------------------
# Import helpers
# ---------------------------------------------------------------------------


def get_tenant_customers(tenant_id: str) -> list[dict]:
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


def get_existing_tracking_code(
    tenant_id: str, customer_id: str, received_date
) -> str | None:
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


def create_packing_list(tenant_id: str, data: dict) -> dict:
    return execute_write_with_tenant(
        tenant_id,
        """
        INSERT INTO packing_list (tenant_id, container_id, customer_id, status, created_by)
        VALUES (%(tenant_id)s, %(container_id)s, %(customer_id)s, 'draft', %(created_by)s)
        RETURNING *
        """,
        data,
    )


def insert_packing_list_items(tenant_id: str, items: list[dict]) -> None:
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
