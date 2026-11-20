"""Business logic for the Refunds service.

Handles refund request creation (overpayment, CBM correction, damage/loss),
accounts review with debt check, tiered approval with role-based authority,
and credit application to future billing.
"""

import logging
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from shared.audit import log_audit
from shared.events import publish_event
from shared.exceptions import (
    ApprovalThresholdExceededError,
    IllegalTransitionError,
    InsufficientPermissionsError,
    ResourceNotFoundError,
)
from shared.fx_rate import get_effective_dollar_rate
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
    req: Any,
    actor_id: str,
    ctx: Any,
    request_id: str = "",
) -> dict[str, Any]:
    """Create a new refund request.

    Ground-truth gap found live via e2e testing: this endpoint's own role
    check (_CREATE_ROLES in handler.py) never included CUSTOMER, so
    RefundRequest.tsx's self-service "Request a Refund" flow — reachable
    from every customer's billing page — always 403'd with "Insufficient
    permissions." Behind that, this function would have failed anyway: it
    used req.customer_id unconditionally, but the frontend deliberately
    sends customer_id="" with the comment "Server derives from JWT for
    customer role" — a derivation that never existed here. Both are fixed
    together: the role is now allowed, and a CUSTOMER caller's identity is
    derived from ctx.user_id and verified to actually own the billing
    record being refunded, the same pattern services/claims/service.py
    uses for filing a claim.
    """
    if ctx.role == UserRole.CUSTOMER:
        customer = repo.get_customer_by_user_id(tenant_id, ctx.user_id)
        if not customer:
            raise ResourceNotFoundError("customer", ctx.user_id)
        customer_id = str(customer["id"])
    else:
        customer_id = req.customer_id

    if req.billing_id:
        billing = repo.get_billing_by_id(tenant_id, req.billing_id)
        if not billing:
            raise ResourceNotFoundError("billing", req.billing_id)
        if ctx.role == UserRole.CUSTOMER and str(billing["customer_id"]) != customer_id:
            # Without this, a customer could request a refund against any
            # billing record in the tenant by guessing/enumerating ids.
            raise ResourceNotFoundError("billing", req.billing_id)

    if req.damage_claim_id:
        claim = repo.get_damage_claim_by_id(tenant_id, req.damage_claim_id)
        if not claim:
            raise ResourceNotFoundError("damage_claim", req.damage_claim_id)

    customer_choice = None
    if req.customer_choice:
        customer_choice = req.customer_choice.value if hasattr(req.customer_choice, "value") else str(req.customer_choice)

    refund_type = req.refund_type.value if hasattr(req.refund_type, "value") else str(req.refund_type)

    refund = repo.create_refund_request(
        tenant_id,
        {
            "tenant_id": tenant_id,
            "customer_id": customer_id,
            "billing_id": req.billing_id,
            "damage_claim_id": req.damage_claim_id,
            "refund_type": refund_type,
            "amount_ngn": req.amount_requested_ngn,
            "reason": req.notes or "",
            "status": "pending_review",
            "customer_choice": customer_choice,
            "requested_by": actor_id,
            "bank_name": req.bank_name,
            "account_number": req.account_number,
            "account_name": req.account_name,
        },
    )

    log_audit(
        tenant_id=tenant_id,
        entity_type="refund_request",
        entity_id=str(refund["id"]),
        action="CREATE",
        actor_id=actor_id,
        actor_role=str(ctx.role),
        after_state={
            "refund_type": refund_type,
            "amount_ngn": str(req.amount_requested_ngn),
            "status": "pending_review",
            "customer_choice": customer_choice,
            # Masked: the audit log never holds bank details (CLAUDE.md).
            **({"bank_name": req.bank_name, "account_number": "***", "account_name": "***"} if req.account_number else {}),
        },
    )

    return _fmt_refund(refund)


# ---------------------------------------------------------------------------
# List / get
# ---------------------------------------------------------------------------


def list_refunds(
    tenant_id: str,
    ctx: Any,
    filters: dict[str, Any],
    limit: int,
    cursor: dict[str, Any] | None,
) -> tuple[list[dict[str, Any]], str | None, bool]:
    rows, next_cursor, has_more = repo.list_refund_requests(tenant_id, filters, limit, cursor)
    return [_fmt_refund(r) for r in rows], next_cursor, has_more


def get_refund(tenant_id: str, refund_id: str, ctx: Any) -> dict[str, Any]:
    refund = repo.get_refund_request_by_id(tenant_id, refund_id)
    if not refund:
        raise ResourceNotFoundError("refund_request", refund_id)

    if ctx.role == UserRole.CUSTOMER:
        customer = repo.get_customer_by_user_id(tenant_id, ctx.user_id)
        if not customer or str(customer["id"]) != str(refund["customer_id"]):
            raise InsufficientPermissionsError("Customers may only view their own refund requests")
        return _customer_view(_fmt_refund(refund), wrote_the_reason=str(refund.get("requested_by") or "") == ctx.user_id)

    result = _fmt_refund(refund)
    try:
        threshold_cfg = repo.get_refund_threshold_config(tenant_id)
        staff_limit_usd = Decimal(str(threshold_cfg.get("staff_limit", 50)))
        dollar_rate = get_effective_dollar_rate(tenant_id)["rate"]
        staff_limit_ngn = staff_limit_usd * dollar_rate
        amount = Decimal(str(refund["amount_ngn"]))
        result["threshold"] = {
            "staff_limit_usd": float(staff_limit_usd),
            "staff_limit_ngn": float(staff_limit_ngn),
            "dollar_rate": float(dollar_rate),
            "exceeds_staff_limit": amount > staff_limit_ngn,
        }
    except Exception as exc:
        logger.warning("Could not load threshold config for refund %s: %s", refund_id, exc)
        result["threshold"] = None
    return result


# ---------------------------------------------------------------------------
# Accounts review
# ---------------------------------------------------------------------------


def accounts_review(
    tenant_id: str,
    refund_id: str,
    req: Any,
    actor_id: str,
    ctx: Any,
) -> dict[str, Any]:
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
    carryover_total = sum(Decimal(str(c["carryover_amount_ngn"])) for c in carryovers)
    total_debt = carryover_total + unpaid_total
    has_debt = total_debt > Decimal("0")

    if req.debt_check_passed:
        new_status = "pending_approval"
        extra = {
            "has_outstanding_debt": has_debt,
            "outstanding_debt_ngn": total_debt,
            "debt_check_passed": True,
            "debt_check_notes": req.debt_check_notes,
        }
    else:
        new_status = "rejected"
        extra = {
            "has_outstanding_debt": has_debt,
            "outstanding_debt_ngn": total_debt,
            "debt_check_passed": False,
            "debt_check_notes": req.debt_check_notes,
            "rejected_by": actor_id,
            "rejection_reason": req.debt_check_notes,
        }

    updated = repo.update_refund_status(tenant_id, refund_id, new_status, extra=extra, expected_status="pending_review")
    if not updated:
        raise IllegalTransitionError(
            entity="refund_request",
            current_state="changed by another request",
            requested_state=new_status,
            allowed=["pending_review"],
        )

    log_audit(
        tenant_id=tenant_id,
        entity_type="refund_request",
        entity_id=refund_id,
        action="STATUS_CHANGE",
        actor_id=actor_id,
        actor_role=str(ctx.role),
        before_state={"status": "pending_review"},
        after_state={"status": new_status, "debt_check_passed": req.debt_check_passed},
    )

    return _fmt_refund(updated)


# ---------------------------------------------------------------------------
# Approve
# ---------------------------------------------------------------------------


def approve_refund(
    tenant_id: str,
    refund_id: str,
    req: Any,
    actor_id: str,
    ctx: Any,
    request_id: str = "",
) -> dict[str, Any]:
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
            raise InsufficientPermissionsError("CBM correction refunds require head_of_finance (tenant_admin) approval")
    elif refund_type == "damage_or_loss" and amount_ngn > _HOF_THRESHOLD_NGN:
        required_level = "head_of_finance"
        if ctx.role != UserRole.TENANT_ADMIN:
            raise InsufficientPermissionsError(
                f"Damage/loss refunds above {_HOF_THRESHOLD_NGN} NGN require head_of_finance (tenant_admin) approval"
            )
    else:
        # overpayment or small damage_or_loss — manager level, any approved role
        required_level = "manager"

    amount_approved = Decimal(str(req.amount_approved_ngn))

    # Enforce refund_threshold_usd.staff_limit from tenant config.
    # Staff (nigeria_office_staff) cannot approve above the configured USD limit;
    # only tenant_admin (head of finance) can override.
    if ctx.role == UserRole.NIGERIA_OFFICE_STAFF:
        try:
            threshold_cfg = repo.get_refund_threshold_config(tenant_id)
            staff_limit_usd = Decimal(str(threshold_cfg.get("staff_limit", 50)))
            dollar_rate = get_effective_dollar_rate(tenant_id)["rate"]
            staff_limit_ngn = staff_limit_usd * dollar_rate
            if amount_approved > staff_limit_ngn:
                raise ApprovalThresholdExceededError(
                    f"Refund of {amount_approved:.0f} NGN exceeds the staff approval limit "
                    f"({staff_limit_usd} USD / {staff_limit_ngn:.0f} NGN). "
                    "Escalate to tenant_admin for approval.",
                    staff_limit_usd=float(staff_limit_usd),
                    staff_limit_ngn=float(staff_limit_ngn),
                    dollar_rate=float(dollar_rate),
                    amount_ngn=float(amount_approved),
                )
        except ApprovalThresholdExceededError:
            raise
        except Exception as exc:
            logger.warning("Could not fetch refund threshold config for tenant %s: %s — skipping threshold check", tenant_id, exc)

    # Determine final status based on customer_choice
    customer_choice = refund.get("customer_choice") or ""
    final_status = "applied_as_credit" if customer_choice == "credit_next_shipment" else "processed"

    # The approval and, for an immediate refund, the reduction of what the invoice
    # owes (plus its status and any new overpayment refund) commit together, and only
    # if the refund is still pending_approval — two approvals cannot both reduce it.
    billing_id = str(refund["billing_id"]) if final_status == "processed" and refund.get("billing_id") else None
    now = datetime.now(UTC)
    updated = repo.approve_refund_and_adjust_billing(
        tenant_id,
        refund_id,
        final_status,
        extra={
            "amount_approved_ngn": amount_approved,
            "approval_level": required_level,
            "approved_by": actor_id,
            "approved_at": now,
        },
        billing_id=billing_id,
        reduction_ngn=amount_approved if billing_id else None,
    )
    if not updated:
        raise IllegalTransitionError(
            entity="refund_request",
            current_state="changed by another request",
            requested_state="approved",
            allowed=["pending_approval"],
        )

    log_audit(
        tenant_id=tenant_id,
        entity_type="refund_request",
        entity_id=refund_id,
        action="STATUS_CHANGE",
        actor_id=actor_id,
        actor_role=str(ctx.role),
        before_state={"status": "pending_approval"},
        after_state={"status": final_status, "amount_approved_ngn": str(amount_approved), "approval_level": required_level},
    )

    publish_event(
        source="logistics.refunds",
        detail_type="RefundApproved",
        tenant_id=tenant_id,
        payload={
            "refund_id": refund_id,
            "refund_type": refund_type,
            "amount_approved": str(amount_approved),
            "final_status": final_status,
            "customer_id": str(refund["customer_id"]),
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
    ctx: Any,
) -> dict[str, Any]:
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

    prev_status = refund["status"]
    updated = repo.update_refund_status(
        tenant_id,
        refund_id,
        "rejected",
        extra={
            "rejected_by": actor_id,
            "rejection_reason": rejection_reason,
        },
        expected_status=prev_status,
    )
    if not updated:
        raise IllegalTransitionError(
            entity="refund_request",
            current_state="changed by another request",
            requested_state="rejected",
            allowed=list(_REJECTABLE_STATES),
        )

    log_audit(
        tenant_id=tenant_id,
        entity_type="refund_request",
        entity_id=refund_id,
        action="STATUS_CHANGE",
        actor_id=actor_id,
        actor_role=str(ctx.role),
        before_state={"status": prev_status},
        after_state={"status": "rejected"},
    )

    return _fmt_refund(updated)


# ---------------------------------------------------------------------------
# Internal formatter
# ---------------------------------------------------------------------------

# Staff's working record of a refund: who signed it off and what the debt check found. Not the customer's to read.
_STAFF_ONLY_FIELDS = ("approval_level", "debt_check_passed", "debt_check_notes")


def _customer_view(refund: dict[str, Any], *, wrote_the_reason: bool) -> dict[str, Any]:
    """Returns a refund as its customer may read it.

    A refund raised from a claim decision carries what staff typed when deciding. That decision was in the
    customer's favour, so its reason stays internal (owner decision, 2026-11-17): the customer gets a reason back only
    when it is the one they wrote. A rejection is against them, so `rejection_reason` is always theirs to read.

    Args:
        refund: The formatted refund.
        wrote_the_reason: Whether this customer raised the request themselves.

    Returns:
        The refund without staff's working record, and with no approval threshold.
    """
    view = {**refund, **dict.fromkeys(_STAFF_ONLY_FIELDS), "threshold": None}
    if refund.get("bank_details"):
        number = str(refund["bank_details"].get("account_number") or "")
        view["bank_details"] = {**refund["bank_details"], "account_number": f"******{number[-4:]}" if number else None}
    if not wrote_the_reason:
        view["reason"] = None
    return view


def _fmt_refund(row: dict[str, Any]) -> dict[str, Any]:
    amount_approved = None
    if row.get("amount_approved_ngn") is not None:
        amount_approved = Decimal(str(row["amount_approved_ngn"]))

    return {
        "id": str(row["id"]),
        "status": row["status"],
        "refund_type": row.get("refund_type") or "",
        "amount_requested_ngn": Decimal(str(row["amount_ngn"])),
        "amount_approved_ngn": amount_approved,
        # For a refund taken as credit: how much of it invoices have used so far (the rest is still the customer's).
        "credit_applied_ngn": Decimal(str(row.get("credit_applied_ngn") or 0)),
        "customer_choice": row.get("customer_choice"),
        "customer_id": str(row["customer_id"]) if row.get("customer_id") else None,
        "billing_id": str(row["billing_id"]) if row.get("billing_id") else None,
        "damage_claim_id": str(row["damage_claim_id"]) if row.get("damage_claim_id") else None,
        # What the ids above are called, for the detail page (FD-17); absent on list rows, which do not join them.
        "customer_name": row.get("customer_name"),
        "invoice_number": row.get("invoice_number"),
        "claim_reference": row.get("claim_reference"),
        "reason": row.get("reason"),
        "rejection_reason": row.get("rejection_reason"),
        "approval_level": row.get("approval_level"),
        "debt_check_passed": row.get("debt_check_passed"),
        "debt_check_notes": row.get("debt_check_notes"),
        # Where a bank refund is paid: what accounts need to make the transfer. Customers see the number masked.
        "bank_details": (
            {
                "bank_name": row.get("bank_name"),
                "account_number": row.get("account_number"),
                "account_name": row.get("account_name"),
            }
            if row.get("account_number")
            else None
        ),
        "created_at": row["created_at"],
    }
