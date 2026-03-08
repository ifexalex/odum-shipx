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

from shared.db import execute_with_tenant, execute_write_with_tenant
from shared.pagination import build_paginated_query, extract_page
from shared.tenant_context import PLATFORM_TENANT_ID

logger = logging.getLogger(__name__)

# Allowlist for dynamic extra fields in claim status update
_CLAIM_STATUS_EXTRA_FIELDS = frozenset(
    {"inspection_method", "reviewed_by", "reviewed_at"}
)

# Terminal states for missing item (set resolved_by / resolved_at)
_MISSING_TERMINAL = {"found_and_shipping", "confirmed_lost", "resolved"}

# Terminal states for seized item (set recovery_date)
_SEIZED_TERMINAL = {"recovered", "permanently_lost"}


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------


def get_customer_by_user_id(tenant_id: str, user_id: str) -> dict | None:
    rows = execute_with_tenant(
        tenant_id,
        "SELECT id, name FROM customer WHERE tenant_id = %s AND user_id = %s LIMIT 1",
        (tenant_id, user_id),
    )
    return rows[0] if rows else None


def get_dollar_rate(tenant_id: str) -> "Decimal":
    """Return the current USD→NGN exchange rate from tenant_config."""
    from decimal import Decimal as _Decimal
    rows = execute_with_tenant(
        tenant_id,
        """
        SELECT config_value FROM tenant_config
        WHERE tenant_id = %s AND config_key = 'dollar_rate' LIMIT 1
        """,
        (tenant_id,),
    )
    if not rows:
        return _Decimal("1550")
    val = rows[0]["config_value"]
    if isinstance(val, dict):
        return _Decimal(str(val.get("rate", "1550")))
    return _Decimal(str(val))


def get_billing_by_id(tenant_id: str, billing_id: str) -> dict | None:
    """Return a billing record by ID."""
    if not billing_id:
        return None
    rows = execute_with_tenant(
        tenant_id,
        "SELECT * FROM billing WHERE tenant_id = %s AND id = %s LIMIT 1",
        (tenant_id, billing_id),
    )
    return rows[0] if rows else None


def get_tenant_config_value(tenant_id: str, config_key: str) -> dict | None:
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


def create_damage_claim(tenant_id: str, data: dict) -> dict:
    return execute_write_with_tenant(
        tenant_id,
        """
        INSERT INTO damage_claim (
            tenant_id, customer_id, container_id,
            cartons_affected, description, status, submitted_by
        ) VALUES (
            %(tenant_id)s, %(customer_id)s, %(container_id)s,
            %(cartons_affected)s, %(description)s, %(status)s, %(submitted_by)s
        ) RETURNING *
        """,
        data,
    )


def get_damage_claim_by_id(tenant_id: str, claim_id: str) -> dict | None:
    rows = execute_with_tenant(
        tenant_id,
        "SELECT * FROM damage_claim WHERE tenant_id = %s AND id = %s LIMIT 1",
        (tenant_id, claim_id),
    )
    return rows[0] if rows else None


def list_damage_claims(
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
    if filters.get("customer_id"):
        conditions.append("customer_id = %(customer_id)s")
        extra["customer_id"] = filters["customer_id"]

    base = f"SELECT * FROM damage_claim WHERE {' AND '.join(conditions)}"
    query, params = build_paginated_query(base, cursor, limit, sort_field="created_at")
    params.update(extra)
    rows = execute_with_tenant(tenant_id, query, params)
    return extract_page(rows, limit)


def update_claim_status(
    tenant_id: str,
    claim_id: str,
    status: str,
    extra: dict | None = None,
) -> dict:
    """Update damage_claim status + optional extra fields (allowlisted)."""
    params: dict = {"status": status, "tenant_id": tenant_id, "id": claim_id}
    extra_clause = ""
    if extra:
        safe = {
            k: v for k, v in extra.items()
            if k in _CLAIM_STATUS_EXTRA_FIELDS and v is not None
        }
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


def get_claim_resolution(tenant_id: str, claim_id: str) -> dict | None:
    rows = execute_with_tenant(
        tenant_id,
        """
        SELECT * FROM claim_resolution
        WHERE tenant_id = %s AND damage_claim_id = %s
        LIMIT 1
        """,
        (tenant_id, claim_id),
    )
    return rows[0] if rows else None


def create_claim_resolution(tenant_id: str, data: dict) -> dict:
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


def create_refund_request_for_claim(tenant_id: str, data: dict) -> dict:
    return execute_write_with_tenant(
        tenant_id,
        """
        INSERT INTO refund_request (
            tenant_id, customer_id, billing_id,
            amount_ngn, reason, status
        ) VALUES (
            %(tenant_id)s, %(customer_id)s, %(billing_id)s,
            %(amount_ngn)s, %(reason)s, 'pending_review'
        ) RETURNING *
        """,
        data,
    )


# ---------------------------------------------------------------------------
# Claim evidence — NO RLS; scoped via damage_claim_id FK
# ---------------------------------------------------------------------------


def create_claim_evidence(data: dict) -> dict:
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
    filters: dict,
    limit: int = 50,
    cursor: dict | None = None,
) -> tuple[list[dict], str | None, bool]:
    conditions = ["tenant_id = %(tenant_id)s"]
    extra: dict = {"tenant_id": tenant_id}

    if filters.get("container_id"):
        # missing_item links to manifest; filter via subquery
        conditions.append(
            "manifest_id IN ("
            "SELECT id FROM manifest "
            "WHERE container_id = %(container_id)s AND tenant_id = %(tenant_id)s)"
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
    filters: dict,
    limit: int = 50,
    cursor: dict | None = None,
) -> tuple[list[dict], str | None, bool]:
    conditions = ["tenant_id = %(tenant_id)s"]
    extra: dict = {"tenant_id": tenant_id}

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


def create_missing_item(tenant_id: str, data: dict) -> dict:
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


def get_missing_item_by_id(tenant_id: str, item_id: str) -> dict | None:
    rows = execute_with_tenant(
        tenant_id,
        "SELECT * FROM missing_item WHERE tenant_id = %s AND id = %s LIMIT 1",
        (tenant_id, item_id),
    )
    return rows[0] if rows else None


def update_missing_item_status(
    tenant_id: str,
    item_id: str,
    status: str,
    notes: str | None = None,
    actor_id: str | None = None,
) -> dict:
    params: dict = {"status": status, "tenant_id": tenant_id, "id": item_id}
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


def create_seized_item(tenant_id: str, data: dict) -> dict:
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


def get_seized_item_by_id(tenant_id: str, item_id: str) -> dict | None:
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
) -> dict:
    from datetime import date
    params: dict = {"recovery_status": recovery_status, "tenant_id": tenant_id, "id": item_id}
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
