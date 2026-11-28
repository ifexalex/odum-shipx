"""Business logic for the Billing service.

Handles auto-billing on container clearance, CBM dispute lifecycle,
carryover/credit application, and billing recalculation on dispute resolution.
"""

import json
import logging
import os
from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

from shared.audit import log_audit
from shared.cbm_rate import compute_cbm_charge, get_cbm_rate_config
from shared.db import tenant_transaction
from shared.events import publish_event
from shared.exceptions import (
    BusinessRuleViolationError,
    IllegalTransitionError,
    InsufficientPermissionsError,
    ResourceNotFoundError,
    ValidationError,
)
from shared.fx_rate import RATE_SOURCE_HARDCODED, RATE_SOURCE_LAST_KNOWN, get_effective_dollar_rate, rate_age_minutes
from shared.notifications import enqueue_notifications
from shared.observability import record_failure
from shared.staff_notifications import notify_staff
from shared.tenant_context import UserRole
from shared.validation import parse_validated

from . import repository as repo
from .models import AddMiscChargeRequest, FileCBMDisputeRequest

logger = logging.getLogger(__name__)

# Sub-kobo balance noise is treated as settled when recomputing payment status
# (mirrors payment_release.service._TOLERANCE for the record-payment path).
_CARRYOVER_TOLERANCE = Decimal("0.01")

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

# SLA windows (must match scheduled-job defaults in sla_check.py + dispute_escalation.py)
_DISPUTE_ACKNOWLEDGE_HOURS = 24
_DISPUTE_INVESTIGATE_DAYS = 5
_DISPUTE_RESOLVE_DAYS = 7


# ---------------------------------------------------------------------------
# Auto-billing: triggered by PaymentDue EventBridge event
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class InvoiceOutcome:
    """What happened when we tried to bill one customer for one container.

    ``created``  - a new invoice was issued.
    ``existing`` - a live invoice was already there; nothing was changed.
    ``skipped``  - no invoice could be issued; ``reason`` is a rule id such as
                   ``RATE_CONFIG_MISSING``, ``RATE_UNAVAILABLE`` or ``NO_CBM``, ``detail`` says why.
    """

    status: str
    billing_id: str | None = None
    invoice_number: str | None = None
    reason: str | None = None
    detail: str | None = None


def handle_payment_due(
    tenant_id: str,
    container_id: str,
    customer_id: str,
    container_number: str | None,
    request_id: str = "",
) -> InvoiceOutcome:
    """Create a billing record for a customer when their container is cleared.

    Idempotent per (customer, container): a second call returns the existing
    invoice and does not notify, publish or audit again. Callers that run in a
    loop (container clearance) should catch exceptions per customer and report
    them; this function raises on a real failure rather than hiding it.
    """
    # 0. Already invoiced? Answer before pricing anything: a repeat run (the
    # "generate missing invoices" retry) should not cost a market-rate lookup per
    # customer who is already done. `create_invoice` below still guards the race.
    already = repo.get_live_invoice(tenant_id, customer_id, container_id)
    if already is not None:
        return InvoiceOutcome(status="existing", billing_id=str(already["id"]), invoice_number=already.get("invoice_number"))

    # 1. Fetch pricing config. Dollar rate is Bybit's live P2P base rate plus
    # this tenant's markup (shared/fx_rate.py). CBM rate is the tenant's
    # currency + carton/bag/bale rate config (shared/cbm_rate.py) — "flat"
    # is just the case where all three rates happen to be equal, so the
    # math below never branches on rate_mode itself.
    cbm_config = get_cbm_rate_config(tenant_id)
    effective_rate = get_effective_dollar_rate(tenant_id)
    dollar_rate = effective_rate["rate"]
    rate_source = effective_rate.get("rate_source")

    # No market rate has ever been fetched: the only number available is a constant in the code. Billing a customer
    # real money at a made-up rate is worse than billing them a little later (audit BE-11). Staff are told in-app
    # (`_notify_unbilled`) and can generate the invoice once a rate has been fetched.
    if rate_source == RATE_SOURCE_HARDCODED:
        logger.error("Not invoicing customer %s on container %s: no market dollar rate is available", customer_id, container_id)
        return InvoiceOutcome(
            status="skipped",
            reason="RATE_UNAVAILABLE",
            detail="No market dollar rate could be fetched. Generate the invoice again once the rate is available.",
        )

    if (cbm_config["carton_rate"] <= 0 and cbm_config["bag_rate"] <= 0 and cbm_config["bale_rate"] <= 0) or dollar_rate <= 0:
        logger.warning(
            "Skipping billing for customer %s — missing tenant config (cbm_rates=%s/%s/%s, dollar_rate=%s)",
            customer_id,
            cbm_config["carton_rate"],
            cbm_config["bag_rate"],
            cbm_config["bale_rate"],
            dollar_rate,
        )
        return InvoiceOutcome(
            status="skipped",
            reason="RATE_CONFIG_MISSING",
            detail="Set the CBM rate and dollar rate in Settings before billing this container.",
        )

    # 2. Sum CBM + carton count from approved packing lists
    totals = repo.get_cbm_and_carton_totals(tenant_id, customer_id, container_id)
    total_cbm = Decimal(str(totals["total_cbm"]))
    total_cartons = int(totals["total_cartons"])

    if total_cbm <= 0:
        logger.info(
            "Skipping billing for customer %s — no CBM for container %s",
            customer_id,
            container_id,
        )
        return InvoiceOutcome(
            status="skipped",
            reason="NO_CBM",
            detail="The customer's packing lists on this container have no CBM to bill.",
        )

    # 3. Calculate subtotals — group CBM by package type (carton/bag/bale,
    # anything unrecognized folds into carton) and price each bucket at its
    # own rate, in whichever currency the tenant configured.
    cbm_by_unit = repo.get_cbm_by_package_type(tenant_id, customer_id, container_id)
    charge = compute_cbm_charge(cbm_by_unit, cbm_config)

    if charge["currency"] == "ngn":
        subtotal_ngn = charge["amount"]
        subtotal_usd = (subtotal_ngn / dollar_rate).quantize(Decimal("0.01"), ROUND_HALF_UP)
    else:
        subtotal_usd = charge["amount"]
        subtotal_ngn = (subtotal_usd * dollar_rate).quantize(Decimal("0.01"), ROUND_HALF_UP)

    # cbm_rate_usd: the snapshotted per-invoice rate other code (CBM dispute
    # resolution, exports, staff/customer UI) treats as ground truth via
    # `total_cbm * cbm_rate_usd == subtotal_usd`. Computed exactly (no
    # rounding drift) whenever there's genuinely one effective rate — the
    # common case, flat or coincidentally-equal per-type rates — and only
    # falls back to the blended average for a genuine multi-rate mix, where
    # no single "the rate" exists to report exactly.
    if cbm_config["carton_rate"] == cbm_config["bag_rate"] == cbm_config["bale_rate"]:
        single_rate = cbm_config["carton_rate"]
        cbm_rate_usd = (
            single_rate
            if cbm_config["currency"] == "usd"
            else (single_rate / dollar_rate).quantize(Decimal("0.0001"), ROUND_HALF_UP)
        )
    else:
        cbm_rate_usd = (subtotal_usd / total_cbm).quantize(Decimal("0.0001"), ROUND_HALF_UP) if total_cbm > 0 else Decimal("0")

    # 4. Carryovers (add to total)
    carryovers = repo.get_outstanding_carryovers(tenant_id, customer_id)
    carryover_ngn = sum(Decimal(str(c["carryover_amount_ngn"])) for c in carryovers)

    # 5. Credits the customer holds reduce what is due, but only down to zero: an invoice never goes negative.
    # What a credit has left stays with the customer for their next invoice.
    due_ngn = (subtotal_ngn + carryover_ngn).quantize(Decimal("0.01"), ROUND_HALF_UP)
    credit_applications = _credits_to_apply(repo.get_pending_credit_refunds(tenant_id, customer_id), due_ngn)
    credits_ngn = sum((c.amount_ngn for c in credit_applications), Decimal("0"))

    # 6. Final total (misc_charges_ngn starts at 0; storage/misc added later). Nothing left to pay is `paid`.
    total_ngn = due_ngn - credits_ngn
    status = "paid" if total_ngn <= Decimal("0") else "unpaid"

    # 7-10. One transaction: allocate the invoice number, insert the invoice, and
    # mark the carryovers and credits it absorbed. A live invoice for this
    # customer and container short-circuits the lot.
    now = datetime.now(UTC)
    tenant_short = repo.get_tenant_short(tenant_id)
    billing, created = repo.create_invoice(
        tenant_id,
        {
            "tenant_id": tenant_id,
            "customer_id": customer_id,
            "container_id": container_id,
            "total_cartons": total_cartons,
            "total_cbm": total_cbm,
            "cbm_rate_usd": cbm_rate_usd,
            "cbm_rate_currency": charge["currency"].upper(),
            "cbm_rate_mode": cbm_config["rate_mode"],
            "cbm_breakdown": json.dumps(charge["breakdown"], default=str),
            "subtotal_usd": subtotal_usd,
            "exchange_rate_ngn": dollar_rate,
            "exchange_rate_source": rate_source,
            "exchange_rate_fetched_at": effective_rate.get("fetched_at"),
            "subtotal_ngn": subtotal_ngn,
            "misc_charges_ngn": Decimal("0"),
            "total_ngn": total_ngn,
            "amount_paid_ngn": Decimal("0"),
            "status": status,
            "billed_at": now,
            "created_by": None,
        },
        number_prefix=f"{tenant_short}-INV-{date.today():%Y%m%d}",
        carryover_ids=[str(c["id"]) for c in carryovers],
        credit_applications=credit_applications,
    )
    billing_id = str(billing["id"])
    invoice_number = billing.get("invoice_number")
    if not created:
        logger.info("Invoice already exists for customer %s / container %s — nothing to do", customer_id, container_id)
        return InvoiceOutcome(status="existing", billing_id=billing_id, invoice_number=invoice_number)

    # 11. Publish PaymentDue event
    publish_event(
        source="logistics.billing",
        detail_type="PaymentDue",
        tenant_id=tenant_id,
        payload={
            "billing_id": billing_id,
            "customer_id": customer_id,
            "container_id": container_id,
            "container_number": container_number,
            "invoice_number": invoice_number,
            "total_ngn": str(total_ngn),
        },
        request_id=request_id,
    )

    # System-triggered (fired from the tracking service's cleared-container
    # event, not a human action) — still a real invoice charging a real
    # customer real money, so it belongs in the tenant's audit trail same as
    # any staff-initiated billing action. Ground-truth gap found while
    # auditing log coverage: this was the one billing-money write with no
    # audit_log entry at all. actor_id=None, not a placeholder string —
    # audit_log.actor_id is a UUID FK column, and a non-UUID string here
    # would silently fail the insert (found live; see the matching fix in
    # payment_release/service.py::process_webhook_payment).
    log_audit(
        tenant_id=tenant_id,
        entity_type="billing",
        entity_id=billing_id,
        action="CREATE",
        actor_id=None,
        actor_role="system",
        after_state={
            "customer_id": customer_id,
            "container_id": container_id,
            "invoice_number": invoice_number,
            "total_ngn": str(total_ngn),
            "status": status,
            "carryover_applied_ngn": str(carryover_ngn),
            "credits_applied_ngn": str(credits_ngn),
            "credits_applied": [{"refund_id": c.refund_id, "amount_ngn": str(c.amount_ngn)} for c in credit_applications],
        },
    )
    logger.info(
        "Billing %s created for customer %s / container %s",
        billing_id,
        customer_id,
        container_id,
    )
    _notify_customer_payment_due(tenant_id, customer_id, container_number, total_ngn, request_id)
    _warn_if_rate_was_old(tenant_id, billing_id, invoice_number, rate_source, effective_rate.get("fetched_at"))
    return InvoiceOutcome(status="created", billing_id=billing_id, invoice_number=invoice_number)


def _rate_max_age_minutes() -> int:
    """How old the exchange rate behind a new invoice may be before tenant admins are told (``FX_RATE_MAX_AGE_MINUTES``).

    The live rate is refreshed every ten minutes, so a rate older than this means the market feed has been down for a
    while. Default two hours.
    """
    try:
        return max(1, int(os.environ.get("FX_RATE_MAX_AGE_MINUTES", "120")))
    except ValueError:
        logger.warning("FX_RATE_MAX_AGE_MINUTES is not a whole number; using 120")
        return 120


def _warn_if_rate_was_old(
    tenant_id: str, billing_id: str, invoice_number: str | None, rate_source: str | None, fetched_at: str | None
) -> None:
    """Tell tenant admins an invoice was priced at a rate fetched long ago (audit BE-11). Never raises."""
    if rate_source != RATE_SOURCE_LAST_KNOWN:
        return
    age = rate_age_minutes(fetched_at)
    if age is not None and age <= _rate_max_age_minutes():
        return
    when = f"{age / 60:.0f} hours ago" if age is not None else "at an unknown time"
    try:
        notify_staff(
            tenant_id=tenant_id,
            event_type="invoice_old_exchange_rate",
            entity_type="billing",
            entity_id=billing_id,
            title="Invoice priced at an old exchange rate",
            body=(
                f"Invoice {invoice_number or billing_id} used the last known dollar rate, fetched {when}, because the "
                "live rate could not be fetched. Check it before the customer pays."
            ),
            target_role=str(UserRole.TENANT_ADMIN),
        )
    except Exception:
        logger.exception("Failed to tell tenant admins invoice %s used an old exchange rate", billing_id)


def _credits_to_apply(credits: list[dict[str, Any]], due_ngn: Decimal) -> list[repo.CreditApplication]:
    """Works out how much of each credit an invoice uses: oldest first, and never more than is due.

    Args:
        credits: The customer's unspent credits, oldest first (`repo.get_pending_credit_refunds`).
        due_ngn: What the invoice comes to before credits.

    Returns:
        One entry per credit that is used, in the order given. Credits that are not needed are left out and stay
        whole; the last one used may be used only in part.
    """
    applications: list[repo.CreditApplication] = []
    still_due = max(due_ngn, Decimal("0"))
    for credit in credits:
        if still_due <= 0:
            break
        # The credit is worth what was approved, which can be less than what was asked for.
        value = Decimal(
            str(credit["amount_approved_ngn"] if credit.get("amount_approved_ngn") is not None else credit["amount_ngn"])
        )
        applied_before = Decimal(str(credit.get("credit_applied_ngn") or 0))
        amount = min(value - applied_before, still_due)
        if amount <= 0:
            continue
        applications.append(repo.CreditApplication(str(credit["id"]), applied_before, amount))
        still_due -= amount
    return applications


def _notify_customer_payment_due(
    tenant_id: str,
    customer_id: str,
    container_number: str | None,
    total_ngn: Decimal,
    request_id: str,
) -> None:
    """Best-effort "your invoice is ready" notification — a real invoice
    charging a real customer real money with no notification at all is the
    same silent gap that let a payment-claim rejection go unnoticed (see
    payment_release/service.py). Never raises: a notification outage must
    not fail billing generation itself.

    An invoice the customer's credit covered in full (total 0) asks for no payment, so no "payment due" SMS,
    WhatsApp or email goes out: it read "NGN 0.00 due". The in-app bell still says the credit covered it. A
    dedicated message would need its own WhatsApp template approved by Meta (2026-11-19).
    """
    try:
        customer = repo.get_customer_contact(tenant_id, customer_id)
        if not customer:
            return
        if total_ngn > 0:
            _enqueue_payment_due(tenant_id, customer_id, customer, container_number, total_ngn, request_id)

        # In-app customer bell — see payment_release/service.py's matching
        # comment: SMS/WhatsApp/email above can each fail for reasons
        # entirely outside this app, and only a customer with a portal
        # account (customer.user_id set) can receive this.
        if customer.get("user_id"):
            notify_staff(
                tenant_id=tenant_id,
                event_type="payment_due",
                entity_type="billing",
                title="New invoice ready",
                body=(
                    f"Container {container_number or ''}: NGN {total_ngn} due."
                    if total_ngn > 0
                    else f"Container {container_number or ''}: nothing to pay. Your credit covered this invoice."
                ),
                target_user_id=str(customer["user_id"]),
            )
    except Exception:
        logger.exception(
            "Failed to enqueue payment_due notification for customer %s",
            customer_id,
        )


def _enqueue_payment_due(
    tenant_id: str,
    customer_id: str,
    customer: dict[str, Any],
    container_number: str | None,
    total_ngn: Decimal,
    request_id: str,
) -> None:
    """The "payment due" SMS / WhatsApp / email, through the customer's consent and channel rules."""
    warehouse_cfg = repo.get_tenant_config_value(tenant_id, "warehouse_address") or {}
    address_parts = [warehouse_cfg.get("address"), warehouse_cfg.get("city"), warehouse_cfg.get("state")]
    warehouse_address = ", ".join(p for p in address_parts if p) or "our warehouse"
    enqueue_notifications(
        tenant_id=tenant_id,
        event_type="payment_due",
        recipient={
            "phone": customer.get("phone") or "",
            "email": customer.get("email") or "",
            "whatsapp": customer.get("whatsapp") or "",
            "name": customer.get("name") or "",
        },
        template_data={
            "container_number": container_number or "",
            "currency": "NGN",
            "amount": str(total_ngn),
            "warehouse_address": warehouse_address,
        },
        locale=customer.get("locale", "en"),
        request_id=request_id,
        customer_id=customer_id,
    )


# ---------------------------------------------------------------------------
# GET billing for customer
# ---------------------------------------------------------------------------


def get_billing_stats(tenant_id: str) -> dict[str, Any]:
    """Tenant-wide billing aggregates for the list stats row + status chips.

    SQL-computed over the whole table so the figures are correct at any scale
    (the frontend previously summed a capped `limit: 500` sample).
    """
    return repo.get_billing_stats(tenant_id)


def get_tenant_report(
    tenant_id: str,
    created_after: str | None = None,
    created_before: str | None = None,
) -> dict[str, Any]:
    """Period report aggregates for the TenantReports page — SQL-computed so the
    financial figures are correct at scale (previously summed a capped sample)."""
    return repo.get_tenant_report(tenant_id, created_after, created_before)


def get_billing(tenant_id: str, billing_id: str, ctx: Any) -> dict[str, Any]:
    """Return one enriched billing record addressed by its own id.

    Backs GET /v1/billing/{billing-id}/detail. The sibling
    GET /v1/billing/{resource-id} route takes a *customer* id, so a billing id
    had no direct read path at all and the UI had to scan the paginated list to
    find a record by id — which only ever searched the first page.

    CUSTOMER role is scoped to their own records, the same force-scoping used by
    list_billing() and get_billing_for_customer(), so a customer cannot read
    another customer's invoice by addressing its billing id directly.

    Args:
        tenant_id: Owning tenant.
        billing_id: The billing record's own id.
        ctx: Tenant context, used for the customer-ownership check.

    Returns:
        The enriched billing record, same shape as a GET /v1/billing row.

    Raises:
        ResourceNotFoundError: No such billing record in this tenant.
        InsufficientPermissionsError: Customer addressing someone else's record.
    """
    row = repo.get_billing_by_id(tenant_id, billing_id)
    if not row:
        raise ResourceNotFoundError("billing", billing_id)

    if ctx is not None and ctx.must_scope_to_customer(UserRole.TENANT_ADMIN, UserRole.NIGERIA_OFFICE_STAFF):
        customer = repo.get_customer_by_user_id(tenant_id, ctx.user_id)
        if not customer or str(customer["id"]) != str(row.get("customer_id")):
            raise InsufficientPermissionsError("Customers may only view their own billing records")
        return _enrich_billing(tenant_id, dict(row))

    # Staff only (audit BE-11): where the exchange rate came from, so an invoice priced at the last known rate during
    # a market-feed outage is visible on the invoice. NULL for invoices issued before migration 068.
    fetched_at = row.get("exchange_rate_fetched_at")
    return {
        **_enrich_billing(tenant_id, dict(row)),
        "exchange_rate_source": row.get("exchange_rate_source"),
        "exchange_rate_fetched_at": fetched_at.isoformat() if isinstance(fetched_at, datetime) else fetched_at,
    }


def get_billing_for_customer(
    tenant_id: str,
    customer_id: str,
    ctx: Any,
    container_id: str | None = None,
) -> list[dict[str, Any]]:
    """Return enriched billing records for a customer.

    CUSTOMER role: verified against ctx.user_id — can only see their own billing.
    """
    if ctx.must_scope_to_customer(UserRole.TENANT_ADMIN, UserRole.NIGERIA_OFFICE_STAFF):
        customer = repo.get_customer_by_user_id(tenant_id, ctx.user_id)
        if not customer or str(customer["id"]) != customer_id:
            raise InsufficientPermissionsError("Customers may only view their own billing records")

    rows = repo.list_billing_for_customer(tenant_id, customer_id, container_id)
    return [_enrich_billing(tenant_id, row) for row in rows]


def _enrich_billing(tenant_id: str, row: dict[str, Any]) -> dict[str, Any]:
    """Attach nested data and compute derived response fields."""
    billing_id = str(row["id"])

    misc_charges = repo.get_misc_charges(tenant_id, billing_id)
    payments = repo.get_payment_records(tenant_id, billing_id)
    applied_cos = repo.get_applied_carryovers(tenant_id, billing_id)
    active_disputes = repo.get_active_disputes(tenant_id, billing_id)

    misc_fees_ngn = sum(Decimal(str(m["amount_ngn"])) for m in misc_charges if m.get("charge_type") != "storage_fee")
    # The fee log is the record of what storage has been charged: the daily job writes
    # it (and adds the fee to the total) but never creates misc_charge rows, so summing
    # those always gave 0 and hid the storage banner and the waive action.
    storage_fees_ngn = repo.get_storage_fee_total(tenant_id, billing_id)
    carryover_ngn = sum(Decimal(str(c["carryover_amount_ngn"])) for c in applied_cos)

    return {
        "id": str(row["id"]),
        "invoice_number": row.get("invoice_number"),
        "customer_id": str(row["customer_id"]) if row.get("customer_id") else None,
        "customer_name": row.get("customer_name"),
        "customer_phone": row.get("customer_phone"),
        "customer_email": row.get("customer_email"),
        "container_id": str(row["container_id"]),
        "container_number": row.get("container_number"),
        "total_cbm": row["total_cbm"],
        "cbm_rate_usd": row["cbm_rate_usd"],
        "cbm_rate_currency": row.get("cbm_rate_currency", "USD"),
        "cbm_rate_mode": row.get("cbm_rate_mode", "flat"),
        "cbm_breakdown": row.get("cbm_breakdown"),
        "dollar_rate": row["exchange_rate_ngn"],
        "subtotal_usd": row["subtotal_usd"],
        "subtotal_ngn": row["subtotal_ngn"],
        "misc_fees": [{"description": m["description"], "amount_ngn": m["amount_ngn"]} for m in misc_charges],
        "misc_fees_ngn": misc_fees_ngn,
        # Credit the customer held, taken off this invoice when it was issued (negative: it reduces the total).
        "adjustments_ngn": -Decimal(str(row.get("credits_applied_ngn") or 0)),
        "carryover_ngn": carryover_ngn,
        "storage_fees_ngn": storage_fees_ngn,
        "total_due_ngn": row["total_ngn"],
        "total_paid_ngn": row["amount_paid_ngn"],
        "outstanding_ngn": row["balance_ngn"],
        "payment_status": row["status"],
        "released_with_outstanding": row.get("released_with_outstanding", False),
        "billed_at": row.get("billed_at"),
        "payments": [
            {
                "id": str(p["id"]),
                "amount_ngn": p["amount_ngn"],
                "payment_method": p.get("payment_method"),
                "payment_reference": p.get("reference_number"),
                "confirmed_at": p["created_at"],
            }
            for p in payments
        ],
        "carryovers": [
            {
                "id": str(c["id"]),
                "amount_ngn": c["carryover_amount_ngn"],
                "source_billing_id": str(c["source_billing_id"]),
                "created_at": c["created_at"],
            }
            for c in applied_cos
        ],
        "_active_disputes": [_fmt_dispute(d) for d in active_disputes],
    }


# ---------------------------------------------------------------------------
# Carryover listing and exemption (BR-BL-005)
# ---------------------------------------------------------------------------


def list_carryovers(
    tenant_id: str,
    filters: dict[str, Any],
    limit: int,
    cursor: dict[str, Any] | None,
) -> tuple[list[dict[str, Any]], str | None, bool]:
    rows, next_cursor, has_more = repo.list_carryovers(tenant_id, filters, limit, cursor)
    return [_fmt_carryover(r) for r in rows], next_cursor, has_more


def exempt_carryover(
    tenant_id: str,
    carryover_id: str,
    notes: str | None,
    actor_id: str,
    ip_address: str | None = None,
) -> dict[str, Any]:
    """Exempt an outstanding carryover; roll debt forward as a new outstanding entry atomically."""
    carryover = repo.get_carryover_by_id(tenant_id, carryover_id)
    if not carryover:
        raise ResourceNotFoundError("carryover_ledger", carryover_id)

    if carryover["status"] != "outstanding":
        raise BusinessRuleViolationError(
            f"Carryover is already '{carryover['status']}' — only 'outstanding' entries can be exempted",
            rule_id="CARRYOVER_NOT_OUTSTANDING",
        )

    with tenant_transaction(tenant_id):
        exempted = repo.exempt_carryover(tenant_id, carryover_id, actor_id, notes)
        if exempted is None:
            raise BusinessRuleViolationError(
                "Carryover is no longer 'outstanding' — it was changed by another request",
                rule_id="CARRYOVER_NOT_OUTSTANDING",
            )

        new_carryover = repo.create_carryover(
            tenant_id,
            {
                "tenant_id": tenant_id,
                "customer_id": str(carryover["customer_id"]),
                "source_billing_id": str(carryover["source_billing_id"]),
                "carryover_amount_ngn": carryover["carryover_amount_ngn"],
                "notes": "Debt rolled forward from exempted carryover",
                "created_by": actor_id,
                "due_date": carryover.get("due_date"),
                "granted_by": carryover.get("granted_by"),
                "release_note_id": carryover.get("release_note_id"),
            },
        )
        if new_carryover is None:
            raise RuntimeError("create_carryover returned None unexpectedly")

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
        "id": str(exempted["id"]),
        "status": "exempted",
        "exempted_at": exempted.get("exempted_at"),
        "new_carryover_id": str(new_carryover["id"]),
        "notes": notes or "Debt rolled forward to next shipment",
    }


# ---------------------------------------------------------------------------
# Misc charge CRUD
# ---------------------------------------------------------------------------


def add_misc_charge(
    tenant_id: str,
    billing_id: str,
    data: dict[str, Any],
    actor_id: str,
    ip_address: str | None = None,
    actor_role: str = str(UserRole.NIGERIA_OFFICE_STAFF),
) -> dict[str, Any]:
    validated = parse_validated(AddMiscChargeRequest, data)
    billing = repo.get_billing_by_id(tenant_id, billing_id)
    if not billing:
        raise ResourceNotFoundError("billing", billing_id)

    if billing.get("status") in {"cancelled", "waived"}:
        raise BusinessRuleViolationError(
            f"Cannot add a charge to a '{billing['status']}' billing record.",
            rule_id="BILLING_NOT_CHARGEABLE",
        )

    amount_ngn = validated.amount_ngn
    amount_usd = validated.amount_usd

    # Charge row, invoice total and recomputed status commit together.
    try:
        charge, _ = repo.add_misc_charge_to_billing(
            tenant_id,
            {
                "billing_id": billing_id,
                "description": validated.description,
                "amount_ngn": amount_ngn,
                "amount_usd": amount_usd,
                "charge_type": validated.charge_type,
                "charge_type_id": validated.charge_type_id or None,
                "created_by": actor_id,
            },
        )
    except repo.BillingStatusConflict as exc:
        raise BusinessRuleViolationError(
            f"Cannot add a charge to a '{exc.status}' billing record.",
            rule_id="BILLING_NOT_CHARGEABLE",
        ) from exc

    log_audit(
        tenant_id=tenant_id,
        entity_type="misc_charge",
        entity_id=str(charge["id"]),
        action="CREATE",
        actor_id=actor_id,
        actor_role=actor_role,
        after_state={"billing_id": billing_id, "amount_ngn": str(amount_ngn)},
        ip_address=ip_address,
    )
    return _fmt_misc_charge(charge)


def list_misc_charges(
    tenant_id: str,
    billing_id: str,
    ctx: Any,
) -> list[dict[str, Any]]:
    billing = repo.get_billing_by_id(tenant_id, billing_id)
    if not billing:
        raise ResourceNotFoundError("billing", billing_id)

    if ctx.must_scope_to_customer(UserRole.TENANT_ADMIN, UserRole.NIGERIA_OFFICE_STAFF):
        customer = repo.get_customer_by_user_id(tenant_id, ctx.user_id)
        if not customer or str(customer["id"]) != str(billing["customer_id"]):
            raise InsufficientPermissionsError("Customers may only view charges on their own billing records")

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

    charge = repo.get_misc_charge_by_id(charge_id, tenant_id=tenant_id)
    if not charge or str(charge["billing_id"]) != billing_id:
        raise ResourceNotFoundError("misc_charge", charge_id)

    amount_ngn = Decimal(str(charge["amount_ngn"]))
    try:
        # Re-checks the invoice is still unpaid under its row lock, deletes the
        # charge and takes exactly that amount off the total, in one transaction.
        repo.delete_misc_charge_from_billing(tenant_id, charge_id, billing_id, required_status="unpaid")
    except repo.BillingStatusConflict as exc:
        raise BusinessRuleViolationError(
            "Misc charges can only be removed from unpaid billing records",
            rule_id="BILLING_NOT_UNPAID",
        ) from exc
    except repo.RecordNotFound as exc:
        raise ResourceNotFoundError("misc_charge", charge_id) from exc

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
    ctx: Any,
) -> list[dict[str, Any]]:
    billing = repo.get_billing_by_id(tenant_id, billing_id)
    if not billing:
        raise ResourceNotFoundError("billing", billing_id)

    if ctx.must_scope_to_customer(UserRole.TENANT_ADMIN, UserRole.NIGERIA_OFFICE_STAFF):
        customer = repo.get_customer_by_user_id(tenant_id, ctx.user_id)
        if not customer or str(customer["id"]) != str(billing["customer_id"]):
            raise InsufficientPermissionsError("Customers may only view storage fees on their own billing records")

    rows = repo.get_storage_fees_for_billing(tenant_id, billing_id)
    return [_fmt_storage_fee(r) for r in rows]


def waive_storage_fees(
    tenant_id: str,
    billing_id: str,
    reason: str,
    actor_id: str,
    ip_address: str = "",
    actor_role: str = "staff",
) -> dict[str, Any]:
    """Waive all storage fees currently charged on a billing record.

    Marks the accrued fee rows waived and takes their total off the invoice, in
    one transaction. If the customer has already paid more than the reduced total,
    a refund request is opened. Fees that accrue after this call are charged as
    normal. Returns the refreshed billing record so the UI can update immediately.

    Roles allowed: tenant_admin, nigeria_office_staff (checked in handler).
    """
    clean_reason = reason.strip() if isinstance(reason, str) else ""
    if not clean_reason:
        raise ValidationError("Waive reason is required", field_errors={"reason": "reason is required"})

    billing = repo.get_billing_by_id(tenant_id, billing_id)
    if not billing:
        raise ResourceNotFoundError("billing", billing_id)

    payment_status = billing.get("payment_status") or billing.get("status")
    if payment_status in {"cancelled", "waived"}:
        raise BusinessRuleViolationError(
            f"Cannot waive storage fees on a billing record with status '{payment_status}'.",
            rule_id="BILLING_NOT_WAIVEABLE",
        )

    try:
        updated, waived = repo.waive_storage_fees_for_billing(tenant_id, billing_id, clean_reason)
    except repo.BillingStatusConflict as exc:
        raise BusinessRuleViolationError(
            f"Cannot waive storage fees on a billing record with status '{exc.status}'.",
            rule_id="BILLING_NOT_WAIVEABLE",
        ) from exc
    if not updated:
        raise ResourceNotFoundError("billing", billing_id)
    if waived <= 0:
        raise BusinessRuleViolationError(
            "There are no storage fees on this billing record to waive.",
            rule_id="NO_STORAGE_FEES",
        )

    log_audit(
        tenant_id=tenant_id,
        entity_type="billing",
        entity_id=billing_id,
        action="WAIVE_STORAGE_FEES",
        actor_id=actor_id,
        actor_role=actor_role,
        before_state={"storage_fees_ngn": str(waived), "total_ngn": str(billing["total_ngn"])},
        after_state={"storage_fees_ngn": "0", "total_ngn": str(updated["total_ngn"]), "reason": clean_reason},
        ip_address=ip_address,
    )

    return _enrich_billing(tenant_id, {**billing, **dict(updated)})


# ---------------------------------------------------------------------------
# Billing list / generate
# ---------------------------------------------------------------------------


def list_billing(
    tenant_id: str,
    filters: dict[str, Any],
    limit: int,
    cursor: dict[str, Any] | None,
    ctx: Any = None,
    sort_field: str = "created_at",
    sort_direction: str = "DESC",
) -> tuple[list[dict[str, Any]], str | None, bool]:
    """List billing records for a tenant (paginated).

    Ground-truth fix (2026-07-19): this backs GET /v1/billing, which
    _BILLING_READ_ROLES allows the customer role to call — but had no
    ownership scoping at all, so any customer could list every other
    customer's billing (amounts, payment status) in the tenant just by
    hitting the endpoint with no filters. CUSTOMER role is now force-scoped
    to their own customer_id, same enforcement as get_billing_for_customer()
    — any customer_id they pass is overridden, not merely validated, so
    there's no way to request someone else's records.
    """
    if ctx is not None and ctx.must_scope_to_customer(UserRole.TENANT_ADMIN, UserRole.NIGERIA_OFFICE_STAFF):
        customer = repo.get_customer_by_user_id(tenant_id, ctx.user_id)
        if not customer:
            return [], None, False
        filters = {**filters, "customer_id": str(customer["id"])}

    rows, next_cursor, has_more = repo.list_billing_all(
        tenant_id, filters, limit, cursor, sort_field=sort_field, sort_direction=sort_direction
    )
    return [_enrich_billing(tenant_id, dict(r)) for r in rows], next_cursor, has_more


def list_recent_payments(tenant_id: str, limit: int = 8) -> list[dict[str, Any]]:
    """Most recent payments across all billings (§6.1 dashboard feed, P2-5)."""
    return [
        {
            "id": str(p["id"]),
            "billing_id": str(p["billing_id"]),
            "customer_name": p.get("customer_name"),
            "amount_ngn": str(p["amount_ngn"]),
            "payment_method": p["payment_method"],
            "reference_number": p.get("reference_number"),
            "payment_date": str(p["payment_date"]) if p.get("payment_date") else None,
            "created_at": p.get("created_at"),
        }
        for p in repo.list_recent_payments(tenant_id, limit)
    ]


_BILLABLE_CONTAINER_STATUSES = frozenset({"cleared", "at_warehouse", "fully_released"})

_SKIP_MESSAGES = {
    "RATE_CONFIG_MISSING": "Set the CBM rate and dollar rate in Settings, then generate the invoice again.",
    "NO_CBM": "The customer's approved packing lists on this container have no CBM to bill.",
    "RATE_UNAVAILABLE": "No market dollar rate could be fetched. Generate the invoice again once the rate is available.",
}


def _outcome_row(customer: dict[str, Any], outcome: InvoiceOutcome) -> dict[str, Any]:
    return {
        "customer_id": str(customer["id"]),
        "customer_name": customer.get("name"),
        "status": outcome.status,
        "billing_id": outcome.billing_id,
        "invoice_number": outcome.invoice_number,
        "reason": outcome.reason,
        "detail": outcome.detail,
    }


def generate_container_invoices(
    tenant_id: str,
    container_id: str,
    container_number: str | None,
    customers: list[dict[str, Any]],
    request_id: str = "",
) -> list[dict[str, Any]]:
    """Bill each customer on a container and report what happened per customer.

    One customer's failure never stops the others. Every outcome, including a
    failure, is returned so the caller can show it; a failure is also logged and
    counted for alerting. Safe to run again: customers who already have an
    invoice come back as ``existing``.

    When any customer could not be billed, tenant admins and Nigeria staff are
    told in-app, with the reason, so an unbilled customer is never silent.
    """
    rows: list[dict[str, Any]] = []
    for customer in customers:
        try:
            outcome = handle_payment_due(
                tenant_id=tenant_id,
                container_id=container_id,
                customer_id=str(customer["id"]),
                container_number=container_number,
                request_id=request_id,
            )
        except Exception:
            logger.exception("Failed to generate invoice for customer %s on container %s", customer["id"], container_id)
            record_failure("invoice_generation")  # a customer left unbilled raises an alarm (audit OPS-04)
            outcome = InvoiceOutcome(
                status="failed",
                reason="GENERATION_ERROR",
                detail="The invoice could not be created. Generate it again from the container page.",
            )
        rows.append(_outcome_row(customer, outcome))

    unbilled = [r for r in rows if r["status"] in {"skipped", "failed"}]
    if unbilled:
        _notify_unbilled(tenant_id, container_id, container_number, unbilled)
    return rows


def _notify_unbilled(tenant_id: str, container_id: str, container_number: str | None, unbilled: list[dict[str, Any]]) -> None:
    """Tell the people who can fix it that customers on a cleared container have no invoice."""
    reasons = sorted({r["reason"] for r in unbilled if r["reason"]})
    body = (
        f"{len(unbilled)} customer(s) on container {container_number or container_id} have no invoice "
        f"({', '.join(reasons)}). Open the container to generate them."
    )
    for role in (UserRole.TENANT_ADMIN, UserRole.NIGERIA_OFFICE_STAFF):
        try:
            notify_staff(
                tenant_id=tenant_id,
                event_type="invoice_not_generated",
                entity_type="container",
                entity_id=container_id,
                title="Some customers were not invoiced",
                body=body,
                target_role=str(role),
            )
        except Exception:
            logger.exception("Failed to notify %s about unbilled customers on container %s", role, container_id)


def list_unbilled_customers(tenant_id: str) -> list[dict[str, Any]]:
    """Customers on cleared containers who should have an invoice and do not.

    Feeds the dashboard queue; the fix is `generate_billing` on the container.
    """
    return repo.list_unbilled_customers(tenant_id)


def generate_billing(
    tenant_id: str,
    req: Any,
    actor_id: str,
    ctx: Any,
) -> dict[str, Any]:
    """Manually generate invoices for a cleared container.

    With ``req.customer_id`` it bills that customer and fails with a specific
    rule if it cannot (``CONTAINER_NOT_CLEARED``, ``CUSTOMER_NOT_ON_CONTAINER``,
    ``ALREADY_BILLED``, ``NO_CBM``, ``RATE_CONFIG_MISSING``, ``RATE_UNAVAILABLE``). Without it, it
    bills every customer on the container who has no invoice yet and returns the
    per-customer results.
    """
    container_id = str(req.container_id)
    container = repo.get_container_for_billing(tenant_id, container_id)
    if not container:
        raise ResourceNotFoundError("container", container_id)
    if container["status"] not in _BILLABLE_CONTAINER_STATUSES:
        raise BusinessRuleViolationError(
            "Invoices can only be generated once the container has cleared customs.",
            rule_id="CONTAINER_NOT_CLEARED",
        )

    customers = repo.get_billable_customers_for_container(tenant_id, container_id)
    if req.customer_id is not None:
        customers = [c for c in customers if c["id"] == str(req.customer_id)]
        if not customers:
            raise BusinessRuleViolationError(
                "That customer has no approved packing list on this container.",
                rule_id="CUSTOMER_NOT_ON_CONTAINER",
            )

    results = generate_container_invoices(tenant_id, container_id, container.get("container_number"), customers)

    if req.customer_id is not None:
        only = results[0]
        if only["status"] == "existing":
            raise BusinessRuleViolationError(
                f"This customer already has invoice {only['invoice_number']} for this container.",
                rule_id="ALREADY_BILLED",
            )
        if only["status"] in {"skipped", "failed"}:
            raise BusinessRuleViolationError(
                _SKIP_MESSAGES.get(only["reason"] or "", only["detail"] or "The invoice could not be generated."),
                rule_id=only["reason"] or "GENERATION_ERROR",
            )
    return {"container_id": container_id, "results": results}


def apply_carryover(
    tenant_id: str,
    billing_id: str,
    carryover_id: str,
    actor_id: str,
    ip_address: str | None = None,
    actor_role: str = str(UserRole.TENANT_ADMIN),
) -> dict[str, Any]:
    """Manually apply an outstanding carryover to a billing record.

    Guards:
      - Billing must exist and not be cancelled or waived.
      - Carryover must be 'outstanding', belong to the same customer as the billing,
        and not originate from the same invoice (no self-carryover).
    Updates billing totals: adds carryover amount to total_ngn and recalculates balance.
    """
    billing = repo.get_billing_by_id(tenant_id, billing_id)
    if not billing:
        raise ResourceNotFoundError("billing", billing_id)

    if billing["status"] in {"cancelled", "waived"}:
        raise BusinessRuleViolationError(
            f"Cannot apply carryover to a '{billing['status']}' billing.",
            rule_id="BR-CARRYOVER-001",
        )

    carryover = repo.get_carryover_by_id(tenant_id, carryover_id)
    if not carryover:
        raise ResourceNotFoundError("carryover_ledger", carryover_id)

    if carryover["status"] != "outstanding":
        raise BusinessRuleViolationError(
            f"Carryover is '{carryover['status']}' — only 'outstanding' entries can be applied.",
            rule_id="BR-CARRYOVER-002",
        )

    if str(carryover["customer_id"]) != str(billing["customer_id"]):
        raise BusinessRuleViolationError(
            "Carryover customer does not match billing customer.",
            rule_id="BR-CARRYOVER-003",
        )

    if str(carryover.get("source_billing_id") or "") == str(billing_id):
        raise BusinessRuleViolationError(
            "Cannot apply a carryover back onto its own source invoice.",
            rule_id="BR-CARRYOVER-SELF",
        )

    # Mark the carryover applied (only if it is still outstanding and this
    # customer's), add its amount and recompute the status, in one transaction under
    # the invoice lock. A 'paid' invoice that takes on carried-forward debt becomes
    # 'partially_paid'; 'released_with_outstanding' is a release state and is left alone.
    try:
        updated, carryover_amount = repo.apply_carryover_to_billing(
            tenant_id, billing_id, carryover_id, str(billing["customer_id"])
        )
    except repo.BillingStatusConflict as exc:
        raise BusinessRuleViolationError(
            f"Cannot apply carryover to a '{exc.status}' billing.",
            rule_id="BR-CARRYOVER-001",
        ) from exc
    except repo.RecordNotFound as exc:
        raise BusinessRuleViolationError(
            "That carryover is no longer outstanding — it was applied by another request.",
            rule_id="BR-CARRYOVER-002",
        ) from exc

    log_audit(
        tenant_id=tenant_id,
        entity_type="billing",
        entity_id=billing_id,
        action="APPLY_CARRYOVER",
        actor_id=actor_id,
        actor_role=actor_role,
        before_state={"total_ngn": str(billing["total_ngn"]), "status": billing["status"]},
        after_state={"total_ngn": str(updated["total_ngn"]), "carryover_id_applied": carryover_id},
        ip_address=ip_address,
    )

    return {
        "billing_id": billing_id,
        "carryover_id": carryover_id,
        "carryover_amount_ngn": carryover_amount,
        "new_total_ngn": Decimal(str(updated["total_ngn"])),
        "new_balance_ngn": Decimal(str(updated.get("balance_ngn", 0))),
    }


def cancel_billing(
    tenant_id: str,
    billing_id: str,
    cancel_reason: str,
    actor_id: str,
    ip_address: str | None = None,
    actor_role: str = str(UserRole.TENANT_ADMIN),
) -> dict[str, Any]:
    """Void an unpaid (or credit-only paid) billing record, and give back what issuing it took.

    The credits the invoice used return to the customer, and the earlier balances it carried over become outstanding
    again for their next invoice (``repo.cancel_billing``, one transaction).

    Guards:
      - Billing must be 'unpaid', OR 'paid' strictly via applied customer credits with 0 cash paid.
      - No confirmed payment records, active release notes, or active CBM disputes may reference this billing.
      - An invoice issued before credit use was recorded per invoice (migration 070) that used credit is refused.
    """
    billing = repo.get_billing_by_id(tenant_id, billing_id)
    if not billing:
        raise ResourceNotFoundError("billing", billing_id)

    credits_used = Decimal(str(billing.get("credits_applied_ngn") or 0))
    amount_paid = Decimal(str(billing.get("amount_paid_ngn") or 0))
    is_credit_only_paid = billing["status"] == "paid" and amount_paid <= Decimal("0") and credits_used > Decimal("0")
    if billing["status"] != "unpaid" and not is_credit_only_paid:
        raise BusinessRuleViolationError(
            f"Cannot cancel billing in status '{billing['status']}'. Only 'unpaid' invoices may be cancelled.",
            rule_id="BR-BL-CANCEL-001",
        )

    if repo.get_confirmed_payment_count(tenant_id, billing_id) > 0:
        raise BusinessRuleViolationError(
            "Cannot cancel billing that has confirmed payment records.",
            rule_id="BR-BL-CANCEL-002",
        )

    if repo.get_active_release_note_count(tenant_id, billing_id) > 0:
        raise BusinessRuleViolationError(
            "Cannot cancel billing with an active release note.",
            rule_id="BR-BL-CANCEL-003",
        )

    if repo.get_active_disputes(tenant_id, billing_id):
        raise BusinessRuleViolationError(
            "Cannot cancel billing with an active CBM dispute.",
            rule_id="BR-BL-CANCEL-004",
        )

    recorded = sum((Decimal(str(a["amount_ngn"])) for a in repo.get_credit_applications(tenant_id, billing_id)), Decimal(0))
    if credits_used > recorded:
        raise BusinessRuleViolationError(
            "This invoice used customer credit before credit use was recorded per invoice, so cancelling it cannot "
            "give the credit back automatically. Ask support to restore the credit, then cancel.",
            rule_id="CREDIT_NOT_TRACEABLE",
        )

    cancelled = repo.cancel_billing(tenant_id, billing_id, actor_id, cancel_reason)
    if cancelled is None:
        raise ResourceNotFoundError("billing", billing_id)
    updated = cancelled.row

    log_audit(
        tenant_id=tenant_id,
        entity_type="billing",
        entity_id=billing_id,
        action="CANCEL",
        actor_id=actor_id,
        actor_role=actor_role,
        before_state={"status": billing["status"]},
        after_state={
            "status": "cancelled",
            "cancel_reason": cancel_reason,
            "credits_restored": [{"refund_request_id": rid, "amount_ngn": str(amt)} for rid, amt in cancelled.credits_restored],
            "carryovers_reopened": cancelled.carryovers_reopened,
        },
        ip_address=ip_address,
    )

    return {
        **updated,
        "credits_restored_ngn": sum((amt for _, amt in cancelled.credits_restored), Decimal(0)),
        "carryovers_reopened": len(cancelled.carryovers_reopened),
    }


# ---------------------------------------------------------------------------
# Top-level dispute listing / management
# ---------------------------------------------------------------------------


def list_disputes(
    tenant_id: str,
    filters: dict[str, Any],
    limit: int,
    cursor: dict[str, Any] | None,
) -> tuple[list[dict[str, Any]], str | None, bool, int]:
    """A page of the tenant's disputes, and how many match in all."""
    rows, next_cursor, has_more = repo.list_all_disputes(tenant_id, filters, limit, cursor)
    total = repo.count_all_disputes(tenant_id, filters)
    return [_dispute_list_item(r) for r in rows], next_cursor, has_more, total


def _dispute_list_item(row: dict[str, Any]) -> dict[str, Any]:
    """A dispute as the list shows it: the usual fields plus which customer, invoice and container it is about."""
    return {
        **_fmt_dispute(row),
        "customer_name": row.get("customer_name"),
        "invoice_number": row.get("invoice_number"),
        "container_number": row.get("container_number"),
    }


# Keep old name as alias for backwards compatibility
list_all_disputes = list_disputes


def get_dispute_detail(tenant_id: str, dispute_id: str) -> dict[str, Any]:
    """One dispute with its measurement data, for the screen a China user resolves it on (audit UX-01).

    Measurement only: no amount, rate or payment appears, because the readers include roles that may not
    read invoices. The invoice page keeps its inline view for the roles that can.
    """
    row = repo.get_dispute_measurements(tenant_id, dispute_id)
    if row is None:
        raise ResourceNotFoundError("cbm_dispute", dispute_id)
    lines = repo.list_measurement_lines(tenant_id, str(row["container_id"]), str(row["customer_id"]))
    return {
        **_fmt_dispute(row),
        "customer_name": row.get("customer_name"),
        "container_number": row.get("container_number"),
        "reason": row.get("dispute_reason"),
        "customer_measured_cbm": row.get("customer_measured_cbm"),
        "billed_cbm": row.get("billed_cbm"),
        "resolution_notes": row.get("resolution_notes"),
        "lines": [
            {
                "reference": ln.get("reference"),
                "carton_tag": ln["carton_tag"],
                "description": ln["description"],
                "quantity": ln["quantity"],
                "package_unit": ln.get("package_unit"),
                "cbm": ln["cbm"],
                "length_cm": ln.get("length_cm"),
                "width_cm": ln.get("width_cm"),
                "height_cm": ln.get("height_cm"),
                "weight_kg": ln.get("weight_actual_kg"),
            }
            for ln in lines
        ],
    }


def create_dispute(
    tenant_id: str,
    body: dict[str, Any],
    actor_id: str,
    ctx: Any,
    request_id: str = "",
    ip_address: str | None = None,
) -> dict[str, Any]:
    """Create a CBM dispute (billing_id taken from request body)."""
    billing_id = body.get("billing_id", "")
    if not isinstance(billing_id, str) or not billing_id.strip():
        raise ValidationError("billing_id is required", field_errors={"billing_id": "required"})
    payload = {
        "customer_measured_cbm": body.get("disputed_cbm", body.get("customer_measured_cbm")),
        "reason": body.get("dispute_reason", body.get("reason", "")),
    }
    req = parse_validated(FileCBMDisputeRequest, payload)
    return file_cbm_dispute(
        tenant_id,
        billing_id.strip(),
        req,
        actor_id=actor_id,
        ctx=ctx,
        request_id=request_id,
        ip_address=ip_address,
    )


_REJECTABLE_DISPUTE_STATES = sorted({"submitted", *_DISPUTE_ALLOWED_SOURCE_STATES})
_ESCALATABLE_DISPUTE_STATES = ["submitted", "acknowledged", "investigating"]


def reject_dispute(
    tenant_id: str,
    dispute_id: str,
    reason: str,
    actor_id: str,
    ctx: Any,
    ip_address: str | None = None,
) -> dict[str, Any]:
    """Reject an active CBM dispute."""
    dispute = repo.get_cbm_dispute_by_id(tenant_id, dispute_id)
    if not dispute:
        raise ResourceNotFoundError("cbm_dispute", dispute_id)
    if dispute["status"] not in _REJECTABLE_DISPUTE_STATES:
        raise IllegalTransitionError(
            entity="cbm_dispute",
            current_state=dispute["status"],
            requested_state="rejected",
            allowed=_REJECTABLE_DISPUTE_STATES,
        )
    updated = repo.set_dispute_status(
        tenant_id,
        dispute_id,
        "rejected",
        {"resolution_notes": reason, "resolved_by": actor_id, "resolved_at": datetime.now(UTC)},
        allowed_from=_REJECTABLE_DISPUTE_STATES,
    )
    if updated is None:
        raise IllegalTransitionError(
            entity="cbm_dispute",
            current_state="changed by another request",
            requested_state="rejected",
            allowed=_REJECTABLE_DISPUTE_STATES,
        )

    log_audit(
        tenant_id=tenant_id,
        entity_type="cbm_dispute",
        entity_id=dispute_id,
        action="STATUS_CHANGE",
        actor_id=actor_id,
        actor_role=str(ctx.role),
        before_state={"status": dispute["status"]},
        after_state={"status": "rejected", "resolution_notes": reason},
        ip_address=ip_address,
    )
    return _fmt_dispute(updated)


def escalate_dispute(
    tenant_id: str,
    dispute_id: str,
    ctx: Any,
    ip_address: str | None = None,
) -> dict[str, Any]:
    """Escalate a CBM dispute to the China office ('escalated_china')."""
    dispute = repo.get_dispute_by_id(tenant_id, dispute_id)
    if not dispute:
        raise ResourceNotFoundError("cbm_dispute", dispute_id)
    if dispute["status"] not in _ESCALATABLE_DISPUTE_STATES:
        raise IllegalTransitionError(
            entity="cbm_dispute",
            current_state=dispute["status"],
            requested_state="escalated_china",
            allowed=_ESCALATABLE_DISPUTE_STATES,
        )
    updated = repo.update_dispute_status(tenant_id, dispute_id, "escalated_china", {}, allowed_from=_ESCALATABLE_DISPUTE_STATES)
    if updated is None:
        raise IllegalTransitionError(
            entity="cbm_dispute",
            current_state="changed by another request",
            requested_state="escalated_china",
            allowed=_ESCALATABLE_DISPUTE_STATES,
        )
    log_audit(
        tenant_id=tenant_id,
        entity_type="cbm_dispute",
        entity_id=dispute_id,
        action="STATUS_CHANGE",
        actor_id=ctx.user_id,
        actor_role=str(ctx.role),
        before_state={"status": dispute["status"]},
        after_state={"status": "escalated_china"},
        ip_address=ip_address,
    )
    return _fmt_dispute(updated)


# ---------------------------------------------------------------------------
# CBM Dispute operations
# ---------------------------------------------------------------------------


def file_cbm_dispute(
    tenant_id: str,
    billing_id: str,
    req: Any,
    actor_id: str,
    ctx: Any,
    request_id: str = "",
    ip_address: str | None = None,
) -> dict[str, Any]:
    """File a CBM dispute against an existing active billing record.

    Guard: billing not cancelled/waived, and no active dispute already open.
    """
    billing = repo.get_billing_by_id(tenant_id, billing_id)
    if not billing:
        raise ResourceNotFoundError("billing", billing_id)

    # CUSTOMER: verify they own this billing
    if ctx.must_scope_to_customer(UserRole.TENANT_ADMIN, UserRole.NIGERIA_OFFICE_STAFF):
        customer = repo.get_customer_by_user_id(tenant_id, ctx.user_id)
        if not customer or str(customer["id"]) != str(billing["customer_id"]):
            raise InsufficientPermissionsError("Customers may only dispute their own billing records")

    if billing.get("status") in {"cancelled", "waived"}:
        raise BusinessRuleViolationError(
            f"Cannot file a CBM dispute against a '{billing['status']}' invoice",
            rule_id="INVALID_BILLING_STATUS",
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
            "tenant_id": tenant_id,
            "billing_id": billing_id,
            "customer_id": str(billing["customer_id"]),
            "disputed_cbm": billing["total_cbm"],
            "customer_measured_cbm": req.customer_measured_cbm,
            "dispute_reason": req.reason,
            "raised_by": actor_id,
        },
    )
    if dispute is None:
        raise RuntimeError("create_cbm_dispute returned None unexpectedly")
    log_audit(
        tenant_id=tenant_id,
        entity_type="cbm_dispute",
        entity_id=str(dispute["id"]),
        action="CREATE",
        actor_id=actor_id,
        actor_role=str(ctx.role),
        after_state={"billing_id": billing_id, "status": "submitted"},
        ip_address=ip_address,
    )
    for role in ("nigeria_office_staff", "tenant_admin"):
        notify_staff(
            tenant_id=tenant_id,
            event_type="cbm_dispute_filed",
            entity_type="cbm_dispute",
            entity_id=str(dispute["id"]),
            title="New CBM dispute filed",
            body=f"A CBM dispute was filed on billing {billing_id}.",
            target_role=role,
        )
    return _fmt_dispute(dispute)


def list_billing_disputes(tenant_id: str, billing_id: str, ctx: Any) -> list[dict[str, Any]]:
    """List all disputes for a billing record."""
    if ctx.must_scope_to_customer(UserRole.TENANT_ADMIN, UserRole.NIGERIA_OFFICE_STAFF):
        billing = repo.get_billing_by_id(tenant_id, billing_id)
        if not billing:
            raise ResourceNotFoundError("billing", billing_id)
        customer = repo.get_customer_by_user_id(tenant_id, ctx.user_id)
        if not customer or str(customer["id"]) != str(billing["customer_id"]):
            raise InsufficientPermissionsError("Customers may only view disputes on their own billing records")
    rows = repo.list_disputes_for_billing(tenant_id, billing_id)
    return [_fmt_dispute(r) for r in rows]


def acknowledge_dispute(
    tenant_id: str,
    dispute_id: str,
    actor_id: str,
    ip_address: str | None = None,
    actor_role: str = str(UserRole.NIGERIA_OFFICE_STAFF),
) -> dict[str, Any]:
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
    if updated is None:
        raise IllegalTransitionError(
            entity="cbm_dispute",
            current_state="changed by another request",
            requested_state="acknowledged",
            allowed=["submitted"],
        )
    log_audit(
        tenant_id=tenant_id,
        entity_type="cbm_dispute",
        entity_id=dispute_id,
        action="STATUS_CHANGE",
        actor_id=actor_id,
        actor_role=actor_role,
        before_state={"status": "submitted"},
        after_state={"status": "acknowledged"},
        ip_address=ip_address,
    )
    return _fmt_dispute(updated)


def _reprice_cbm_for_dispute(billing: dict[str, Any], new_cbm: Decimal) -> tuple[Decimal, Decimal]:
    """Compute ``(new_subtotal_usd, new_subtotal_ngn)`` for a corrected CBM without NGN round-trip drift."""
    exchange_rate = Decimal(str(billing["exchange_rate_ngn"]))
    currency = str(billing.get("cbm_rate_currency") or "USD").upper()
    if currency == "NGN":
        breakdown = billing.get("cbm_breakdown")
        if isinstance(breakdown, str):
            try:
                breakdown = json.loads(breakdown)
            except ValueError:
                breakdown = None
        if isinstance(breakdown, dict) and breakdown:
            rates = {Decimal(str(v["rate"])) for v in breakdown.values() if isinstance(v, dict) and v.get("rate") is not None}
            if len(rates) == 1:
                ngn_rate = next(iter(rates))
                new_subtotal_ngn = (new_cbm * ngn_rate).quantize(Decimal("0.01"), ROUND_HALF_UP)
                new_subtotal_usd = (
                    (new_subtotal_ngn / exchange_rate).quantize(Decimal("0.01"), ROUND_HALF_UP)
                    if exchange_rate > 0
                    else Decimal("0.00")
                )
                return new_subtotal_usd, new_subtotal_ngn
    cbm_rate_usd = Decimal(str(billing["cbm_rate_usd"]))
    new_subtotal_usd = (new_cbm * cbm_rate_usd).quantize(Decimal("0.01"), ROUND_HALF_UP)
    new_subtotal_ngn = (new_subtotal_usd * exchange_rate).quantize(Decimal("0.01"), ROUND_HALF_UP)
    return new_subtotal_usd, new_subtotal_ngn


def resolve_dispute(
    tenant_id: str,
    dispute_id: str,
    req: Any,
    actor_id: str,
    ctx: Any,
    request_id: str = "",
    ip_address: str | None = None,
) -> dict[str, Any]:
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

    is_admin = ctx.has_role(UserRole.TENANT_ADMIN)
    # Four-eyes / SoD: non-admin staff cannot resolve a dispute they raised themselves.
    if not is_admin and dispute.get("raised_by") and str(dispute["raised_by"]) == str(actor_id):
        from shared.exceptions import SelfApprovalForbiddenError

        raise SelfApprovalForbiddenError()
    # China office staff may only resolve disputes explicitly escalated to China.
    if (
        ctx.has_role(UserRole.CHINA_OFFICE_STAFF)
        and not ctx.has_role(UserRole.TENANT_ADMIN, UserRole.NIGERIA_OFFICE_STAFF)
        and current != "escalated_china"
    ):
        raise InsufficientPermissionsError("China office staff can only resolve disputes in 'escalated_china' status")

    target = req.status.value if hasattr(req.status, "value") else str(req.status)
    if target not in _DISPUTE_ALLOWED_TARGET_STATES:
        raise BusinessRuleViolationError(
            f"Cannot transition dispute to '{target}' via the resolve endpoint",
            rule_id="INVALID_DISPUTE_TARGET_STATE",
        )

    extra: dict[str, Any] = {}
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
        if billing.get("status") in {"cancelled", "waived"}:
            raise BusinessRuleViolationError(
                f"Cannot adjust CBM on a '{billing['status']}' invoice",
                rule_id="INVALID_BILLING_STATUS",
            )

        new_cbm = Decimal(str(req.corrected_cbm))
        new_subtotal_usd, new_subtotal_ngn = _reprice_cbm_for_dispute(billing, new_cbm)

        try:
            # Re-price the invoice, refund any new overpayment, and move the dispute
            # to resolved_adjusted in one transaction; a dispute already resolved by
            # someone else re-prices nothing.
            updated, _, _ = repo.resolve_dispute_with_adjustment(
                tenant_id,
                dispute_id,
                str(billing["id"]),
                sorted(_DISPUTE_ALLOWED_SOURCE_STATES),
                new_cbm,
                new_subtotal_usd,
                new_subtotal_ngn,
                {
                    "agreed_cbm": new_cbm,
                    "resolution_notes": req.resolution_notes,
                    "resolved_by": actor_id,
                    "resolved_at": datetime.now(UTC),
                },
            )
        except repo.BillingStatusConflict as exc:
            raise BusinessRuleViolationError(
                f"Cannot adjust CBM on a '{exc.status}' invoice",
                rule_id="INVALID_BILLING_STATUS",
            ) from exc
        except repo.RecordNotFound as exc:
            raise IllegalTransitionError(
                entity="cbm_dispute",
                current_state="already resolved",
                requested_state=target,
                allowed=sorted(_DISPUTE_ALLOWED_SOURCE_STATES),
            ) from exc

        publish_event(
            source="logistics.billing",
            detail_type="CBMDisputeResolved",
            tenant_id=tenant_id,
            payload={
                "dispute_id": dispute_id,
                "billing_id": str(dispute["billing_id"]),
                "original_cbm": str(dispute["disputed_cbm"]),
                "corrected_cbm": str(new_cbm),
            },
            request_id=request_id,
        )
    else:
        if is_terminal:
            extra["resolution_notes"] = req.resolution_notes
            extra["resolved_by"] = actor_id
            extra["resolved_at"] = datetime.now(UTC)
        moved = repo.set_dispute_status(tenant_id, dispute_id, target, extra, allowed_from=sorted(_DISPUTE_ALLOWED_SOURCE_STATES))
        if moved is None:
            raise IllegalTransitionError(
                entity="cbm_dispute",
                current_state="changed by another request",
                requested_state=target,
                allowed=sorted(_DISPUTE_ALLOWED_SOURCE_STATES),
            )
        updated = moved

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


def _fmt_dispute(row: dict[str, Any]) -> dict[str, Any]:
    from datetime import timedelta

    status = row["status"]
    submitted_at = row.get("created_at")
    acknowledged_at = row.get("acknowledged_at")

    acknowledge_due_by = (submitted_at + timedelta(hours=_DISPUTE_ACKNOWLEDGE_HOURS)) if submitted_at else None
    investigate_due_by = (acknowledged_at + timedelta(days=_DISPUTE_INVESTIGATE_DAYS)) if acknowledged_at else None
    resolve_due_by = (acknowledged_at + timedelta(days=_DISPUTE_RESOLVE_DAYS)) if acknowledged_at else None
    auto_escalated_at = row.get("updated_at") if status in {"escalated_china", "escalated"} else None

    return {
        "id": str(row["id"]),
        "billing_id": str(row["billing_id"]),
        "original_cbm": row.get("disputed_cbm"),
        "corrected_cbm": row.get("agreed_cbm"),
        "status": status,
        "submitted_at": submitted_at,
        "acknowledged_at": acknowledged_at,
        "acknowledge_due_by": acknowledge_due_by,
        "investigate_due_by": investigate_due_by,
        "resolve_due_by": resolve_due_by,
        "auto_escalated_at": auto_escalated_at,
    }


def _fmt_carryover(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": str(row["id"]),
        "customer_id": str(row["customer_id"]),
        "customer_name": row.get("customer_name"),
        "source_billing_id": str(row["source_billing_id"]),
        "source_container_number": row.get("source_container_number"),
        "target_billing_id": str(row["target_billing_id"]) if row.get("target_billing_id") else None,
        "amount_ngn": row["carryover_amount_ngn"],
        "status": row["status"],
        "created_at": row["created_at"],
    }


def _fmt_misc_charge(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": str(row["id"]),
        "billing_id": str(row["billing_id"]),
        "charge_type": row["charge_type"],
        "description": row.get("description", ""),
        "amount_usd": row.get("amount_usd"),
        "amount_ngn": row["amount_ngn"],
        "created_at": row["created_at"],
    }


def _fmt_storage_fee(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": str(row["id"]),
        "day_number": row.get("days_in_storage"),
        "carton_count": row.get("cartons_in_storage"),
        "daily_rate_ngn": row.get("daily_rate_ngn"),
        "fee_amount_ngn": row.get("amount_ngn"),
        "accrual_date": row.get("accrual_date"),
    }
