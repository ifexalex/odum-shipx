"""Business logic for the Payment Release service.

Handles payment confirmation against billing records, release note generation
(full and partial), warehouse pickup recording with delegate support, and
carryover ledger creation when releasing with outstanding balances.
"""

import logging
from datetime import UTC, date, datetime
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

_TOLERANCE = Decimal("0.01")


# ---------------------------------------------------------------------------
# Payment confirmation
# ---------------------------------------------------------------------------


def confirm_payment(
    tenant_id: str,
    billing_id: str,
    req,
    actor_id: str,
    ctx,
    request_id: str = "",
) -> dict:
    """Record a payment and update billing status."""
    billing = repo.get_billing_by_id(tenant_id, billing_id)
    if not billing:
        raise ResourceNotFoundError("billing", billing_id)

    amount_ngn = Decimal(str(req.amount_ngn))
    current_paid = Decimal(str(billing["amount_paid_ngn"]))
    total_due = Decimal(str(billing["total_ngn"]))

    new_paid = current_paid + amount_ngn
    new_balance = total_due - new_paid

    if abs(new_balance) <= _TOLERANCE:
        new_status = "paid"
    elif new_balance < -_TOLERANCE:
        new_status = "overpaid"
    else:
        new_status = "partially_paid"

    delegate_id_type = (
        req.delegate_id_type.value
        if hasattr(req, "delegate_id_type") and req.delegate_id_type and hasattr(req.delegate_id_type, "value")
        else getattr(req, "delegate_id_type", None)
    )

    payment = repo.create_payment_record(
        tenant_id,
        {
            "tenant_id":        tenant_id,
            "billing_id":       billing_id,
            "amount_ngn":       amount_ngn,
            "payment_method":   req.payment_method,
            "reference_number": req.payment_reference,
            "payment_date":     date.today(),
            "recorded_by":      actor_id,
        },
    )

    updated_billing = repo.update_billing_payment(
        tenant_id, billing_id, amount_ngn, new_status
    )

    if new_status == "overpaid":
        overpayment = abs(new_balance)
        repo.create_overpayment_refund_request(
            tenant_id,
            {
                "tenant_id":   tenant_id,
                "customer_id": str(billing["customer_id"]),
                "billing_id":  billing_id,
                "amount_ngn":  overpayment,
                "reason":      f"Overpayment on invoice {billing.get('invoice_number', billing_id)}",
            },
        )

    publish_event(
        source="logistics.payment_release",
        detail_type="PaymentConfirmed",
        tenant_id=tenant_id,
        payload={
            "payment_id": str(payment["id"]),
            "billing_id": billing_id,
            "amount_ngn": str(amount_ngn),
            "new_status": new_status,
        },
        request_id=request_id,
    )

    confirmed_at = payment.get("created_at") or datetime.now(UTC)
    outstanding = Decimal(str(updated_billing["balance_ngn"]))

    return {
        "payment_id":            str(payment["id"]),
        "billing_id":            billing_id,
        "amount_ngn":            amount_ngn,
        "new_payment_status":    new_status,
        "outstanding_ngn":       outstanding,
        "release_note_available": new_status in {"paid", "overpaid"},
        "confirmed_at":          confirmed_at,
    }


# ---------------------------------------------------------------------------
# Release note generation
# ---------------------------------------------------------------------------


def generate_release_note(
    tenant_id: str,
    req,
    actor_id: str,
    ctx,
    request_id: str = "",
) -> dict:
    """Generate a release note for a customer's cartons.

    Enforces payment rules (BR-BL-002, BR-BL-003, BR-BL-004).
    """
    billing = repo.get_billing_by_id(tenant_id, req.billing_id)
    if not billing:
        raise ResourceNotFoundError("billing", req.billing_id)

    payment_status = billing["status"]
    amount_paid = Decimal(str(billing["amount_paid_ngn"]))
    total_due = Decimal(str(billing["total_ngn"]))
    total_cbm = Decimal(str(billing["total_cbm"] or "0"))

    # Payment check
    if payment_status in {"paid", "overpaid"}:
        pass  # fully paid — always allow
    elif payment_status == "partially_paid":
        if not req.release_with_outstanding:
            # Partial release: check proportional CBM payment
            selected_cbm = repo.get_cbm_for_carton_tags(
                tenant_id,
                str(billing["customer_id"]),
                str(billing["container_id"]),
                list(req.carton_tags),
            )
            if total_cbm > Decimal("0"):
                required_payment = (selected_cbm / total_cbm) * total_due
            else:
                required_payment = total_due
            if amount_paid < required_payment - _TOLERANCE:
                raise BusinessRuleViolationError(
                    f"Insufficient payment for requested cartons. "
                    f"Required: {required_payment:.2f} NGN, Paid: {amount_paid:.2f} NGN",
                    rule_id="PAYMENT_REQUIRED",
                )
    elif payment_status == "unpaid":
        if not req.release_with_outstanding:
            raise BusinessRuleViolationError(
                "Payment is required before generating a release note",
                rule_id="PAYMENT_REQUIRED",
            )
    # released_with_outstanding, waived — pass through

    if req.release_with_outstanding:
        if not req.approval_notes:
            raise BusinessRuleViolationError(
                "approval_notes is required when releasing with outstanding balance",
                rule_id="APPROVAL_NOTES_REQUIRED",
            )
        balance = Decimal(str(billing["balance_ngn"]))
        repo.mark_billing_released_with_outstanding(tenant_id, req.billing_id)
        if balance > Decimal("0"):
            repo.create_carryover_entry(
                tenant_id,
                {
                    "tenant_id":             tenant_id,
                    "customer_id":           str(billing["customer_id"]),
                    "source_billing_id":     req.billing_id,
                    "carryover_amount_ngn":  balance,
                    "notes":                 req.approval_notes,
                    "created_by":            actor_id,
                },
            )

    tenant_short = repo.get_tenant_short(tenant_id)
    seq = repo.get_next_release_note_seq(tenant_id)
    reference_number = f"{tenant_short}-RN-{date.today():%Y%m%d}-{seq:04d}"

    total_cartons_for_customer = int(billing["total_cartons"] or 0)
    carton_tags = list(req.carton_tags)
    is_partial = len(carton_tags) < total_cartons_for_customer

    note = repo.create_release_note(
        tenant_id,
        {
            "tenant_id":        tenant_id,
            "billing_id":       req.billing_id,
            "customer_id":      str(billing["customer_id"]),
            "container_id":     str(billing["container_id"]),
            "reference_number": reference_number,
            "carton_tags":      carton_tags,
            "total_cartons":    len(carton_tags),
            "is_partial":       is_partial,
            "status":           "active",
            "issued_by":        actor_id,
            "notes":            getattr(req, "approval_notes", None),
        },
    )

    publish_event(
        source="logistics.payment_release",
        detail_type="ReleaseNoteGenerated",
        tenant_id=tenant_id,
        payload={
            "release_note_id":  str(note["id"]),
            "reference_number": reference_number,
            "billing_id":       req.billing_id,
            "customer_id":      str(billing["customer_id"]),
            "is_partial":       is_partial,
        },
        request_id=request_id,
    )

    return _fmt_release_note(note, billing, total_cartons_for_customer)


# ---------------------------------------------------------------------------
# Release note read
# ---------------------------------------------------------------------------


def get_release_note(tenant_id: str, note_id: str, ctx) -> dict:
    note = repo.get_release_note_by_id(tenant_id, note_id)
    if not note:
        raise ResourceNotFoundError("release_note", note_id)

    if ctx.role == UserRole.CUSTOMER:
        customer = repo.get_customer_by_user_id(tenant_id, ctx.user_id)
        if not customer or str(customer["id"]) != str(note["customer_id"]):
            raise InsufficientPermissionsError(
                "Customers may only view their own release notes"
            )

    total_cartons_for_customer = int(note.get("billing_total_cartons") or 0)
    return _fmt_release_note(note, note, total_cartons_for_customer)


# ---------------------------------------------------------------------------
# Pickup recording
# ---------------------------------------------------------------------------


def record_pickup(
    tenant_id: str,
    note_id: str,
    req,
    actor_id: str,
    ctx,
    request_id: str = "",
) -> dict:
    """Record warehouse pickup for a release note."""
    note = repo.get_release_note_by_id(tenant_id, note_id)
    if not note:
        raise ResourceNotFoundError("release_note", note_id)

    if note["status"] != "active":
        raise IllegalTransitionError(
            entity="release_note",
            current_state=note["status"],
            requested_state="picked_up",
            allowed=["active"],
        )

    if req.is_delegate:
        missing = [
            field for field, val in [
                ("delegate_name",      req.delegate_name),
                ("delegate_phone",     req.delegate_phone),
                ("delegate_id_type",   req.delegate_id_type),
                ("delegate_id_number", req.delegate_id_number),
            ]
            if not val
        ]
        if missing:
            raise BusinessRuleViolationError(
                f"Delegate details required: {', '.join(missing)}",
                rule_id="DELEGATE_DETAILS_REQUIRED",
            )

    delegate_id_type_val = None
    if req.delegate_id_type:
        delegate_id_type_val = (
            req.delegate_id_type.value
            if hasattr(req.delegate_id_type, "value")
            else str(req.delegate_id_type)
        )

    pickup = repo.create_pickup_record(
        tenant_id,
        {
            "tenant_id":          tenant_id,
            "release_note_id":    note_id,
            "customer_id":        str(note["customer_id"]),
            "carton_tags_picked": [],
            "cartons_count":      req.cartons_released,
            "pickup_date":        date.today(),
            "is_delegate":        req.is_delegate,
            "delegate_name":      req.delegate_name,
            "delegate_phone":     req.delegate_phone,
            "id_type":            delegate_id_type_val,
            "id_number":          req.delegate_id_number,
            "received_by":        actor_id,
            "notes":              req.notes,
        },
    )

    # Determine new release note status
    total_picked = repo.sum_cartons_picked_for_release_note(tenant_id, note_id)
    note_total = int(note["total_cartons"] or 0)

    if total_picked >= note_total:
        repo.update_release_note_status(tenant_id, note_id, "picked_up")
        note_status = "picked_up"
    else:
        note_status = "active"

    # Update shipment_tracking if all customer cartons released
    customer_total = int(note.get("billing_total_cartons") or 0)
    customer_released = repo.sum_cartons_released_for_customer(
        tenant_id, str(note["customer_id"]), str(note["container_id"])
    )
    shipment_status = None
    if customer_total > 0 and customer_released >= customer_total:
        repo.update_shipment_tracking_for_customer(
            tenant_id, str(note["customer_id"]), str(note["container_id"]), "picked_up"
        )
        shipment_status = "picked_up"

    # Update container to fully_released if all customers done
    container_total = repo.sum_total_cartons_from_billing(
        tenant_id, str(note["container_id"])
    )
    container_released = repo.sum_cartons_released_for_container(
        tenant_id, str(note["container_id"])
    )
    if container_total > 0 and container_released >= container_total:
        repo.update_container_status(
            tenant_id, str(note["container_id"]), "fully_released"
        )

    remaining = max(0, note_total - total_picked)

    pickup_time = None
    created_at = pickup.get("created_at")
    if created_at and hasattr(created_at, "strftime"):
        pickup_time = created_at.strftime("%H:%M")

    return {
        "release_note_id":     note_id,
        "release_note_status": note_status,
        "pickup_record_id":    str(pickup["id"]),
        "pickup_date":         pickup["pickup_date"],
        "pickup_time":         pickup_time,
        "attendant_name":      None,
        "remaining_cartons":   remaining,
        "shipment_status":     shipment_status,
    }


# ---------------------------------------------------------------------------
# Internal formatters
# ---------------------------------------------------------------------------


def _fmt_release_note(note: dict, billing: dict, total_cartons_for_customer: int) -> dict:
    tags = note.get("carton_tags") or []
    return {
        "id":                       str(note["id"]),
        "reference_number":         note["reference_number"],
        "customer_name":            note.get("customer_name"),
        "container_number":         note.get("container_number"),
        "carton_count":             int(note.get("total_cartons") or 0),
        "total_cartons_for_customer": total_cartons_for_customer,
        "is_partial_release":       bool(note.get("is_partial", False)),
        "carton_tags":              list(tags),
        "payment_status":           note.get("payment_status") or billing.get("status", ""),
        "status":                   note["status"],
        "authorized_at":            note["created_at"],
        "warehouse_address":        None,
    }
