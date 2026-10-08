"""Database access layer for the Tracking service.

Pure SQL — no business logic.
All queries use parameterized statements (%s / %(name)s) — never f-strings on
user-supplied values.

Notes:
  - container has RLS (tenant_id isolation).
  - shipment_tracking has RLS.
  - tracking_event has NO RLS — use PLATFORM_TENANT_ID scope.
  - packing_list_item has NO RLS — always join through packing_list for tenant scope.
"""

import logging
from typing import Any

from shared.db import execute_with_tenant, execute_write_with_tenant
from shared.pagination import build_paginated_query, extract_page
from shared.tenant_context import PLATFORM_TENANT_ID

logger = logging.getLogger(__name__)

# Allowlist for dynamic extra fields in container status update
_CONTAINER_EXTRA_FIELDS = frozenset({"ship_date", "actual_arrival_date", "notes"})


# ---------------------------------------------------------------------------
# Container CRUD — tenant RLS scope
# ---------------------------------------------------------------------------


def create_container(tenant_id: str, data: dict[str, Any]) -> dict[str, Any] | None:
    return execute_write_with_tenant(
        tenant_id,
        """
        INSERT INTO container (
            tenant_id, container_number, parcel_number, origin, destination,
            estimated_arrival_date, notes, created_by,
            vessel_name, voyage_number, shipping_line, seal_number, container_type,
            capacity_cbm, recommended_cbm
        ) VALUES (
            %(tenant_id)s, %(container_number)s, %(parcel_number)s,
            %(origin)s, %(destination)s, %(estimated_arrival_date)s,
            %(notes)s, %(created_by)s,
            %(vessel_name)s, %(voyage_number)s, %(shipping_line)s,
            %(seal_number)s, %(container_type)s,
            %(capacity_cbm)s, %(recommended_cbm)s
        ) RETURNING *
        """,
        data,
    )


def get_container_by_id(tenant_id: str, container_id: str) -> dict[str, Any] | None:
    rows = execute_with_tenant(
        tenant_id,
        """
        SELECT c.*,
               tu.full_name AS created_by_name,
               (SELECT COUNT(*) FROM packing_list pl
                WHERE pl.container_id = c.id AND pl.tenant_id = c.tenant_id) AS packing_list_count,
               (SELECT COUNT(*) FROM packing_list pl
                WHERE pl.container_id = c.id AND pl.tenant_id = c.tenant_id
                  AND pl.status = 'approved') AS approved_packing_list_count,
               (SELECT COALESCE(SUM(pli.cbm), 0)
                FROM packing_list_item pli
                JOIN packing_list pl2 ON pl2.id = pli.packing_list_id
                WHERE pl2.container_id = c.id AND pl2.tenant_id = c.tenant_id) AS total_cbm_packed
        FROM container c
        LEFT JOIN tenant_user tu ON tu.id = c.created_by AND tu.tenant_id = c.tenant_id
        WHERE c.tenant_id = %s AND c.id = %s LIMIT 1
        """,
        (tenant_id, container_id),
    )
    return rows[0] if rows else None


def list_containers(
    tenant_id: str,
    filters: dict[str, Any],
    limit: int = 50,
    cursor: dict[str, Any] | None = None,
    sort_field: str = "created_at",
    sort_direction: str = "DESC",
) -> tuple[list[dict[str, Any]], str | None, bool]:
    conditions = ["tenant_id = %(tenant_id)s"]
    extra: dict[str, Any] = {"tenant_id": tenant_id}

    if filters.get("status"):
        # Accepts either a single status string or a list (Filters panel's
        # multi-select sends several) — always parameterized via ANY(), same
        # idiom as billing/repository.py::mark_carryovers_applied's `id =
        # ANY(%(ids)s)`. Never string-interpolated.
        statuses = filters["status"]
        if isinstance(statuses, str):
            statuses = [statuses]
        conditions.append("status = ANY(%(statuses)s)")
        extra["statuses"] = list(statuses)
    if filters.get("created_after"):
        conditions.append("created_at >= %(created_after)s")
        extra["created_after"] = filters["created_after"]
    if filters.get("created_before"):
        conditions.append("created_at <= %(created_before)s")
        extra["created_before"] = filters["created_before"]
    if filters.get("eta_after"):
        conditions.append("estimated_arrival_date >= %(eta_after)s")
        extra["eta_after"] = filters["eta_after"]
    if filters.get("eta_before"):
        conditions.append("estimated_arrival_date <= %(eta_before)s")
        extra["eta_before"] = filters["eta_before"]

    # Free-text search across container number, vessel name, and voyage number.
    # Appended separately from `conditions` below (which get blanket-prefixed
    # with "c.") since this is already a compound multi-column OR expression —
    # folding it into `conditions` would double-prefix it into invalid SQL
    # (e.g. "c.(c.container_number ILIKE ...)"). See services/packing_list/
    # repository.py::list_packing_lists for the same q_clause pattern.
    q_clause = ""
    if filters.get("q"):
        q_clause = " AND (c.container_number ILIKE %(q)s" " OR c.vessel_name ILIKE %(q)s" " OR c.voyage_number ILIKE %(q)s)"
        extra["q"] = f"%{filters['q']}%"

    # Wrap the correlated packing-list aggregates in a subquery so
    # build_paginated_query's cursor condition (AND id > ...) references the
    # outer unambiguous columns instead of clashing with packing_list.id.
    where_clause = " AND ".join(f"c.{cond}" for cond in conditions)
    inner = f"""
        SELECT c.*,
               (SELECT COUNT(*) FROM packing_list pl
                WHERE pl.container_id = c.id AND pl.tenant_id = c.tenant_id) AS packing_list_count,
               (SELECT COUNT(*) FROM packing_list pl
                WHERE pl.container_id = c.id AND pl.tenant_id = c.tenant_id
                  AND pl.status = 'approved') AS approved_packing_list_count,
               (SELECT COALESCE(SUM(pli.cbm), 0)
                FROM packing_list_item pli
                JOIN packing_list pl2 ON pl2.id = pli.packing_list_id
                WHERE pl2.container_id = c.id AND pl2.tenant_id = c.tenant_id) AS total_cbm_packed
        FROM container c
        WHERE {where_clause}{q_clause}
    """
    base = f"SELECT * FROM ({inner}) AS t WHERE 1=1"
    query, params = build_paginated_query(base, cursor, limit, sort_field=sort_field, sort_direction=sort_direction)
    params.update(extra)
    rows = execute_with_tenant(tenant_id, query, params)
    return extract_page(rows, limit)


def get_container_stats(tenant_id: str) -> dict[str, int]:
    """Tenant-wide per-status container counts for the list stats row + chips.

    SQL-computed over the whole table so figures stay correct at scale (the
    frontend previously counted a capped `limit: 200` sample). Groups (Active,
    Cleared, …) are summed client-side from these per-status counts; the
    date-scoped `cleared_30d` is computed here since it needs a created_at
    predicate.
    """
    rows = execute_with_tenant(
        tenant_id,
        """
        SELECT
            COUNT(*)                                                    AS total,
            COUNT(*) FILTER (WHERE status = 'loading')                  AS loading,
            COUNT(*) FILTER (WHERE status = 'sealed')                   AS sealed,
            COUNT(*) FILTER (WHERE status = 'in_transit')               AS in_transit,
            COUNT(*) FILTER (WHERE status = 'arrived')                  AS arrived,
            COUNT(*) FILTER (WHERE status = 'customs_clearance')        AS customs_clearance,
            COUNT(*) FILTER (WHERE status = 'cleared')                  AS cleared,
            COUNT(*) FILTER (WHERE status = 'at_warehouse')             AS at_warehouse,
            COUNT(*) FILTER (WHERE status = 'fully_released')           AS fully_released,
            COUNT(*) FILTER (WHERE status = 'cancelled')               AS cancelled,
            COUNT(*) FILTER (WHERE status IN ('cleared', 'at_warehouse', 'fully_released')
                             AND created_at >= now() - interval '30 days')  AS cleared_30d
        FROM container
        WHERE tenant_id = %s
        """,
        (tenant_id,),
    )
    row = rows[0] if rows else {}
    keys = (
        "total",
        "loading",
        "sealed",
        "in_transit",
        "arrived",
        "customs_clearance",
        "cleared",
        "at_warehouse",
        "fully_released",
        "cancelled",
        "cleared_30d",
    )
    return {k: int(row.get(k) or 0) for k in keys}


def update_container_status(
    tenant_id: str,
    container_id: str,
    status: str,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    """Update container status + optional date/notes fields.

    extra keys are restricted to _CONTAINER_EXTRA_FIELDS (allowlist guard).
    """
    params: dict[str, Any] = {"status": status, "tenant_id": tenant_id, "id": container_id}
    extra_clause = ""
    if extra:
        safe_extra = {k: v for k, v in extra.items() if k in _CONTAINER_EXTRA_FIELDS and v is not None}
        for key, val in safe_extra.items():
            extra_clause += f", {key} = %({key})s"
            params[key] = val

    return execute_write_with_tenant(
        tenant_id,
        f"""
        UPDATE container
        SET status = %(status)s, updated_at = NOW(){extra_clause}
        WHERE tenant_id = %(tenant_id)s AND id = %(id)s
        RETURNING *
        """,
        params,
    )


# ---------------------------------------------------------------------------
# Validation helpers — tenant RLS scope
# ---------------------------------------------------------------------------


def count_all_packing_lists(tenant_id: str, container_id: str) -> int:
    """Count all packing lists for a container regardless of status."""
    rows = execute_with_tenant(
        tenant_id,
        "SELECT COUNT(*) AS cnt FROM packing_list WHERE tenant_id = %s AND container_id = %s",
        (tenant_id, container_id),
    )
    return int(rows[0]["cnt"]) if rows else 0


def delete_container(tenant_id: str, container_id: str) -> dict[str, Any] | None:
    """Hard-delete a container. Caller must verify preconditions (status + no PLs)."""
    return execute_write_with_tenant(
        tenant_id,
        "DELETE FROM container WHERE tenant_id = %s AND id = %s RETURNING *",
        (tenant_id, container_id),
    )


def count_approved_packing_lists(tenant_id: str, container_id: str) -> int:
    rows = execute_with_tenant(
        tenant_id,
        """
        SELECT COUNT(*) AS cnt FROM packing_list
        WHERE tenant_id = %s AND container_id = %s AND status = 'approved'
        """,
        (tenant_id, container_id),
    )
    return int(rows[0]["cnt"]) if rows else 0


def get_manifest_for_container(tenant_id: str, container_id: str) -> dict[str, Any] | None:
    rows = execute_with_tenant(
        tenant_id,
        "SELECT id, verification_status FROM manifest WHERE tenant_id = %s AND container_id = %s LIMIT 1",
        (tenant_id, container_id),
    )
    return rows[0] if rows else None


# ---------------------------------------------------------------------------
# Bulk tracking operations — tenant RLS scope for shipment_tracking;
# PLATFORM scope for tracking_event (no RLS on that table)
# ---------------------------------------------------------------------------


def bulk_update_tracking_status(tenant_id: str, container_id: str, tracking_status: str) -> None:
    """Bulk-update shipment_tracking.status for all codes in this container."""
    execute_write_with_tenant(
        tenant_id,
        """
        UPDATE shipment_tracking
        SET status = %(status)s, updated_at = NOW()
        FROM (
            SELECT DISTINCT pli.tracking_code
            FROM packing_list_item pli
            JOIN packing_list pl ON pl.id = pli.packing_list_id
            WHERE pl.container_id = %(container_id)s AND pl.tenant_id = %(tenant_id)s
        ) sub
        WHERE shipment_tracking.tracking_code = sub.tracking_code
          AND shipment_tracking.tenant_id     = %(tenant_id)s
        RETURNING shipment_tracking.id
        """,
        {"status": tracking_status, "container_id": container_id, "tenant_id": tenant_id},
    )


def bulk_insert_tracking_events(
    tenant_id: str,
    container_id: str,
    to_status: str,
    description: str | None,
    actor_id: str,
) -> None:
    """Insert one tracking_event per affected shipment_tracking row.

    tracking_event has no RLS — use PLATFORM scope so the SET command
    doesn't interfere with per-row RLS policies.
    """
    execute_write_with_tenant(
        PLATFORM_TENANT_ID,
        """
        INSERT INTO tracking_event (
            shipment_tracking_id, from_status, to_status, description, created_by
        )
        SELECT
            st.id,
            st.status,
            %(to_status)s,
            %(description)s,
            %(created_by)s
        FROM shipment_tracking st
        JOIN (
            SELECT DISTINCT pli.tracking_code
            FROM packing_list_item pli
            JOIN packing_list pl ON pl.id = pli.packing_list_id
            WHERE pl.container_id = %(container_id)s AND pl.tenant_id = %(tenant_id)s
        ) sub ON sub.tracking_code = st.tracking_code
        WHERE st.tenant_id = %(tenant_id)s
        RETURNING id
        """,
        {
            "to_status": to_status,
            "description": description,
            "created_by": actor_id,
            "container_id": container_id,
            "tenant_id": tenant_id,
        },
    )


# ---------------------------------------------------------------------------
# Billing trigger helper — tenant RLS scope
# ---------------------------------------------------------------------------


def get_customers_for_container(tenant_id: str, container_id: str) -> list[dict[str, Any]]:
    """Return distinct customers with approved packing lists for this container.

    Includes the portal user's locale (from tenant_user) so callers can pass the
    correct EN/ZH template to enqueue_notifications. Defaults to 'en' for customers
    without a portal account. `user_id` is included so callers can also target
    the in-app customer notification bell (shared.staff_notifications.notify_staff).
    """
    return execute_with_tenant(
        tenant_id,
        """
        SELECT DISTINCT c.id::text AS id, c.user_id, c.name, c.phone, c.email, c.whatsapp,
            COALESCE(tu.locale, 'en') AS locale
        FROM customer c
        JOIN packing_list pl ON pl.customer_id = c.id AND pl.tenant_id = c.tenant_id
        LEFT JOIN tenant_user tu ON tu.id = c.user_id AND tu.tenant_id = c.tenant_id
        WHERE pl.container_id = %s AND pl.tenant_id = %s AND pl.status = 'approved'
        """,
        (container_id, tenant_id),
    )


# ---------------------------------------------------------------------------
# Shipment tracking reads
# ---------------------------------------------------------------------------


def list_shipments(
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
    if filters.get("tracking_code"):
        conditions.append("tracking_code = %(tracking_code)s")
        extra["tracking_code"] = filters["tracking_code"]

    base = f"SELECT * FROM shipment_tracking WHERE {' AND '.join(conditions)}"
    query, params = build_paginated_query(base, cursor, limit, sort_field="created_at")
    params.update(extra)
    rows = execute_with_tenant(tenant_id, query, params)
    return extract_page(rows, limit)


def list_customer_shipments(
    tenant_id: str,
    customer_id: str,
    limit: int = 50,
    cursor: dict[str, Any] | None = None,
) -> tuple[list[dict[str, Any]], str | None, bool]:
    """Return shipment_tracking rows for a specific customer (via packing list join)."""
    extra: dict[str, Any] = {"tenant_id": tenant_id, "customer_id": customer_id}
    base = """
        SELECT st.*
        FROM shipment_tracking st
        WHERE st.tenant_id = %(tenant_id)s
          AND st.tracking_code IN (
            SELECT DISTINCT pli.tracking_code
            FROM packing_list_item pli
            JOIN packing_list pl ON pl.id = pli.packing_list_id
            WHERE pl.tenant_id   = %(tenant_id)s
              AND pl.customer_id = %(customer_id)s
          )
    """
    query, params = build_paginated_query(base, cursor, limit, sort_field="created_at")
    params.update(extra)
    rows = execute_with_tenant(tenant_id, query, params)
    return extract_page(rows, limit)


def get_customer_by_user_id(tenant_id: str, user_id: str) -> dict[str, Any] | None:
    rows = execute_with_tenant(
        tenant_id,
        "SELECT id FROM customer WHERE tenant_id = %s AND user_id = %s LIMIT 1",
        (tenant_id, user_id),
    )
    return rows[0] if rows else None


def get_shipment_by_tracking_code_and_phone(tracking_code: str, phone: str) -> dict[str, Any] | None:
    """Public lookup — bypasses RLS via PLATFORM scope.

    Verifies ownership by joining through packing_list → customer.phone.
    """
    rows = execute_with_tenant(
        PLATFORM_TENANT_ID,
        """
        SELECT DISTINCT ON (st.id)
            st.*,
            t.company_name,
            t.branding_config
        FROM shipment_tracking st
        JOIN tenant t ON t.id = st.tenant_id
        JOIN (
            SELECT DISTINCT pli.tracking_code, pl.customer_id, pl.tenant_id
            FROM packing_list_item pli
            JOIN packing_list pl ON pl.id = pli.packing_list_id
        ) code_map ON code_map.tracking_code = st.tracking_code
                  AND code_map.tenant_id      = st.tenant_id
        JOIN customer c ON c.id          = code_map.customer_id
                       AND c.tenant_id   = code_map.tenant_id
        WHERE st.tracking_code = %s
          AND (c.phone = %s OR c.whatsapp = %s)
        LIMIT 1
        """,
        (tracking_code, phone, phone),
    )
    return rows[0] if rows else None


def get_tracking_events(shipment_tracking_id: str) -> list[dict[str, Any]]:
    """Fetch ordered tracking_event history for a shipment_tracking row.

    tracking_event has no RLS — use PLATFORM scope.
    """
    return execute_with_tenant(
        PLATFORM_TENANT_ID,
        """
        SELECT * FROM tracking_event
        WHERE shipment_tracking_id = %s
        ORDER BY created_at ASC
        """,
        (shipment_tracking_id,),
    )


def insert_container_event(
    tenant_id: str,
    container_id: str,
    from_status: str,
    to_status: str,
    actor_id: str | None,
    notes: str | None = None,
) -> None:
    """Append an audit event for a container status change.

    container_event has no RLS — use PLATFORM_TENANT_ID scope.
    """
    execute_write_with_tenant(
        PLATFORM_TENANT_ID,
        """
        INSERT INTO container_event (tenant_id, container_id, from_status, to_status, actor_id, notes)
        VALUES (%(tenant_id)s, %(container_id)s, %(from_status)s, %(to_status)s, %(actor_id)s, %(notes)s)
        RETURNING id
        """,
        {
            "tenant_id": tenant_id,
            "container_id": container_id,
            "from_status": from_status,
            "to_status": to_status,
            "actor_id": actor_id,
            "notes": notes,
        },
    )


def get_container_events(tenant_id: str, container_id: str) -> list[dict[str, Any]]:
    """Return ordered container_event history with actor display name and role.

    No RLS on container_event — query scoped via WHERE clause instead.
    LEFT JOIN tenant_user so events survive if the actor account is deleted.
    """
    return execute_with_tenant(
        PLATFORM_TENANT_ID,
        """
        SELECT
            ce.*,
            tu.full_name  AS actor_name,
            tu.role  AS actor_role
        FROM container_event ce
        LEFT JOIN tenant_user tu
            ON tu.id = ce.actor_id::uuid AND tu.tenant_id = ce.tenant_id
        WHERE ce.tenant_id = %s AND ce.container_id = %s
        ORDER BY ce.created_at ASC
        """,
        (tenant_id, container_id),
    )


# ---------------------------------------------------------------------------
# Container documents — tenant RLS scope
# ---------------------------------------------------------------------------


def create_container_document(tenant_id: str, data: dict[str, Any]) -> dict[str, Any] | None:
    return execute_write_with_tenant(
        tenant_id,
        """
        INSERT INTO container_document (
            tenant_id, container_id, document_type, s3_key, filename,
            content_type, uploaded_by
        ) VALUES (
            %(tenant_id)s, %(container_id)s, %(document_type)s, %(s3_key)s,
            %(filename)s, %(content_type)s, %(uploaded_by)s
        ) RETURNING *
        """,
        data,
    )


def list_container_documents(tenant_id: str, container_id: str) -> list[dict[str, Any]]:
    return execute_with_tenant(
        tenant_id,
        """
        SELECT * FROM container_document
        WHERE tenant_id = %s AND container_id = %s
        ORDER BY created_at DESC
        """,
        (tenant_id, container_id),
    )


def get_container_document_by_id(
    tenant_id: str,
    container_id: str,
    doc_id: str,
) -> dict[str, Any] | None:
    rows = execute_with_tenant(
        tenant_id,
        """
        SELECT * FROM container_document
        WHERE tenant_id = %s AND container_id = %s AND id = %s
        LIMIT 1
        """,
        (tenant_id, container_id, doc_id),
    )
    return rows[0] if rows else None
