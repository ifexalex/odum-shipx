"""Database access layer for the Manifest service.

Pure SQL — no business logic.
All queries use parameterized statements (%s / %(name)s) — never f-strings on
user-supplied values.

Notes:
  - manifest has RLS (tenant_id isolation).
  - missing_item has RLS.
  - packing_list_item has NO RLS — always join through packing_list for tenant scope.
"""

import logging
from typing import Any

from shared.db import execute_with_tenant, execute_write_with_tenant
from shared.pagination import build_paginated_query, extract_page

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Manifest reads
# ---------------------------------------------------------------------------


def get_manifest_by_id(tenant_id: str, manifest_id: str) -> dict[str, Any] | None:
    """Fetch manifest row joined with container_number."""
    rows = execute_with_tenant(
        tenant_id,
        """
        SELECT m.*, co.container_number
        FROM manifest m
        LEFT JOIN container co
               ON co.id = m.container_id AND co.tenant_id = m.tenant_id
        WHERE m.tenant_id = %s AND m.id = %s
        LIMIT 1
        """,
        (tenant_id, manifest_id),
    )
    return rows[0] if rows else None


def list_manifests(
    tenant_id: str,
    filters: dict[str, Any],
    limit: int = 50,
    cursor: dict[str, Any] | None = None,
) -> tuple[list[dict[str, Any]], str | None, bool]:
    """Paginated manifest list with optional filters.

    Supported filters: verification_status, container_id.
    container_number omitted from list view to avoid JOIN ambiguity with
    build_paginated_query's appended ORDER BY / cursor conditions.
    """
    conditions = ["tenant_id = %(tenant_id)s"]
    extra: dict[str, Any] = {"tenant_id": tenant_id}

    if filters.get("verification_status"):
        conditions.append("verification_status = %(verification_status)s")
        extra["verification_status"] = filters["verification_status"]
    if filters.get("container_id"):
        conditions.append("container_id = %(container_id)s")
        extra["container_id"] = filters["container_id"]

    base = f"SELECT * FROM manifest WHERE {' AND '.join(conditions)}"
    query, params = build_paginated_query(base, cursor, limit, sort_field="created_at")
    params.update(extra)
    rows = execute_with_tenant(tenant_id, query, params)
    return extract_page(rows, limit)


def get_customer_summaries(tenant_id: str, manifest_id: str) -> list[dict[str, Any]]:
    """Aggregate approved packing list items per customer for a manifest.

    Returns one row per customer with:
      - carton_count, total_weight_kg, total_cbm
      - carton_tags list (PostgreSQL array → Python list via psycopg2)
      - packing_list_id: earliest packing list for that customer
    """
    return execute_with_tenant(
        tenant_id,
        """
        SELECT
            pl.customer_id::text                                                    AS customer_id,
            c.name                                                                  AS customer_name,
            (array_agg(pl.id::text ORDER BY pl.created_at ASC))[1]                 AS packing_list_id,
            COUNT(pli.id)                                                           AS carton_count,
            COALESCE(SUM(pli.weight_actual_kg), 0)                                 AS total_weight_kg,
            COALESCE(SUM(pli.cbm), 0)                                              AS total_cbm,
            array_agg(pli.carton_tag ORDER BY pli.created_at ASC)                  AS carton_tags
        FROM packing_list pl
        JOIN packing_list_item pli ON pli.packing_list_id = pl.id
        LEFT JOIN customer c ON c.id = pl.customer_id AND c.tenant_id = pl.tenant_id
        WHERE pl.manifest_id = %s
          AND pl.tenant_id   = %s
          AND pl.status      = 'approved'
        GROUP BY pl.customer_id, c.name
        ORDER BY c.name ASC
        """,
        (manifest_id, tenant_id),
    )


# ---------------------------------------------------------------------------
# Manifest state transitions
# ---------------------------------------------------------------------------


def set_manifest_verified(
    tenant_id: str,
    manifest_id: str,
    verified_by: str,
    notes: str | None = None,
) -> dict[str, Any] | None:
    return execute_write_with_tenant(
        tenant_id,
        """
        UPDATE manifest
        SET verification_status = 'verified',
            verified_by         = %(verified_by)s,
            verified_at         = NOW(),
            notes               = COALESCE(%(notes)s, notes),
            updated_at          = NOW()
        WHERE tenant_id = %(tenant_id)s AND id = %(id)s
        RETURNING *
        """,
        {
            "verified_by": verified_by,
            "notes": notes,
            "tenant_id": tenant_id,
            "id": manifest_id,
        },
    )


def set_manifest_discrepancies_found(
    tenant_id: str,
    manifest_id: str,
    verified_by: str,
) -> dict[str, Any] | None:
    return execute_write_with_tenant(
        tenant_id,
        """
        UPDATE manifest
        SET verification_status = 'discrepancies_found',
            verified_by         = %(verified_by)s,
            verified_at         = NOW(),
            updated_at          = NOW()
        WHERE tenant_id = %(tenant_id)s AND id = %(id)s
        RETURNING *
        """,
        {"verified_by": verified_by, "tenant_id": tenant_id, "id": manifest_id},
    )


# ---------------------------------------------------------------------------
# Missing item helpers
# ---------------------------------------------------------------------------


def get_item_by_carton_tag(tenant_id: str, carton_tag: str) -> dict[str, Any] | None:
    """Look up packing_list_id + tracking_code from a carton tag.

    packing_list_item has no RLS — join through packing_list for tenant scope.
    """
    rows = execute_with_tenant(
        tenant_id,
        """
        SELECT pli.packing_list_id::text, pli.tracking_code
        FROM packing_list_item pli
        JOIN packing_list pl ON pl.id = pli.packing_list_id
        WHERE pli.carton_tag = %s AND pl.tenant_id = %s
        LIMIT 1
        """,
        (carton_tag, tenant_id),
    )
    return rows[0] if rows else None


def create_missing_item(tenant_id: str, data: dict[str, Any]) -> dict[str, Any] | None:
    return execute_write_with_tenant(
        tenant_id,
        """
        INSERT INTO missing_item (
            tenant_id, manifest_id, customer_id, packing_list_id,
            carton_tag, tracking_code, description, notes, reported_by
        ) VALUES (
            %(tenant_id)s, %(manifest_id)s, %(customer_id)s, %(packing_list_id)s,
            %(carton_tag)s, %(tracking_code)s, %(description)s, %(notes)s, %(reported_by)s
        ) RETURNING *
        """,
        data,
    )
