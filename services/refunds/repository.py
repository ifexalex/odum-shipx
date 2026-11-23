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
from typing import Any

from shared.billing_money import adjust_billing_and_refund_overpayment
from shared.db import execute_with_tenant, execute_write_with_tenant, tenant_transaction
from shared.encryption import decrypt_field
from shared.pagination import build_paginated_query, extract_page

logger = logging.getLogger(__name__)


def _decrypt_refund_row(row: dict[str, Any]) -> dict[str, Any]:
    """Decrypt sensitive bank-detail fields before returning a refund_request row.

    account_number / account_name / bank_name are encrypted at rest using
    envelope encryption (shared.encryption). This must be called on every
    row returned from refund_request SELECTs so callers always receive
    plaintext values.

    NOTE: When a "capture bank details" write path is added, the values
    MUST be passed through encrypt_field() before the INSERT/UPDATE.
    """
    return {
        **row,
        "account_number": decrypt_field(row.get("account_number")),
        "account_name": decrypt_field(row.get("account_name")),
    }


# Allowlist for dynamic SET clauses in refund status updates
_STATUS_EXTRA_FIELDS = frozenset(
    {
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
    }
)


# ---------------------------------------------------------------------------
# Tenant / customer helpers
# ---------------------------------------------------------------------------


def get_customer_by_user_id(tenant_id: str, user_id: str) -> dict[str, Any] | None:
    rows = execute_with_tenant(
        tenant_id,
        "SELECT id FROM customer WHERE tenant_id = %s AND user_id = %s LIMIT 1",
        (tenant_id, user_id),
    )
    return rows[0] if rows else None


# ---------------------------------------------------------------------------
# Cross-service read helpers
# ---------------------------------------------------------------------------


def get_billing_by_id(tenant_id: str, billing_id: str) -> dict[str, Any] | None:
    rows = execute_with_tenant(
        tenant_id,
        "SELECT id, customer_id, balance_ngn FROM billing WHERE tenant_id = %s AND id = %s LIMIT 1",
        (tenant_id, billing_id),
    )
    return rows[0] if rows else None


def get_damage_claim_by_id(tenant_id: str, claim_id: str) -> dict[str, Any] | None:
    rows = execute_with_tenant(
        tenant_id,
        "SELECT id FROM damage_claim WHERE tenant_id = %s AND id = %s LIMIT 1",
        (tenant_id, claim_id),
    )
    return rows[0] if rows else None


# ---------------------------------------------------------------------------
# Refund request CRUD — tenant RLS scope
# ---------------------------------------------------------------------------


def create_refund_request(tenant_id: str, data: dict[str, Any]) -> dict[str, Any]:
    row = execute_write_with_tenant(
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
    if row is None:
        return {}
    return _decrypt_refund_row(row)


def get_refund_request_by_id(tenant_id: str, refund_id: str) -> dict[str, Any] | None:
    rows = execute_with_tenant(
        tenant_id,
        "SELECT * FROM refund_request WHERE tenant_id = %s AND id = %s LIMIT 1",
        (tenant_id, refund_id),
    )
    return _decrypt_refund_row(rows[0]) if rows else None


def list_refund_requests(
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
    if filters.get("customer_id"):
        conditions.append("customer_id = %(customer_id)s")
        extra["customer_id"] = filters["customer_id"]

    base = f"SELECT * FROM refund_request WHERE {' AND '.join(conditions)}"
    query, params = build_paginated_query(base, cursor, limit, sort_field="created_at")
    params.update(extra)
    rows = execute_with_tenant(tenant_id, query, params)
    page, cursor_out, has_more = extract_page(rows, limit)
    return [_decrypt_refund_row(r) for r in page], cursor_out, has_more


def update_refund_status(
    tenant_id: str,
    refund_id: str,
    status: str,
    extra: dict[str, Any] | None = None,
    expected_status: str | None = None,
) -> dict[str, Any]:
    """Update refund_request status + optional allowlisted extra fields.

    With ``expected_status`` the update only applies if the refund is still in that
    status, so two requests cannot both move it. Returns ``{}`` when nothing was
    updated (not found, or no longer in ``expected_status``).
    """
    params: dict[str, Any] = {"status": status, "tenant_id": tenant_id, "id": refund_id}
    guard = ""
    if expected_status is not None:
        guard = " AND status = %(expected_status)s"
        params["expected_status"] = expected_status
    extra_clause = ""
    if extra:
        safe = {k: v for k, v in extra.items() if k in _STATUS_EXTRA_FIELDS and v is not None}
        for key, val in safe.items():
            extra_clause += f", {key} = %({key})s"
            params[key] = val

    row = execute_write_with_tenant(
        tenant_id,
        f"""
        UPDATE refund_request
        SET status = %(status)s, updated_at = NOW(){extra_clause}
        WHERE tenant_id = %(tenant_id)s AND id = %(id)s{guard}
        RETURNING *
        """,
        params,
    )
    if row is None:
        return {}
    return _decrypt_refund_row(row)


def approve_refund_and_adjust_billing(
    tenant_id: str,
    refund_id: str,
    final_status: str,
    extra: dict[str, Any],
    billing_id: str | None,
    reduction_ngn: Decimal | None,
) -> dict[str, Any]:
    """Approve a refund and, for an immediate refund, reduce what the invoice owes, atomically.

    The refund moves out of ``pending_approval`` only if it is still there, so two
    approvals cannot both reduce the invoice. The invoice reduction, its status
    recompute and any new overpayment refund commit with the approval; if any step
    fails none of them happen.

    Returns:
        The updated refund row, or ``{}`` if it is no longer ``pending_approval``.
    """
    with tenant_transaction(tenant_id):
        row = update_refund_status(tenant_id, refund_id, final_status, extra=extra, expected_status="pending_approval")
        if not row:
            return {}
        if reduction_ngn and billing_id:
            adjust_billing_and_refund_overpayment(
                tenant_id,
                billing_id,
                -reduction_ngn,
                f"Overpayment after refund adjustment on refund {refund_id}",
            )
    return row


# ---------------------------------------------------------------------------
# Debt check helpers
# ---------------------------------------------------------------------------


def get_outstanding_carryovers_for_customer(tenant_id: str, customer_id: str) -> list[dict[str, Any]]:
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


def get_unpaid_billing_totals_for_customer(tenant_id: str, customer_id: str) -> Decimal:
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
# Tenant config helpers
# ---------------------------------------------------------------------------


def get_refund_threshold_config(tenant_id: str) -> dict[str, Any]:
    """Return the refund threshold config from tenant_config.

    Reads the `refund_threshold_usd` config key. Returns a dict with key
    `staff_limit` (float, default 50). The dollar rate used to convert this
    into a NGN threshold is no longer tenant_config data — see
    shared.fx_rate.get_effective_dollar_rate, called separately by
    services/refunds/service.py.
    """
    rows = execute_with_tenant(
        tenant_id,
        """
        SELECT config_value
        FROM tenant_config
        WHERE tenant_id = %s AND config_key = 'refund_threshold_usd'
        LIMIT 1
        """,
        (tenant_id,),
    )
    threshold_cfg = rows[0]["config_value"] if rows else {}
    staff_limit = threshold_cfg.get("staff_limit", 50) if isinstance(threshold_cfg, dict) else 50
    return {"staff_limit": staff_limit}


# ---------------------------------------------------------------------------
# Billing adjustment — on immediate refund approval
# ---------------------------------------------------------------------------
