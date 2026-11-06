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
from datetime import UTC, date, datetime
from typing import Any

from shared.db import execute_with_tenant, execute_write_with_tenant, execute_write_with_tenant_many
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


def get_customer_contact(tenant_id: str, customer_id: str) -> dict[str, Any] | None:
    """Contact info for enqueue_notifications — name/phone/email/whatsapp plus
    the portal user's locale (defaults to 'en' for customers without one).
    `user_id` (== tenant_user.id when the customer has a portal account, else
    NULL) is included so callers can also target the in-app customer
    notification bell via shared.staff_notifications.notify_staff — same
    shape as tracking/repository.py::get_customers_for_container."""
    rows = execute_with_tenant(
        tenant_id,
        """
        SELECT c.id::text AS id, c.user_id, c.name, c.phone, c.email, c.whatsapp,
            COALESCE(tu.locale, 'en') AS locale
        FROM customer c
        LEFT JOIN tenant_user tu ON tu.id = c.user_id AND tu.tenant_id = c.tenant_id
        WHERE c.tenant_id = %s AND c.id = %s AND c.anonymised_at IS NULL
        LIMIT 1
        """,
        (tenant_id, customer_id),
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


def get_next_pl_reference(tenant_id: str) -> str:
    """Generate the next PL reference for this tenant in PL-YYYYMMDD-NNN format."""
    date_str = datetime.now(tz=UTC).strftime("%Y%m%d")
    prefix = f"PL-{date_str}-"
    rows = execute_with_tenant(
        tenant_id,
        "SELECT COUNT(*) AS cnt FROM packing_list WHERE tenant_id = %s AND reference LIKE %s",
        (tenant_id, prefix + "%"),
    )
    seq = (int(rows[0]["cnt"]) + 1) if rows else 1
    return f"{prefix}{seq:03d}"


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
        INSERT INTO packing_list (
            tenant_id, container_id, customer_id, status, created_by, reference,
            loading_date, delivery_date, arrival_warehouse_id
        )
        VALUES (
            %(tenant_id)s, %(container_id)s, %(customer_id)s, 'draft', %(created_by)s, %(reference)s,
            %(loading_date)s, %(delivery_date)s, %(arrival_warehouse_id)s
        )
        RETURNING *
        """,
        {
            "loading_date": data.get("loading_date"),
            "delivery_date": data.get("delivery_date"),
            "arrival_warehouse_id": data.get("arrival_warehouse_id"),
            **data,
        },
    )


def set_packing_list_warehouse(tenant_id: str, pl_id: str, warehouse_id: str | None) -> dict[str, Any] | None:
    return execute_write_with_tenant(
        tenant_id,
        """
        UPDATE packing_list
        SET arrival_warehouse_id = %(warehouse_id)s, updated_at = NOW()
        WHERE tenant_id = %(tenant_id)s AND id = %(id)s
        RETURNING *
        """,
        {"tenant_id": tenant_id, "id": pl_id, "warehouse_id": warehouse_id},
    )


def set_packing_list_dates(tenant_id: str, pl_id: str, loading_date: Any, delivery_date: Any) -> dict[str, Any] | None:
    return execute_write_with_tenant(
        tenant_id,
        """
        UPDATE packing_list
        SET loading_date = %(loading_date)s, delivery_date = %(delivery_date)s, updated_at = NOW()
        WHERE tenant_id = %(tenant_id)s AND id = %(id)s
        RETURNING *
        """,
        {"tenant_id": tenant_id, "id": pl_id, "loading_date": loading_date, "delivery_date": delivery_date},
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
                received_date, declared_value_usd, package_unit, bale_type
            ) VALUES (
                %(packing_list_id)s, %(description)s, %(weight_dispatch_kg)s,
                %(weight_actual_kg)s, %(carton_tag)s, %(tracking_code)s, %(cbm)s,
                %(length_cm)s, %(width_cm)s, %(height_cm)s, %(received_date)s,
                %(declared_value_usd)s, %(package_unit)s, %(bale_type)s
            ) RETURNING *
            """,
            item,
        )
        results.append(row)
    return results


def get_packing_list_by_id(tenant_id: str, pl_id: str) -> dict[str, Any] | None:
    # Ground-truth fix: this query never joined `container`, so the detail
    # response had no container_number/container_status at all — the customer
    # shipment-detail page (MyShipmentDetail.tsx) fell back to a fictional
    # default status ('active' → "Preparing") regardless of the container's
    # real state (e.g. at_warehouse / ready for pickup). list_packing_lists()
    # already carries this same join; mirror it here.
    rows = execute_with_tenant(
        tenant_id,
        """
        SELECT pl.*,
               c.name  AS customer_name,
               c.phone AS customer_phone,
               co.container_number,
               co.status AS container_status,
               w.name AS arrival_warehouse_name,
               tu_a.full_name AS approved_by_name,
               tu_r.full_name AS rejected_by_name,
               tu_c.full_name AS created_by_name
        FROM packing_list pl
        LEFT JOIN customer c
               ON c.id = pl.customer_id AND c.tenant_id = pl.tenant_id
        LEFT JOIN container co
               ON co.id = pl.container_id AND co.tenant_id = pl.tenant_id
        LEFT JOIN warehouse w
               ON w.id = pl.arrival_warehouse_id AND w.tenant_id = pl.tenant_id
        LEFT JOIN tenant_user tu_a
               ON tu_a.id = pl.approved_by AND tu_a.tenant_id = pl.tenant_id
        LEFT JOIN tenant_user tu_r
               ON tu_r.id = pl.rejected_by AND tu_r.tenant_id = pl.tenant_id
        LEFT JOIN tenant_user tu_c
               ON tu_c.id = pl.created_by AND tu_c.tenant_id = pl.tenant_id
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


def _packing_list_predicates(tenant_id: str, filters: dict[str, Any]) -> tuple[str, str, dict[str, Any]]:
    """Build the shared WHERE predicate for listing and counting packing lists.

    Extracted so the list query and its total count can never drift apart —
    a count computed from a different predicate than the rows it describes is
    worse than no count at all.

    Returns (where_clause, q_clause, params). `q_clause` is separate because it
    references joined columns (customer, container) and so must be appended to
    the joined inner query rather than to the pl-prefixed conditions.
    """
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

    q_clause = ""
    if filters.get("q"):
        # Matches the search box's own placeholder: reference, customer name,
        # container. `reference` was missing, so searching for a PL number
        # found nothing even once the filter was wired up.
        q_clause = " AND (cu.name ILIKE %(q)s OR c.container_number ILIKE %(q)s OR pl.reference ILIKE %(q)s)"
        extra["q"] = f"%{filters['q']}%"

    where_clause = " AND ".join(f"pl.{cond}" for cond in conditions)
    return where_clause, q_clause, extra


def count_packing_lists(tenant_id: str, filters: dict[str, Any]) -> int:
    """Total rows matching the same filters as list_packing_lists.

    Powers "showing 50 of 68". Without a total the UI could only show a page of
    50 with no hint that more existed, which read as "this container has 50
    packing lists" when it had 68.
    """
    where_clause, q_clause, params = _packing_list_predicates(tenant_id, filters)
    rows = execute_with_tenant(
        tenant_id,
        f"""
        SELECT COUNT(*)::int AS total
        FROM packing_list pl
        LEFT JOIN container c  ON c.id  = pl.container_id AND c.tenant_id  = pl.tenant_id
        LEFT JOIN customer  cu ON cu.id = pl.customer_id  AND cu.tenant_id = pl.tenant_id
        WHERE {where_clause}{q_clause}
        """,
        params,
    )
    return int(rows[0]["total"]) if rows else 0


def list_packing_lists(
    tenant_id: str,
    filters: dict[str, Any],
    limit: int = 50,
    cursor: dict[str, Any] | None = None,
) -> tuple[list[dict[str, Any]], str | None, bool]:
    where_clause, q_clause, extra = _packing_list_predicates(tenant_id, filters)

    # Wrap the joined query in a subquery so build_paginated_query's cursor
    # condition (AND id > ...) references the outer unambiguous columns instead
    # of clashing with container.id in the inner JOIN.
    inner = f"""
        SELECT pl.*,
               c.container_number,
               c.status AS container_status,
               c.estimated_arrival_date AS container_eta,
               c.vessel_name,
               c.voyage_number,
               cu.name AS customer_name,
               cu.phone AS customer_phone,
               w.name AS arrival_warehouse_name,
               COALESCE(agg.carton_count, 0)    AS carton_count,
               COALESCE(agg.package_count, 0)   AS package_count,
               COALESCE(agg.package_mix, '{{}}'::jsonb) AS package_mix,
               COALESCE(agg.total_cbm, 0)       AS total_cbm,
               COALESCE(agg.total_weight_kg, 0) AS total_weight_kg
        FROM packing_list pl
        LEFT JOIN container c
               ON c.id = pl.container_id AND c.tenant_id = pl.tenant_id
        LEFT JOIN customer cu
               ON cu.id = pl.customer_id AND cu.tenant_id = pl.tenant_id
        LEFT JOIN warehouse w
               ON w.id = pl.arrival_warehouse_id AND w.tenant_id = pl.tenant_id
        LEFT JOIN (
            -- Two levels on purpose: sum quantities per unit first, then fold
            -- those into one row. jsonb_object_agg over the raw items would
            -- collapse duplicate keys (two 'bale' rows -> one), silently
            -- under-reporting the mix.
            SELECT packing_list_id,
                   -- ::int matters. COUNT() came back as a bigint (a JSON
                   -- number), but SUM() over numeric comes back as Decimal and
                   -- serialises as a *string* — the frontend then concatenated
                   -- counts instead of adding them ("0" + "1" + "13" ...).
                   SUM(row_count)::int                 AS carton_count,
                   SUM(cbm_sum)                        AS total_cbm,
                   SUM(weight_sum)                     AS total_weight_kg,
                   -- Packages keyed by unit, e.g. 2 bale + 16 bag. A row is no
                   -- longer one carton (migration 040 made it a bulk quantity),
                   -- so a row count alone cannot tell staff whether they are
                   -- looking at bales or cartons. Rows with no unit fall under
                   -- 'unspecified' rather than dropping out of the totals.
                   jsonb_object_agg(unit, qty)         AS package_mix,
                   SUM(qty)::int                       AS package_count
            FROM (
                SELECT packing_list_id,
                       COALESCE(NULLIF(package_unit, ''), 'unspecified') AS unit,
                       COUNT(*)                                          AS row_count,
                       COALESCE(SUM(cbm), 0)                             AS cbm_sum,
                       COALESCE(SUM(weight_actual_kg), 0)                AS weight_sum,
                       COALESCE(SUM(COALESCE(quantity, 1)), 0)::int      AS qty
                FROM packing_list_item
                GROUP BY packing_list_id, COALESCE(NULLIF(package_unit, ''), 'unspecified')
            ) per_unit
            GROUP BY packing_list_id
        ) agg ON agg.packing_list_id = pl.id
        WHERE {where_clause}{q_clause}
    """
    base = f"SELECT * FROM ({inner}) AS t WHERE 1=1"
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
        "UPDATE packing_list SET updated_at = NOW() WHERE tenant_id = %(tenant_id)s AND id = %(id)s RETURNING id",
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


# ---------------------------------------------------------------------------
# Bulk operations
# ---------------------------------------------------------------------------


def get_packing_lists_by_ids(tenant_id: str, ids: list[str]) -> list[dict[str, Any]]:
    """Fetch multiple packing lists by ID in one query."""
    if not ids:
        return []
    rows = execute_with_tenant(
        tenant_id,
        """
        SELECT pl.*,
               cu.name AS customer_name
        FROM packing_list pl
        LEFT JOIN customer cu ON cu.id = pl.customer_id AND cu.tenant_id = pl.tenant_id
        WHERE pl.tenant_id = %s AND pl.id = ANY(%s::uuid[])
        """,
        (tenant_id, ids),
    )
    return list(rows)


def bulk_set_status(tenant_id: str, ids: list[str], status: str, actor_id: str) -> list[dict[str, Any]]:
    """Set status (+ the matching actor column) on multiple packing lists atomically.

    Only the transitions the bulk endpoints actually perform are allowed. This
    used to branch `if approved / else rejected`, which silently coerced *any*
    other status to 'rejected' — passing 'pending_approval' marked the rows
    rejected instead. Unknown statuses now raise rather than guessing.
    """
    if not ids:
        return []

    if status == "approved":
        set_clause = "status = 'approved', approved_by = %(actor_id)s"
    elif status == "rejected":
        set_clause = "status = 'rejected', rejected_by = %(actor_id)s"
    elif status == "pending_approval":
        # Submitting for review records no actor column — approved_by /
        # rejected_by belong to the reviewer, who hasn't acted yet.
        set_clause = "status = 'pending_approval'"
    else:
        raise ValueError(f"bulk_set_status does not support status: {status}")

    rows = execute_write_with_tenant_many(
        tenant_id,
        f"""
        UPDATE packing_list
        SET {set_clause},
            updated_at = NOW()
        WHERE tenant_id = %(tenant_id)s AND id = ANY(%(ids)s::uuid[])
        RETURNING *
        """,
        {"tenant_id": tenant_id, "ids": ids, "actor_id": actor_id},
    )
    return list(rows)
