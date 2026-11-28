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

from shared.billing_money import settle_overpayment_refund
from shared.db import execute_with_tenant, execute_write_with_tenant, tenant_transaction
from shared.encryption import decrypt_field, encrypt_field
from shared.pagination import build_paginated_query, extract_page

logger = logging.getLogger(__name__)


def _decrypt_refund_row(row: dict[str, Any]) -> dict[str, Any]:
    """Decrypt sensitive bank-detail fields before returning a refund_request row.

    account_number / account_name are encrypted at rest using
    envelope encryption (shared.encryption). This must be called on every
    row returned from refund_request SELECTs so callers always receive
    plaintext values.

    account_number / account_name are written through encrypt_field() by
    create_refund_request (the customer refund form, 2026-11-19); bank_name is
    not sensitive and is stored as typed.
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
        "processed_by",
        "processed_at",
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
        """
        SELECT id, customer_id, status, total_ngn, amount_paid_ngn, balance_ngn
        FROM billing
        WHERE tenant_id = %s AND id = %s
        LIMIT 1
        """,
        (tenant_id, billing_id),
    )
    return rows[0] if rows else None


def get_damage_claim_by_id(tenant_id: str, claim_id: str) -> dict[str, Any] | None:
    rows = execute_with_tenant(
        tenant_id,
        "SELECT id, customer_id, status FROM damage_claim WHERE tenant_id = %s AND id = %s LIMIT 1",
        (tenant_id, claim_id),
    )
    return rows[0] if rows else None


def sum_active_refunds_for_billing(
    tenant_id: str,
    billing_id: str,
    *,
    refund_types: tuple[str, ...] | None = None,
) -> Decimal:
    """Sum non-rejected refund amounts already linked to a billing record."""
    if refund_types:
        rows = execute_with_tenant(
            tenant_id,
            """
            SELECT COALESCE(SUM(COALESCE(amount_approved_ngn, amount_ngn)), 0) AS total
            FROM refund_request
            WHERE tenant_id = %s AND billing_id = %s AND status != 'rejected'
              AND refund_type = ANY(%s)
            """,
            (tenant_id, billing_id, list(refund_types)),
        )
    else:
        rows = execute_with_tenant(
            tenant_id,
            """
            SELECT COALESCE(SUM(COALESCE(amount_approved_ngn, amount_ngn)), 0) AS total
            FROM refund_request
            WHERE tenant_id = %s AND billing_id = %s AND status != 'rejected'
            """,
            (tenant_id, billing_id),
        )
    return Decimal(str(rows[0]["total"])) if rows else Decimal("0")


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
            customer_choice, requested_by,
            bank_name, account_number, account_name
        ) VALUES (
            %(tenant_id)s, %(customer_id)s, %(billing_id)s, %(damage_claim_id)s,
            %(refund_type)s, %(amount_ngn)s, %(reason)s, %(status)s,
            %(customer_choice)s, %(requested_by)s,
            %(bank_name)s, %(account_number)s, %(account_name)s
        ) RETURNING *
        """,
        {
            "bank_name": None,
            **data,
            # PII: encrypted at rest (migration 013, widened to TEXT by 071).
            "account_number": encrypt_field(data.get("account_number")),
            "account_name": encrypt_field(data.get("account_name")),
        },
    )
    if row is None:
        return {}
    return _decrypt_refund_row(row)


def get_refund_request_by_id(tenant_id: str, refund_id: str) -> dict[str, Any] | None:
    """One refund request, with the names a reader needs instead of ids (FD-17).

    Joins the customer's name, the invoice number and the damage claim's reference, each scoped to the same tenant, so
    the detail page shows "Ngozi Adeyemi", "INV-A-002" and "DC-20261113-001" rather than three UUIDs.
    """
    rows = execute_with_tenant(
        tenant_id,
        """
        SELECT r.*,
               c.name          AS customer_name,
               b.invoice_number AS invoice_number,
               d.reference     AS claim_reference
          FROM refund_request r
          LEFT JOIN customer c ON c.id = r.customer_id AND c.tenant_id = r.tenant_id
          LEFT JOIN billing b ON b.id = r.billing_id AND b.tenant_id = r.tenant_id
          LEFT JOIN damage_claim d ON d.id = r.damage_claim_id AND d.tenant_id = r.tenant_id
         WHERE r.tenant_id = %s AND r.id = %s
         LIMIT 1
        """,
        (tenant_id, refund_id),
    )
    return _decrypt_refund_row(rows[0]) if rows else None


def list_refund_requests(
    tenant_id: str,
    filters: dict[str, Any],
    limit: int = 50,
    cursor: dict[str, Any] | None = None,
) -> tuple[list[dict[str, Any]], str | None, bool]:
    conditions = ["r.tenant_id = %(tenant_id)s"]
    extra: dict[str, Any] = {"tenant_id": tenant_id}

    if filters.get("status"):
        conditions.append("r.status = %(status)s")
        extra["status"] = filters["status"]
    if filters.get("customer_id"):
        conditions.append("r.customer_id = %(customer_id)s")
        extra["customer_id"] = filters["customer_id"]

    base = (
        "SELECT r.*, c.name AS customer_name, b.invoice_number AS invoice_number, d.reference AS claim_reference "
        "FROM refund_request r "
        "LEFT JOIN customer c ON c.id = r.customer_id AND c.tenant_id = r.tenant_id "
        "LEFT JOIN billing b ON b.id = r.billing_id AND b.tenant_id = r.tenant_id "
        "LEFT JOIN damage_claim d ON d.id = r.damage_claim_id AND d.tenant_id = r.tenant_id "
        f"WHERE {' AND '.join(conditions)}"
    )
    query, params = build_paginated_query(base, cursor, limit, sort_field="r.created_at")
    params.update(extra)
    rows = execute_with_tenant(tenant_id, query, params)
    page, cursor_out, has_more = extract_page(rows, limit)
    # Never bulk-decrypt bank PII on list views (avoids 2*N KMS decrypts & bulk PII exposure).
    sanitized = [{**r, "account_number": None, "account_name": None} for r in page]
    return sanitized, cursor_out, has_more


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
    """Approve a refund and, for an overpayment/CBM-correction refund, settle excess cash atomically.

    The refund moves out of ``pending_approval`` only if it is still there, so two
    approvals cannot both settle the invoice. For overpayment/CBM-correction refunds,
    ``settle_overpayment_refund`` reduces ``amount_paid_ngn`` by at most the current
    overpayment excess (flipping ``overpaid`` back to ``paid``) without modifying
    ``total_ngn`` or spawning a cascading overpayment refund.

    Returns:
        The updated refund row, or ``{}`` if it is no longer ``pending_approval``.
    """
    with tenant_transaction(tenant_id):
        row = update_refund_status(tenant_id, refund_id, final_status, extra=extra, expected_status="pending_approval")
        if not row:
            return {}
        if reduction_ngn and billing_id:
            settled = settle_overpayment_refund(tenant_id, billing_id, reduction_ngn)
            if settled is None:
                raise RuntimeError(f"billing {billing_id} not found in tenant")
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
    """Return the effective refund threshold policy for today.

    Resolves ``refund_threshold_usd`` through ``shared.tenant_policies`` so
    effective-dated changes in ``tenant_policy_history`` apply automatically.
    """
    from shared.tenant_policies import resolve_policy_for_date

    threshold_cfg = resolve_policy_for_date(tenant_id, "refund_threshold_usd")
    staff_limit = threshold_cfg.get("staff_limit", 50) if isinstance(threshold_cfg, dict) else 50
    return {"staff_limit": staff_limit}


# ---------------------------------------------------------------------------
# Billing adjustment — on immediate refund approval
# ---------------------------------------------------------------------------
