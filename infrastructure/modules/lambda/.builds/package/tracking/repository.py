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

from shared.db import execute_with_tenant, execute_write_with_tenant
from shared.pagination import build_paginated_query, extract_page
from shared.tenant_context import PLATFORM_TENANT_ID

logger = logging.getLogger(__name__)

# Allowlist for dynamic extra fields in container status update
_CONTAINER_EXTRA_FIELDS = frozenset({"ship_date", "actual_arrival_date", "notes"})


# ---------------------------------------------------------------------------
# Container CRUD — tenant RLS scope
# ---------------------------------------------------------------------------


def create_container(tenant_id: str, data: dict) -> dict:
    return execute_write_with_tenant(
        tenant_id,
        """
        INSERT INTO container (
            tenant_id, container_number, parcel_number, origin, destination,
            estimated_arrival_date, notes, created_by
        ) VALUES (
            %(tenant_id)s, %(container_number)s, %(parcel_number)s,
            %(origin)s, %(destination)s, %(estimated_arrival_date)s,
            %(notes)s, %(created_by)s
        ) RETURNING *
        """,
        data,
    )


def get_container_by_id(tenant_id: str, container_id: str) -> dict | None:
    rows = execute_with_tenant(
        tenant_id,
        "SELECT * FROM container WHERE tenant_id = %s AND id = %s LIMIT 1",
        (tenant_id, container_id),
    )
    return rows[0] if rows else None


def list_containers(
    tenant_id: str,
    filters: dict,
    limit: int = 50,
    cursor: dict | None = None,
) -> tuple[list[dict], str | None, bool]:
    conditions = ["tenant_id = %(tenant_id)s"]
    extra: dict = {"tenant_id": tenant_id}

    if filters.get("status"):
        conditions.append("status = %(status)s")
        extra["status"] = filters["status"]
    if filters.get("q"):
        conditions.append("container_number ILIKE %(q)s")
        extra["q"] = f"%{filters['q']}%"

    base = f"SELECT * FROM container WHERE {' AND '.join(conditions)}"
    query, params = build_paginated_query(base, cursor, limit, sort_field="created_at")
    params.update(extra)
    rows = execute_with_tenant(tenant_id, query, params)
    return extract_page(rows, limit)


def update_container_status(
    tenant_id: str,
    container_id: str,
    status: str,
    extra: dict | None = None,
) -> dict:
    """Update container status + optional date/notes fields.

    extra keys are restricted to _CONTAINER_EXTRA_FIELDS (allowlist guard).
    """
    params: dict = {"status": status, "tenant_id": tenant_id, "id": container_id}
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


def get_manifest_for_container(tenant_id: str, container_id: str) -> dict | None:
    rows = execute_with_tenant(
        tenant_id,
        "SELECT id FROM manifest WHERE tenant_id = %s AND container_id = %s LIMIT 1",
        (tenant_id, container_id),
    )
    return rows[0] if rows else None


# ---------------------------------------------------------------------------
# Bulk tracking operations — tenant RLS scope for shipment_tracking;
# PLATFORM scope for tracking_event (no RLS on that table)
# ---------------------------------------------------------------------------


def bulk_update_tracking_status(
    tenant_id: str, container_id: str, tracking_status: str
) -> None:
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


def get_customers_for_container(tenant_id: str, container_id: str) -> list[dict]:
    """Return distinct customers with approved packing lists for this container."""
    return execute_with_tenant(
        tenant_id,
        """
        SELECT DISTINCT c.id::text AS id, c.name, c.phone
        FROM customer c
        JOIN packing_list pl ON pl.customer_id = c.id AND pl.tenant_id = c.tenant_id
        WHERE pl.container_id = %s AND pl.tenant_id = %s AND pl.status = 'approved'
        """,
        (container_id, tenant_id),
    )


# ---------------------------------------------------------------------------
# Shipment tracking reads
# ---------------------------------------------------------------------------


def list_shipments(
    tenant_id: str,
    filters: dict,
    limit: int = 50,
    cursor: dict | None = None,
) -> tuple[list[dict], str | None, bool]:
    conditions = ["tenant_id = %(tenant_id)s"]
    extra: dict = {"tenant_id": tenant_id}

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
    cursor: dict | None = None,
) -> tuple[list[dict], str | None, bool]:
    """Return shipment_tracking rows for a specific customer (via packing list join)."""
    extra: dict = {"tenant_id": tenant_id, "customer_id": customer_id}
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


def get_customer_by_user_id(tenant_id: str, user_id: str) -> dict | None:
    rows = execute_with_tenant(
        tenant_id,
        "SELECT id FROM customer WHERE tenant_id = %s AND user_id = %s LIMIT 1",
        (tenant_id, user_id),
    )
    return rows[0] if rows else None


def get_shipment_by_tracking_code_and_phone(
    tracking_code: str, phone: str
) -> dict | None:
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


def get_tracking_events(shipment_tracking_id: str) -> list[dict]:
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
