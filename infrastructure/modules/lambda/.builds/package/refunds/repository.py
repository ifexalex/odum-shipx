"""Database access layer for the Refunds service.

Pure SQL — no business logic.
All queries use parameterized statements (%s / %(name)s) — never f-strings on
user-supplied values.

Notes:
  - refund_request has RLS (tenant_id isolation).
  - billing has RLS.
  - carryover_ledger has RLS.
  - damage_claim has RLS.
"""

import logging
from decimal import Decimal

from shared.db import execute_with_tenant, execute_write_with_tenant
from shared.pagination import build_paginated_query, extract_page

logger = logging.getLogger(__name__)

# Allowlist for dynamic SET clauses in refund status updates
_STATUS_EXTRA_FIELDS = frozenset({
    "has_outstanding_debt",
    "outstanding_debt_ngn",
    "debt_check_passed",
    "debt_check_notes",
    "amount_approved_ngn",
    "approval_level",
    "approved_by",
    "approved_at",
    "rejected_by",
    "rejection_reason",
})


# ---------------------------------------------------------------------------
# Tenant / customer helpers
# ---------------------------------------------------------------------------


def get_customer_by_user_id(tenant_id: str, user_id: str) -> dict | None:
    rows = execute_with_tenant(
        tenant_id,
        "SELECT id FROM customer WHERE tenant_id = %s AND user_id = %s LIMIT 1",
        (tenant_id, user_id),
    )
    return rows[0] if rows else None


# ---------------------------------------------------------------------------
# Cross-service read helpers
# ---------------------------------------------------------------------------


def get_billing_by_id(tenant_id: str, billing_id: str) -> dict | None:
    rows = execute_with_tenant(
        tenant_id,
        "SELECT id, customer_id, balance_ngn FROM billing WHERE tenant_id = %s AND id = %s LIMIT 1",
        (tenant_id, billing_id),
    )
    return rows[0] if rows else None


def get_damage_claim_by_id(tenant_id: str, claim_id: str) -> dict | None:
    rows = execute_with_tenant(
        tenant_id,
        "SELECT id FROM damage_claim WHERE tenant_id = %s AND id = %s LIMIT 1",
        (tenant_id, claim_id),
    )
    return rows[0] if rows else None


# ---------------------------------------------------------------------------
# Refund request CRUD — tenant RLS scope
# ---------------------------------------------------------------------------


def create_refund_request(tenant_id: str, data: dict) -> dict:
    return execute_write_with_tenant(
        tenant_id,
        """
        INSERT INTO refund_request (
            tenant_id, customer_id, billing_id, damage_claim_id,
            refund_type, amount_ngn, reason, status,
            customer_choice, requested_by
        ) VALUES (
            %(tenant_id)s, %(customer_id)s, %(billing_id)s, %(damage_claim_id)s,
            %(refund_type)s, %(amount_ngn)s, %(reason)s, %(status)s,
            %(customer_choice)s, %(requested_by)s
        ) RETURNING *
        """,
        data,
    )


def get_refund_request_by_id(tenant_id: str, refund_id: str) -> dict | None:
    rows = execute_with_tenant(
        tenant_id,
        "SELECT * FROM refund_request WHERE tenant_id = %s AND id = %s LIMIT 1",
        (tenant_id, refund_id),
    )
    return rows[0] if rows else None


def list_refund_requests(
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

    base = f"SELECT * FROM refund_request WHERE {' AND '.join(conditions)}"
    query, params = build_paginated_query(base, cursor, limit, sort_field="created_at")
    params.update(extra)
    rows = execute_with_tenant(tenant_id, query, params)
    return extract_page(rows, limit)


def update_refund_status(
    tenant_id: str,
    refund_id: str,
    status: str,
    extra: dict | None = None,
) -> dict:
    """Update refund_request status + optional allowlisted extra fields."""
    params: dict = {"status": status, "tenant_id": tenant_id, "id": refund_id}
    extra_clause = ""
    if extra:
        safe = {
            k: v for k, v in extra.items()
            if k in _STATUS_EXTRA_FIELDS and v is not None
        }
        for key, val in safe.items():
            extra_clause += f", {key} = %({key})s"
            params[key] = val

    return execute_write_with_tenant(
        tenant_id,
        f"""
        UPDATE refund_request
        SET status = %(status)s, updated_at = NOW(){extra_clause}
        WHERE tenant_id = %(tenant_id)s AND id = %(id)s
        RETURNING *
        """,
        params,
    )


# ---------------------------------------------------------------------------
# Debt check helpers
# ---------------------------------------------------------------------------


def get_outstanding_carryovers_for_customer(
    tenant_id: str, customer_id: str
) -> list[dict]:
    return execute_with_tenant(
        tenant_id,
        """
        SELECT * FROM carryover_ledger
        WHERE tenant_id   = %s
          AND customer_id = %s
          AND status      = 'outstanding'
        ORDER BY created_at ASC
        """,
        (tenant_id, customer_id),
    )


def get_unpaid_billing_totals_for_customer(
    tenant_id: str, customer_id: str
) -> Decimal:
    """Sum balance_ngn (outstanding) across unpaid/partially_paid billing records."""
    rows = execute_with_tenant(
        tenant_id,
        """
        SELECT COALESCE(SUM(balance_ngn), 0) AS total_unpaid
        FROM billing
        WHERE tenant_id   = %s
          AND customer_id = %s
          AND status      IN ('unpaid', 'partially_paid')
        """,
        (tenant_id, customer_id),
    )
    return Decimal(str(rows[0]["total_unpaid"])) if rows else Decimal("0")


# ---------------------------------------------------------------------------
# Billing adjustment — on immediate refund approval
# ---------------------------------------------------------------------------


def reduce_billing_total(
    tenant_id: str, billing_id: str, reduction_amount
) -> dict:
    """Subtract reduction_amount from billing.total_ngn; balance_ngn is GENERATED."""
    return execute_write_with_tenant(
        tenant_id,
        """
        UPDATE billing
        SET total_ngn  = total_ngn - %(amount)s,
            updated_at = NOW()
        WHERE tenant_id = %(tenant_id)s AND id = %(id)s
        RETURNING *
        """,
        {
            "tenant_id": tenant_id,
            "id": billing_id,
            "amount": reduction_amount,
        },
    )


def create_overpayment_refund_request(tenant_id: str, data: dict) -> dict:
    return execute_write_with_tenant(
        tenant_id,
        """
        INSERT INTO refund_request (
            tenant_id, customer_id, billing_id, amount_ngn, reason, status
        ) VALUES (
            %(tenant_id)s, %(customer_id)s, %(billing_id)s,
            %(amount_ngn)s, %(reason)s, 'pending_review'
        ) RETURNING *
        """,
        data,
    )
