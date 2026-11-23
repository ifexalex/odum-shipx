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


# Per-manifest package breakdown by unit (carton/bag/pallet/bale/sack), summing
# each item's quantity — a row is a bulk quantity since migration 040, so a row
# count no longer equals a package count. Units left blank fall under
# 'unspecified'. Built from the manifest's *approved* packing lists, matching
# get_customer_summaries. Returns a JSONB map {unit: qty}, NULL when empty.
_PACKAGE_MIX_LATERAL = """
    LEFT JOIN LATERAL (
        SELECT jsonb_object_agg(unit, qty) AS package_mix
        FROM (
            SELECT COALESCE(NULLIF(pli.package_unit, ''), 'unspecified') AS unit,
                   SUM(COALESCE(pli.quantity, 1))::int                   AS qty
            FROM packing_list pl
            JOIN packing_list_item pli ON pli.packing_list_id = pl.id
            WHERE pl.manifest_id = m.id
              AND pl.tenant_id   = m.tenant_id
              AND pl.status      = 'approved'
            GROUP BY 1
        ) per_unit
    ) pm ON TRUE
"""


def get_manifest_by_id(tenant_id: str, manifest_id: str) -> dict[str, Any] | None:
    """Fetch manifest row joined with container_number, container_status, package_mix."""
    rows = execute_with_tenant(
        tenant_id,
        f"""
        SELECT m.*, co.container_number, co.status AS container_status, pm.package_mix
        FROM manifest m
        LEFT JOIN container co
               ON co.id = m.container_id AND co.tenant_id = m.tenant_id
        {_PACKAGE_MIX_LATERAL}
        WHERE m.tenant_id = %s AND m.id = %s
        LIMIT 1
        """,
        (tenant_id, manifest_id),
    )
    return rows[0] if rows else None


def _manifest_predicates(tenant_id: str, filters: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    """The WHERE clause (on alias ``m``) and its parameters, shared by the list and its count."""
    conditions = ["tenant_id = %(tenant_id)s"]
    params: dict[str, Any] = {"tenant_id": tenant_id}
    if filters.get("verification_status"):
        conditions.append("verification_status = %(verification_status)s")
        params["verification_status"] = filters["verification_status"]
    if filters.get("container_id"):
        conditions.append("container_id = %(container_id)s")
        params["container_id"] = filters["container_id"]
    return " AND ".join(f"m.{c}" for c in conditions), params


def count_manifests(tenant_id: str, filters: dict[str, Any]) -> int:
    """How many manifests match the same filters as ``list_manifests`` (for "showing 50 of 68")."""
    where_clause, params = _manifest_predicates(tenant_id, filters)
    rows = execute_with_tenant(
        tenant_id,
        f"SELECT COUNT(*)::int AS total FROM manifest m WHERE {where_clause}",  # noqa: S608 - fixed fragments only
        params,
    )
    return int(rows[0]["total"]) if rows else 0


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
    where_clause, extra = _manifest_predicates(tenant_id, filters)
    inner = f"""
        SELECT m.*, co.container_number, co.status AS container_status, pm.package_mix
        FROM manifest m
        LEFT JOIN container co
               ON co.id = m.container_id AND co.tenant_id = m.tenant_id
        {_PACKAGE_MIX_LATERAL}
        WHERE {where_clause}
    """
    base = f"SELECT * FROM ({inner}) AS t WHERE 1=1"
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
            c.phone                                                                 AS customer_phone,
            (array_agg(pl.id::text ORDER BY pl.created_at ASC))[1]                 AS packing_list_id,
            COALESCE(SUM(COALESCE(pli.quantity, 1)), 0)::int                        AS carton_count,
            COALESCE(SUM(pli.weight_actual_kg), 0)                                 AS total_weight_kg,
            COALESCE(SUM(pli.cbm), 0)                                              AS total_cbm,
            array_agg(pli.carton_tag ORDER BY pli.created_at ASC)                  AS carton_tags
        FROM packing_list pl
        JOIN packing_list_item pli ON pli.packing_list_id = pl.id
        LEFT JOIN customer c ON c.id = pl.customer_id AND c.tenant_id = pl.tenant_id
        WHERE pl.manifest_id = %s
          AND pl.tenant_id   = %s
          AND pl.status      = 'approved'
        GROUP BY pl.customer_id, c.name, c.phone
        ORDER BY c.name ASC
        """,
        (manifest_id, tenant_id),
    )


def get_missing_items_for_manifest(tenant_id: str, manifest_id: str) -> list[dict[str, Any]]:
    """Fetch all missing_item rows linked to a manifest (for diff view)."""
    return execute_with_tenant(
        tenant_id,
        """
        SELECT id::text, customer_id::text, carton_tags, description, status, created_at
        FROM missing_item
        WHERE tenant_id = %s AND manifest_id = %s
        ORDER BY created_at ASC
        """,
        (tenant_id, manifest_id),
    )


# ---------------------------------------------------------------------------
# Manifest state transitions
# ---------------------------------------------------------------------------


def revoke_manifest_verification(tenant_id: str, manifest_id: str) -> dict[str, Any] | None:
    """Reset a verified manifest back to pending, clearing verified_by/verified_at."""
    return execute_write_with_tenant(
        tenant_id,
        """
        UPDATE manifest
        SET verification_status = 'pending',
            verified_by         = NULL,
            verified_at         = NULL,
            updated_at          = NOW()
        WHERE tenant_id = %(tenant_id)s AND id = %(id)s
          AND verification_status = 'verified'
        RETURNING *
        """,
        {"tenant_id": tenant_id, "id": manifest_id},
    )


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
        WHERE tenant_id = %(tenant_id)s
          AND id = %(id)s
          AND verification_status = 'pending'
        RETURNING *
        """,
        {
            "verified_by": verified_by,
            "notes": notes,
            "tenant_id": tenant_id,
            "id": manifest_id,
        },
    )


def resolve_manifest_discrepancy(
    tenant_id: str,
    manifest_id: str,
    resolved_by: str,
    resolution_notes: str,
    final_counts: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    """Transition discrepancies_found → resolved and record resolution actor/timestamp/notes."""
    return execute_write_with_tenant(
        tenant_id,
        """
        UPDATE manifest
        SET verification_status = 'resolved',
            verified_by         = %(resolved_by)s,
            verified_at         = NOW(),
            notes               = COALESCE(%(notes)s, notes),
            updated_at          = NOW()
        WHERE tenant_id = %(tenant_id)s
          AND id        = %(id)s
          AND verification_status = 'discrepancies_found'
        RETURNING *
        """,
        {
            "tenant_id": tenant_id,
            "id": manifest_id,
            "resolved_by": resolved_by,
            "notes": resolution_notes,
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
        WHERE tenant_id = %(tenant_id)s
          AND id = %(id)s
          AND verification_status = 'pending'
        RETURNING *
        """,
        {"verified_by": verified_by, "tenant_id": tenant_id, "id": manifest_id},
    )


# ---------------------------------------------------------------------------
# Weight reconciliation
# ---------------------------------------------------------------------------


def get_items_with_weights_for_manifest(tenant_id: str, manifest_id: str) -> list[dict[str, Any]]:
    """Return approved packing list items with both weight fields for a manifest.

    packing_list_item has no RLS — join through packing_list for tenant scope.
    """
    return execute_with_tenant(
        tenant_id,
        """
        SELECT
            pli.id::text            AS id,
            pli.carton_tag,
            pli.tracking_code,
            pli.description,
            pli.weight_dispatch_kg,
            pli.weight_actual_kg,
            pl.customer_id::text    AS customer_id
        FROM packing_list_item pli
        JOIN packing_list pl ON pl.id = pli.packing_list_id
        WHERE pl.manifest_id = %s
          AND pl.tenant_id   = %s
          AND pl.status      = 'approved'
        ORDER BY pli.created_at ASC
        """,
        (manifest_id, tenant_id),
    )


# ---------------------------------------------------------------------------
# Missing item helpers
# ---------------------------------------------------------------------------


def get_item_by_carton_tag(
    tenant_id: str,
    carton_tag: str,
    *,
    manifest_id: str | None = None,
    customer_id: str | None = None,
) -> dict[str, Any] | None:
    """Look up packing_list_id + tracking_code from a carton tag on an approved packing list.

    When manifest_id / customer_id are supplied, scopes strictly to that manifest
    and customer so duplicate tags across containers cannot cross-link.
    """
    conditions = [
        "pli.carton_tag = %(carton_tag)s",
        "pl.tenant_id = %(tenant_id)s",
        "pl.status = 'approved'",
    ]
    params: dict[str, Any] = {"carton_tag": carton_tag, "tenant_id": tenant_id}
    if manifest_id:
        conditions.append("pl.manifest_id = %(manifest_id)s")
        params["manifest_id"] = manifest_id
    if customer_id:
        conditions.append("pl.customer_id = %(customer_id)s")
        params["customer_id"] = customer_id
    rows = execute_with_tenant(
        tenant_id,
        f"""
        SELECT pli.packing_list_id::text, pli.tracking_code
        FROM packing_list_item pli
        JOIN packing_list pl ON pl.id = pli.packing_list_id
        WHERE {" AND ".join(conditions)}
        LIMIT 1
        """,
        params,
    )
    return rows[0] if rows else None


def create_missing_item(tenant_id: str, data: dict[str, Any]) -> dict[str, Any] | None:
    payload = {
        **data,
        "carton_tags": data.get("carton_tags") or ([data["carton_tag"]] if data.get("carton_tag") else []),
    }
    return execute_write_with_tenant(
        tenant_id,
        """
        INSERT INTO missing_item (
            tenant_id, manifest_id, customer_id, packing_list_id,
            carton_tag, carton_tags, tracking_code, description, notes, reported_by
        ) VALUES (
            %(tenant_id)s, %(manifest_id)s, %(customer_id)s, %(packing_list_id)s,
            %(carton_tag)s, %(carton_tags)s, %(tracking_code)s, %(description)s, %(notes)s, %(reported_by)s
        ) RETURNING *
        """,
        payload,
    )


def get_manifest_stats(tenant_id: str) -> dict[str, int]:
    """Per-verification-status aggregates for the manifest list stats row (§6.2, P2-4).

    `overdue` uses the B11 predicate: still pending while the container has
    already reached Nigeria (arrived → at_warehouse).
    """
    rows = execute_with_tenant(
        tenant_id,
        """
        SELECT
            COUNT(*) FILTER (WHERE m.verification_status = 'pending')              AS pending,
            COUNT(*) FILTER (WHERE m.verification_status = 'verified')             AS verified,
            COUNT(*) FILTER (WHERE m.verification_status = 'discrepancies_found')  AS discrepancies_found,
            COUNT(*) FILTER (WHERE m.verification_status = 'resolved')             AS resolved,
            COUNT(*) FILTER (WHERE m.verification_status = 'pending'
                             AND co.status IN ('arrived', 'customs_clearance',
                                               'cleared', 'at_warehouse'))         AS overdue
        FROM manifest m
        LEFT JOIN container co ON co.id = m.container_id AND co.tenant_id = m.tenant_id
        WHERE m.tenant_id = %s
        """,
        (tenant_id,),
    )
    row = rows[0] if rows else {}
    return {k: int(row.get(k) or 0) for k in ("pending", "verified", "discrepancies_found", "resolved", "overdue")}


# ---------------------------------------------------------------------------
# Manifest evidence — NO RLS; scoped via manifest_id FK (mirrors claim_evidence).
# Tenant isolation is enforced by the caller (manifest looked up tenant-scoped
# before insert) and by the {tenant_id}/manifests/... S3 key prefix.
# ---------------------------------------------------------------------------


def create_manifest_evidence(tenant_id: str, data: dict[str, Any]) -> dict[str, Any] | None:
    """Insert a manifest_evidence row. Returns the created row."""
    return execute_write_with_tenant(
        tenant_id,
        """
        INSERT INTO manifest_evidence (
            manifest_id, file_key, file_name, file_type, file_size_bytes, label, uploaded_by
        ) VALUES (
            %(manifest_id)s, %(file_key)s, %(file_name)s, %(file_type)s,
            %(file_size_bytes)s, %(label)s, %(uploaded_by)s
        ) RETURNING *
        """,
        data,
    )


def list_manifest_evidence(tenant_id: str, manifest_id: str) -> list[dict[str, Any]]:
    """The manifest's confirmed evidence rows, newest first (an unconfirmed upload is not listed)."""
    return execute_with_tenant(
        tenant_id,
        """
        SELECT id, manifest_id, file_key, file_name, file_type, file_size_bytes,
               label, uploaded_by, created_at
        FROM manifest_evidence
        WHERE manifest_id = %s AND confirmed_at IS NOT NULL
        ORDER BY created_at DESC
        """,
        (manifest_id,),
    )


def get_manifest_evidence(tenant_id: str, manifest_id: str, evidence_id: str) -> dict[str, Any] | None:
    """One evidence row of a manifest, confirmed or not. The caller has checked the manifest is the tenant's."""
    rows = execute_with_tenant(
        tenant_id,
        "SELECT * FROM manifest_evidence WHERE manifest_id = %s AND id = %s",
        (manifest_id, evidence_id),
    )
    return rows[0] if rows else None


def confirm_manifest_evidence(tenant_id: str, manifest_id: str, evidence_id: str, size_bytes: int) -> dict[str, Any] | None:
    """Record the checked size and list the file. Confirming twice keeps the first time."""
    return execute_write_with_tenant(
        tenant_id,
        """
        UPDATE manifest_evidence
        SET file_size_bytes = %s, confirmed_at = COALESCE(confirmed_at, NOW())
        WHERE manifest_id = %s AND id = %s
        RETURNING *
        """,
        (size_bytes, manifest_id, evidence_id),
    )


def delete_unconfirmed_manifest_evidence(tenant_id: str, manifest_id: str, evidence_id: str) -> dict[str, Any] | None:
    """Drop the row of an upload that was refused at confirmation. A confirmed row is never deleted here."""
    return execute_write_with_tenant(
        tenant_id,
        """
        DELETE FROM manifest_evidence
        WHERE manifest_id = %s AND id = %s AND confirmed_at IS NULL
        RETURNING id
        """,
        (manifest_id, evidence_id),
    )
