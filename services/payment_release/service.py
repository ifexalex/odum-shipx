"""Business logic for the Payment Release service.

Handles payment confirmation against billing records, release note generation
(full and partial), warehouse pickup recording with delegate support, and
carryover ledger creation when releasing with outstanding balances.
"""

import logging
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Any

from shared.audit import log_audit
from shared.events import publish_event
from shared.exceptions import (
    BusinessRuleViolationError,
    IllegalTransitionError,
    InsufficientPermissionsError,
    ResourceNotFoundError,
)
from shared.notifications import enqueue_notifications
from shared.providers import get_storage_provider
from shared.staff_notifications import notify_staff
from shared.tenant_context import UserRole
from shared.validation import safe_filename

from . import repository as repo
from .models import ConfirmPaymentRequest

logger = logging.getLogger(__name__)

_TOLERANCE = Decimal("0.01")

# ---------------------------------------------------------------------------
# S3 configuration for payment-claim evidence
# ---------------------------------------------------------------------------

_ALLOWED_CONTENT_TYPES = frozenset({"image/jpeg", "image/png", "application/pdf"})
_MAX_FILE_SIZE = 10 * 1024 * 1024  # 10 MB
_URL_EXPIRY = 3600  # 1 hour


# ---------------------------------------------------------------------------
# Payment confirmation
# ---------------------------------------------------------------------------


def confirm_payment(
    tenant_id: str,
    billing_id: str,
    req: Any,
    actor_id: str,
    ctx: Any,
    request_id: str = "",
) -> dict[str, Any]:
    """Record a payment and update billing status."""
    billing = repo.get_billing_by_id(tenant_id, billing_id)
    if not billing:
        raise ResourceNotFoundError("billing", billing_id)

    # Same rule as the gateway path (webhook.validate_billing_for_webhook): money
    # cannot be recorded against an invoice that was cancelled or waived. Without it
    # the status recompute below would flip a cancelled invoice to 'paid'.
    if billing["status"] in {"cancelled", "waived"}:
        raise BusinessRuleViolationError(
            f"Billing {billing_id} is '{billing['status']}' and cannot accept payments.",
            rule_id="BILLING_NOT_PAYABLE",
        )

    amount_ngn = Decimal(str(req.amount_ngn))

    # Receipt number — generated for every payment, mirroring the physical
    # cash receipt booklet (e.g. "ACM-RCT-20260822-0001"). Feeds the receipt
    # PDF generator (services/excel/export_receipt_pdf.py). The number itself is
    # allocated inside record_payment's transaction so two payments recorded at
    # the same moment cannot share one.
    tenant_short = repo.get_tenant_short(tenant_id)

    # Payment record, invoice total + status, and any overpayment refund are
    # written in one transaction; the status is computed from the stored total.
    recorded = repo.record_payment(
        tenant_id,
        billing_id,
        amount_ngn,
        {
            "payment_method": req.payment_method,
            "reference_number": req.payment_reference,
            "payment_date": date.today(),
            "recorded_by": actor_id,
            "payer_name": getattr(req, "payer_name", None),
            "payer_address": getattr(req, "payer_address", None),
            "bank_name": getattr(req, "bank_name", None),
            "cheque_number": getattr(req, "cheque_number", None),
            "warehouse_id": getattr(req, "warehouse_id", None),
            "physical_receipt_number": getattr(req, "physical_receipt_number", None),
        },
        tolerance=_TOLERANCE,
        receipt_prefix=f"{tenant_short}-RCT-{date.today():%Y%m%d}",
    )
    if recorded is None:
        raise RuntimeError("record_payment returned None for a manual payment")
    payment = recorded.payment
    updated_billing = recorded.billing
    new_status = str(updated_billing["status"])

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

    log_audit(
        tenant_id=tenant_id,
        entity_type="payment_record",
        entity_id=str(payment["id"]),
        action="CREATE",
        actor_id=actor_id,
        actor_role=str(ctx.role),
        after_state={"billing_id": billing_id, "amount_ngn": str(amount_ngn), "billing_status": new_status},
    )

    confirmed_at = payment.get("created_at") or datetime.now(UTC)
    outstanding = Decimal(str(updated_billing["balance_ngn"]))

    return {
        "payment_id": str(payment["id"]),
        "billing_id": billing_id,
        "amount_ngn": amount_ngn,
        "new_payment_status": new_status,
        "outstanding_ngn": outstanding,
        "release_note_available": new_status in {"paid", "overpaid"},
        "confirmed_at": confirmed_at,
        "receipt_number": payment.get("receipt_number"),
    }


# ---------------------------------------------------------------------------
# Payment claims — customer-submitted "I've made this payment" + evidence
#
# Bug found live: the manual bank-transfer option only ever showed static
# instructions with no way for the customer to say "I've sent it," and no
# required proof — staff had no queue and no paper trail, only whatever they
# happened to notice arrive in the bank account. A claim is the customer's
# submission; confirming one creates the real `payment_record` (the actual
# source of truth for billing totals) via the existing confirm_payment()
# above — the claim itself is a queue/audit trail, never a second ledger.
# ---------------------------------------------------------------------------


def _customer_owns_billing(tenant_id: str, ctx: Any, billing: dict[str, Any]) -> bool:
    if ctx.role != UserRole.CUSTOMER:
        return True
    customer = repo.get_customer_by_user_id(tenant_id, ctx.user_id)
    return customer is not None and str(billing["customer_id"]) == str(customer["id"])


def generate_payment_claim_upload_url(
    tenant_id: str,
    billing_id: str,
    filename: str,
    content_type: str,
    ctx: Any,
) -> dict[str, Any]:
    if content_type not in _ALLOWED_CONTENT_TYPES:
        raise BusinessRuleViolationError(
            f"content_type '{content_type}' is not allowed. Allowed: {', '.join(sorted(_ALLOWED_CONTENT_TYPES))}",
            rule_id="INVALID_CONTENT_TYPE",
        )

    billing = repo.get_billing_by_id(tenant_id, billing_id)
    if not billing or not _customer_owns_billing(tenant_id, ctx, billing):
        raise ResourceNotFoundError("billing", billing_id)

    filename = safe_filename(filename)
    file_key = f"{tenant_id}/payment-claims/{billing_id}/{filename}"

    ticket = get_storage_provider().presigned_upload(file_key, content_type=content_type, expires_in=_URL_EXPIRY)

    return {"file_key": file_key, **ticket.as_response()}


def submit_payment_claim(
    tenant_id: str,
    billing_id: str,
    req: Any,
    actor_id: str,
    ctx: Any,
    request_id: str = "",
) -> dict[str, Any]:
    """Record a customer's "I've made this payment" claim. Evidence is
    mandatory at the model level (SubmitPaymentClaimRequest) — a claim can
    never reach this far without a file already uploaded to S3.
    """
    billing = repo.get_billing_by_id(tenant_id, billing_id)
    if not billing or not _customer_owns_billing(tenant_id, ctx, billing):
        raise ResourceNotFoundError("billing", billing_id)

    if billing["status"] in {"paid", "waived"}:
        raise BusinessRuleViolationError(
            "This invoice has no outstanding balance to submit a payment against.",
            rule_id="BILLING_NOT_PAYABLE",
        )

    customer = repo.get_customer_by_user_id(tenant_id, actor_id)
    customer_id = str(customer["id"]) if customer else str(billing["customer_id"])

    claim = repo.create_payment_claim(
        tenant_id,
        {
            "tenant_id": tenant_id,
            "billing_id": billing_id,
            "customer_id": customer_id,
            "amount_ngn": Decimal(str(req.amount_ngn)),
            "evidence_file_key": req.evidence_file_key,
            "evidence_file_name": req.evidence_file_name,
            "customer_note": req.customer_note,
        },
    )
    if claim is None:
        # Only failure mode: idx_payment_claim_one_pending_per_billing already
        # has a pending claim for this billing — surface as a clear business
        # rule, not a raw unique-violation 500.
        raise BusinessRuleViolationError(
            "A payment claim is already pending review for this invoice.",
            rule_id="PAYMENT_CLAIM_ALREADY_PENDING",
        )

    publish_event(
        source="logistics.payment_release",
        detail_type="PaymentClaimSubmitted",
        tenant_id=tenant_id,
        payload={"claim_id": str(claim["id"]), "billing_id": billing_id, "amount_ngn": str(claim["amount_ngn"])},
        request_id=request_id,
    )
    log_audit(
        tenant_id=tenant_id,
        entity_type="payment_claim",
        entity_id=str(claim["id"]),
        action="CREATE",
        actor_id=actor_id,
        actor_role=str(ctx.role),
        after_state={"billing_id": billing_id, "amount_ngn": str(claim["amount_ngn"]), "status": "pending"},
    )
    # Ground-truth gap found live, reported by the user: they submitted a
    # payment but "on the staff's notification, it did not tell the staff
    # the customer who submitted the payment" — the notification carried
    # only an amount, nothing to identify who paid or which invoice/container
    # it was for, so a staff member had to open the claim just to know whose
    # payment they were looking at. `billing` already carries customer_name/
    # customer_phone/container_number/invoice_number for free (get_billing_by_id's
    # join) — no extra query needed to include them here.
    # Customer name lives in the (unclamped) title, not repeated here — the
    # notification panel's body text is CSS-clamped to 2 lines, so every
    # character here is competing for very little space.
    customer_name = billing.get("customer_name") or "A customer"
    identifying_bits = [f"NGN {claim['amount_ngn']}", f"Invoice {billing['invoice_number']}"]
    if billing.get("container_number"):
        identifying_bits.append(f"Container {billing['container_number']}")
    if billing.get("customer_phone"):
        identifying_bits.append(str(billing["customer_phone"]))
    body = " · ".join(identifying_bits)

    for role in ("nigeria_office_staff", "tenant_admin"):
        notify_staff(
            tenant_id=tenant_id,
            event_type="payment_claim_submitted",
            entity_type="payment_claim",
            entity_id=str(claim["id"]),
            title=f"New payment claim — {customer_name}",
            body=body,
            target_role=role,
        )
    return dict(claim)


def list_payment_claims(tenant_id: str, billing_id: str, ctx: Any) -> list[dict[str, Any]]:
    billing = repo.get_billing_by_id(tenant_id, billing_id)
    if not billing or not _customer_owns_billing(tenant_id, ctx, billing):
        raise ResourceNotFoundError("billing", billing_id)
    return [dict(c) for c in repo.list_payment_claims_for_billing(tenant_id, billing_id)]


def get_payment_claim_evidence_url(tenant_id: str, claim_id: str, ctx: Any) -> dict[str, Any]:
    """Presigned GET for a claim's evidence file — staff need to actually see
    the receipt before confirming a claim, not just its filename."""
    claim = repo.get_payment_claim_by_id(tenant_id, claim_id)
    if not claim:
        raise ResourceNotFoundError("payment_claim", claim_id)

    billing = repo.get_billing_by_id(tenant_id, str(claim["billing_id"]))
    if not billing or not _customer_owns_billing(tenant_id, ctx, billing):
        raise ResourceNotFoundError("payment_claim", claim_id)

    file_key: str = claim["evidence_file_key"]
    if not file_key.startswith(f"{tenant_id}/"):
        raise ResourceNotFoundError("payment_claim", claim_id)

    disposition = f'inline; filename="{safe_filename(claim["evidence_file_name"], default="evidence")}"'
    url = get_storage_provider().presigned_get_url(file_key, expires_in=300, response_content_disposition=disposition)
    return {"url": url}


def confirm_payment_claim(
    tenant_id: str,
    claim_id: str,
    actor_id: str,
    ctx: Any,
    request_id: str = "",
) -> dict[str, Any]:
    """Staff confirms a claim: records the real payment via confirm_payment()
    (the same code path used for any other manually-recorded payment) and
    links the claim to it. Never mutates billing totals directly — the claim
    is a queue entry, confirm_payment() is the single writer of truth.
    """
    claim = repo.get_payment_claim_by_id(tenant_id, claim_id)
    if not claim:
        raise ResourceNotFoundError("payment_claim", claim_id)
    if claim["status"] != "pending":
        raise BusinessRuleViolationError(
            f"Claim is already {claim['status']} — nothing to confirm.",
            rule_id="PAYMENT_CLAIM_NOT_PENDING",
        )

    confirm_req = ConfirmPaymentRequest(
        amount_ngn=Decimal(str(claim["amount_ngn"])),
        payment_method="bank_transfer",
        payment_reference=f"payment_claim:{claim_id}",
    )
    payment_result = confirm_payment(
        tenant_id, str(claim["billing_id"]), confirm_req, actor_id=actor_id, ctx=ctx, request_id=request_id
    )

    updated = repo.update_payment_claim_status(
        tenant_id,
        claim_id,
        status="confirmed",
        reviewed_by=actor_id,
        payment_record_id=payment_result["payment_id"],
    )
    if updated is None:
        raise RuntimeError("update_payment_claim_status returned None unexpectedly")

    log_audit(
        tenant_id=tenant_id,
        entity_type="payment_claim",
        entity_id=claim_id,
        action="UPDATE",
        actor_id=actor_id,
        actor_role=str(ctx.role),
        before_state={"status": "pending"},
        after_state={"status": "confirmed", "payment_record_id": payment_result["payment_id"]},
    )
    _notify_customer_payment_claim_reviewed(
        tenant_id,
        str(claim["customer_id"]),
        "payment_claim_confirmed",
        request_id,
        template_data={"amount_ngn": str(claim["amount_ngn"])},
    )
    return {**dict(updated), **payment_result}


def reject_payment_claim(
    tenant_id: str,
    claim_id: str,
    req: Any,
    actor_id: str,
    ctx: Any,
    request_id: str = "",
) -> dict[str, Any]:
    claim = repo.get_payment_claim_by_id(tenant_id, claim_id)
    if not claim:
        raise ResourceNotFoundError("payment_claim", claim_id)
    if claim["status"] != "pending":
        raise BusinessRuleViolationError(
            f"Claim is already {claim['status']} — nothing to reject.",
            rule_id="PAYMENT_CLAIM_NOT_PENDING",
        )

    updated = repo.update_payment_claim_status(
        tenant_id, claim_id, status="rejected", reviewed_by=actor_id, rejection_reason=req.reason
    )
    if updated is None:
        raise RuntimeError("update_payment_claim_status returned None unexpectedly")

    publish_event(
        source="logistics.payment_release",
        detail_type="PaymentClaimRejected",
        tenant_id=tenant_id,
        payload={"claim_id": claim_id, "billing_id": str(claim["billing_id"]), "reason": req.reason},
        request_id=request_id,
    )
    log_audit(
        tenant_id=tenant_id,
        entity_type="payment_claim",
        entity_id=claim_id,
        action="UPDATE",
        actor_id=actor_id,
        actor_role=str(ctx.role),
        before_state={"status": "pending"},
        after_state={"status": "rejected", "rejection_reason": req.reason},
    )
    _notify_customer_payment_claim_reviewed(
        tenant_id,
        str(claim["customer_id"]),
        "payment_claim_rejected",
        request_id,
        template_data={"amount_ngn": str(claim["amount_ngn"]), "reason": req.reason},
    )
    return dict(updated)


def _notify_customer_payment_claim_reviewed(
    tenant_id: str,
    customer_id: str,
    event_type: str,
    request_id: str,
    template_data: dict[str, Any],
) -> None:
    """Best-effort customer notification for a confirmed/rejected payment
    claim — a claim review with no notification left the customer (and
    every staff member who checked "did the customer hear back") with no
    signal the review had even happened. Never raises: a notification outage
    must not fail the confirm/reject request itself."""
    try:
        customer = repo.get_customer_contact(tenant_id, customer_id)
        if not customer:
            return
        enqueue_notifications(
            tenant_id=tenant_id,
            event_type=event_type,
            recipient={
                "phone": customer.get("phone") or "",
                "email": customer.get("email") or "",
                "whatsapp": customer.get("whatsapp") or "",
                "name": customer.get("name") or "",
            },
            template_data=template_data,
            locale=customer.get("locale", "en"),
            request_id=request_id,
            customer_id=customer_id,
        )

        # In-app customer bell — ground-truth gap found live, reported by
        # the user right after using this exact flow: SMS/WhatsApp/email
        # above can fail for reasons entirely outside this app (unregistered
        # WhatsApp template, no SMS credits, an email provider outage), and
        # the customer portal itself showed nothing until they happened to
        # open this one billing record. Only customers with a portal account
        # (customer.user_id set) can receive this — reuses the same
        # staff_notification table via target_user_id instead of
        # target_role, which is what the staff-facing bell uses.
        if customer.get("user_id"):
            if event_type == "payment_claim_confirmed":
                title = "Payment confirmed"
                body = f"Your payment of NGN {template_data.get('amount_ngn')} has been confirmed."
            else:
                title = "Payment claim rejected"
                body = (
                    f"Your payment claim of NGN {template_data.get('amount_ngn')} was not "
                    f"confirmed. Reason: {template_data.get('reason')}"
                )
            notify_staff(
                tenant_id=tenant_id,
                event_type=event_type,
                entity_type="payment_claim",
                title=title,
                body=body,
                target_user_id=str(customer["user_id"]),
            )
    except Exception:
        logger.exception(
            "Failed to enqueue %s notification for customer %s",
            event_type,
            customer_id,
        )


def process_webhook_payment(
    tenant_id: str,
    billing_id: str,
    amount_ngn: Decimal,
    payment_method: str,
    payment_reference: str,
    gateway_transaction_id: str,
    request_id: str = "",
) -> dict[str, Any] | None:
    """Confirm a payment received via gateway webhook.

    Returns the payment confirmation dict, or None if the payment was already
    recorded (duplicate webhook delivery).

    Duplicate detection: ON CONFLICT DO NOTHING on gateway_transaction_id means
    create_webhook_payment_record returns None on a duplicate — we surface that as
    a no-op rather than an error.
    """
    from . import webhook as wh

    billing = repo.get_billing_by_id(tenant_id, billing_id)
    if not billing:
        raise ResourceNotFoundError("billing", billing_id)

    wh.validate_billing_for_webhook(billing, billing_id)

    amount_ngn = Decimal(str(amount_ngn))

    recorded = repo.record_payment(
        tenant_id,
        billing_id,
        amount_ngn,
        {
            "payment_method": payment_method,
            "reference_number": payment_reference,
            "payment_date": datetime.now(UTC).date(),
            "recorded_by": None,
        },
        tolerance=_TOLERANCE,
        gateway_transaction_id=gateway_transaction_id,
    )

    if recorded is None:
        logger.info(
            "Duplicate webhook payment skipped: billing=%s gateway_tx=%s",
            billing_id,
            gateway_transaction_id,
        )
        return None

    payment = recorded.payment
    updated_billing = recorded.billing
    new_status = str(updated_billing["status"])

    publish_event(
        source="logistics.payment_release",
        detail_type="PaymentConfirmed",
        tenant_id=tenant_id,
        payload={
            "payment_id": str(payment["id"]),
            "billing_id": billing_id,
            "amount_ngn": str(amount_ngn),
            "new_status": new_status,
            "source": "gateway_webhook",
            "gateway": payment_method,
        },
        request_id=request_id,
    )

    # Ground-truth gap found live: actor_id="gateway" is not a UUID, but
    # audit_log.actor_id is a `UUID REFERENCES tenant_user(id)` column —
    # every webhook-confirmed payment has silently failed to write an audit
    # record since this code was written (log_audit swallows the resulting
    # exception and only logs a WARNING, so nothing here ever surfaced it).
    # Confirmed live: the raw insert raises "invalid input syntax for type
    # uuid: gateway". None is a valid, intentional "no human actor" value —
    # actor_role="system" already says why.
    log_audit(
        tenant_id=tenant_id,
        entity_type="payment_record",
        entity_id=str(payment["id"]),
        action="CREATE",
        actor_id=None,
        actor_role="system",
        after_state={
            "billing_id": billing_id,
            "amount_ngn": str(amount_ngn),
            "billing_status": new_status,
            "gateway": payment_method,
        },
    )

    outstanding = Decimal(str(updated_billing["balance_ngn"]))
    return {
        "payment_id": str(payment["id"]),
        "billing_id": billing_id,
        "amount_ngn": amount_ngn,
        "new_payment_status": new_status,
        "outstanding_ngn": outstanding,
        "release_note_available": new_status in {"paid", "overpaid"},
        "confirmed_at": payment.get("created_at") or datetime.now(UTC),
    }


# ---------------------------------------------------------------------------
# Release note generation
# ---------------------------------------------------------------------------


def generate_release_note(
    tenant_id: str,
    req: Any,
    actor_id: str,
    ctx: Any,
    request_id: str = "",
) -> dict[str, Any]:
    """Generate a release note for a customer's cartons.

    Enforces payment rules (BR-BL-002, BR-BL-003, BR-BL-004).

    Supports two release-quantity models (additive — see 13_api_payment_release.md):
      - carton_tags: the existing per-carton-tag flow (claims/manifest tags).
      - packages_released + package_unit: count-based ("5 of 8 CTNS"), matching
        both the physical paper form and bulk-quantity manifest import (7.41)
        data that carries no per-carton tags at all.
    """
    billing = repo.get_billing_by_id(tenant_id, req.billing_id)
    if not billing:
        raise ResourceNotFoundError("billing", req.billing_id)

    payment_status = billing["status"]
    amount_paid = Decimal(str(billing["amount_paid_ngn"]))
    total_due = Decimal(str(billing["total_ngn"]))
    total_cbm = Decimal(str(billing["total_cbm"] or "0"))
    total_cartons_for_customer = int(billing["total_cartons"] or 0)

    carton_tags = list(req.carton_tags)
    is_count_based = not carton_tags and req.packages_released is not None
    packages_released = req.packages_released if is_count_based else None
    # Narrowed int for the count-based quantity math below; `packages_released`
    # itself stays None for carton-tag notes so the column persists as NULL.
    count_released = int(packages_released) if packages_released is not None else 0

    # Ground-truth gap found live: neither release-quantity model was ever
    # checked against release notes already issued for this billing —
    # create_release_note is a bare INSERT with no uniqueness constraint, so
    # re-submitting the same carton_tags (or count) created a second,
    # fully-valid 'active' release note authorising the same cartons for
    # pickup a second time, silently double-releasing already-picked-up
    # cargo. split_release_note/reissue_release_note are unaffected — they
    # go through repo.create_split_release_note directly, not this function,
    # and already validate against their specific parent note's own tags.
    if is_count_based:
        already_released = repo.get_active_release_note_packages_released(tenant_id, req.billing_id)
        if already_released + count_released > total_cartons_for_customer:
            remaining = max(0, total_cartons_for_customer - already_released)
            raise BusinessRuleViolationError(
                f"Requested {count_released} {req.package_unit} exceeds the {remaining} "
                f"remaining unreleased (of {total_cartons_for_customer} total; "
                f"{already_released} already on an active or picked-up release note).",
                rule_id="BR-RN-OVERRELEASE-001",
            )
    else:
        already_released_tags = set(repo.get_active_release_note_carton_tags(tenant_id, req.billing_id))
        duplicate_tags = already_released_tags & set(carton_tags)
        if duplicate_tags:
            raise BusinessRuleViolationError(
                f"These carton tags are already on an active or picked-up release note: {', '.join(sorted(duplicate_tags))}",
                rule_id="BR-RN-DUPLICATE-001",
            )

    # Payment check
    if payment_status in {"paid", "overpaid"}:
        pass  # fully paid — always allow
    elif payment_status == "partially_paid":
        if not req.release_with_outstanding:
            if is_count_based:
                # Count-based partial release: check proportional carton-count payment
                # (no per-carton CBM data exists for bulk-quantity manifest rows, 7.41).
                required_payment = (
                    Decimal(count_released) / total_cartons_for_customer * total_due
                    if total_cartons_for_customer > 0
                    else total_due
                )
            else:
                # Partial release: check proportional CBM payment
                selected_cbm = repo.get_cbm_for_carton_tags(
                    tenant_id,
                    str(billing["customer_id"]),
                    str(billing["container_id"]),
                    carton_tags,
                )
                required_payment = selected_cbm / total_cbm * total_due if total_cbm > Decimal("0") else total_due
            if amount_paid < required_payment - _TOLERANCE:
                raise BusinessRuleViolationError(
                    f"Insufficient payment for requested cartons. "
                    f"Required: {required_payment:.2f} NGN, Paid: {amount_paid:.2f} NGN",
                    rule_id="PAYMENT_REQUIRED",
                )
    elif payment_status == "unpaid" and not req.release_with_outstanding:
        raise BusinessRuleViolationError(
            "Payment is required before generating a release note",
            rule_id="PAYMENT_REQUIRED",
        )
    # released_with_outstanding, waived — pass through

    if req.release_with_outstanding and not req.approval_notes:
        raise BusinessRuleViolationError(
            "approval_notes is required when releasing with outstanding balance",
            rule_id="APPROVAL_NOTES_REQUIRED",
        )

    warehouse_id = getattr(req, "warehouse_id", None)
    warehouse_row = repo.get_warehouse_by_id(tenant_id, warehouse_id) if warehouse_id else None
    if warehouse_row is None:
        warehouse_row = repo.get_default_warehouse(tenant_id)
        warehouse_id = str(warehouse_row["id"]) if warehouse_row else None

    is_on_credit = bool(req.release_with_outstanding)
    credit_granted_by = actor_id if is_on_credit else None
    credit_granted_by_name = req.credit_granted_by_name if is_on_credit else None

    tenant_short = repo.get_tenant_short(tenant_id)
    seq = repo.get_next_release_note_seq(tenant_id)
    reference_number = f"{tenant_short}-RN-{date.today():%Y%m%d}-{seq:04d}"

    if is_count_based:
        total_cartons = count_released
        packages_balance = max(0, total_cartons_for_customer - total_cartons)
        is_partial = total_cartons < total_cartons_for_customer
    else:
        total_cartons = len(carton_tags)
        packages_balance = max(0, total_cartons_for_customer - total_cartons)
        is_partial = total_cartons < total_cartons_for_customer

    note = repo.create_release_note(
        tenant_id,
        {
            "tenant_id": tenant_id,
            "billing_id": req.billing_id,
            "customer_id": str(billing["customer_id"]),
            "container_id": str(billing["container_id"]),
            "reference_number": reference_number,
            "carton_tags": carton_tags,
            "total_cartons": total_cartons,
            "is_partial": is_partial,
            "status": "active",
            "issued_by": actor_id,
            "notes": getattr(req, "approval_notes", None),
            "valid_until": date.today() + timedelta(days=14),
            "warehouse_id": warehouse_id,
            "payment_record_id": None,  # ON CREDIT until a payment is confirmed and linked
            "is_on_credit": is_on_credit,
            "credit_granted_by": credit_granted_by,
            "credit_granted_by_name": credit_granted_by_name,
            "packages_released": packages_released,
            "package_unit": req.package_unit if is_count_based else None,
            "packages_balance": packages_balance,
            "physical_document_number": getattr(req, "physical_document_number", None),
            "packing_list_invoice_numbers": list(getattr(req, "packing_list_invoice_numbers", None) or []),
        },
    )
    if note is None:
        raise RuntimeError("create_release_note returned None unexpectedly")

    # create_release_note's RETURNING row carries no joins — _fmt_release_note
    # reads customer/container/warehouse fields expecting the joined shape
    # get_release_note_by_id/list_release_notes produce, so without this the
    # immediate POST response silently showed null customer/container/
    # warehouse info until the caller made a separate GET. Found live testing
    # the new warehouse_id field end-to-end.
    note["customer_name"] = billing.get("customer_name")
    note["container_number"] = billing.get("container_number")
    if warehouse_row:
        note["warehouse_name"] = warehouse_row.get("name")
        note["warehouse_address"] = warehouse_row.get("address")
        note["warehouse_phone"] = warehouse_row.get("phone")

    # Carryover ledger — written AFTER the release note so release_note_id
    # can be linked (the form's authorizer + "Debt Payment Date" fields).
    if req.release_with_outstanding:
        balance = Decimal(str(billing["balance_ngn"]))
        repo.mark_billing_released_with_outstanding(tenant_id, req.billing_id)
        if balance > Decimal("0"):
            repo.create_carryover_entry(
                tenant_id,
                {
                    "tenant_id": tenant_id,
                    "customer_id": str(billing["customer_id"]),
                    "source_billing_id": req.billing_id,
                    "carryover_amount_ngn": balance,
                    "notes": req.approval_notes,
                    "created_by": actor_id,
                    "due_date": getattr(req, "due_date", None),
                    "granted_by": actor_id,
                    "release_note_id": str(note["id"]),
                },
            )
            # _fmt_release_note reads debt_due_date off `note` uniformly
            # (the same key get_release_note_by_id's join produces on a
            # later fetch) — set it here too so the immediate POST response
            # already shows the due date the caller just supplied.
            note["debt_due_date"] = getattr(req, "due_date", None)

    publish_event(
        source="logistics.payment_release",
        detail_type="ReleaseNoteGenerated",
        tenant_id=tenant_id,
        payload={
            "release_note_id": str(note["id"]),
            "reference_number": reference_number,
            "billing_id": req.billing_id,
            "customer_id": str(billing["customer_id"]),
            "is_partial": is_partial,
        },
        request_id=request_id,
    )

    log_audit(
        tenant_id=tenant_id,
        entity_type="release_note",
        entity_id=str(note["id"]),
        action="CREATE",
        actor_id=actor_id,
        actor_role=str(ctx.role),
        after_state={"reference_number": reference_number, "billing_id": req.billing_id, "is_partial": is_partial},
    )

    return _fmt_release_note(note, billing, total_cartons_for_customer)


# ---------------------------------------------------------------------------
# Release note list
# ---------------------------------------------------------------------------


def list_release_notes(
    tenant_id: str,
    filters: dict[str, Any],
    limit: int,
    cursor: dict[str, Any] | None,
    ctx: Any,
) -> tuple[list[dict[str, Any]], str | None, bool]:
    """Return a paginated list of release notes with optional filters.

    Customers are restricted to their own records.
    """
    if ctx.role == UserRole.CUSTOMER:
        customer = repo.get_customer_by_user_id(tenant_id, ctx.user_id)
        if customer:
            filters = {**filters, "customer_id": str(customer["id"])}
        else:
            return [], None, False

    rows, next_cursor, has_more = repo.list_release_notes(tenant_id, filters, limit, cursor)
    # Same wire shape as the detail response (raw rows leaked carton_count /
    # authorized_at / is_partial_release mismatches before — P2 audit fix).
    page = [_fmt_release_note(row, row, int(row.get("billing_total_cartons") or 0)) for row in rows]
    return page, next_cursor, has_more


def get_release_note_stats(tenant_id: str) -> dict[str, int]:
    """Per-status counts for the release-notes stats row (§9.1, P2-3)."""
    return repo.get_release_note_stats(tenant_id)


# ---------------------------------------------------------------------------
# Warehouses (branch/office letterheads — migration 041)
# ---------------------------------------------------------------------------


def list_warehouses(tenant_id: str) -> list[dict[str, Any]]:
    return [dict(w) for w in repo.list_warehouses(tenant_id)]


def create_warehouse(tenant_id: str, req: Any, actor_id: str, actor_role: str) -> dict[str, Any]:
    # A tenant's very first warehouse must become the default — otherwise
    # get_default_warehouse() keeps returning None (nothing else ever sets
    # is_default), and every release note this tenant generates silently
    # resolves no warehouse at all, exactly the gap found live when this
    # tenant's own warehouse list came back empty.
    is_first_warehouse = len(repo.list_warehouses(tenant_id)) == 0

    # Reject a name already taken by an ACTIVE warehouse up front, so the caller
    # gets "that name is in use" instead of a raw unique-index violation
    # surfacing as a 500. Only active rows collide (migration 056 scoped the
    # index), so reusing a retired warehouse's name is deliberately allowed.
    from shared.exceptions import DuplicateResourceError

    clash = repo.find_warehouse_by_name(tenant_id, req.name, active_only=True)
    if clash:
        raise DuplicateResourceError("warehouse", req.name)

    # The first warehouse must become the default — nothing else ever sets
    # is_default, so without this get_default_warehouse() stays None and every
    # release note silently resolves no warehouse. Beyond the first, the caller
    # can ask for it explicitly: creating a warehouse and *then* hunting for a
    # "Set default" action was the only route before, which is not discoverable.
    # `is True` rather than a truthiness test: only an explicit boolean promotes.
    # Anything else (a missing attribute, a stub, a stray string) must not
    # silently reassign a tenant's default warehouse as a side effect of create.
    wants_default = is_first_warehouse or getattr(req, "is_default", False) is True

    row = repo.create_warehouse(
        tenant_id,
        {
            "tenant_id": tenant_id,
            "name": req.name,
            "address": req.address,
            "city": req.city,
            "state": req.state,
            "country": req.country,
            "phone": req.phone,
            # Created unflagged when promoting, then promoted below in one
            # transaction: setting is_default here while another row still holds
            # it would violate idx_warehouse_one_default mid-INSERT.
            "is_default": is_first_warehouse,
            "created_by": actor_id,
        },
    )
    if row is None:
        raise RuntimeError("create_warehouse returned None unexpectedly")

    # Promote only when the caller asked for a default that the INSERT did not
    # already set. The first warehouse was inserted with is_default = TRUE
    # directly, so re-promoting it would be a redundant transaction.
    if wants_default and not is_first_warehouse:
        promoted = repo.set_default_warehouse(tenant_id, str(row["id"]))
        if promoted is not None:
            row = promoted

    log_audit(
        tenant_id=tenant_id,
        entity_type="warehouse",
        entity_id=str(row["id"]),
        action="CREATE",
        actor_id=actor_id,
        actor_role=actor_role,
        after_state={"name": req.name, "is_default": bool(row.get("is_default"))},
    )
    return dict(row)


def set_default_warehouse(tenant_id: str, warehouse_id: str, actor_id: str, actor_role: str) -> dict[str, Any]:
    warehouse = repo.get_warehouse_by_id(tenant_id, warehouse_id)
    if not warehouse:
        from shared.exceptions import ResourceNotFoundError

        raise ResourceNotFoundError("warehouse", warehouse_id)

    updated = repo.set_default_warehouse(tenant_id, warehouse_id)
    if updated is None:
        raise RuntimeError("set_default_warehouse returned None unexpectedly")

    log_audit(
        tenant_id=tenant_id,
        entity_type="warehouse",
        entity_id=warehouse_id,
        action="UPDATE",
        actor_id=actor_id,
        actor_role=actor_role,
        after_state={"is_default": True},
    )
    return dict(updated)


def update_warehouse(tenant_id: str, warehouse_id: str, req: Any, actor_id: str, actor_role: str) -> dict[str, Any]:
    from shared.exceptions import ResourceNotFoundError

    existing = repo.get_warehouse_by_id(tenant_id, warehouse_id)
    if not existing:
        raise ResourceNotFoundError("warehouse", warehouse_id)

    # Only the fields the caller actually sent (exclude_unset) are patched, so a
    # PATCH that omits a field leaves it untouched rather than nulling it.
    updates = req.model_dump(exclude_unset=True) if hasattr(req, "model_dump") else dict(req)

    # Deactivating must not be reachable here: the default-warehouse and
    # last-active guards live on the delete/deactivate path, and a bare PATCH
    # would walk straight past them and leave a tenant with no usable warehouse.
    # Reactivating (is_active = True) is fine and stays allowed.
    if updates.get("is_active") is False:
        from shared.exceptions import BusinessRuleViolationError

        raise BusinessRuleViolationError(
            "Use DELETE /v1/warehouses/{id} to remove a warehouse — it checks that "
            "this is not the default or the last active warehouse.",
            rule_id="WAREHOUSE_DEACTIVATE_VIA_DELETE",
        )

    # Renaming onto a name another ACTIVE warehouse holds would hit the partial
    # unique index as a 500; reject it as a 409 the caller can act on. Comparing
    # against a different id lets a no-op rename of the row itself through.
    new_name = updates.get("name")
    if new_name:
        clash = repo.find_warehouse_by_name(tenant_id, new_name, active_only=True)
        if clash and str(clash["id"]) != str(warehouse_id):
            from shared.exceptions import DuplicateResourceError

            raise DuplicateResourceError("warehouse", new_name)

    row = repo.update_warehouse(tenant_id, warehouse_id, updates)
    if row is None:
        raise RuntimeError("update_warehouse returned None unexpectedly")

    log_audit(
        tenant_id=tenant_id,
        entity_type="warehouse",
        entity_id=warehouse_id,
        action="UPDATE",
        actor_id=actor_id,
        actor_role=actor_role,
        after_state=updates,
    )
    return dict(row)


def _assert_warehouse_removable(tenant_id: str, existing: dict[str, Any], warehouse_id: str) -> None:
    """Guards shared by delete and deactivate.

    The default warehouse can't be removed (reassign the default first) and the
    last active one can't be removed — release-note generation must always
    resolve a warehouse, so a tenant left with none is a broken tenant.
    """
    from shared.exceptions import BusinessRuleViolationError

    if existing.get("is_default"):
        raise BusinessRuleViolationError(
            "The default warehouse cannot be removed — set another warehouse as default first.",
            rule_id="WAREHOUSE_DEFAULT_IMMUTABLE",
        )
    if existing.get("is_active") and repo.count_active_warehouses(tenant_id) <= 1:
        raise BusinessRuleViolationError(
            "At least one active warehouse is required.",
            rule_id="WAREHOUSE_LAST_ACTIVE",
        )


def delete_warehouse(tenant_id: str, warehouse_id: str, actor_id: str, actor_role: str) -> dict[str, Any]:
    """Permanently delete a warehouse when nothing references it.

    Removing a warehouse used to only flip `is_active`, which produced two
    surprises reported from live use: the warehouse appeared gone but still
    reserved its name, so it could not be recreated; and there was no way to
    actually get rid of a mistyped entry.

    A warehouse is therefore really deleted — *unless* a handover document points
    at it. `release_note` / `pickup_record` / `payment_record` are the record of
    whose goods were released from where; `packing_list` records where cargo is
    bound. Those must not lose their warehouse, so when any of them reference it
    the delete is refused with the counts, and deactivating is offered instead.
    The FKs would refuse regardless, but a foreign-key error is not an answer an
    operator can act on.
    """
    from shared.exceptions import BusinessRuleViolationError, ResourceNotFoundError

    existing = repo.get_warehouse_by_id(tenant_id, warehouse_id)
    if not existing:
        raise ResourceNotFoundError("warehouse", warehouse_id)
    _assert_warehouse_removable(tenant_id, existing, warehouse_id)

    references = repo.count_warehouse_references(tenant_id, warehouse_id)
    if references:
        detail = ", ".join(f"{count} {label}{'s' if count != 1 else ''}" for label, count in sorted(references.items()))
        raise BusinessRuleViolationError(
            f"This warehouse is referenced by {detail}, so deleting it would leave those "
            "records without a warehouse. Deactivate it instead — it will stop appearing "
            "in pickers while those records keep their history.",
            rule_id="WAREHOUSE_IN_USE",
        )

    row = repo.delete_warehouse(tenant_id, warehouse_id)
    if row is None:
        # Deleted between the read above and here; the caller's intent is already
        # satisfied, so report the row it asked about rather than failing.
        return dict(existing)

    # Audited before returning: a hard delete is unrecoverable, so the trail is
    # the only remaining record that this warehouse ever existed. before_state
    # carries enough to recreate it by hand.
    log_audit(
        tenant_id=tenant_id,
        entity_type="warehouse",
        entity_id=warehouse_id,
        action="DELETE",
        actor_id=actor_id,
        actor_role=actor_role,
        before_state={
            "name": existing.get("name"),
            "address": existing.get("address"),
            "city": existing.get("city"),
            "state": existing.get("state"),
            "phone": existing.get("phone"),
        },
    )
    return dict(row)


def deactivate_warehouse(tenant_id: str, warehouse_id: str, actor_id: str, actor_role: str) -> dict[str, Any]:
    """Retire a warehouse without deleting it (`is_active = FALSE`).

    The path for a warehouse that handover documents reference: it stops
    appearing in pickers, those records keep their history, and — since migration
    056 scoped name uniqueness to active rows — its name becomes reusable.
    """
    from shared.exceptions import ResourceNotFoundError

    existing = repo.get_warehouse_by_id(tenant_id, warehouse_id)
    if not existing:
        raise ResourceNotFoundError("warehouse", warehouse_id)
    _assert_warehouse_removable(tenant_id, existing, warehouse_id)

    row = repo.update_warehouse(tenant_id, warehouse_id, {"is_active": False})
    if row is None:
        raise RuntimeError("deactivate_warehouse returned None unexpectedly")

    log_audit(
        tenant_id=tenant_id,
        entity_type="warehouse",
        entity_id=warehouse_id,
        action="UPDATE",
        actor_id=actor_id,
        actor_role=actor_role,
        after_state={"is_active": False},
    )
    return dict(row)


# ---------------------------------------------------------------------------
# Release note read
# ---------------------------------------------------------------------------


def get_release_note(tenant_id: str, note_id: str, ctx: Any) -> dict[str, Any]:
    note = repo.get_release_note_by_id(tenant_id, note_id)
    if not note:
        raise ResourceNotFoundError("release_note", note_id)

    if ctx.role == UserRole.CUSTOMER:
        customer = repo.get_customer_by_user_id(tenant_id, ctx.user_id)
        if not customer or str(customer["id"]) != str(note["customer_id"]):
            # 404, not 403: a 403 would confirm to a customer that another customer's note id exists.
            raise ResourceNotFoundError("release_note", note_id)

    total_cartons_for_customer = int(note.get("billing_total_cartons") or 0)
    return _fmt_release_note(note, note, total_cartons_for_customer)


# ---------------------------------------------------------------------------
# Release note split
# ---------------------------------------------------------------------------


def split_release_note(
    tenant_id: str,
    note_id: str,
    req: Any,
    actor_id: str,
    ctx: Any,
    request_id: str = "",
) -> dict[str, Any]:
    """Create a child release note for un-collected carton tags.

    Guards:
    - Parent must be active.
    - Requested tags must be a subset of the parent's carton_tags.
    - Tags must not have already been picked up.
    """
    note = repo.get_release_note_by_id(tenant_id, note_id)
    if not note:
        raise ResourceNotFoundError("release_note", note_id)

    if note["status"] != "active":
        raise BusinessRuleViolationError(
            f"Release note status is '{note['status']}' — only active notes can be split",
            rule_id="RELEASE_NOTE_NOT_ACTIVE",
        )

    parent_tags: set[str] = set(note.get("carton_tags") or [])
    requested_tags: list[str] = list(req.carton_tags)
    requested_set = set(requested_tags)

    invalid = requested_set - parent_tags
    if invalid:
        raise BusinessRuleViolationError(
            f"Tags not in parent release note: {', '.join(sorted(invalid))}",
            rule_id="INVALID_CARTON_TAGS",
        )

    already_picked = set(repo.get_picked_carton_tags(tenant_id, note_id))
    already_requested = requested_set & already_picked
    if already_requested:
        raise BusinessRuleViolationError(
            f"Tags already picked up: {', '.join(sorted(already_requested))}",
            rule_id="TAGS_ALREADY_PICKED",
        )

    billing = repo.get_billing_by_id(tenant_id, str(note.get("billing_id", "")))
    tenant_short = repo.get_tenant_short(tenant_id)
    seq = repo.get_next_release_note_seq(tenant_id)
    reference_number = f"{tenant_short}-RN-{date.today():%Y%m%d}-{seq:04d}"

    child_note = repo.create_split_release_note(
        tenant_id,
        {
            "tenant_id": tenant_id,
            "billing_id": str(note.get("billing_id")),
            "customer_id": str(note.get("customer_id")),
            "container_id": str(note.get("container_id")),
            "reference_number": reference_number,
            "carton_tags": requested_tags,
            "total_cartons": len(requested_tags),
            "is_partial": len(requested_tags) < len(parent_tags),
            "parent_release_note_id": note_id,
            "status": "active",
            "issued_by": actor_id,
            "notes": req.notes,
            "valid_until": date.today() + timedelta(days=14),
            # Carried forward from the parent — same warehouse, same invoices,
            # same credit terms (the whole billing is still on credit, if it
            # was). Package-count fields are deliberately NOT copied: a split
            # is inherently a carton_tags-based sub-release, not a re-run of
            # the count-based accounting the parent may have used.
            "warehouse_id": note.get("warehouse_id"),
            "packing_list_invoice_numbers": list(note.get("packing_list_invoice_numbers") or []),
            "is_on_credit": bool(note.get("is_on_credit", False)),
            "credit_granted_by": note.get("credit_granted_by"),
            "credit_granted_by_name": note.get("credit_granted_by_name"),
        },
    )
    if child_note is None:
        raise RuntimeError("create_split_release_note returned None unexpectedly")

    publish_event(
        source="logistics.payment_release",
        detail_type="ReleaseNoteSplit",
        tenant_id=tenant_id,
        payload={
            "child_release_note_id": str(child_note["id"]),
            "parent_release_note_id": note_id,
            "carton_tags": requested_tags,
        },
        request_id=request_id,
    )

    log_audit(
        tenant_id=tenant_id,
        entity_type="release_note",
        entity_id=str(child_note["id"]),
        action="CREATE",
        actor_id=actor_id,
        actor_role=str(ctx.role),
        after_state={"parent_release_note_id": note_id, "carton_tags": requested_tags},
    )

    total_cartons_for_customer = int((billing or {}).get("total_cartons") or 0)
    return _fmt_release_note(child_note, billing or note, total_cartons_for_customer)


# ---------------------------------------------------------------------------
# Release note reissue
# ---------------------------------------------------------------------------


def reissue_release_note(
    tenant_id: str,
    note_id: str,
    actor_id: str,
    ctx: Any,
    request_id: str = "",
) -> dict[str, Any]:
    """Re-issue an expired release note with a fresh 14-day validity window.

    The original expired note is preserved; the new note carries the same
    carton_tags and billing, with parent_release_note_id pointing back to it.
    Only notes with status 'expired' may be reissued.
    """
    note = repo.get_release_note_by_id(tenant_id, note_id)
    if not note:
        raise ResourceNotFoundError("release_note", note_id)

    if note["status"] != "expired":
        raise BusinessRuleViolationError(
            f"Only expired release notes can be re-issued — current status is '{note['status']}'",
            rule_id="RELEASE_NOTE_NOT_EXPIRED",
        )

    tenant_short = repo.get_tenant_short(tenant_id)
    seq = repo.get_next_release_note_seq(tenant_id)
    reference_number = f"{tenant_short}-RN-{date.today():%Y%m%d}-{seq:04d}"

    new_note = repo.create_split_release_note(
        tenant_id,
        {
            "tenant_id": tenant_id,
            "billing_id": str(note.get("billing_id")),
            "customer_id": str(note.get("customer_id")),
            "container_id": str(note.get("container_id")),
            "reference_number": reference_number,
            "carton_tags": list(note.get("carton_tags") or []),
            "total_cartons": int(note.get("total_cartons") or 0),
            "is_partial": bool(note.get("is_partial", False)),
            "parent_release_note_id": note_id,
            "status": "active",
            "issued_by": actor_id,
            "notes": note.get("notes"),
            "valid_until": date.today() + timedelta(days=14),
            # Reissue is a near-identical clone of the expired note (same
            # release, same warehouse, same credit terms — just a fresh
            # validity window), so every migration-041 field carries forward
            # unchanged, unlike split_release_note above.
            "warehouse_id": note.get("warehouse_id"),
            "is_on_credit": bool(note.get("is_on_credit", False)),
            "credit_granted_by": note.get("credit_granted_by"),
            "credit_granted_by_name": note.get("credit_granted_by_name"),
            "packages_released": note.get("packages_released"),
            "package_unit": note.get("package_unit"),
            "packages_balance": note.get("packages_balance"),
            "physical_document_number": note.get("physical_document_number"),
            "packing_list_invoice_numbers": list(note.get("packing_list_invoice_numbers") or []),
        },
    )
    if new_note is None:
        raise RuntimeError("create_split_release_note returned None unexpectedly during reissue")

    billing = repo.get_billing_by_id(tenant_id, str(note.get("billing_id", "")))

    publish_event(
        source="logistics.payment_release",
        detail_type="ReleaseNoteReissued",
        tenant_id=tenant_id,
        payload={
            "new_release_note_id": str(new_note["id"]),
            "original_release_note_id": note_id,
            "reference_number": reference_number,
        },
        request_id=request_id,
    )

    log_audit(
        tenant_id=tenant_id,
        entity_type="release_note",
        entity_id=str(new_note["id"]),
        action="CREATE",
        actor_id=actor_id,
        actor_role=str(ctx.role),
        after_state={
            "reference_number": reference_number,
            "parent_release_note_id": note_id,
            "valid_until": str(date.today() + timedelta(days=14)),
        },
    )

    total_cartons_for_customer = int((billing or {}).get("total_cartons") or int(note.get("billing_total_cartons") or 0))
    return _fmt_release_note(new_note, billing or note, total_cartons_for_customer)


# ---------------------------------------------------------------------------
# Pickup recording
# ---------------------------------------------------------------------------


def record_pickup(
    tenant_id: str,
    note_id: str,
    req: Any,
    actor_id: str,
    ctx: Any,
    request_id: str = "",
) -> dict[str, Any]:
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
            field
            for field, val in [
                ("delegate_name", req.delegate_name),
                ("delegate_phone", req.delegate_phone),
                ("delegate_id_type", req.delegate_id_type),
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
        delegate_id_type_val = req.delegate_id_type.value if hasattr(req.delegate_id_type, "value") else str(req.delegate_id_type)

    # Bug fix (ground-truth audit): collected_by_name was never written —
    # only the delegate path recorded a name. When the customer collects in
    # person, collected_by_name is now required (enforced by
    # RecordPickupRequest's model validator) and persisted here.
    collected_by_name = req.delegate_name if req.is_delegate else req.collected_by_name

    pickup = repo.create_pickup_record(
        tenant_id,
        {
            "tenant_id": tenant_id,
            "release_note_id": note_id,
            "customer_id": str(note["customer_id"]),
            # Bug fix (ground-truth audit): previously always written as [] —
            # per-pickup carton tags are now recorded when supplied.
            "carton_tags_picked": list(getattr(req, "carton_tags_picked", None) or []),
            "cartons_count": req.cartons_released,
            "pickup_date": date.today(),
            "collected_by_name": collected_by_name,
            "is_delegate": req.is_delegate,
            "delegate_name": req.delegate_name,
            "delegate_phone": req.delegate_phone,
            "id_type": delegate_id_type_val,
            "id_number": req.delegate_id_number,
            "received_by": actor_id,
            "notes": req.notes,
            "warehouse_id": getattr(req, "warehouse_id", None),
            "customer_service_officer_id": getattr(req, "customer_service_officer_id", None),
            "accounting_officer_id": getattr(req, "accounting_officer_id", None),
            "warehouse_attendant_id": getattr(req, "warehouse_attendant_id", None),
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
    customer_released = repo.sum_cartons_released_for_customer(tenant_id, str(note["customer_id"]), str(note["container_id"]))
    shipment_status = None
    if customer_total > 0 and customer_released >= customer_total:
        repo.update_shipment_tracking_for_customer(tenant_id, str(note["customer_id"]), str(note["container_id"]), "picked_up")
        shipment_status = "picked_up"

    # Update container to fully_released if all customers done
    container_total = repo.sum_total_cartons_from_billing(tenant_id, str(note["container_id"]))
    container_released = repo.sum_cartons_released_for_container(tenant_id, str(note["container_id"]))
    if container_total > 0 and container_released >= container_total:
        repo.update_container_status(tenant_id, str(note["container_id"]), "fully_released")

    remaining = max(0, note_total - total_picked)

    pickup_time = None
    created_at = pickup.get("created_at")
    if created_at and hasattr(created_at, "strftime"):
        pickup_time = created_at.strftime("%H:%M")

    # Bug fix (ground-truth audit): attendant_name was hardcoded None —
    # resolve the warehouse_attendant_id (falling back to the acting user,
    # who is always a warehouse_attendant on this route) to a real name.
    attendant_id = getattr(req, "warehouse_attendant_id", None) or actor_id
    attendant_name = repo.get_tenant_user_name(tenant_id, attendant_id)

    # Ground-truth gap found live, against a real paper "Goods Release Note"
    # reference: the form has two further named sign-off lines (Customer
    # Service Officer, Accounting Officer) alongside the warehouse attendant.
    # RecordPickupRequest already captures both officer ids; only their
    # names were never resolved (get_tenant_user_name's own docstring
    # already anticipated this — "used to populate attendant_name / officer
    # names" — it just wasn't called for these two yet).
    cso_id = getattr(req, "customer_service_officer_id", None)
    accounting_officer_id = getattr(req, "accounting_officer_id", None)
    customer_service_officer_name = repo.get_tenant_user_name(tenant_id, cso_id) if cso_id else None
    accounting_officer_name = repo.get_tenant_user_name(tenant_id, accounting_officer_id) if accounting_officer_id else None

    log_audit(
        tenant_id=tenant_id,
        entity_type="pickup_record",
        entity_id=str(pickup["id"]),
        action="CREATE",
        actor_id=actor_id,
        actor_role=str(ctx.role),
        after_state={"release_note_id": note_id, "release_note_status": note_status, "cartons_count": req.cartons_released},
    )

    return {
        "release_note_id": note_id,
        "release_note_status": note_status,
        "pickup_record_id": str(pickup["id"]),
        "pickup_date": pickup["pickup_date"],
        "pickup_time": pickup_time,
        "attendant_name": attendant_name,
        "customer_service_officer_name": customer_service_officer_name,
        "accounting_officer_name": accounting_officer_name,
        "collected_by_name": pickup.get("collected_by_name"),
        "delegate_phone": pickup.get("delegate_phone"),
        "remaining_cartons": remaining,
        "shipment_status": shipment_status,
    }


# ---------------------------------------------------------------------------
# Internal formatters
# ---------------------------------------------------------------------------


def _first_present(*sources_and_keys: tuple[dict[str, Any], str]) -> Any:
    """First non-None value across a priority list of (dict, key) pairs.

    Needed because `note`/`billing` carry the same figures under different
    key names depending on which call site built them: `get_release_note_by_id`
    aliases them `billing_amount_paid_ngn` etc. (prefixed, to avoid clashing
    with `rn.*`'s own columns), while `get_billing_by_id` (the `billing`
    param on the generate/split/reissue paths) returns them unprefixed.
    """
    for source, key in sources_and_keys:
        val = source.get(key)
        if val is not None:
            return val
    return None


def _fmt_release_note(note: dict[str, Any], billing: dict[str, Any], total_cartons_for_customer: int) -> dict[str, Any]:
    tags = note.get("carton_tags") or []
    status = note["status"]
    # `or "0"` would be wrong here — Decimal("0.00") is falsy, so a genuinely
    # zero balance would incorrectly fall through to the "missing" default
    # and print as "0" instead of "0.00". Check for None explicitly.
    amount_paid_ngn = _first_present((note, "billing_amount_paid_ngn"), (billing, "amount_paid_ngn"))
    balance_ngn = _first_present((note, "billing_balance_ngn"), (billing, "balance_ngn"))
    total_ngn = _first_present((note, "billing_total_ngn"), (billing, "total_ngn"))
    return {
        "id": str(note["id"]),
        "reference_number": note["reference_number"],
        "customer_name": note.get("customer_name"),
        "container_number": note.get("container_number"),
        "carton_count": int(note.get("total_cartons") or 0),
        "total_cartons_for_customer": total_cartons_for_customer,
        "is_partial_release": bool(note.get("is_partial", False)),
        "carton_tags": list(tags),
        "packages_released": note.get("packages_released"),
        "package_unit": note.get("package_unit"),
        "packages_balance": note.get("packages_balance"),
        "payment_status": note.get("payment_status") or billing.get("status", ""),
        "status": status,
        "authorized_at": note["created_at"],
        # Bug fix (ground-truth audit): this was hardcoded None — now the
        # real address/name from the linked warehouse row (join added in
        # repository.get_release_note_by_id / list_release_notes).
        "warehouse_address": note.get("warehouse_address"),
        "warehouse_name": note.get("warehouse_name"),
        "warehouse_phone": note.get("warehouse_phone"),
        "is_on_credit": bool(note.get("is_on_credit", False)),
        "credit_granted_by_name": note.get("credit_granted_by_name"),
        "receipt_number": note.get("receipt_number"),
        # Ground-truth gap found live, reported by the user against a real
        # paper "Goods Release Note" reference: physical_document_number and
        # packing_list_invoice_numbers were captured on create but dropped
        # here before ever reaching the API response; amount paid / balance
        # owed / debt payment date were already joined by the repository
        # layer and dropped the same way.
        "physical_document_number": note.get("physical_document_number"),
        "packing_list_invoice_numbers": list(note.get("packing_list_invoice_numbers") or []),
        "amount_paid_ngn": str(amount_paid_ngn) if amount_paid_ngn is not None else "0",
        "balance_ngn": str(balance_ngn) if balance_ngn is not None else "0",
        "total_ngn": str(total_ngn) if total_ngn is not None else "0",
        "debt_due_date": str(note["debt_due_date"]) if note.get("debt_due_date") else None,
        # Expiry fields — valid_until is set when the note is issued (14-day window).
        # expired_at is the updated_at timestamp when status transitioned to expired.
        "valid_until": str(note["valid_until"]) if note.get("valid_until") else None,
        "expired_at": str(note.get("updated_at")) if status == "expired" else None,
        # picked_up_at — updated_at when the status flipped (same proxy as expired_at).
        # Feeds the warehouse "completed today" count (P2-2).
        "picked_up_at": str(note.get("updated_at")) if status == "picked_up" else None,
        # Outstanding storage balance on the linked billing record — shown in expired state UI.
        "storage_fees_ngn": str(billing.get("storage_fees_ngn", "0")),
        # parent_release_note_id — set on re-issued notes to link back to the original.
        "parent_release_note_id": str(note["parent_release_note_id"]) if note.get("parent_release_note_id") else None,
    }


# ---------------------------------------------------------------------------
# Online payment initialization (audit gap B12 — Paystack checkout)
# ---------------------------------------------------------------------------


def initialize_online_payment(
    tenant_id: str,
    billing_id: str,
    ctx: Any,
    callback_url: str | None,
    request_id: str = "",
) -> dict[str, Any]:
    """Create a Paystack checkout session for the customer's own billing record.

    Ownership is enforced here (customer role only reaches this route): the
    caller's user_id must resolve to the customer on the billing record. The
    payment itself is recorded by the HMAC-verified gateway webhook, never by
    this call or the browser redirect.
    """
    from . import paystack

    billing = repo.get_billing_by_id(tenant_id, billing_id)
    if not billing:
        raise ResourceNotFoundError("billing", billing_id)

    customer = repo.get_customer_by_user_id(tenant_id, ctx.user_id)
    if not customer or str(customer["id"]) != str(billing["customer_id"]):
        raise InsufficientPermissionsError(action="initialize_online_payment", required_role="owner")

    if billing["status"] in {"cancelled", "waived"}:
        raise BusinessRuleViolationError(
            f"This billing record is '{billing['status']}' and cannot accept payments.",
            rule_id="BR-PAY-INIT-001",
        )

    outstanding = Decimal(str(billing["balance_ngn"]))
    if outstanding <= 0:
        raise BusinessRuleViolationError(
            "Nothing is outstanding on this billing record.",
            rule_id="BR-PAY-INIT-002",
        )

    email = (billing.get("customer_email") or "").strip()
    if not email:
        raise BusinessRuleViolationError(
            "Add an email address to your profile to pay online — the payment gateway requires one.",
            rule_id="BR-PAY-INIT-003",
        )

    if callback_url and not callback_url.startswith(("https://", "http://")):
        raise BusinessRuleViolationError(
            "callback_url must be an http(s) URL.",
            rule_id="BR-PAY-INIT-004",
        )

    # Multi-tenant Paystack (2026-07-19): each tenant connects their own
    # secret key so payments land in their own account — no platform-wide
    # fallback. A tenant who hasn't configured one yet gets a clear error;
    # bank transfer remains available regardless.
    secret_key = repo.get_tenant_paystack_secret(tenant_id)
    if not secret_key:
        raise BusinessRuleViolationError(
            "Online payment isn't set up for this shipping company yet — please use bank transfer instead.",
            rule_id="PAYMENT_GATEWAY_NOT_CONFIGURED",
        )

    return paystack.initialize_transaction(
        secret_key=secret_key,
        email=email,
        amount_ngn=outstanding,
        billing_id=billing_id,
        callback_url=callback_url,
        tenant_id=tenant_id,
        request_id=request_id,
    )


def confirm_online_payment(
    tenant_id: str,
    billing_id: str,
    reference: str,
    ctx: Any,
    request_id: str = "",
) -> dict[str, Any]:
    """Reconcile a Paystack payment directly, without waiting on the webhook.

    Ground-truth gap found live: the webhook (services/payment_release/
    webhook.py) is the only thing that ever updated billing.status after an
    online payment — but Paystack's servers cannot reach a local dev
    `localhost` URL at all, and even in production a webhook can be delayed
    or lost. A customer would see Paystack's own "successful" page, click
    "View invoice", and find the bill still unpaid with "Pay" still live.
    Called from the customer's `callback_url` redirect (PaymentSuccess.tsx)
    with the `reference` Paystack appends to that URL — verifies the
    transaction directly against Paystack's own API rather than trusting the
    redirect, then reuses process_webhook_payment() so both this path and a
    webhook that arrives later (or first) share one confirmation code path;
    `gateway_transaction_id`'s unique constraint makes running both harmless.

    Returns:
        {"payment_status": "success" | "pending" | "failed", "billing": {...}}
        — "pending"/"failed" mean Paystack itself hasn't confirmed the charge
        yet (or it didn't succeed); this is not an error, just not-yet-paid.
    """
    from . import paystack

    billing = repo.get_billing_by_id(tenant_id, billing_id)
    if not billing:
        raise ResourceNotFoundError("billing", billing_id)

    customer = repo.get_customer_by_user_id(tenant_id, ctx.user_id)
    if not customer or str(customer["id"]) != str(billing["customer_id"]):
        raise InsufficientPermissionsError(action="confirm_online_payment", required_role="owner")

    # The reference must actually belong to this billing record — paystack.py
    # mints it as "{billing_id}.{nonce}" precisely so this can be checked;
    # otherwise a customer could try to apply someone else's reference (or a
    # stale one of their own) to a bill it was never issued for.
    if reference.split(".", 1)[0] != billing_id:
        raise BusinessRuleViolationError(
            "This payment reference does not belong to this billing record.",
            rule_id="BR-PAY-VERIFY-001",
        )

    secret_key = repo.get_tenant_paystack_secret(tenant_id)
    if not secret_key:
        raise BusinessRuleViolationError(
            "Online payment isn't set up for this shipping company yet — please use bank transfer instead.",
            rule_id="PAYMENT_GATEWAY_NOT_CONFIGURED",
        )

    data = paystack.verify_transaction(secret_key, reference)

    if data.get("status") != "success":
        # Not our error — the charge itself didn't succeed (or hasn't yet).
        # Report Paystack's own status rather than raising, so the frontend
        # can show "still pending" instead of a scary error.
        return {
            "gateway_status": data.get("status", "pending"),
            "new_payment_status": billing["status"],
            "outstanding_ngn": Decimal(str(billing["balance_ngn"])),
        }

    amount_ngn = Decimal(str(data.get("amount", 0))) / Decimal("100")
    gateway_transaction_id = str(data.get("id", ""))

    result = process_webhook_payment(
        tenant_id=tenant_id,
        billing_id=billing_id,
        amount_ngn=amount_ngn,
        payment_method="paystack",
        payment_reference=reference,
        gateway_transaction_id=gateway_transaction_id,
        request_id=request_id,
    )
    if result is None:
        # Already recorded — the webhook (or an earlier call to this same
        # endpoint, e.g. the customer refreshing the success page) beat us
        # to it. Not an error: re-fetch so the response still reflects the
        # (already correct) current billing state.
        current = repo.get_billing_by_id(tenant_id, billing_id)
        if current is None:
            raise ResourceNotFoundError("billing", billing_id)
        result = {
            "billing_id": billing_id,
            "amount_ngn": amount_ngn,
            "new_payment_status": current["status"],
            "outstanding_ngn": Decimal(str(current["balance_ngn"])),
            "release_note_available": current["status"] in {"paid", "overpaid"},
        }

    return {"gateway_status": "success", **result}
