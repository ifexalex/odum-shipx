"""Business logic for the Payment Release service.

Handles payment confirmation against billing records, release note generation
(full and partial), warehouse pickup recording with delegate support, and
carryover ledger creation when releasing with outstanding balances.
"""

import logging
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Any

from shared import pickup_code, uploads
from shared.audit import log_audit
from shared.db import tenant_transaction
from shared.events import publish_event
from shared.exceptions import (
    BusinessRuleViolationError,
    IllegalTransitionError,
    InsufficientPermissionsError,
    ResourceNotFoundError,
    ServiceUnavailableError,
    ValidationError,
)
from shared.notifications import enqueue_notification, enqueue_notifications
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

_URL_EXPIRY = 3600  # 1 hour


def _is_note_expired(note: dict[str, Any]) -> bool:
    """Return True if a release note's valid_until date is strictly in the past."""
    vu = note.get("valid_until")
    if vu is None:
        return False
    if isinstance(vu, datetime):
        vu_date = vu.date()
    elif isinstance(vu, date):
        vu_date = vu
    elif isinstance(vu, str) and vu.strip():
        try:
            vu_date = date.fromisoformat(vu.strip()[:10])
        except ValueError:
            return False
    else:
        return False
    return vu_date < date.today()


def _validate_evidence_file_key(tenant_id: str, billing_id: str, file_key: str) -> None:
    """Ensure a payment-claim evidence S3 key belongs strictly to this tenant and billing."""
    prefix = f"{tenant_id}/payment-claims/{billing_id}/"
    if not isinstance(file_key, str) or not file_key.startswith(prefix):
        raise ValidationError(
            "Invalid evidence file key for this invoice.",
            field_errors={"evidence_file_key": "Must reference a file uploaded for this billing record"},
        )
    remainder = file_key[len(prefix) :]
    if not remainder or "/" in remainder or "\\" in remainder or ".." in remainder:
        raise ValidationError(
            "Invalid evidence file key.",
            field_errors={"evidence_file_key": "Invalid file path"},
        )


def _is_customer_only(ctx: Any) -> bool:
    return bool(getattr(ctx, "is_customer_only", ctx.role == UserRole.CUSTOMER))


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
    ip_address: str | None = None,
    *,
    _tenant_short: str | None = None,
    _defer_side_effects: bool = False,
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
    tenant_short = _tenant_short if _tenant_short is not None else repo.get_tenant_short(tenant_id)

    # Payment record, invoice total + status, and any overpayment refund are
    # written in one transaction; the status is computed from the stored total.
    try:
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
    except repo.BillingNotPayableError as exc:
        raise BusinessRuleViolationError(
            f"Billing {billing_id} cannot accept payments ({exc.reason}).",
            rule_id="BILLING_NOT_PAYABLE",
        ) from exc
    if recorded is None:
        raise RuntimeError("record_payment returned None for a manual payment")
    payment = recorded.payment
    updated_billing = recorded.billing
    new_status = str(updated_billing["status"])

    if not _defer_side_effects:
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
            ip_address=ip_address,
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
    if not _is_customer_only(ctx):
        return True
    customer = repo.get_customer_by_user_id(tenant_id, ctx.user_id)
    return customer is not None and str(billing["customer_id"]) == str(customer["id"])


def generate_payment_claim_upload_url(
    tenant_id: str,
    billing_id: str,
    filename: str,
    content_type: str,
    ctx: Any,
    size_bytes: object = None,
) -> dict[str, Any]:
    uploads.EVIDENCE.check(content_type, size_bytes)

    billing = repo.get_billing_by_id(tenant_id, billing_id)
    if not billing or not _customer_owns_billing(tenant_id, ctx, billing):
        raise ResourceNotFoundError("billing", billing_id)

    upload = uploads.presign_upload(
        uploads.EVIDENCE, tenant_id, ("payment-claims", billing_id), filename, content_type, size_bytes
    )
    return {"file_key": upload.key, **upload.as_response()}


def submit_payment_claim(
    tenant_id: str,
    billing_id: str,
    req: Any,
    actor_id: str,
    ctx: Any,
    request_id: str = "",
    ip_address: str | None = None,
) -> dict[str, Any]:
    """Record a customer's "I've made this payment" claim. Evidence is
    mandatory at the model level (SubmitPaymentClaimRequest) — a claim can
    never reach this far without a file already uploaded to S3.
    """
    billing = repo.get_billing_by_id(tenant_id, billing_id)
    if not billing or not _customer_owns_billing(tenant_id, ctx, billing):
        raise ResourceNotFoundError("billing", billing_id)

    if billing["status"] in {"paid", "overpaid", "waived", "cancelled"} or (
        billing.get("balance_ngn") is not None and Decimal(str(billing["balance_ngn"])) <= Decimal("0")
    ):
        raise BusinessRuleViolationError(
            "This invoice has no outstanding balance to submit a payment against.",
            rule_id="BILLING_NOT_PAYABLE",
        )

    _validate_evidence_file_key(tenant_id, billing_id, req.evidence_file_key)

    # The evidence must exist and be within the limit; an Azure upload is not bound to its declared size.
    uploads.check_stored_size(uploads.EVIDENCE, req.evidence_file_key)

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
        ip_address=ip_address,
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
    expected_prefix = f"{tenant_id}/payment-claims/{claim['billing_id']}/"
    if not file_key.startswith(expected_prefix) or ".." in file_key[len(expected_prefix) :]:
        raise ResourceNotFoundError("payment_claim", claim_id)

    disposition = f'attachment; filename="{safe_filename(claim["evidence_file_name"], default="evidence")}"'
    url = get_storage_provider().presigned_get_url(file_key, expires_in=300, response_content_disposition=disposition)
    return {"url": url}


def confirm_payment_claim(
    tenant_id: str,
    claim_id: str,
    actor_id: str,
    ctx: Any,
    request_id: str = "",
    ip_address: str | None = None,
) -> dict[str, Any]:
    """Staff confirms a claim: records the real payment via confirm_payment()
    (the same code path used for any other manually-recorded payment) and
    links the claim to it atomically inside one transaction.
    """
    claim = repo.get_payment_claim_by_id(tenant_id, claim_id)
    if not claim:
        raise ResourceNotFoundError("payment_claim", claim_id)
    if claim["status"] != "pending":
        raise BusinessRuleViolationError(
            f"Claim is already {claim['status']} — nothing to confirm.",
            rule_id="PAYMENT_CLAIM_NOT_PENDING",
        )

    # Resolve PLATFORM-scoped tenant_short BEFORE opening tenant_transaction.
    tenant_short = repo.get_tenant_short(tenant_id)
    billing_id_str = str(claim["billing_id"])
    amount_ngn = Decimal(str(claim["amount_ngn"]))
    confirm_req = ConfirmPaymentRequest(
        amount_ngn=amount_ngn,
        payment_method="bank_transfer",
        payment_reference=f"payment_claim:{claim_id}",
    )
    with tenant_transaction(tenant_id):
        locked = repo.lock_payment_claim(tenant_id, claim_id)
        if locked is not None and locked.get("status") != "pending":
            raise BusinessRuleViolationError(
                f"Claim is already {locked['status']} — nothing to confirm.",
                rule_id="PAYMENT_CLAIM_NOT_PENDING",
            )
        payment_result = confirm_payment(
            tenant_id,
            billing_id_str,
            confirm_req,
            actor_id=actor_id,
            ctx=ctx,
            request_id=request_id,
            ip_address=ip_address,
            _tenant_short=tenant_short,
            _defer_side_effects=True,
        )
        updated = repo.update_payment_claim_status(
            tenant_id,
            claim_id,
            status="confirmed",
            reviewed_by=actor_id,
            payment_record_id=payment_result["payment_id"],
        )
        if updated is None:
            raise BusinessRuleViolationError(
                "Claim is no longer pending — confirmation aborted.",
                rule_id="PAYMENT_CLAIM_NOT_PENDING",
            )

    publish_event(
        source="logistics.payment_release",
        detail_type="PaymentConfirmed",
        tenant_id=tenant_id,
        payload={
            "payment_id": payment_result["payment_id"],
            "billing_id": billing_id_str,
            "amount_ngn": str(amount_ngn),
            "new_status": payment_result["new_payment_status"],
        },
        request_id=request_id,
    )
    log_audit(
        tenant_id=tenant_id,
        entity_type="payment_record",
        entity_id=payment_result["payment_id"],
        action="CREATE",
        actor_id=actor_id,
        actor_role=str(ctx.role),
        after_state={
            "billing_id": billing_id_str,
            "amount_ngn": str(amount_ngn),
            "billing_status": payment_result["new_payment_status"],
        },
        ip_address=ip_address,
    )
    log_audit(
        tenant_id=tenant_id,
        entity_type="payment_claim",
        entity_id=claim_id,
        action="UPDATE",
        actor_id=actor_id,
        actor_role=str(ctx.role),
        before_state={"status": "pending"},
        after_state={"status": "confirmed", "payment_record_id": payment_result["payment_id"]},
        ip_address=ip_address,
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
    ip_address: str | None = None,
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
        raise BusinessRuleViolationError(
            "Claim is no longer pending — nothing to reject.",
            rule_id="PAYMENT_CLAIM_NOT_PENDING",
        )

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
        ip_address=ip_address,
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

    try:
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
    except repo.BillingNotPayableError as exc:
        raise BusinessRuleViolationError(
            f"Billing {billing_id} cannot accept payments ({exc.reason}).",
            rule_id="BR-WEBHOOK-001",
        ) from exc

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
    ip_address: str | None = None,
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

    carton_tags = list(dict.fromkeys(req.carton_tags))
    is_count_based = not carton_tags and req.packages_released is not None
    packages_released = req.packages_released if is_count_based else None
    count_released = int(packages_released) if packages_released is not None else 0

    if req.release_with_outstanding and not req.approval_notes:
        raise BusinessRuleViolationError(
            "approval_notes is required when releasing with outstanding balance",
            rule_id="APPROVAL_NOTES_REQUIRED",
        )

    requested_warehouse_id = getattr(req, "warehouse_id", None)
    warehouse_row = repo.get_warehouse_by_id(tenant_id, requested_warehouse_id) if requested_warehouse_id else None
    if requested_warehouse_id and warehouse_row is not None and not warehouse_row.get("is_active", True):
        raise BusinessRuleViolationError(
            "Selected warehouse is inactive and cannot be used for new release notes.",
            rule_id="WAREHOUSE_INACTIVE",
        )
    warehouse_id = requested_warehouse_id
    if warehouse_row is None:
        warehouse_row = repo.get_default_warehouse(tenant_id)
        warehouse_id = str(warehouse_row["id"]) if warehouse_row else None

    if not is_count_based:
        approved_tags = repo.get_approved_carton_tags_for_billing(
            tenant_id, str(billing["customer_id"]), str(billing["container_id"])
        )
        if approved_tags:
            unknown_tags = set(carton_tags) - set(approved_tags)
            if unknown_tags:
                raise BusinessRuleViolationError(
                    f"Carton tags not found on approved packing lists for this invoice: {', '.join(sorted(unknown_tags))}",
                    rule_id="INVALID_CARTON_TAGS",
                )

    is_on_credit = bool(req.release_with_outstanding)
    credit_granted_by = actor_id if is_on_credit else None
    credit_granted_by_name = req.credit_granted_by_name if is_on_credit else None

    tenant_short = repo.get_tenant_short(tenant_id)

    with tenant_transaction(tenant_id):
        locked_billing = repo.lock_billing(tenant_id, req.billing_id)
        if locked_billing is not None:
            billing = {**billing, **locked_billing}

        payment_status = billing["status"]
        if payment_status == "cancelled":
            raise BusinessRuleViolationError(
                "Cannot generate a release note for a cancelled invoice.",
                rule_id="BILLING_CANCELLED",
            )

        amount_paid = Decimal(str(billing["amount_paid_ngn"]))
        total_due = Decimal(str(billing["total_ngn"]))
        total_cbm = Decimal(str(billing["total_cbm"] or "0"))
        total_cartons_for_customer = int(billing["total_cartons"] or 0)

        already_total_cartons = repo.get_active_release_note_total_cartons(tenant_id, req.billing_id)
        already_released_tags: set[str] = set()
        already_released_count = 0
        selected_tag_count = len(carton_tags)

        if is_count_based:
            already_released_count = max(
                repo.get_active_release_note_packages_released(tenant_id, req.billing_id),
                already_total_cartons,
            )
            if already_released_count + count_released > total_cartons_for_customer:
                remaining = max(0, total_cartons_for_customer - already_released_count)
                raise BusinessRuleViolationError(
                    f"Requested {count_released} {req.package_unit} exceeds the {remaining} "
                    f"remaining unreleased (of {total_cartons_for_customer} total; "
                    f"{already_released_count} already on an active or picked-up release note).",
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
            tag_quantities = repo.get_carton_tag_quantities(
                tenant_id,
                str(billing["customer_id"]),
                str(billing["container_id"]),
                carton_tags,
            )
            selected_tag_count = sum(tag_quantities.get(tag, 1) for tag in carton_tags)
            already_released_count = max(len(already_released_tags), already_total_cartons)
            if total_cartons_for_customer > 0 and already_released_count + selected_tag_count > total_cartons_for_customer:
                remaining = max(0, total_cartons_for_customer - already_released_count)
                raise BusinessRuleViolationError(
                    f"Requested {selected_tag_count} cartons exceeds the {remaining} "
                    f"remaining unreleased (of {total_cartons_for_customer} total).",
                    rule_id="BR-RN-OVERRELEASE-001",
                )

        # Payment check (cumulative across already-released + newly-requested cartons)
        if payment_status in {"paid", "overpaid"}:
            pass  # fully paid — always allow
        elif payment_status == "partially_paid":
            if not req.release_with_outstanding:
                if is_count_based:
                    cumulative_count = already_released_count + count_released
                    required_payment = (
                        Decimal(cumulative_count) / total_cartons_for_customer * total_due
                        if total_cartons_for_customer > 0
                        else total_due
                    )
                else:
                    tags_for_cbm = (
                        list(dict.fromkeys([*sorted(already_released_tags), *carton_tags]))
                        if already_released_tags
                        else carton_tags
                    )
                    selected_cbm = repo.get_cbm_for_carton_tags(
                        tenant_id,
                        str(billing["customer_id"]),
                        str(billing["container_id"]),
                        tags_for_cbm,
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

        seq = repo.get_next_release_note_seq(tenant_id)
        reference_number = f"{tenant_short}-RN-{date.today():%Y%m%d}-{seq:04d}"

        if is_count_based:
            total_cartons = count_released
            packages_balance = max(0, total_cartons_for_customer - (already_released_count + total_cartons))
            is_partial = total_cartons < total_cartons_for_customer
        else:
            total_cartons = selected_tag_count
            packages_balance = max(0, total_cartons_for_customer - (already_released_count + total_cartons))
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

        # Carryover ledger — written AFTER the release note inside the same transaction
        # so release_note_id can be linked; guarded so a second credit note on the same
        # invoice does not duplicate customer debt.
        if req.release_with_outstanding:
            balance = Decimal(str(billing["balance_ngn"]))
            repo.mark_billing_released_with_outstanding(tenant_id, req.billing_id)
            if balance > Decimal("0") and not repo.has_active_carryover_for_billing(tenant_id, req.billing_id):
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
                note["debt_due_date"] = getattr(req, "due_date", None)

    note["customer_name"] = billing.get("customer_name")
    note["container_number"] = billing.get("container_number")
    if warehouse_row:
        note["warehouse_name"] = warehouse_row.get("name")
        note["warehouse_address"] = warehouse_row.get("address")
        note["warehouse_phone"] = warehouse_row.get("phone")

    _issue_pickup_code(tenant_id, note, request_id)

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
        ip_address=ip_address,
    )

    return _fmt_release_note(note, billing, total_cartons_for_customer)


# ---------------------------------------------------------------------------
# Pickup code (audit UX-09)
# ---------------------------------------------------------------------------


def _issue_pickup_code(
    tenant_id: str,
    note: dict[str, Any],
    request_id: str = "",
    *,
    restore_previous_on_failure: bool = False,
) -> list[str]:
    """Give a release note a pickup code and send it to its customer; return the channels it went out on.

    Best effort: the release note exists and is valid whatever happens here, so this never raises. If it cannot issue a
    code on initial generation the note is left without one; on explicit reissue (`restore_previous_on_failure=True`),
    the previously valid hash is restored rather than stripping pickup-code protection.
    """
    note_id = str(note["id"])
    previous_hash = note.get("pickup_code_hash")
    if not pickup_code.is_configured():
        return []
    try:
        contact = repo.get_customer_contact(tenant_id, str(note["customer_id"]))
        addresses = (("sms", (contact or {}).get("phone")), ("email", (contact or {}).get("email")))
        if not contact or not any(address for _, address in addresses):
            logger.warning("No phone or email to send a pickup code to for release note %s: it has no code", note_id)
            return []

        code = pickup_code.new_code()
        code_hash = pickup_code.hash_code(note_id, code)
        if repo.set_pickup_code(tenant_id, note_id, code_hash) is None:
            return []

        sent: list[str] = []
        for channel, address in addresses:
            if not address:
                continue
            try:
                if enqueue_notification(
                    tenant_id=tenant_id,
                    channel=channel,
                    recipient=str(address),
                    template_id="pickup_code_issued",
                    template_vars={"reference_number": note.get("reference_number", ""), "pickup_code": code},
                    locale=str(contact.get("locale") or "en"),
                    request_id=request_id,
                    customer_id=str(note["customer_id"]),
                ):
                    sent.append(channel)
            except Exception:
                logger.warning("Could not enqueue a pickup code %s for release note %s", channel, note_id, exc_info=True)

        if not sent:
            fallback_hash = previous_hash if restore_previous_on_failure else None
            repo.set_pickup_code(tenant_id, note_id, fallback_hash)
            logger.warning(
                "A pickup code for release note %s could not be sent on any channel (restored_previous=%s)",
                note_id,
                restore_previous_on_failure,
            )
            return []
        note["pickup_code_hash"] = code_hash
        note["pickup_code_failed_attempts"] = 0
        return sent
    except Exception:
        logger.warning("Could not issue a pickup code for release note %s", note_id, exc_info=True)
        return []


def reissue_pickup_code(
    tenant_id: str,
    note_id: str,
    actor_id: str,
    ctx: Any,
    request_id: str = "",
    ip_address: str | None = None,
) -> dict[str, Any]:
    """Issue a fresh pickup code for an active, unexpired release note and send it to the customer (staff action)."""
    if not pickup_code.is_configured():
        raise BusinessRuleViolationError("Pickup codes are not set up for this system", rule_id="PICKUP_CODES_NOT_CONFIGURED")
    note = repo.get_release_note_by_id(tenant_id, note_id)
    if not note:
        raise ResourceNotFoundError("release_note", note_id)
    if note["status"] != "active":
        raise BusinessRuleViolationError(
            f"A pickup code can only be issued for an active release note: this one is '{note['status']}'",
            rule_id="RELEASE_NOTE_NOT_ACTIVE",
        )
    if _is_note_expired(note):
        raise BusinessRuleViolationError(
            "This release note has expired — reissue the release note instead of its pickup code.",
            rule_id="RELEASE_NOTE_EXPIRED",
        )

    channels = _issue_pickup_code(tenant_id, note, request_id, restore_previous_on_failure=True)
    if not channels:
        raise BusinessRuleViolationError(
            "The new pickup code could not be sent: the customer has no phone or email on file, "
            "or those channels are switched off",
            rule_id="PICKUP_CODE_NOT_DELIVERABLE",
        )

    log_audit(
        tenant_id=tenant_id,
        entity_type="release_note",
        entity_id=note_id,
        action="UPDATE",
        actor_id=actor_id,
        actor_role=str(ctx.role),
        after_state={"pickup_code_reissued": True, "sent_via": channels},
        ip_address=ip_address,
    )
    return {"release_note_id": note_id, "sent_via": channels}


def _verify_pickup_code(tenant_id: str, note: dict[str, Any], entered: str | None, actor_id: str, ctx: Any) -> None:
    """Check the code the collector gave, or refuse the pickup. Called only for a note that carries a code.

    A wrong code is counted; after `MAX_FAILED_ATTEMPTS` the note takes no more codes until staff reissue one, so a
    six digit code cannot be guessed at the counter. Nothing here ever includes the code, right or wrong.
    """
    note_id = str(note["id"])
    if not pickup_code.is_configured():
        # The note has a code but this system cannot check it. Letting the pickup through would defeat the point.
        raise ServiceUnavailableError("Pickup codes cannot be checked right now. Try again shortly.")

    failed = int(note.get("pickup_code_failed_attempts") or 0)
    if failed >= pickup_code.MAX_FAILED_ATTEMPTS:
        raise BusinessRuleViolationError(
            "This release note is locked after too many wrong pickup codes. Ask the shipping company to issue a new code.",
            rule_id="PICKUP_CODE_LOCKED",
        )
    if not pickup_code.normalise(entered):
        raise BusinessRuleViolationError(
            "Ask the collector for the pickup code that was sent to the customer.", rule_id="PICKUP_CODE_REQUIRED"
        )

    if pickup_code.matches(note_id, entered, str(note["pickup_code_hash"])):
        if failed:
            repo.reset_pickup_code_attempts(tenant_id, note_id)
        return

    total = repo.record_failed_pickup_code(tenant_id, note_id) or failed + 1
    log_audit(
        tenant_id=tenant_id,
        entity_type="release_note",
        entity_id=note_id,
        action="UPDATE",
        actor_id=actor_id,
        actor_role=str(ctx.role),
        after_state={"pickup_code_failed_attempts": total},
    )
    if total >= pickup_code.MAX_FAILED_ATTEMPTS:
        logger.warning("Release note %s locked after %d wrong pickup codes", note_id, total)
        for role in ("nigeria_office_staff", "tenant_admin"):
            notify_staff(
                tenant_id=tenant_id,
                event_type="pickup_code_locked",
                entity_type="release_note",
                entity_id=note_id,
                title="Pickup code locked",
                body=f"Release note {note.get('reference_number', '')} is locked after wrong pickup codes. Issue a new code.",
                target_role=role,
            )
        raise BusinessRuleViolationError(
            "That pickup code is not right, and this release note is now locked. Ask the shipping company to issue a new code.",
            rule_id="PICKUP_CODE_LOCKED",
        )
    remaining = pickup_code.MAX_FAILED_ATTEMPTS - total
    tries = "try" if remaining == 1 else "tries"
    raise BusinessRuleViolationError(
        f"That pickup code is not right. {remaining} {tries} left before this release note is locked.",
        rule_id="PICKUP_CODE_INVALID",
    )


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
    if _is_customer_only(ctx):
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
    if not warehouse.get("is_active", True):
        raise BusinessRuleViolationError(
            "An inactive warehouse cannot be set as the default warehouse — reactivate it first.",
            rule_id="WAREHOUSE_INACTIVE",
        )

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

    if _is_customer_only(ctx):
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
    ip_address: str | None = None,
) -> dict[str, Any]:
    """Create a child release note for un-collected carton tags and shrink the parent atomically.

    Guards:
    - Parent must be active and unexpired.
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
    if _is_note_expired(note):
        raise BusinessRuleViolationError(
            "This release note has expired — reissue it before splitting.",
            rule_id="RELEASE_NOTE_EXPIRED",
        )

    requested_tags: list[str] = list(dict.fromkeys(req.carton_tags))
    requested_set = set(requested_tags)
    billing = repo.get_billing_by_id(tenant_id, str(note.get("billing_id", "")))
    tenant_short = repo.get_tenant_short(tenant_id)

    with tenant_transaction(tenant_id):
        locked = repo.lock_release_note(tenant_id, note_id)
        if locked is not None:
            if locked["status"] != "active":
                raise BusinessRuleViolationError(
                    f"Release note status is '{locked['status']}' — only active notes can be split",
                    rule_id="RELEASE_NOTE_NOT_ACTIVE",
                )
            note = {**note, **locked}

        parent_tag_list: list[str] = list(note.get("carton_tags") or [])
        parent_tags: set[str] = set(parent_tag_list)

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
                "warehouse_id": note.get("warehouse_id"),
                "packing_list_invoice_numbers": list(note.get("packing_list_invoice_numbers") or []),
                "is_on_credit": bool(note.get("is_on_credit", False)),
                "credit_granted_by": note.get("credit_granted_by"),
                "credit_granted_by_name": note.get("credit_granted_by_name"),
            },
        )
        if child_note is None:
            raise RuntimeError("create_split_release_note returned None unexpectedly")

        remaining_tags = [t for t in parent_tag_list if t not in requested_set]
        remaining_unpicked = set(remaining_tags) - already_picked
        new_parent_status = "picked_up" if not remaining_unpicked else "active"
        repo.update_parent_release_note_after_split(
            tenant_id,
            note_id,
            remaining_tags,
            len(remaining_tags),
            new_parent_status,
        )

    _issue_pickup_code(tenant_id, child_note, request_id)

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
        ip_address=ip_address,
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
    ip_address: str | None = None,
) -> dict[str, Any]:
    """Re-issue an expired release note with a fresh 14-day validity window.

    Guards:
    - Original note must be 'expired' and not already reissued to an active/picked-up child.
    - Linked billing must not be cancelled and must still be eligible for release.
    - Only un-collected cartons/tags are carried onto the reissued note.
    """
    note = repo.get_release_note_by_id(tenant_id, note_id)
    if not note:
        raise ResourceNotFoundError("release_note", note_id)

    if note["status"] != "expired":
        raise BusinessRuleViolationError(
            f"Only expired release notes can be re-issued — current status is '{note['status']}'",
            rule_id="RELEASE_NOTE_NOT_EXPIRED",
        )

    billing_id = str(note.get("billing_id", ""))
    billing = repo.get_billing_by_id(tenant_id, billing_id)
    tenant_short = repo.get_tenant_short(tenant_id)

    with tenant_transaction(tenant_id):
        locked = repo.lock_release_note(tenant_id, note_id)
        if locked is not None:
            if locked["status"] != "expired":
                raise BusinessRuleViolationError(
                    f"Only expired release notes can be re-issued — current status is '{locked['status']}'",
                    rule_id="RELEASE_NOTE_NOT_EXPIRED",
                )
            note = {**note, **locked}

        locked_billing = repo.lock_billing(tenant_id, billing_id) if billing_id else None
        if locked_billing is not None:
            billing = {**(billing or {}), **locked_billing}

        if billing is not None:
            b_status = billing.get("status")
            if b_status == "cancelled":
                raise BusinessRuleViolationError(
                    "Cannot re-issue a release note for a cancelled invoice.",
                    rule_id="BILLING_CANCELLED",
                )
            b_balance = Decimal(str(billing.get("balance_ngn") or "0"))
            if (
                b_balance > _TOLERANCE
                and not bool(note.get("is_on_credit"))
                and b_status not in {"paid", "overpaid", "waived", "released_with_outstanding", "partially_paid"}
            ):
                raise BusinessRuleViolationError(
                    "Invoice has an unpaid balance — settle payment before re-issuing this release note.",
                    rule_id="PAYMENT_REQUIRED",
                )

        if repo.has_active_child_release_note(tenant_id, note_id):
            raise BusinessRuleViolationError(
                "This expired release note has already been re-issued.",
                rule_id="RELEASE_NOTE_ALREADY_REISSUED",
            )

        orig_tags = list(note.get("carton_tags") or [])
        if orig_tags:
            picked_tags = set(repo.get_picked_carton_tags(tenant_id, note_id))
            reissue_tags = [t for t in orig_tags if t not in picked_tags]
            if not reissue_tags:
                raise BusinessRuleViolationError(
                    "All cartons on this release note have already been picked up.",
                    rule_id="NOTHING_REMAINING_TO_REISSUE",
                )
            reissue_cartons = len(reissue_tags)
            reissue_packages = note.get("packages_released")
        else:
            reissue_tags = []
            already_picked_count = repo.sum_cartons_picked_for_release_note(tenant_id, note_id)
            orig_total = int(note.get("total_cartons") or 0)
            reissue_cartons = max(0, orig_total - already_picked_count)
            if orig_total > 0 and reissue_cartons <= 0:
                raise BusinessRuleViolationError(
                    "All cartons on this release note have already been picked up.",
                    rule_id="NOTHING_REMAINING_TO_REISSUE",
                )
            reissue_packages = reissue_cartons if note.get("packages_released") is not None else None

        seq = repo.get_next_release_note_seq(tenant_id)
        reference_number = f"{tenant_short}-RN-{date.today():%Y%m%d}-{seq:04d}"

        new_note = repo.create_split_release_note(
            tenant_id,
            {
                "tenant_id": tenant_id,
                "billing_id": billing_id,
                "customer_id": str(note.get("customer_id")),
                "container_id": str(note.get("container_id")),
                "reference_number": reference_number,
                "carton_tags": reissue_tags,
                "total_cartons": reissue_cartons,
                "is_partial": bool(note.get("is_partial", False)),
                "parent_release_note_id": note_id,
                "status": "active",
                "issued_by": actor_id,
                "notes": note.get("notes"),
                "valid_until": date.today() + timedelta(days=14),
                "warehouse_id": note.get("warehouse_id"),
                "is_on_credit": bool(note.get("is_on_credit", False)),
                "credit_granted_by": note.get("credit_granted_by"),
                "credit_granted_by_name": note.get("credit_granted_by_name"),
                "packages_released": reissue_packages,
                "package_unit": note.get("package_unit"),
                "packages_balance": note.get("packages_balance"),
                "physical_document_number": note.get("physical_document_number"),
                "packing_list_invoice_numbers": list(note.get("packing_list_invoice_numbers") or []),
            },
        )
        if new_note is None:
            raise RuntimeError("create_split_release_note returned None unexpectedly during reissue")

    _issue_pickup_code(tenant_id, new_note, request_id)

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
        ip_address=ip_address,
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
    ip_address: str | None = None,
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

    if _is_note_expired(note):
        raise BusinessRuleViolationError(
            "This release note has expired and cannot be used for pickup — ask staff to reissue it.",
            rule_id="RELEASE_NOTE_EXPIRED",
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

    raw_tags_picked = list(getattr(req, "carton_tags_picked", None) or [])
    carton_tags_picked = list(dict.fromkeys(raw_tags_picked))
    note_tags_initial = list(note.get("carton_tags") or [])
    note_total_initial = int(note.get("total_cartons") or 0)
    # A line item with quantity > 1 carries a single carton_tag (e.g. 1 tag for 10 units),
    # so total_cartons > len(carton_tags). Only require 1:1 tag-to-count matching when
    # every tag on the note represents a single unit.
    has_multi_unit_tags = bool(note_tags_initial) and note_total_initial > len(note_tags_initial)
    if carton_tags_picked and not has_multi_unit_tags and len(carton_tags_picked) != req.cartons_released:
        raise BusinessRuleViolationError(
            f"Number of carton_tags_picked ({len(carton_tags_picked)}) must match cartons_released ({req.cartons_released}).",
            rule_id="CARTON_TAG_COUNT_MISMATCH",
        )

    # Verify pickup code outside the pickup transaction so failed-attempt increments persist.
    code_checked = False
    if note.get("pickup_code_hash"):
        _verify_pickup_code(tenant_id, note, getattr(req, "pickup_code", None), actor_id, ctx)
        code_checked = True

    delegate_id_type_val = None
    if req.delegate_id_type:
        delegate_id_type_val = req.delegate_id_type.value if hasattr(req.delegate_id_type, "value") else str(req.delegate_id_type)

    collected_by_name = req.delegate_name if req.is_delegate else req.collected_by_name

    with tenant_transaction(tenant_id):
        locked = repo.lock_release_note(tenant_id, note_id)
        if locked is not None:
            if locked["status"] != "active":
                raise IllegalTransitionError(
                    entity="release_note",
                    current_state=locked["status"],
                    requested_state="picked_up",
                    allowed=["active"],
                )
            note = {**note, **locked}

        note_tags = set(note.get("carton_tags") or [])
        if carton_tags_picked and note_tags:
            invalid_tags = set(carton_tags_picked) - note_tags
            if invalid_tags:
                raise BusinessRuleViolationError(
                    f"Picked carton tags not on this release note: {', '.join(sorted(invalid_tags))}",
                    rule_id="INVALID_CARTON_TAGS",
                )
            # For single-unit tags (1 tag = 1 carton), forbid picking the same tag twice.
            # For multi-unit tags (e.g. 1 tag representing qty 10), partial pickups reuse
            # the same tag and are bounded below by sum_cartons_picked <= note_total.
            if not has_multi_unit_tags:
                already_picked_tags = set(repo.get_picked_carton_tags(tenant_id, note_id))
                dup_picked = set(carton_tags_picked) & already_picked_tags
                if dup_picked:
                    raise BusinessRuleViolationError(
                        f"Carton tags already picked up: {', '.join(sorted(dup_picked))}",
                        rule_id="TAGS_ALREADY_PICKED",
                    )

        pickup = repo.create_pickup_record(
            tenant_id,
            {
                "tenant_id": tenant_id,
                "release_note_id": note_id,
                "customer_id": str(note["customer_id"]),
                "carton_tags_picked": carton_tags_picked,
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

        # Enforce carton conservation atomically — raising here rolls back create_pickup_record.
        total_picked = repo.sum_cartons_picked_for_release_note(tenant_id, note_id)
        note_total = int(note["total_cartons"] or 0)
        if note_total > 0 and total_picked > note_total:
            raise BusinessRuleViolationError(
                f"Cannot pick up {req.cartons_released} cartons: total picked ({total_picked}) "
                f"exceeds release note total ({note_total}).",
                rule_id="PICKUP_EXCEEDS_RELEASE_NOTE",
            )

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
            repo.update_shipment_tracking_for_customer(
                tenant_id, str(note["customer_id"]), str(note["container_id"]), "picked_up"
            )
            shipment_status = "picked_up"

        # Update container to fully_released iff every customer on the container has collected all billed cartons
        all_done = repo.all_container_customers_fully_released(tenant_id, str(note["container_id"]))
        if all_done is None:
            container_total = repo.sum_total_cartons_from_billing(tenant_id, str(note["container_id"]))
            container_released = repo.sum_cartons_released_for_container(tenant_id, str(note["container_id"]))
            all_done = container_total > 0 and container_released >= container_total
        if all_done:
            repo.update_container_status(tenant_id, str(note["container_id"]), "fully_released")

    remaining = max(0, note_total - total_picked)

    pickup_time = None
    created_at = pickup.get("created_at")
    if created_at and hasattr(created_at, "strftime"):
        pickup_time = created_at.strftime("%H:%M")

    attendant_id = getattr(req, "warehouse_attendant_id", None) or actor_id
    attendant_name = repo.get_tenant_user_name(tenant_id, attendant_id)

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
        after_state={
            "release_note_id": note_id,
            "release_note_status": note_status,
            "cartons_count": req.cartons_released,
            "pickup_code_verified": code_checked,
        },
        ip_address=ip_address,
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
    total_cartons = int(note.get("total_cartons") or 0)
    cartons_picked_up = int(note.get("cartons_picked_up") or 0)
    if status == "picked_up" and cartons_picked_up == 0:
        cartons_picked_up = total_cartons
    cartons_remaining = max(0, total_cartons - cartons_picked_up)
    return {
        "id": str(note["id"]),
        "reference_number": note["reference_number"],
        "customer_name": note.get("customer_name"),
        "container_number": note.get("container_number"),
        "carton_count": total_cartons,
        "cartons_picked_up": cartons_picked_up,
        "cartons_remaining": cartons_remaining,
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
        # Pickup code (audit UX-09). Whether the warehouse must ask for one, and whether wrong guesses have locked the
        # note. The code is never in a response: it exists only in the message sent to the customer.
        "pickup_code_required": bool(note.get("pickup_code_hash")) and status == "active",
        "pickup_code_locked": bool(note.get("pickup_code_hash"))
        and int(note.get("pickup_code_failed_attempts") or 0) >= pickup_code.MAX_FAILED_ATTEMPTS,
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

    amount_ngn = paystack.charge_amount_ngn(data)
    if amount_ngn is None:
        # A successful charge that is not a positive naira amount is not applied (the same rule as the webhook).
        raise BusinessRuleViolationError(
            "This payment was not made in naira, so it has not been applied to your invoice. Please contact the office.",
            rule_id="BR-PAY-VERIFY-002",
        )
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
