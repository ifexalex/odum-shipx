"""Business logic for the Billing service.

Handles auto-billing on container clearance, CBM dispute lifecycle,
carryover/credit application, and billing recalculation on dispute resolution.
"""

import logging
from datetime import UTC, date, datetime
from decimal import ROUND_HALF_UP, Decimal

from shared.audit import log_audit
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

# ---------------------------------------------------------------------------
# CBM dispute state machine
# ---------------------------------------------------------------------------

_DISPUTE_ALLOWED_SOURCE_STATES = {
    "acknowledged",
    "investigating",
    "escalated_china",
}

_DISPUTE_ALLOWED_TARGET_STATES = {
    "investigating",
    "escalated_china",
    "resolved_adjusted",
    "resolved_no_change",
}


# ---------------------------------------------------------------------------
# Auto-billing: triggered by PaymentDue EventBridge event
# ---------------------------------------------------------------------------


def handle_payment_due(
    tenant_id: str,
    container_id: str,
    customer_id: str,
    container_number: str | None,
    request_id: str = "",
) -> None:
    """Create a billing record for a customer when their container is cleared.

    Called from the EventBridge handler — fire and return; errors are logged
    but should not crash the event processor.
    """
    # 1. Fetch pricing config
    cbm_cfg = repo.get_tenant_config_value(tenant_id, "cbm_rate_per_unit") or {}
    dollar_cfg = repo.get_tenant_config_value(tenant_id, "dollar_rate") or {}

    cbm_rate_usd = Decimal(str(cbm_cfg.get("rate_usd", 0)))
    dollar_rate = Decimal(str(dollar_cfg.get("rate", 0)))

    if cbm_rate_usd <= 0 or dollar_rate <= 0:
        logger.warning(
            "Skipping billing for customer %s — missing tenant config "
            "(cbm_rate_usd=%s, dollar_rate=%s)",
            customer_id, cbm_rate_usd, dollar_rate,
        )
        return

    # 2. Sum CBM + carton count from approved packing lists
    totals = repo.get_cbm_and_carton_totals(tenant_id, customer_id, container_id)
    total_cbm = Decimal(str(totals["total_cbm"]))
    total_cartons = int(totals["total_cartons"])

    if total_cbm <= 0:
        logger.info(
            "Skipping billing for customer %s — no CBM for container %s",
            customer_id, container_id,
        )
        return

    # 3. Calculate subtotals
    subtotal_usd = (total_cbm * cbm_rate_usd).quantize(Decimal("0.01"), ROUND_HALF_UP)
    subtotal_ngn = (subtotal_usd * dollar_rate).quantize(Decimal("0.01"), ROUND_HALF_UP)

    # 4. Carryovers (add to total)
    carryovers = repo.get_outstanding_carryovers(tenant_id, customer_id)
    carryover_ngn = sum(
        Decimal(str(c["carryover_amount_ngn"])) for c in carryovers
    )

    # 5. Credits from approved credit-note refunds (subtract from total)
    credits = repo.get_pending_credit_refunds(tenant_id, customer_id)
    credits_ngn = sum(Decimal(str(r["amount_ngn"])) for r in credits)

    # 6. Final total (misc_charges_ngn starts at 0; storage/misc added later)
    total_ngn = (subtotal_ngn + carryover_ngn - credits_ngn).quantize(
        Decimal("0.01"), ROUND_HALF_UP
    )

    # 7. Generate invoice number
    tenant_short = repo.get_tenant_short(tenant_id)
    today_str = date.today().strftime("%Y%m%d")
    seq = repo.get_next_invoice_seq(tenant_id)
    invoice_number = f"{tenant_short}-INV-{today_str}-{seq:04d}"

    # 8. Persist billing record
    now = datetime.now(UTC)
    billing = repo.create_billing(
        tenant_id,
        {
            "tenant_id":        tenant_id,
            "customer_id":      customer_id,
            "container_id":     container_id,
            "invoice_number":   invoice_number,
            "total_cartons":    total_cartons,
            "total_cbm":        total_cbm,
            "cbm_rate_usd":     cbm_rate_usd,
            "subtotal_usd":     subtotal_usd,
            "exchange_rate_ngn": dollar_rate,
            "subtotal_ngn":     subtotal_ngn,
            "misc_charges_ngn": Decimal("0"),
            "total_ngn":        total_ngn,
            "amount_paid_ngn":  Decimal("0"),
            "status":           "unpaid",
            "billed_at":        now,
            "created_by":       None,
        },
    )
    billing_id = str(billing["id"])

    # 9. Mark carryovers as applied
    if carryovers:
        repo.mark_carryovers_applied(
            tenant_id, [str(c["id"]) for c in carryovers], billing_id
        )

    # 10. Mark credit refunds as applied
    if credits:
        repo.mark_credit_refunds_applied(
            tenant_id, [str(r["id"]) for r in credits]
        )

    # 11. Publish PaymentDue event
    publish_event(
        source="logistics.billing",
        detail_type="PaymentDue",
        tenant_id=tenant_id,
        payload={
            "billing_id":       billing_id,
            "customer_id":      customer_id,
            "container_id":     container_id,
            "container_number": container_number,
            "invoice_number":   invoice_number,
            "total_ngn":        str(total_ngn),
        },
        request_id=request_id,
    )
    logger.info(
        "Billing %s created for customer %s / container %s",
        billing_id, customer_id, container_id,
    )


# ---------------------------------------------------------------------------
# GET billing for customer
# ---------------------------------------------------------------------------


def get_billing_for_customer(
    tenant_id: str,
    customer_id: str,
    ctx,
    container_id: str | None = None,
) -> list[dict]:
    """Return enriched billing records for a customer.

    CUSTOMER role: verified against ctx.user_id — can only see their own billing.
    """
    if ctx.role == UserRole.CUSTOMER:
        customer = repo.get_customer_by_user_id(tenant_id, ctx.user_id)
        if not customer or str(customer["id"]) != customer_id:
            raise InsufficientPermissionsError(
                "Customers may only view their own billing records"
            )

    rows = repo.list_billing_for_customer(tenant_id, customer_id, container_id)
    return [_enrich_billing(tenant_id, row) for row in rows]


def _enrich_billing(tenant_id: str, row: dict) -> dict:
    """Attach nested data and compute derived response fields."""
    billing_id = str(row["id"])

    misc_charges = repo.get_misc_charges(tenant_id, billing_id)
    payments = repo.get_payment_records(tenant_id, billing_id)
    applied_cos = repo.get_applied_carryovers(tenant_id, billing_id)
    active_disputes = repo.get_active_disputes(tenant_id, billing_id)

    misc_fees_ngn = sum(
        Decimal(str(m["amount_ngn"]))
        for m in misc_charges
        if m.get("charge_type") != "storage_fee"
    )
    storage_fees_ngn = sum(
        Decimal(str(m["amount_ngn"]))
        for m in misc_charges
        if m.get("charge_type") == "storage_fee"
    )
    carryover_ngn = sum(
        Decimal(str(c["carryover_amount_ngn"])) for c in applied_cos
    )

    return {
        "id":                       str(row["id"]),
        "container_id":             str(row["container_id"]),
        "container_number":         row.get("container_number"),
        "total_cbm":                row["total_cbm"],
        "cbm_rate_usd":             row["cbm_rate_usd"],
        "dollar_rate":              row["exchange_rate_ngn"],
        "subtotal_usd":             row["subtotal_usd"],
        "subtotal_ngn":             row["subtotal_ngn"],
        "misc_fees":                [
            {"description": m["description"], "amount_ngn": m["amount_ngn"]}
            for m in misc_charges
        ],
        "misc_fees_ngn":            misc_fees_ngn,
        "adjustments_ngn":          Decimal("0"),
        "carryover_ngn":            carryover_ngn,
        "storage_fees_ngn":         storage_fees_ngn,
        "total_due_ngn":            row["total_ngn"],
        "total_paid_ngn":           row["amount_paid_ngn"],
        "outstanding_ngn":          row["balance_ngn"],
        "payment_status":           row["status"],
        "released_with_outstanding": row.get("released_with_outstanding", False),
        "billed_at":                row.get("billed_at"),
        "payments":                 [
            {
                "id":               str(p["id"]),
                "amount_ngn":       p["amount_ngn"],
                "payment_method":   p.get("payment_method"),
                "payment_reference": p.get("reference_number"),
                "confirmed_at":     p["created_at"],
            }
            for p in payments
        ],
        "carryovers":               [
            {
                "id":                str(c["id"]),
                "amount_ngn":        c["carryover_amount_ngn"],
                "source_billing_id": str(c["source_billing_id"]),
                "created_at":        c["created_at"],
            }
            for c in applied_cos
        ],
        "_active_disputes":         [_fmt_dispute(d) for d in active_disputes],
    }


# ---------------------------------------------------------------------------
# Carryover listing and exemption (BR-BL-005)
# ---------------------------------------------------------------------------


def list_carryovers(
    tenant_id: str,
    filters: dict,
    limit: int,
    cursor: dict | None,
) -> tuple[list[dict], str | None, bool]:
    rows, next_cursor, has_more = repo.list_carryovers(tenant_id, filters, limit, cursor)
    return [_fmt_carryover(r) for r in rows], next_cursor, has_more


def exempt_carryover(
    tenant_id: str,
    carryover_id: str,
    notes: str | None,
    actor_id: str,
    ip_address: str | None = None,
) -> dict:
    """Exempt an outstanding carryover; roll debt forward as a new outstanding entry."""
    carryover = repo.get_carryover_by_id(tenant_id, carryover_id)
    if not carryover:
        raise ResourceNotFoundError("carryover_ledger", carryover_id)

    if carryover["status"] != "outstanding":
        raise BusinessRuleViolationError(
            f"Carryover is already '{carryover['status']}' — only 'outstanding' entries can be exempted",
            rule_id="CARRYOVER_NOT_OUTSTANDING",
        )

    exempted = repo.exempt_carryover(tenant_id, carryover_id, actor_id, notes)

    new_carryover = repo.create_carryover(
        tenant_id,
        {
            "tenant_id":            tenant_id,
            "customer_id":          str(carryover["customer_id"]),
            "source_billing_id":    str(carryover["source_billing_id"]),
            "carryover_amount_ngn": carryover["carryover_amount_ngn"],
            "notes":                "Debt rolled forward from exempted carryover",
            "created_by":           actor_id,
        },
    )

    log_audit(
        tenant_id=tenant_id,
        entity_type="carryover_ledger",
        entity_id=carryover_id,
        action="EXEMPT",
        actor_id=actor_id,
        actor_role=str(UserRole.TENANT_ADMIN),
        before_state={"status": "outstanding"},
        after_state={"status": "exempted", "new_carryover_id": str(new_carryover["id"])},
        ip_address=ip_address,
    )

    return {
        "id":               str(exempted["id"]),
        "status":           "exempted",
        "exempted_at":      exempted.get("exempted_at"),
        "new_carryover_id": str(new_carryover["id"]),
        "notes":            notes or "Debt rolled forward to next shipment",
    }


# ---------------------------------------------------------------------------
# Misc charge CRUD
# ---------------------------------------------------------------------------


def add_misc_charge(
    tenant_id: str,
    billing_id: str,
    data: dict,
    actor_id: str,
    ip_address: str | None = None,
) -> dict:
    billing = repo.get_billing_by_id(tenant_id, billing_id)
    if not billing:
        raise ResourceNotFoundError("billing", billing_id)

    amount_ngn = Decimal(str(data.get("amount_ngn", 0)))
    amount_usd = data.get("amount_usd")

    charge = repo.add_misc_charge(
        tenant_id,
        {
            "billing_id":   billing_id,
            "description":  data.get("description", ""),
            "amount_ngn":   amount_ngn,
            "amount_usd":   amount_usd,
            "charge_type":  data.get("charge_type", "other"),
            "created_by":   actor_id,
        },
    )
    repo.increment_billing_misc_fees(tenant_id, billing_id, amount_ngn)

    log_audit(
        tenant_id=tenant_id,
        entity_type="misc_charge",
        entity_id=str(charge["id"]),
        action="CREATE",
        actor_id=actor_id,
        actor_role=str(UserRole.NIGERIA_OFFICE_STAFF),
        after_state={"billing_id": billing_id, "amount_ngn": str(amount_ngn)},
        ip_address=ip_address,
    )
    return _fmt_misc_charge(charge)


def list_misc_charges(
    tenant_id: str,
    billing_id: str,
    ctx,
) -> list[dict]:
    billing = repo.get_billing_by_id(tenant_id, billing_id)
    if not billing:
        raise ResourceNotFoundError("billing", billing_id)

    if ctx.role == UserRole.CUSTOMER:
        customer = repo.get_customer_by_user_id(tenant_id, ctx.user_id)
        if not customer or str(customer["id"]) != str(billing["customer_id"]):
            raise InsufficientPermissionsError(
                "Customers may only view charges on their own billing records"
            )

    charges = repo.get_misc_charges(tenant_id, billing_id)
    return [_fmt_misc_charge(c) for c in charges]


def delete_misc_charge(
    tenant_id: str,
    billing_id: str,
    charge_id: str,
    actor_id: str,
    ip_address: str | None = None,
) -> None:
    billing = repo.get_billing_by_id(tenant_id, billing_id)
    if not billing:
        raise ResourceNotFoundError("billing", billing_id)

    if billing["status"] != "unpaid":
        raise BusinessRuleViolationError(
            "Misc charges can only be removed from unpaid billing records",
            rule_id="BILLING_NOT_UNPAID",
        )

    charge = repo.get_misc_charge_by_id(charge_id)
    if not charge or str(charge["billing_id"]) != billing_id:
        raise ResourceNotFoundError("misc_charge", charge_id)

    amount_ngn = Decimal(str(charge["amount_ngn"]))
    repo.delete_misc_charge(charge_id, billing_id)
    repo.decrement_billing_misc_fees(tenant_id, billing_id, amount_ngn)

    log_audit(
        tenant_id=tenant_id,
        entity_type="misc_charge",
        entity_id=charge_id,
        action="DELETE",
        actor_id=actor_id,
        actor_role=str(UserRole.TENANT_ADMIN),
        before_state={"billing_id": billing_id, "amount_ngn": str(amount_ngn)},
        ip_address=ip_address,
    )


# ---------------------------------------------------------------------------
# Storage fee log
# ---------------------------------------------------------------------------


def list_storage_fees(
    tenant_id: str,
    billing_id: str,
    ctx,
) -> list[dict]:
    billing = repo.get_billing_by_id(tenant_id, billing_id)
    if not billing:
        raise ResourceNotFoundError("billing", billing_id)

    if ctx.role == UserRole.CUSTOMER:
        customer = repo.get_customer_by_user_id(tenant_id, ctx.user_id)
        if not customer or str(customer["id"]) != str(billing["customer_id"]):
            raise InsufficientPermissionsError(
                "Customers may only view storage fees on their own billing records"
            )

    rows = repo.get_storage_fees_for_billing(tenant_id, billing_id)
    return [_fmt_storage_fee(r) for r in rows]


# ---------------------------------------------------------------------------
# Billing list / generate
# ---------------------------------------------------------------------------


def list_billing(
    tenant_id: str,
    filters: dict,
    limit: int,
    cursor: dict | None,
) -> tuple[list[dict], str | None, bool]:
    """List all billing records for a tenant (paginated)."""
    rows, next_cursor, has_more = repo.list_billing_all(tenant_id, filters, limit, cursor)
    return [_enrich_billing(tenant_id, dict(r)) for r in rows], next_cursor, has_more


def generate_billing(
    tenant_id: str,
    body: dict,
    actor_id: str,
    ctx,
) -> dict:
    """Manually generate a billing record for a container+customer pair."""
    container_id = body.get("container_id", "")
    customer_id = body.get("customer_id", "")
    container_number = body.get("container_number")
    handle_payment_due(
        tenant_id=tenant_id,
        container_id=container_id,
        customer_id=customer_id,
        container_number=container_number,
    )
    # Return minimal confirmation
    return {"container_id": container_id, "customer_id": customer_id, "status": "generated"}


# ---------------------------------------------------------------------------
# Top-level dispute listing / management
# ---------------------------------------------------------------------------


def list_disputes(
    tenant_id: str,
    filters: dict,
    limit: int,
    cursor: dict | None,
) -> tuple[list[dict], str | None, bool]:
    """Top-level paginated list of all disputes for a tenant."""
    rows, next_cursor, has_more = repo.list_all_disputes(tenant_id, filters, limit, cursor)
    return [_fmt_dispute(r) for r in rows], next_cursor, has_more


# Keep old name as alias for backwards compatibility
list_all_disputes = list_disputes


def create_dispute(
    tenant_id: str,
    body: dict,
    actor_id: str,
    ctx,
    request_id: str = "",
) -> dict:
    """Create a CBM dispute (billing_id taken from request body)."""
    billing_id = body.get("billing_id", "")
    from .models import FileCBMDisputeRequest
    req = FileCBMDisputeRequest(
        customer_measured_cbm=body.get("disputed_cbm", body.get("customer_measured_cbm", 0)),
        reason=body.get("dispute_reason", body.get("reason", "")),
    )
    return file_cbm_dispute(tenant_id, billing_id, req, actor_id=actor_id, ctx=ctx, request_id=request_id)


def reject_dispute(
    tenant_id: str,
    dispute_id: str,
    reason: str,
    actor_id: str,
    ctx,
) -> dict:
    """Reject a CBM dispute."""
    dispute = repo.get_cbm_dispute_by_id(tenant_id, dispute_id)
    if not dispute:
        raise ResourceNotFoundError("cbm_dispute", dispute_id)
    updated = repo.set_dispute_status(tenant_id, dispute_id, "rejected", {"resolution_notes": reason, "resolved_by": actor_id})
    return _fmt_dispute(updated)


def escalate_dispute(
    tenant_id: str,
    dispute_id: str,
    ctx,
) -> dict:
    """Escalate a CBM dispute."""
    dispute = repo.get_dispute_by_id(tenant_id, dispute_id)
    if not dispute:
        raise ResourceNotFoundError("cbm_dispute", dispute_id)
    updated = repo.update_dispute_status(tenant_id, dispute_id, "escalated", {})
    log_audit(
        tenant_id=tenant_id,
        entity_type="cbm_dispute",
        entity_id=dispute_id,
        action="STATUS_CHANGE",
        actor_id=ctx.user_id,
        actor_role=str(ctx.role),
        before_state={"status": dispute["status"]},
        after_state={"status": "escalated"},
    )
    return _fmt_dispute(updated)


# ---------------------------------------------------------------------------
# CBM Dispute operations
# ---------------------------------------------------------------------------


def file_cbm_dispute(
    tenant_id: str,
    billing_id: str,
    req,
    actor_id: str,
    ctx,
    request_id: str = "",
) -> dict:
    """File a CBM dispute against an existing billing record.

    Only CUSTOMER role can file disputes (enforced in handler).
    Guard: no active (non-closed) dispute already open.
    """
    billing = repo.get_billing_by_id(tenant_id, billing_id)
    if not billing:
        raise ResourceNotFoundError("billing", billing_id)

    # CUSTOMER: verify they own this billing
    if ctx.role == UserRole.CUSTOMER:
        customer = repo.get_customer_by_user_id(tenant_id, ctx.user_id)
        if not customer or str(customer["id"]) != str(billing["customer_id"]):
            raise InsufficientPermissionsError(
                "Customers may only dispute their own billing records"
            )

    active = repo.get_active_disputes(tenant_id, billing_id)
    if active:
        raise BusinessRuleViolationError(
            "A CBM dispute is already open for this billing record",
            rule_id="DISPUTE_ALREADY_OPEN",
        )

    dispute = repo.create_cbm_dispute(
        tenant_id,
        {
            "tenant_id":             tenant_id,
            "billing_id":            billing_id,
            "customer_id":           str(billing["customer_id"]),
            "disputed_cbm":          billing["total_cbm"],
            "customer_measured_cbm": req.customer_measured_cbm,
            "dispute_reason":        req.reason,
            "raised_by":             actor_id,
        },
    )
    return _fmt_dispute(dispute)


def list_billing_disputes(tenant_id: str, billing_id: str, ctx) -> list[dict]:
    """List all disputes for a billing record."""
    if ctx.role == UserRole.CUSTOMER:
        billing = repo.get_billing_by_id(tenant_id, billing_id)
        if not billing:
            raise ResourceNotFoundError("billing", billing_id)
        customer = repo.get_customer_by_user_id(tenant_id, ctx.user_id)
        if not customer or str(customer["id"]) != str(billing["customer_id"]):
            raise InsufficientPermissionsError(
                "Customers may only view disputes on their own billing records"
            )
    rows = repo.list_disputes_for_billing(tenant_id, billing_id)
    return [_fmt_dispute(r) for r in rows]


def acknowledge_dispute(
    tenant_id: str,
    dispute_id: str,
    actor_id: str,
    ip_address: str | None = None,
) -> dict:
    dispute = repo.get_cbm_dispute_by_id(tenant_id, dispute_id)
    if not dispute:
        raise ResourceNotFoundError("cbm_dispute", dispute_id)

    if dispute["status"] != "submitted":
        raise IllegalTransitionError(
            entity="cbm_dispute",
            current_state=dispute["status"],
            requested_state="acknowledged",
            allowed=["submitted"],
        )

    updated = repo.set_dispute_acknowledged(tenant_id, dispute_id, actor_id)
    log_audit(
        tenant_id=tenant_id,
        entity_type="cbm_dispute",
        entity_id=dispute_id,
        action="STATUS_CHANGE",
        actor_id=actor_id,
        actor_role=str(UserRole.NIGERIA_OFFICE_STAFF),
        before_state={"status": "submitted"},
        after_state={"status": "acknowledged"},
        ip_address=ip_address,
    )
    return _fmt_dispute(updated)


def resolve_dispute(
    tenant_id: str,
    dispute_id: str,
    req,
    actor_id: str,
    ctx,
    request_id: str = "",
    ip_address: str | None = None,
) -> dict:
    """Transition a dispute to investigating/escalated_china/resolved_adjusted/resolved_no_change."""
    dispute = repo.get_cbm_dispute_by_id(tenant_id, dispute_id)
    if not dispute:
        raise ResourceNotFoundError("cbm_dispute", dispute_id)

    current = dispute["status"]
    if current not in _DISPUTE_ALLOWED_SOURCE_STATES:
        raise IllegalTransitionError(
            entity="cbm_dispute",
            current_state=current,
            requested_state=req.status,
            allowed=list(_DISPUTE_ALLOWED_SOURCE_STATES),
        )

    target = req.status.value if hasattr(req.status, "value") else str(req.status)
    if target not in _DISPUTE_ALLOWED_TARGET_STATES:
        raise BusinessRuleViolationError(
            f"Cannot transition dispute to '{target}' via the resolve endpoint",
            rule_id="INVALID_DISPUTE_TARGET_STATE",
        )

    extra: dict = {}
    is_terminal = target in {"resolved_adjusted", "resolved_no_change"}

    if target == "resolved_adjusted":
        if not req.corrected_cbm:
            raise BusinessRuleViolationError(
                "corrected_cbm is required for resolved_adjusted",
                rule_id="MISSING_CORRECTED_CBM",
            )

        billing = repo.get_billing_by_id(tenant_id, str(dispute["billing_id"]))
        if not billing:
            raise ResourceNotFoundError("billing", str(dispute["billing_id"]))

        cbm_rate_usd = Decimal(str(billing["cbm_rate_usd"]))
        exchange_rate = Decimal(str(billing["exchange_rate_ngn"]))

        new_cbm = Decimal(str(req.corrected_cbm))
        new_subtotal_usd = (new_cbm * cbm_rate_usd).quantize(Decimal("0.01"), ROUND_HALF_UP)
        new_subtotal_ngn = (new_subtotal_usd * exchange_rate).quantize(Decimal("0.01"), ROUND_HALF_UP)
        delta_ngn = new_subtotal_ngn - Decimal(str(billing["subtotal_ngn"]))
        new_total_ngn = (Decimal(str(billing["total_ngn"])) + delta_ngn).quantize(
            Decimal("0.01"), ROUND_HALF_UP
        )

        repo.update_billing_cbm(
            tenant_id,
            str(billing["id"]),
            new_cbm,
            new_subtotal_usd,
            new_subtotal_ngn,
            new_total_ngn,
        )

        # Create overpayment refund if customer already paid more than new total
        amount_paid = Decimal(str(billing.get("amount_paid_ngn", 0)))
        if amount_paid > new_total_ngn:
            overpayment = amount_paid - new_total_ngn
            try:
                repo.create_overpayment_refund_request(
                    tenant_id,
                    {
                        "tenant_id":   tenant_id,
                        "customer_id": str(billing["customer_id"]),
                        "billing_id":  str(billing["id"]),
                        "amount_ngn":  overpayment,
                        "reason":      f"CBM dispute overpayment — dispute {dispute_id}",
                    },
                )
            except Exception:
                logger.exception("Failed to create overpayment refund for dispute %s", dispute_id)

        publish_event(
            source="logistics.billing",
            detail_type="CBMDisputeResolved",
            tenant_id=tenant_id,
            payload={
                "dispute_id":    dispute_id,
                "billing_id":    str(dispute["billing_id"]),
                "original_cbm":  str(dispute["disputed_cbm"]),
                "corrected_cbm": str(new_cbm),
            },
            request_id=request_id,
        )

        extra["agreed_cbm"] = new_cbm

    if is_terminal:
        extra["resolution_notes"] = req.resolution_notes
        extra["resolved_by"] = actor_id
        extra["resolved_at"] = datetime.now(UTC)

    updated = repo.set_dispute_status(tenant_id, dispute_id, target, extra)

    log_audit(
        tenant_id=tenant_id,
        entity_type="cbm_dispute",
        entity_id=dispute_id,
        action="STATUS_CHANGE",
        actor_id=actor_id,
        actor_role=str(ctx.role),
        before_state={"status": current},
        after_state={"status": target},
        ip_address=ip_address,
    )
    return _fmt_dispute(updated)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _fmt_dispute(row: dict) -> dict:
    return {
        "id":            str(row["id"]),
        "billing_id":    str(row["billing_id"]),
        "original_cbm":  row.get("disputed_cbm"),
        "corrected_cbm": row.get("agreed_cbm"),
        "status":        row["status"],
        "submitted_at":  row.get("created_at"),
    }


def _fmt_carryover(row: dict) -> dict:
    return {
        "id":                      str(row["id"]),
        "customer_id":             str(row["customer_id"]),
        "customer_name":           row.get("customer_name"),
        "source_billing_id":       str(row["source_billing_id"]),
        "source_container_number": row.get("source_container_number"),
        "target_billing_id":       str(row["target_billing_id"]) if row.get("target_billing_id") else None,
        "amount_ngn":              row["carryover_amount_ngn"],
        "status":                  row["status"],
        "created_at":              row["created_at"],
    }


def _fmt_misc_charge(row: dict) -> dict:
    return {
        "id":          str(row["id"]),
        "billing_id":  str(row["billing_id"]),
        "charge_type": row["charge_type"],
        "description": row.get("description", ""),
        "amount_usd":  row.get("amount_usd"),
        "amount_ngn":  row["amount_ngn"],
        "created_at":  row["created_at"],
    }


def _fmt_storage_fee(row: dict) -> dict:
    return {
        "id":              str(row["id"]),
        "day_number":      row.get("days_in_storage"),
        "carton_count":    row.get("cartons_in_storage"),
        "daily_rate_ngn":  row.get("daily_rate_ngn"),
        "fee_amount_ngn":  row.get("amount_ngn"),
        "accrual_date":    row.get("accrual_date"),
    }
