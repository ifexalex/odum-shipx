"""Business logic for the Refunds service.

Handles refund request creation (overpayment, CBM correction, damage/loss),
accounts review with debt check, tiered approval with role-based authority,
and credit application to future billing.
"""

import logging
from datetime import datetime, timezone
from decimal import Decimal

from shared.events import publish_event
from shared.exceptions import (
    BusinessRuleViolationError,
    IllegalTransitionError,
    InsufficientPermissionsError,
    ResourceNotFoundError,
)
from shared.tenant_context import UserRole

from . import repository as repo

logger = logging.getLogger(__name__)

# Threshold for damage_or_loss: above this requires head_of_finance (tenant_admin)
_HOF_THRESHOLD_NGN = Decimal("30000")  # ~$50 USD at typical NGN/USD rates

# States from which a rejection is allowed
_REJECTABLE_STATES = {"pending_review", "pending_approval"}


# ---------------------------------------------------------------------------
# Create refund request
# ---------------------------------------------------------------------------


def create_refund(
    tenant_id: str,
    req,
    actor_id: str,
    ctx,
    request_id: str = "",
) -> dict:
    """Create a new refund request."""
    if req.billing_id:
        billing = repo.get_billing_by_id(tenant_id, req.billing_id)
        if not billing:
            raise ResourceNotFoundError("billing", req.billing_id)
        customer_id = req.customer_id
    else:
        customer_id = req.customer_id

    if req.damage_claim_id:
        claim = repo.get_damage_claim_by_id(tenant_id, req.damage_claim_id)
        if not claim:
            raise ResourceNotFoundError("damage_claim", req.damage_claim_id)

    customer_choice = None
    if req.customer_choice:
        customer_choice = (
            req.customer_choice.value
            if hasattr(req.customer_choice, "value")
            else str(req.customer_choice)
        )

    refund_type = (
        req.refund_type.value
        if hasattr(req.refund_type, "value")
        else str(req.refund_type)
    )

    refund = repo.create_refund_request(
        tenant_id,
        {
            "tenant_id":          tenant_id,
            "customer_id":        customer_id,
            "billing_id":         req.billing_id,
            "damage_claim_id":    req.damage_claim_id,
            "refund_type":        refund_type,
            "amount_ngn":         req.amount_requested_ngn,
            "reason":             req.notes or "",
            "status":             "pending_review",
            "customer_choice":    customer_choice,
            "requested_by":       actor_id,
        },
    )

    return _fmt_refund(refund)


# ---------------------------------------------------------------------------
# List / get
# ---------------------------------------------------------------------------


def list_refunds(
    tenant_id: str,
    ctx,
    filters: dict,
    limit: int,
    cursor: dict | None,
) -> tuple[list[dict], str | None, bool]:
    rows, next_cursor, has_more = repo.list_refund_requests(
        tenant_id, filters, limit, cursor
    )
    return [_fmt_refund(r) for r in rows], next_cursor, has_more


def get_refund(tenant_id: str, refund_id: str, ctx) -> dict:
    refund = repo.get_refund_request_by_id(tenant_id, refund_id)
    if not refund:
        raise ResourceNotFoundError("refund_request", refund_id)

    if ctx.role == UserRole.CUSTOMER:
        customer = repo.get_customer_by_user_id(tenant_id, ctx.user_id)
        if not customer or str(customer["id"]) != str(refund["customer_id"]):
            raise InsufficientPermissionsError(
                "Customers may only view their own refund requests"
            )

    return _fmt_refund(refund)


# ---------------------------------------------------------------------------
# Accounts review
# ---------------------------------------------------------------------------


def accounts_review(
    tenant_id: str,
    refund_id: str,
    req,
    actor_id: str,
    ctx,
) -> dict:
    """Accounts team reviews debt and decides whether to advance the refund."""
    refund = repo.get_refund_request_by_id(tenant_id, refund_id)
    if not refund:
        raise ResourceNotFoundError("refund_request", refund_id)

    if refund["status"] != "pending_review":
        raise IllegalTransitionError(
            entity="refund_request",
            current_state=refund["status"],
            requested_state="pending_approval",
            allowed=["pending_review"],
        )

    # Query customer's current debt
    customer_id = str(refund["customer_id"])
    carryovers = repo.get_outstanding_carryovers_for_customer(tenant_id, customer_id)
    unpaid_total = repo.get_unpaid_billing_totals_for_customer(tenant_id, customer_id)
    carryover_total = sum(
        Decimal(str(c["carryover_amount_ngn"])) for c in carryovers
    )
    total_debt = carryover_total + unpaid_total
    has_debt = total_debt > Decimal("0")

    if req.debt_check_passed:
        new_status = "pending_approval"
        extra = {
            "has_outstanding_debt": has_debt,
            "outstanding_debt_ngn": total_debt,
            "debt_check_passed":    True,
            "debt_check_notes":     req.debt_check_notes,
        }
    else:
        new_status = "rejected"
        extra = {
            "has_outstanding_debt": has_debt,
            "outstanding_debt_ngn": total_debt,
            "debt_check_passed":    False,
            "debt_check_notes":     req.debt_check_notes,
            "rejected_by":          actor_id,
            "rejection_reason":     req.debt_check_notes,
        }

    updated = repo.update_refund_status(tenant_id, refund_id, new_status, extra=extra)
    return _fmt_refund(updated)


# ---------------------------------------------------------------------------
# Approve
# ---------------------------------------------------------------------------


def approve_refund(
    tenant_id: str,
    refund_id: str,
    req,
    actor_id: str,
    ctx,
    request_id: str = "",
) -> dict:
    """Approve a refund request with role-based authority enforcement."""
    refund = repo.get_refund_request_by_id(tenant_id, refund_id)
    if not refund:
        raise ResourceNotFoundError("refund_request", refund_id)

    if refund["status"] != "pending_approval":
        raise IllegalTransitionError(
            entity="refund_request",
            current_state=refund["status"],
            requested_state="approved",
            allowed=["pending_approval"],
        )

    refund_type = refund.get("refund_type") or ""
    amount_ngn = Decimal(str(refund["amount_ngn"]))

    # Determine required approval level and enforce role
    if refund_type == "cbm_correction":
        required_level = "head_of_finance"
        if ctx.role != UserRole.TENANT_ADMIN:
            raise InsufficientPermissionsError(
                "CBM correction refunds require head_of_finance (tenant_admin) approval"
            )
    elif refund_type == "damage_or_loss" and amount_ngn > _HOF_THRESHOLD_NGN:
        required_level = "head_of_finance"
        if ctx.role != UserRole.TENANT_ADMIN:
            raise InsufficientPermissionsError(
                f"Damage/loss refunds above {_HOF_THRESHOLD_NGN} NGN require "
                "head_of_finance (tenant_admin) approval"
            )
    else:
        # overpayment or small damage_or_loss — manager level, any approved role
        required_level = "manager"

    amount_approved = Decimal(str(req.amount_approved_ngn))

    # Determine final status based on customer_choice
    customer_choice = refund.get("customer_choice") or ""
    if customer_choice == "credit_next_shipment":
        final_status = "applied_as_credit"
    else:
        final_status = "processed"

    # On immediate refund: adjust billing total if billing_id exists
    if final_status == "processed" and refund.get("billing_id"):
        billing_id = str(refund["billing_id"])
        updated_billing = repo.reduce_billing_total(
            tenant_id, billing_id, amount_approved
        )
        # Create new overpayment refund if reduction caused new negative balance
        new_balance = Decimal(str(updated_billing.get("balance_ngn", "0")))
        if new_balance < Decimal("-0.01"):
            overpayment = abs(new_balance)
            repo.create_overpayment_refund_request(
                tenant_id,
                {
                    "tenant_id":   tenant_id,
                    "customer_id": str(refund["customer_id"]),
                    "billing_id":  billing_id,
                    "amount_ngn":  overpayment,
                    "reason":      f"Overpayment after refund adjustment on refund {refund_id}",
                },
            )

    now = datetime.now(timezone.utc)
    updated = repo.update_refund_status(
        tenant_id,
        refund_id,
        final_status,
        extra={
            "amount_approved_ngn": amount_approved,
            "approval_level":      required_level,
            "approved_by":         actor_id,
            "approved_at":         now,
        },
    )

    publish_event(
        source="logistics.refunds",
        detail_type="RefundApproved",
        tenant_id=tenant_id,
        payload={
            "refund_id":       refund_id,
            "refund_type":     refund_type,
            "amount_approved": str(amount_approved),
            "final_status":    final_status,
            "customer_id":     str(refund["customer_id"]),
        },
        request_id=request_id,
    )

    return _fmt_refund(updated)


# ---------------------------------------------------------------------------
# Reject
# ---------------------------------------------------------------------------


def reject_refund(
    tenant_id: str,
    refund_id: str,
    rejection_reason: str,
    actor_id: str,
    ctx,
) -> dict:
    refund = repo.get_refund_request_by_id(tenant_id, refund_id)
    if not refund:
        raise ResourceNotFoundError("refund_request", refund_id)

    if refund["status"] not in _REJECTABLE_STATES:
        raise IllegalTransitionError(
            entity="refund_request",
            current_state=refund["status"],
            requested_state="rejected",
            allowed=list(_REJECTABLE_STATES),
        )

    updated = repo.update_refund_status(
        tenant_id,
        refund_id,
        "rejected",
        extra={
            "rejected_by":      actor_id,
            "rejection_reason": rejection_reason,
        },
    )
    return _fmt_refund(updated)


# ---------------------------------------------------------------------------
# Internal formatter
# ---------------------------------------------------------------------------


def _fmt_refund(row: dict) -> dict:
    amount_approved = None
    if row.get("amount_approved_ngn") is not None:
        amount_approved = Decimal(str(row["amount_approved_ngn"]))

    return {
        "id":                   str(row["id"]),
        "status":               row["status"],
        "refund_type":          row.get("refund_type") or "",
        "amount_requested_ngn": Decimal(str(row["amount_ngn"])),
        "amount_approved_ngn":  amount_approved,
        "customer_choice":      row.get("customer_choice"),
        "created_at":           row["created_at"],
    }
