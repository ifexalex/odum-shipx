"""Database access layer for the Packing List service.

Pure SQL — no business logic.
All queries use parameterized statements (%s / %(name)s) — never f-strings on
user-supplied values.

Notes:
  - packing_list has RLS (tenant_id isolation).
  - packing_list_item has NO RLS; queries always join through packing_list to
    enforce tenant scope.
  - manifest and shipment_tracking have RLS.
"""

import logging
from datetime import date
from typing import Any

from shared.db import execute_with_tenant, execute_write_with_tenant
from shared.pagination import build_paginated_query, extract_page
from shared.tenant_context import PLATFORM_TENANT_ID

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Lookup helpers — tenant RLS scope
# ---------------------------------------------------------------------------


def get_container_by_id(tenant_id: str, container_id: str) -> dict[str, Any] | None:
    rows = execute_with_tenant(
        tenant_id,
        "SELECT id, container_number, status FROM container WHERE tenant_id = %s AND id = %s LIMIT 1",
        (tenant_id, container_id),
    )
    return rows[0] if rows else None


def get_customer_by_id(tenant_id: str, customer_id: str) -> dict[str, Any] | None:
    rows = execute_with_tenant(
        tenant_id,
        "SELECT id, name, user_id FROM customer WHERE tenant_id = %s AND id = %s LIMIT 1",
        (tenant_id, customer_id),
    )
    return rows[0] if rows else None


def get_customer_by_user_id(tenant_id: str, user_id: str) -> dict[str, Any] | None:
    rows = execute_with_tenant(
        tenant_id,
        "SELECT id, name, user_id FROM customer WHERE tenant_id = %s AND user_id = %s LIMIT 1",
        (tenant_id, user_id),
    )
    return rows[0] if rows else None


def get_tenant_short(tenant_id: str) -> str:
    """Return a 3-char uppercase prefix derived from the tenant's company name."""
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
# Sequence helpers (used for carton tags + tracking codes)
# ---------------------------------------------------------------------------


def get_next_carton_sequence(tenant_id: str, container_id: str) -> int:
    """Return 1-based next carton sequence for a container."""
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


def get_existing_tracking_code(tenant_id: str, customer_id: str, received_date: date) -> str | None:
    """Return an existing tracking code for (customer, date) if one already exists."""
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
    """Return 1-based next tracking code sequence for (tenant, date prefix).

    date_prefix e.g. "ACM-TRK-20240115" — safe alphanumeric chars only.
    """
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


# ---------------------------------------------------------------------------
# Packing list CRUD — tenant RLS scope
# ---------------------------------------------------------------------------


def create_packing_list(tenant_id: str, data: dict[str, Any]) -> dict[str, Any] | None:
    return execute_write_with_tenant(
        tenant_id,
        """
        INSERT INTO packing_list (tenant_id, container_id, customer_id, status, created_by)
        VALUES (%(tenant_id)s, %(container_id)s, %(customer_id)s, 'draft', %(created_by)s)
        RETURNING *
        """,
        data,
    )


def insert_packing_list_items(tenant_id: str, items: list[dict[str, Any]]) -> list[dict[str, Any] | None]:
    """Insert packing list items individually, returning all inserted rows."""
    results: list[dict[str, Any] | None] = []
    for item in items:
        row = execute_write_with_tenant(
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
            ) RETURNING *
            """,
            item,
        )
        results.append(row)
    return results


def get_packing_list_by_id(tenant_id: str, pl_id: str) -> dict[str, Any] | None:
    rows = execute_with_tenant(
        tenant_id,
        """
        SELECT pl.*, c.name AS customer_name
        FROM packing_list pl
        LEFT JOIN customer c ON c.id = pl.customer_id AND c.tenant_id = pl.tenant_id
        WHERE pl.tenant_id = %s AND pl.id = %s
        LIMIT 1
        """,
        (tenant_id, pl_id),
    )
    return rows[0] if rows else None


def get_items_by_packing_list(tenant_id: str, pl_id: str) -> list[dict[str, Any]]:
    """Fetch all items for a packing list. Uses tenant scope for DB set/reset."""
    return execute_with_tenant(
        tenant_id,
        "SELECT * FROM packing_list_item WHERE packing_list_id = %s ORDER BY created_at ASC",
        (pl_id,),
    )


def list_packing_lists(
    tenant_id: str,
    filters: dict[str, Any],
    limit: int = 50,
    cursor: dict[str, Any] | None = None,
) -> tuple[list[dict[str, Any]], str | None, bool]:
    conditions = ["tenant_id = %(tenant_id)s"]
    extra: dict[str, Any] = {"tenant_id": tenant_id}

    if filters.get("status"):
        conditions.append("status = %(status)s")
        extra["status"] = filters["status"]
    if filters.get("container_id"):
        conditions.append("container_id = %(container_id)s")
        extra["container_id"] = filters["container_id"]
    if filters.get("customer_id"):
        conditions.append("customer_id = %(customer_id)s")
        extra["customer_id"] = filters["customer_id"]
    if filters.get("created_after"):
        conditions.append("created_at >= %(created_after)s")
        extra["created_after"] = filters["created_after"]
    if filters.get("created_before"):
        conditions.append("created_at <= %(created_before)s")
        extra["created_before"] = filters["created_before"]

    base = f"SELECT * FROM packing_list WHERE {' AND '.join(conditions)}"
    query, params = build_paginated_query(base, cursor, limit, sort_field="created_at")
    params.update(extra)
    rows = execute_with_tenant(tenant_id, query, params)
    return extract_page(rows, limit)


def delete_items_by_packing_list(tenant_id: str, pl_id: str) -> None:
    """Delete all items for a packing list (used when replacing items on update)."""
    execute_write_with_tenant(
        tenant_id,
        """
        DELETE FROM packing_list_item
        WHERE packing_list_id IN (
            SELECT id FROM packing_list WHERE id = %s AND tenant_id = %s
        )
        RETURNING id
        """,
        (pl_id, tenant_id),
    )


# ---------------------------------------------------------------------------
# State transition updates — tenant RLS scope
# ---------------------------------------------------------------------------


def set_packing_list_status(tenant_id: str, pl_id: str, status: str) -> dict[str, Any] | None:
    """Generic status update for draft ↔ pending_approval transitions."""
    return execute_write_with_tenant(
        tenant_id,
        """
        UPDATE packing_list
        SET status = %(status)s, updated_at = NOW()
        WHERE tenant_id = %(tenant_id)s AND id = %(id)s
        RETURNING *
        """,
        {"status": status, "tenant_id": tenant_id, "id": pl_id},
    )


def approve_packing_list_row(tenant_id: str, pl_id: str, approved_by: str) -> dict[str, Any] | None:
    return execute_write_with_tenant(
        tenant_id,
        """
        UPDATE packing_list
        SET status = 'approved', approved_by = %(approved_by)s,
            approved_at = NOW(), updated_at = NOW()
        WHERE tenant_id = %(tenant_id)s AND id = %(id)s
        RETURNING *
        """,
        {"approved_by": approved_by, "tenant_id": tenant_id, "id": pl_id},
    )


def reject_packing_list_row(tenant_id: str, pl_id: str, rejected_by: str, approval_comments_json: str) -> dict[str, Any] | None:
    return execute_write_with_tenant(
        tenant_id,
        """
        UPDATE packing_list
        SET status = 'rejected', rejected_by = %(rejected_by)s,
            rejected_at = NOW(), approval_comments = %(comments)s::jsonb,
            updated_at = NOW()
        WHERE tenant_id = %(tenant_id)s AND id = %(id)s
        RETURNING *
        """,
        {
            "rejected_by": rejected_by,
            "comments": approval_comments_json,
            "tenant_id": tenant_id,
            "id": pl_id,
        },
    )


def link_manifest(tenant_id: str, pl_id: str, manifest_id: str) -> None:
    execute_write_with_tenant(
        tenant_id,
        """
        UPDATE packing_list
        SET manifest_id = %(manifest_id)s, updated_at = NOW()
        WHERE tenant_id = %(tenant_id)s AND id = %(id)s
        RETURNING id
        """,
        {"manifest_id": manifest_id, "tenant_id": tenant_id, "id": pl_id},
    )


def touch_updated_at(tenant_id: str, pl_id: str) -> None:
    execute_write_with_tenant(
        tenant_id,
        "UPDATE packing_list SET updated_at = NOW() " "WHERE tenant_id = %(tenant_id)s AND id = %(id)s RETURNING id",
        {"tenant_id": tenant_id, "id": pl_id},
    )


# ---------------------------------------------------------------------------
# Manifest — tenant RLS scope
# ---------------------------------------------------------------------------


def get_manifest_by_container(tenant_id: str, container_id: str) -> dict[str, Any] | None:
    rows = execute_with_tenant(
        tenant_id,
        "SELECT * FROM manifest WHERE tenant_id = %s AND container_id = %s LIMIT 1",
        (tenant_id, container_id),
    )
    return rows[0] if rows else None


def create_manifest(tenant_id: str, container_id: str) -> dict[str, Any] | None:
    return execute_write_with_tenant(
        tenant_id,
        """
        INSERT INTO manifest (tenant_id, container_id)
        VALUES (%(tenant_id)s, %(container_id)s)
        RETURNING *
        """,
        {"tenant_id": tenant_id, "container_id": container_id},
    )


def recalculate_manifest_totals(tenant_id: str, manifest_id: str) -> dict[str, Any] | None:
    """Recompute manifest aggregates from approved packing lists + their items."""
    return execute_write_with_tenant(
        tenant_id,
        """
        UPDATE manifest
        SET total_customers = sub.customers,
            total_cartons   = sub.cartons,
            total_weight_kg = sub.weight,
            total_cbm       = sub.cbm,
            updated_at      = NOW()
        FROM (
            SELECT
                COUNT(DISTINCT pl.customer_id)         AS customers,
                COUNT(pli.id)                          AS cartons,
                COALESCE(SUM(pli.weight_actual_kg), 0) AS weight,
                COALESCE(SUM(pli.cbm), 0)              AS cbm
            FROM packing_list pl
            JOIN packing_list_item pli ON pli.packing_list_id = pl.id
            WHERE pl.manifest_id = %(manifest_id)s
              AND pl.tenant_id   = %(tenant_id)s
              AND pl.status      = 'approved'
        ) sub
        WHERE manifest.id         = %(manifest_id)s
          AND manifest.tenant_id  = %(tenant_id)s
        RETURNING *
        """,
        {"manifest_id": manifest_id, "tenant_id": tenant_id},
    )


# ---------------------------------------------------------------------------
# Aliases for test compatibility
# ---------------------------------------------------------------------------


def list_packing_list_items(tenant_id: str, pl_id: str) -> list[dict[str, Any]]:
    """Alias for get_items_by_packing_list."""
    return get_items_by_packing_list(tenant_id, pl_id)


def update_packing_list_status(tenant_id: str, pl_id: str, status: str) -> dict[str, Any] | None:
    """Alias for set_packing_list_status."""
    return set_packing_list_status(tenant_id, pl_id, status)


# ---------------------------------------------------------------------------
# Shipment tracking — tenant RLS scope
# ---------------------------------------------------------------------------


def upsert_shipment_tracking(tenant_id: str, tracking_code: str) -> None:
    """Create a shipment_tracking row if it doesn't already exist."""
    execute_write_with_tenant(
        tenant_id,
        """
        INSERT INTO shipment_tracking (tenant_id, tracking_code)
        VALUES (%(tenant_id)s, %(tracking_code)s)
        ON CONFLICT (tenant_id, tracking_code) DO NOTHING
        RETURNING id
        """,
        {"tenant_id": tenant_id, "tracking_code": tracking_code},
    )
