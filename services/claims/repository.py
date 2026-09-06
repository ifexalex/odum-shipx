"""Database access layer for the Claims service.

Pure SQL — no business logic.
All queries use parameterized statements (%s / %(name)s) — never f-strings on
user-supplied values.

Notes:
  - damage_claim has RLS (tenant_id isolation).
  - claim_resolution has RLS.
  - claim_evidence has NO RLS — scoped via damage_claim_id FK.
  - missing_item has RLS.
  - seized_item has RLS.
  - tenant_config has RLS.
"""

import logging
from datetime import date
from decimal import Decimal
from typing import Any

from shared.db import execute_with_tenant, execute_write_with_tenant
from shared.pagination import build_paginated_query, extract_page
from shared.tenant_context import PLATFORM_TENANT_ID

logger = logging.getLogger(__name__)

# Allowlist for dynamic extra fields in claim status update
_CLAIM_STATUS_EXTRA_FIELDS = frozenset({"inspection_method", "reviewed_by", "reviewed_at"})

# Terminal states for missing item (set resolved_by / resolved_at)
_MISSING_TERMINAL = {"found_and_shipping", "confirmed_lost", "resolved"}

# Terminal states for seized item (set recovery_date)
_SEIZED_TERMINAL = {"recovered", "permanently_lost"}


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------


def get_customer_by_user_id(tenant_id: str, user_id: str) -> dict[str, Any] | None:
    rows = execute_with_tenant(
        tenant_id,
        "SELECT id, name FROM customer WHERE tenant_id = %s AND user_id = %s LIMIT 1",
        (tenant_id, user_id),
    )
    return rows[0] if rows else None


def get_dollar_rate(tenant_id: str) -> Decimal:
    """Return the current USD→NGN exchange rate from tenant_config."""
    rows = execute_with_tenant(
        tenant_id,
        """
        SELECT config_value FROM tenant_config
        WHERE tenant_id = %s AND config_key = 'dollar_rate' LIMIT 1
        """,
        (tenant_id,),
    )
    if not rows:
        return Decimal("1550")
    val = rows[0]["config_value"]
    if isinstance(val, dict):
        return Decimal(str(val.get("rate", "1550")))
    return Decimal(str(val))


def get_billing_by_id(tenant_id: str, billing_id: str) -> dict[str, Any] | None:
    """Return a billing record by ID."""
    if not billing_id:
        return None
    rows = execute_with_tenant(
        tenant_id,
        "SELECT * FROM billing WHERE tenant_id = %s AND id = %s LIMIT 1",
        (tenant_id, billing_id),
    )
    return rows[0] if rows else None


def get_tenant_config_value(tenant_id: str, config_key: str) -> dict[str, Any] | None:
    """Return the JSONB config_value dict for a given key, or None."""
    rows = execute_with_tenant(
        tenant_id,
        """
        SELECT config_value FROM tenant_config
        WHERE tenant_id = %s AND config_key = %s LIMIT 1
        """,
        (tenant_id, config_key),
    )
    if not rows:
        return None
    val = rows[0]["config_value"]
    return val if isinstance(val, dict) else {}


# ---------------------------------------------------------------------------
# Damage claim CRUD — tenant RLS scope
# ---------------------------------------------------------------------------


def resolve_container_id(tenant_id: str, container_id_or_number: str) -> str | None:
    """Resolve a container reference that may be a UUID or a container number.

    Ground-truth gap found live: FileDamageClaimRequest.container_id was
    passed straight into a `uuid` column with no resolution at all, while the
    frontend's own field label and placeholder ("Container ID or number …
    e.g. ACME-001 or paste the UUID") promised number support that never
    existed. A customer typing what they actually see — the container
    number, never its internal UUID — hit `InvalidTextRepresentation` on
    every attempt to file a claim.

    Returns the container's real id, or None if nothing matches (a genuinely
    unknown container, not a caller error).
    """
    rows = execute_with_tenant(
        tenant_id,
        "SELECT id FROM container WHERE tenant_id = %(tenant_id)s AND (id::text = %(ref)s OR container_number = %(ref)s) LIMIT 1",
        {"tenant_id": tenant_id, "ref": container_id_or_number},
    )
    return str(rows[0]["id"]) if rows else None


def customer_has_cargo_in_container(tenant_id: str, customer_id: str, container_id: str) -> bool:
    """True if this customer has at least one packing list on this container.

    Guards file_claim: without it, a customer could file (and staff would
    then investigate) a damage claim against any container in the tenant by
    guessing or enumerating container numbers, not only their own cargo.
    """
    rows = execute_with_tenant(
        tenant_id,
        "SELECT 1 FROM packing_list WHERE tenant_id = %(tenant_id)s"
        " AND customer_id = %(customer_id)s AND container_id = %(container_id)s LIMIT 1",
        {"tenant_id": tenant_id, "customer_id": customer_id, "container_id": container_id},
    )
    return bool(rows)


def create_damage_claim(tenant_id: str, data: dict[str, Any]) -> dict[str, Any] | None:
    return execute_write_with_tenant(
        tenant_id,
        """
        INSERT INTO damage_claim (
            tenant_id, customer_id, container_id,
            cartons_affected, description, status, submitted_by, reference
        ) VALUES (
            %(tenant_id)s, %(customer_id)s, %(container_id)s,
            %(cartons_affected)s, %(description)s, %(status)s, %(submitted_by)s, %(reference)s
        ) RETURNING *
        """,
        data,
    )


def get_damage_claim_by_id(tenant_id: str, claim_id: str) -> dict[str, Any] | None:
    rows = execute_with_tenant(
        tenant_id,
        "SELECT * FROM damage_claim WHERE tenant_id = %s AND id = %s LIMIT 1",
        (tenant_id, claim_id),
    )
    return rows[0] if rows else None


def get_next_claim_reference(tenant_id: str) -> str:
    """Generate the next DC reference for this tenant in DC-YYYYMMDD-NNN format."""
    from datetime import datetime, timezone
    date_str = datetime.now(tz=timezone.utc).strftime("%Y%m%d")
    prefix = f"DC-{date_str}-"
    rows = execute_with_tenant(
        tenant_id,
        "SELECT COUNT(*) AS cnt FROM damage_claim WHERE tenant_id = %s AND reference LIKE %s",
        (tenant_id, prefix + "%"),
    )
    seq = (int(rows[0]["cnt"]) + 1) if rows else 1
    return f"{prefix}{seq:03d}"


def list_damage_claims(
    tenant_id: str,
    filters: dict[str, Any],
    limit: int = 50,
    cursor: dict[str, Any] | None = None,
    sort_field: str = "created_at",
    sort_direction: str = "DESC",
) -> tuple[list[dict[str, Any]], str | None, bool]:
    conditions = ["dc.tenant_id = %(tenant_id)s"]
    extra: dict[str, Any] = {"tenant_id": tenant_id}

    if filters.get("status"):
        conditions.append("dc.status = %(status)s")
        extra["status"] = filters["status"]
    if filters.get("customer_id"):
        conditions.append("dc.customer_id = %(customer_id)s")
        extra["customer_id"] = filters["customer_id"]
    if filters.get("q"):
        conditions.append(
            "(dc.reference ILIKE %(q)s OR cu.name ILIKE %(q)s OR c.container_number ILIKE %(q)s)"
        )
        extra["q"] = f"%{filters['q']}%"

    base = f"""
        SELECT dc.*,
               cu.name  AS customer_name,
               c.container_number
        FROM damage_claim dc
        LEFT JOIN customer  cu ON cu.id = dc.customer_id  AND cu.tenant_id = dc.tenant_id
        LEFT JOIN container c  ON c.id  = dc.container_id AND c.tenant_id  = dc.tenant_id
        WHERE {' AND '.join(conditions)}
    """
    query, params = build_paginated_query(
        base, cursor, limit, sort_field=f"dc.{sort_field}", sort_direction=sort_direction
    )
    params.update(extra)
    rows = execute_with_tenant(tenant_id, query, params)
    return extract_page(rows, limit)


def update_claim_status(
    tenant_id: str,
    claim_id: str,
    status: str,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    """Update damage_claim status + optional extra fields (allowlisted)."""
    params: dict[str, Any] = {"status": status, "tenant_id": tenant_id, "id": claim_id}
    extra_clause = ""
    if extra:
        safe = {k: v for k, v in extra.items() if k in _CLAIM_STATUS_EXTRA_FIELDS and v is not None}
        for key, val in safe.items():
            extra_clause += f", {key} = %({key})s"
            params[key] = val

    return execute_write_with_tenant(
        tenant_id,
        f"""
        UPDATE damage_claim
        SET status = %(status)s, updated_at = NOW(){extra_clause}
        WHERE tenant_id = %(tenant_id)s AND id = %(id)s
        RETURNING *
        """,
        params,
    )


# ---------------------------------------------------------------------------
# Claim resolution — tenant RLS scope
# ---------------------------------------------------------------------------


def create_claim_resolution(tenant_id: str, data: dict[str, Any]) -> dict[str, Any] | None:
    return execute_write_with_tenant(
        tenant_id,
        """
        INSERT INTO claim_resolution (
            tenant_id, damage_claim_id, resolution_type,
            resolution_amount_ngn, approval_level, approved_by, notes,
            refund_request_id, discount_percentage
        ) VALUES (
            %(tenant_id)s, %(damage_claim_id)s, %(resolution_type)s,
            %(resolution_amount_ngn)s, %(approval_level)s, %(approved_by)s, %(notes)s,
            %(refund_request_id)s, %(discount_percentage)s
        ) RETURNING *
        """,
        data,
    )


def create_refund_request_for_claim(tenant_id: str, data: dict[str, Any]) -> dict[str, Any] | None:
    """Insert a refund_request created from a resolved damage claim.

    Ground-truth gap found live: this never set refund_type, though migration
    009 added the column (and its CHECK constraint) with exactly this case in
    mind — 'damage_or_loss' is one of its three allowed values. Every
    claim-triggered refund had refund_type NULL, and the frontend's
    refundTypeLabel() switch has no fallback for that, so RefundDetail.tsx's
    page title silently rendered blank for every one of them.
    """
    return execute_write_with_tenant(
        tenant_id,
        """
        INSERT INTO refund_request (
            tenant_id, customer_id, billing_id,
            amount_ngn, reason, status, refund_type
        ) VALUES (
            %(tenant_id)s, %(customer_id)s, %(billing_id)s,
            %(amount_ngn)s, %(reason)s, 'pending_review', 'damage_or_loss'
        ) RETURNING *
        """,
        data,
    )


# ---------------------------------------------------------------------------
# Claim evidence — NO RLS; scoped via damage_claim_id FK
# ---------------------------------------------------------------------------


def create_claim_evidence(data: dict[str, Any]) -> dict[str, Any] | None:
    """Insert a claim_evidence record.

    claim_evidence has no RLS — use PLATFORM_TENANT_ID scope.
    """
    return execute_write_with_tenant(
        PLATFORM_TENANT_ID,
        """
        INSERT INTO claim_evidence (
            damage_claim_id, file_key, file_name,
            file_type, file_size_bytes, uploaded_by
        ) VALUES (
            %(damage_claim_id)s, %(file_key)s, %(file_name)s,
            %(file_type)s, %(file_size_bytes)s, %(uploaded_by)s
        ) RETURNING *
        """,
        data,
    )


# ---------------------------------------------------------------------------
# Missing items — tenant RLS scope
# ---------------------------------------------------------------------------


def list_missing_items(
    tenant_id: str,
    filters: dict[str, Any],
    limit: int = 50,
    cursor: dict[str, Any] | None = None,
) -> tuple[list[dict[str, Any]], str | None, bool]:
    conditions = ["tenant_id = %(tenant_id)s"]
    extra: dict[str, Any] = {"tenant_id": tenant_id}

    if filters.get("container_id"):
        # missing_item links to manifest; filter via subquery
        conditions.append(
            "manifest_id IN (" "SELECT id FROM manifest " "WHERE container_id = %(container_id)s AND tenant_id = %(tenant_id)s)"
        )
        extra["container_id"] = filters["container_id"]
    if filters.get("customer_id"):
        conditions.append("customer_id = %(customer_id)s")
        extra["customer_id"] = filters["customer_id"]
    if filters.get("status"):
        conditions.append("status = %(status)s")
        extra["status"] = filters["status"]

    base = f"SELECT * FROM missing_item WHERE {' AND '.join(conditions)}"
    query, params = build_paginated_query(base, cursor, limit, sort_field="created_at")
    params.update(extra)
    rows = execute_with_tenant(tenant_id, query, params)
    return extract_page(rows, limit)


def list_seized_items(
    tenant_id: str,
    filters: dict[str, Any],
    limit: int = 50,
    cursor: dict[str, Any] | None = None,
) -> tuple[list[dict[str, Any]], str | None, bool]:
    conditions = ["tenant_id = %(tenant_id)s"]
    extra: dict[str, Any] = {"tenant_id": tenant_id}

    if filters.get("container_id"):
        conditions.append("container_id = %(container_id)s")
        extra["container_id"] = filters["container_id"]
    if filters.get("customer_id"):
        conditions.append("customer_id = %(customer_id)s")
        extra["customer_id"] = filters["customer_id"]
    if filters.get("status"):
        conditions.append("recovery_status = %(status)s")
        extra["status"] = filters["status"]

    base = f"SELECT * FROM seized_item WHERE {' AND '.join(conditions)}"
    query, params = build_paginated_query(base, cursor, limit, sort_field="created_at")
    params.update(extra)
    rows = execute_with_tenant(tenant_id, query, params)
    return extract_page(rows, limit)


def create_missing_item(tenant_id: str, data: dict[str, Any]) -> dict[str, Any] | None:
    return execute_write_with_tenant(
        tenant_id,
        """
        INSERT INTO missing_item (
            tenant_id, manifest_id, customer_id,
            carton_tags, description, status, reported_by
        ) VALUES (
            %(tenant_id)s, %(manifest_id)s, %(customer_id)s,
            %(carton_tags)s, %(description)s, %(status)s, %(reported_by)s
        ) RETURNING *
        """,
        data,
    )


def get_missing_item_by_id(tenant_id: str, item_id: str) -> dict[str, Any] | None:
    rows = execute_with_tenant(
        tenant_id,
        "SELECT * FROM missing_item WHERE tenant_id = %s AND id = %s LIMIT 1",
        (tenant_id, item_id),
    )
    return rows[0] if rows else None


def link_refund_to_missing_item(
    tenant_id: str, item_id: str, refund_request_id: str
) -> dict[str, Any] | None:
    """Set refund_request_id on a missing_item row. Returns updated row."""
    return execute_write_with_tenant(
        tenant_id,
        """
        UPDATE missing_item
        SET refund_request_id = %(refund_request_id)s, updated_at = NOW()
        WHERE tenant_id = %(tenant_id)s AND id = %(id)s
        RETURNING *
        """,
        {"tenant_id": tenant_id, "id": item_id, "refund_request_id": refund_request_id},
    )


def link_refund_to_seized_item(
    tenant_id: str, item_id: str, refund_request_id: str
) -> dict[str, Any] | None:
    """Set refund_request_id on a seized_item row. Returns updated row."""
    return execute_write_with_tenant(
        tenant_id,
        """
        UPDATE seized_item
        SET refund_request_id = %(refund_request_id)s, updated_at = NOW()
        WHERE tenant_id = %(tenant_id)s AND id = %(id)s
        RETURNING *
        """,
        {"tenant_id": tenant_id, "id": item_id, "refund_request_id": refund_request_id},
    )


def update_missing_item_status(
    tenant_id: str,
    item_id: str,
    status: str,
    notes: str | None = None,
    actor_id: str | None = None,
) -> dict[str, Any] | None:
    params: dict[str, Any] = {"status": status, "tenant_id": tenant_id, "id": item_id}
    extra_clause = ""
    if notes is not None:
        extra_clause += ", notes = %(notes)s"
        params["notes"] = notes
    if status in _MISSING_TERMINAL and actor_id:
        extra_clause += ", resolved_by = %(resolved_by)s, resolved_at = NOW()"
        params["resolved_by"] = actor_id

    return execute_write_with_tenant(
        tenant_id,
        f"""
        UPDATE missing_item
        SET status = %(status)s, updated_at = NOW(){extra_clause}
        WHERE tenant_id = %(tenant_id)s AND id = %(id)s
        RETURNING *
        """,
        params,
    )


# ---------------------------------------------------------------------------
# Seized items — tenant RLS scope
# ---------------------------------------------------------------------------


def create_seized_item(tenant_id: str, data: dict[str, Any]) -> dict[str, Any] | None:
    return execute_write_with_tenant(
        tenant_id,
        """
        INSERT INTO seized_item (
            tenant_id, container_id, customer_id,
            carton_tags, description, seizure_date,
            recovery_status, created_by
        ) VALUES (
            %(tenant_id)s, %(container_id)s, %(customer_id)s,
            %(carton_tags)s, %(description)s, %(seizure_date)s,
            %(recovery_status)s, %(created_by)s
        ) RETURNING *
        """,
        data,
    )


def get_seized_item_by_id(tenant_id: str, item_id: str) -> dict[str, Any] | None:
    rows = execute_with_tenant(
        tenant_id,
        "SELECT * FROM seized_item WHERE tenant_id = %s AND id = %s LIMIT 1",
        (tenant_id, item_id),
    )
    return rows[0] if rows else None


def update_seized_item_status(
    tenant_id: str,
    item_id: str,
    recovery_status: str,
    notes: str | None = None,
    actor_id: str | None = None,
) -> dict[str, Any] | None:
    params: dict[str, Any] = {"recovery_status": recovery_status, "tenant_id": tenant_id, "id": item_id}
    extra_clause = ""
    if notes is not None:
        extra_clause += ", notes = %(notes)s"
        params["notes"] = notes
    if recovery_status in _SEIZED_TERMINAL:
        extra_clause += ", recovery_date = %(recovery_date)s"
        params["recovery_date"] = date.today()

    return execute_write_with_tenant(
        tenant_id,
        f"""
        UPDATE seized_item
        SET recovery_status = %(recovery_status)s, updated_at = NOW(){extra_clause}
        WHERE tenant_id = %(tenant_id)s AND id = %(id)s
        RETURNING *
        """,
        params,
    )
