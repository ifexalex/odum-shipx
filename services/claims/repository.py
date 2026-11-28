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
from datetime import UTC, date
from typing import Any

from shared.db import execute_with_tenant, execute_write_with_tenant, take_tenant_counter
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


def get_billing_for_claim(tenant_id: str, customer_id: str, container_id: str) -> dict[str, Any] | None:
    """Return the active (non-cancelled, non-waived) billing record for a customer on a container."""
    rows = execute_with_tenant(
        tenant_id,
        """
        SELECT * FROM billing
        WHERE tenant_id = %s AND customer_id = %s AND container_id = %s
          AND status NOT IN ('cancelled', 'waived')
        ORDER BY created_at DESC
        LIMIT 1
        """,
        (tenant_id, customer_id, container_id),
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


def get_container_status(tenant_id: str, container_id: str) -> str | None:
    """The container's current lifecycle status, or None if it no longer exists."""
    rows = execute_with_tenant(
        tenant_id,
        "SELECT status FROM container WHERE tenant_id = %(tenant_id)s AND id = %(container_id)s LIMIT 1",
        {"tenant_id": tenant_id, "container_id": container_id},
    )
    return str(rows[0]["status"]) if rows else None


def customer_has_cargo_in_container(tenant_id: str, customer_id: str, container_id: str) -> bool:
    """True if this customer has at least one non-draft, non-rejected packing list on this container.

    Guards file_claim: without it, a customer could file (and staff would
    then investigate) a damage claim against any container in the tenant by
    guessing or enumerating container numbers, or via a rejected/draft list.
    """
    rows = execute_with_tenant(
        tenant_id,
        "SELECT 1 FROM packing_list WHERE tenant_id = %(tenant_id)s"
        " AND customer_id = %(customer_id)s AND container_id = %(container_id)s"
        " AND status NOT IN ('draft', 'rejected') LIMIT 1",
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
    """One claim with its customer's name and its container's number (for the claim page and the list-style fields)."""
    rows = execute_with_tenant(
        tenant_id,
        """
        SELECT dc.*,
               cu.name             AS customer_name,
               c.container_number  AS container_number
        FROM damage_claim dc
        LEFT JOIN customer  cu ON cu.id = dc.customer_id  AND cu.tenant_id = dc.tenant_id
        LEFT JOIN container c  ON c.id  = dc.container_id AND c.tenant_id  = dc.tenant_id
        WHERE dc.tenant_id = %s AND dc.id = %s
        LIMIT 1
        """,
        (tenant_id, claim_id),
    )
    return rows[0] if rows else None


def get_claim_outcome(tenant_id: str, claim_id: str) -> dict[str, Any] | None:
    """The claim's latest resolution with the status of the refund it created, if any.

    `reason` is what staff typed when deciding (`claim_resolution.notes`). The service decides who is shown it: a
    customer sees it only when the decision went against them. `approval_level` and `approved_by` are staff's
    internal record and are never selected.
    """
    rows = execute_with_tenant(
        tenant_id,
        """
        SELECT cr.resolution_type,
               cr.resolution_amount_ngn,
               cr.discount_percentage,
               cr.notes              AS reason,
               cr.created_at         AS resolved_at,
               rr.id                 AS refund_id,
               rr.status             AS refund_status,
               COALESCE(rr.amount_approved_ngn, rr.amount_ngn) AS refund_amount_ngn
        FROM claim_resolution cr
        LEFT JOIN refund_request rr ON rr.id = cr.refund_request_id AND rr.tenant_id = cr.tenant_id
        WHERE cr.tenant_id = %s AND cr.damage_claim_id = %s
        ORDER BY cr.created_at DESC
        LIMIT 1
        """,
        (tenant_id, claim_id),
    )
    return rows[0] if rows else None


def get_next_claim_reference(tenant_id: str) -> str:
    """Generate the next atomic DC reference for this tenant in DC-YYYYMMDD-NNN format."""
    from datetime import datetime

    date_str = datetime.now(tz=UTC).strftime("%Y%m%d")
    seq = take_tenant_counter(tenant_id, f"damage_claim:{date_str}")
    return f"DC-{date_str}-{seq:03d}"


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
    if filters.get("created_after"):
        conditions.append("dc.created_at >= %(created_after)s")
        extra["created_after"] = filters["created_after"]
    if filters.get("created_before"):
        conditions.append("dc.created_at <= %(created_before)s")
        extra["created_before"] = filters["created_before"]
    if filters.get("q"):
        conditions.append("(dc.reference ILIKE %(q)s OR cu.name ILIKE %(q)s OR c.container_number ILIKE %(q)s)")
        extra["q"] = f"%{filters['q']}%"

    base = f"""
        SELECT dc.*,
               cu.name  AS customer_name,
               c.container_number
        FROM damage_claim dc
        LEFT JOIN customer  cu ON cu.id = dc.customer_id  AND cu.tenant_id = dc.tenant_id
        LEFT JOIN container c  ON c.id  = dc.container_id AND c.tenant_id  = dc.tenant_id
        WHERE {" AND ".join(conditions)}
    """
    query, params = build_paginated_query(base, cursor, limit, sort_field=f"dc.{sort_field}", sort_direction=sort_direction)
    params.update(extra)
    rows = execute_with_tenant(tenant_id, query, params)
    return extract_page(rows, limit, sort_field)


def get_claim_stats(tenant_id: str) -> dict[str, int]:
    """Tenant-wide damage-claim aggregates for the list stats row + status chips.

    SQL-computed over the whole table so figures stay correct at scale (the
    frontend previously counted a capped `limit: 500` sample).
    """
    rows = execute_with_tenant(
        tenant_id,
        """
        SELECT
            COUNT(*)                                                              AS total,
            COUNT(*) FILTER (WHERE status IN ('filed', 'under_inspection',
                                              'inspection_complete',
                                              'pending_resolution'))              AS open,
            COUNT(*) FILTER (WHERE status = 'under_inspection')                   AS under_inspection,
            COUNT(*) FILTER (WHERE status = 'resolved'
                             AND created_at > now() - interval '30 days')         AS resolved_30d,
            COUNT(*) FILTER (WHERE status = 'filed')                              AS filed,
            COUNT(*) FILTER (WHERE status = 'pending_resolution')                 AS pending_resolution,
            COUNT(*) FILTER (WHERE status = 'resolved')                           AS resolved,
            COUNT(*) FILTER (WHERE status = 'closed')                             AS closed
        FROM damage_claim
        WHERE tenant_id = %s
        """,
        (tenant_id,),
    )
    row = rows[0] if rows else {}
    keys = ("total", "open", "under_inspection", "resolved_30d", "filed", "pending_resolution", "resolved", "closed")
    return {k: int(row.get(k) or 0) for k in keys}


def update_claim_status(
    tenant_id: str,
    claim_id: str,
    status: str,
    extra: dict[str, Any] | None = None,
    allowed_from: list[str] | None = None,
) -> dict[str, Any] | None:
    """Update damage_claim status + optional extra fields (allowlisted).

    With ``allowed_from`` the update only applies if the claim is currently in one
    of those statuses, so two requests cannot both resolve it; ``None`` is returned
    when it is not (or the claim does not exist).
    """
    params: dict[str, Any] = {"status": status, "tenant_id": tenant_id, "id": claim_id}
    guard = ""
    if allowed_from is not None:
        guard = " AND status = ANY(%(allowed_from)s)"
        params["allowed_from"] = allowed_from
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
        WHERE tenant_id = %(tenant_id)s AND id = %(id)s{guard}
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

    Links damage_claim_id and requested_by so audit/deduplication/segregation-of-duties
    checks in the refunds service can trace back to the claim and actor.
    """
    params = {
        "damage_claim_id": None,
        "requested_by": None,
        **data,
    }
    return execute_write_with_tenant(
        tenant_id,
        """
        INSERT INTO refund_request (
            tenant_id, customer_id, billing_id, damage_claim_id,
            amount_ngn, reason, status, refund_type, requested_by
        ) VALUES (
            %(tenant_id)s, %(customer_id)s, %(billing_id)s, %(damage_claim_id)s,
            %(amount_ngn)s, %(reason)s, 'pending_review', 'damage_or_loss', %(requested_by)s
        ) RETURNING *
        """,
        params,
    )


def count_claim_evidence(claim_id: str, tenant_id: str | None = None) -> int:
    """Count evidence rows (confirmed or pending) attached to a claim."""
    if tenant_id:
        rows = execute_with_tenant(
            tenant_id,
            """
            SELECT COUNT(*) AS cnt
            FROM claim_evidence ce
            JOIN damage_claim dc ON dc.id = ce.damage_claim_id AND dc.tenant_id = %s
            WHERE ce.damage_claim_id = %s
            """,
            (tenant_id, claim_id),
        )
    else:
        rows = execute_with_tenant(
            PLATFORM_TENANT_ID,
            "SELECT COUNT(*) AS cnt FROM claim_evidence WHERE damage_claim_id = %s",
            (claim_id,),
        )
    return int(rows[0]["cnt"]) if rows else 0


# ---------------------------------------------------------------------------
# Claim evidence — scoped via damage_claim_id FK (tenant-scoped when tenant_id supplied)
# ---------------------------------------------------------------------------


def create_claim_evidence(data: dict[str, Any], tenant_id: str | None = None) -> dict[str, Any] | None:
    """Insert a claim_evidence record."""
    if tenant_id:
        return execute_write_with_tenant(
            tenant_id,
            """
            INSERT INTO claim_evidence (
                damage_claim_id, file_key, file_name,
                file_type, file_size_bytes, uploaded_by
            )
            SELECT
                dc.id, %(file_key)s, %(file_name)s,
                %(file_type)s, %(file_size_bytes)s, %(uploaded_by)s
            FROM damage_claim dc
            WHERE dc.id = %(damage_claim_id)s AND dc.tenant_id = %(tenant_id)s
            RETURNING *
            """,
            {**data, "tenant_id": tenant_id},
        )
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


def list_claim_evidence(claim_id: str, tenant_id: str | None = None) -> list[dict[str, Any]]:
    """The confirmed evidence files recorded against a claim, oldest first (an unconfirmed upload is not listed)."""
    if tenant_id:
        return execute_with_tenant(
            tenant_id,
            """
            SELECT ce.id, ce.file_key, ce.file_name, ce.file_type, ce.file_size_bytes, ce.created_at
            FROM claim_evidence ce
            JOIN damage_claim dc ON dc.id = ce.damage_claim_id AND dc.tenant_id = %s
            WHERE ce.damage_claim_id = %s AND ce.confirmed_at IS NOT NULL
            ORDER BY ce.created_at ASC
            """,
            (tenant_id, claim_id),
        )
    return execute_with_tenant(
        PLATFORM_TENANT_ID,
        """
        SELECT id, file_key, file_name, file_type, file_size_bytes, created_at
        FROM claim_evidence
        WHERE damage_claim_id = %s AND confirmed_at IS NOT NULL
        ORDER BY created_at ASC
        """,
        (claim_id,),
    )


def get_claim_evidence(claim_id: str, evidence_id: str, tenant_id: str | None = None) -> dict[str, Any] | None:
    """One evidence row of a claim, confirmed or not."""
    if tenant_id:
        rows = execute_with_tenant(
            tenant_id,
            """
            SELECT ce.*
            FROM claim_evidence ce
            JOIN damage_claim dc ON dc.id = ce.damage_claim_id AND dc.tenant_id = %s
            WHERE ce.damage_claim_id = %s AND ce.id = %s
            """,
            (tenant_id, claim_id, evidence_id),
        )
        return rows[0] if rows else None
    rows = execute_with_tenant(
        PLATFORM_TENANT_ID,
        "SELECT * FROM claim_evidence WHERE damage_claim_id = %s AND id = %s",
        (claim_id, evidence_id),
    )
    return rows[0] if rows else None


def confirm_claim_evidence(
    claim_id: str,
    evidence_id: str,
    size_bytes: int,
    tenant_id: str | None = None,
) -> dict[str, Any] | None:
    """Record the checked size and list the file. Confirming twice keeps the first time."""
    if tenant_id:
        return execute_write_with_tenant(
            tenant_id,
            """
            UPDATE claim_evidence ce
            SET file_size_bytes = %s, confirmed_at = COALESCE(ce.confirmed_at, NOW())
            FROM damage_claim dc
            WHERE dc.id = ce.damage_claim_id AND dc.tenant_id = %s
              AND ce.damage_claim_id = %s AND ce.id = %s
            RETURNING ce.*
            """,
            (size_bytes, tenant_id, claim_id, evidence_id),
        )
    return execute_write_with_tenant(
        PLATFORM_TENANT_ID,
        """
        UPDATE claim_evidence
        SET file_size_bytes = %s, confirmed_at = COALESCE(confirmed_at, NOW())
        WHERE damage_claim_id = %s AND id = %s
        RETURNING *
        """,
        (size_bytes, claim_id, evidence_id),
    )


def delete_unconfirmed_claim_evidence(
    claim_id: str,
    evidence_id: str,
    tenant_id: str | None = None,
) -> dict[str, Any] | None:
    """Drop the row of an upload that was refused at confirmation. A confirmed row is never deleted here."""
    if tenant_id:
        return execute_write_with_tenant(
            tenant_id,
            """
            DELETE FROM claim_evidence ce
            USING damage_claim dc
            WHERE dc.id = ce.damage_claim_id AND dc.tenant_id = %s
              AND ce.damage_claim_id = %s AND ce.id = %s AND ce.confirmed_at IS NULL
            RETURNING ce.id
            """,
            (tenant_id, claim_id, evidence_id),
        )
    return execute_write_with_tenant(
        PLATFORM_TENANT_ID,
        """
        DELETE FROM claim_evidence
        WHERE damage_claim_id = %s AND id = %s AND confirmed_at IS NULL
        RETURNING id
        """,
        (claim_id, evidence_id),
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
    conditions = ["m.tenant_id = %(tenant_id)s"]
    extra: dict[str, Any] = {"tenant_id": tenant_id}

    if filters.get("container_id"):
        # missing_item links to manifest; filter via joined manifest
        conditions.append("mf.container_id = %(container_id)s")
        extra["container_id"] = filters["container_id"]
    if filters.get("customer_id"):
        conditions.append("m.customer_id = %(customer_id)s")
        extra["customer_id"] = filters["customer_id"]
    if filters.get("status"):
        conditions.append("m.status = %(status)s")
        extra["status"] = filters["status"]

    base = (
        "SELECT m.*, c.name AS customer_name, ctn.container_number AS container_number "
        "FROM missing_item m "
        "LEFT JOIN customer c ON c.id = m.customer_id AND c.tenant_id = m.tenant_id "
        "LEFT JOIN manifest mf ON mf.id = m.manifest_id AND mf.tenant_id = m.tenant_id "
        "LEFT JOIN container ctn ON ctn.id = mf.container_id AND ctn.tenant_id = m.tenant_id "
        f"WHERE {' AND '.join(conditions)}"
    )
    query, params = build_paginated_query(base, cursor, limit, sort_field="m.created_at")
    params.update(extra)
    rows = execute_with_tenant(tenant_id, query, params)
    return extract_page(rows, limit)


def list_seized_items(
    tenant_id: str,
    filters: dict[str, Any],
    limit: int = 50,
    cursor: dict[str, Any] | None = None,
) -> tuple[list[dict[str, Any]], str | None, bool]:
    conditions = ["s.tenant_id = %(tenant_id)s"]
    extra: dict[str, Any] = {"tenant_id": tenant_id}

    if filters.get("container_id"):
        conditions.append("s.container_id = %(container_id)s")
        extra["container_id"] = filters["container_id"]
    if filters.get("customer_id"):
        conditions.append("s.customer_id = %(customer_id)s")
        extra["customer_id"] = filters["customer_id"]
    if filters.get("status"):
        conditions.append("s.recovery_status = %(status)s")
        extra["status"] = filters["status"]

    base = (
        "SELECT s.*, c.name AS customer_name, ctn.container_number AS container_number "
        "FROM seized_item s "
        "LEFT JOIN customer c ON c.id = s.customer_id AND c.tenant_id = s.tenant_id "
        "LEFT JOIN container ctn ON ctn.id = s.container_id AND ctn.tenant_id = s.tenant_id "
        f"WHERE {' AND '.join(conditions)}"
    )
    query, params = build_paginated_query(base, cursor, limit, sort_field="s.created_at")
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


def link_refund_to_missing_item(tenant_id: str, item_id: str, refund_request_id: str) -> dict[str, Any] | None:
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


def link_refund_to_seized_item(tenant_id: str, item_id: str, refund_request_id: str) -> dict[str, Any] | None:
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
    expected_status: str | None = None,
) -> dict[str, Any] | None:
    params: dict[str, Any] = {"status": status, "tenant_id": tenant_id, "id": item_id}
    guard = ""
    if expected_status is not None:
        guard = " AND status = %(expected_status)s"
        params["expected_status"] = expected_status
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
        WHERE tenant_id = %(tenant_id)s AND id = %(id)s{guard}
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
    expected_status: str | None = None,
) -> dict[str, Any] | None:
    params: dict[str, Any] = {"recovery_status": recovery_status, "tenant_id": tenant_id, "id": item_id}
    guard = ""
    if expected_status is not None:
        guard = " AND recovery_status = %(expected_status)s"
        params["expected_status"] = expected_status
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
        WHERE tenant_id = %(tenant_id)s AND id = %(id)s{guard}
        RETURNING *
        """,
        params,
    )
