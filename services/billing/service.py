"""Business logic for the Billing service.

Handles auto-billing on container clearance, CBM dispute lifecycle,
carryover/credit application, and billing recalculation on dispute resolution.
"""

import json
import logging
from datetime import UTC, date, datetime
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

from shared.audit import log_audit
from shared.cbm_rate import compute_cbm_charge, get_cbm_rate_config
from shared.events import publish_event
from shared.exceptions import (
    BusinessRuleViolationError,
    IllegalTransitionError,
    InsufficientPermissionsError,
    ResourceNotFoundError,
)
from shared.fx_rate import get_effective_dollar_rate
from shared.notifications import enqueue_notifications
from shared.staff_notifications import notify_staff
from shared.tenant_context import UserRole

from . import repository as repo

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
    # 1. Fetch pricing config. Dollar rate is Bybit's live P2P base rate plus
    # this tenant's markup (shared/fx_rate.py). CBM rate is the tenant's
    # currency + carton/bag/bale rate config (shared/cbm_rate.py) — "flat"
    # is just the case where all three rates happen to be equal, so the
    # math below never branches on rate_mode itself.
    cbm_config = get_cbm_rate_config(tenant_id)
    dollar_rate = get_effective_dollar_rate(tenant_id)["rate"]

    if (cbm_config["carton_rate"] <= 0 and cbm_config["bag_rate"] <= 0 and cbm_config["bale_rate"] <= 0) or dollar_rate <= 0:
        logger.warning(
            "Skipping billing for customer %s — missing tenant config (cbm_rates=%s/%s/%s, dollar_rate=%s)",
            customer_id,
            cbm_config["carton_rate"],
            cbm_config["bag_rate"],
            cbm_config["bale_rate"],
            dollar_rate,
        )
        return

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
        return

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

    # 5. Credits from approved credit-note refunds (subtract from total)
    credits = repo.get_pending_credit_refunds(tenant_id, customer_id)
    credits_ngn = sum(Decimal(str(r["amount_ngn"])) for r in credits)

    # 6. Final total (misc_charges_ngn starts at 0; storage/misc added later)
    total_ngn = (subtotal_ngn + carryover_ngn - credits_ngn).quantize(Decimal("0.01"), ROUND_HALF_UP)

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
            "tenant_id": tenant_id,
            "customer_id": customer_id,
            "container_id": container_id,
            "invoice_number": invoice_number,
            "total_cartons": total_cartons,
            "total_cbm": total_cbm,
            "cbm_rate_usd": cbm_rate_usd,
            "cbm_rate_currency": charge["currency"].upper(),
            "cbm_rate_mode": cbm_config["rate_mode"],
            "cbm_breakdown": json.dumps(charge["breakdown"], default=str),
            "subtotal_usd": subtotal_usd,
            "exchange_rate_ngn": dollar_rate,
            "subtotal_ngn": subtotal_ngn,
            "misc_charges_ngn": Decimal("0"),
            "total_ngn": total_ngn,
            "amount_paid_ngn": Decimal("0"),
            "status": "unpaid",
            "billed_at": now,
            "created_by": None,
        },
    )
    if billing is None:
        raise RuntimeError("create_billing returned None unexpectedly")
    billing_id = str(billing["id"])

    # 9. Mark carryovers as applied
    if carryovers:
        repo.mark_carryovers_applied(tenant_id, [str(c["id"]) for c in carryovers], billing_id)

    # 10. Mark credit refunds as applied
    if credits:
        repo.mark_credit_refunds_applied(tenant_id, [str(r["id"]) for r in credits])

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
            "carryover_applied_ngn": str(carryover_ngn),
            "credits_applied_ngn": str(credits_ngn),
        },
    )
    logger.info(
        "Billing %s created for customer %s / container %s",
        billing_id,
        customer_id,
        container_id,
    )
    _notify_customer_payment_due(tenant_id, customer_id, container_number, total_ngn, request_id)


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
    not fail billing generation itself."""
    try:
        customer = repo.get_customer_contact(tenant_id, customer_id)
        if not customer:
            return
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
                body=f"Container {container_number or ''}: NGN {total_ngn} due.",
                target_user_id=str(customer["user_id"]),
            )
    except Exception:
        logger.exception(
            "Failed to enqueue payment_due notification for customer %s",
            customer_id,
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

    if ctx is not None and ctx.role == UserRole.CUSTOMER:
        customer = repo.get_customer_by_user_id(tenant_id, ctx.user_id)
        if not customer or str(customer["id"]) != str(row.get("customer_id")):
            raise InsufficientPermissionsError("Customers may only view their own billing records")

    return _enrich_billing(tenant_id, dict(row))


def get_billing_for_customer(
    tenant_id: str,
    customer_id: str,
    ctx: Any,
    container_id: str | None = None,
) -> list[dict[str, Any]]:
    """Return enriched billing records for a customer.

    CUSTOMER role: verified against ctx.user_id — can only see their own billing.
    """
    if ctx.role == UserRole.CUSTOMER:
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
    storage_fees_ngn = sum(Decimal(str(m["amount_ngn"])) for m in misc_charges if m.get("charge_type") == "storage_fee")
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
        "adjustments_ngn": Decimal("0"),
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
    if exempted is None:
        raise RuntimeError("exempt_carryover returned None unexpectedly")

    new_carryover = repo.create_carryover(
        tenant_id,
        {
            "tenant_id": tenant_id,
            "customer_id": str(carryover["customer_id"]),
            "source_billing_id": str(carryover["source_billing_id"]),
            "carryover_amount_ngn": carryover["carryover_amount_ngn"],
            "notes": "Debt rolled forward from exempted carryover",
            "created_by": actor_id,
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
) -> dict[str, Any]:
    billing = repo.get_billing_by_id(tenant_id, billing_id)
    if not billing:
        raise ResourceNotFoundError("billing", billing_id)

    amount_ngn = Decimal(str(data.get("amount_ngn", 0)))
    amount_usd = data.get("amount_usd")

    charge = repo.add_misc_charge(
        tenant_id,
        {
            "billing_id": billing_id,
            "description": data.get("description", ""),
            "amount_ngn": amount_ngn,
            "amount_usd": amount_usd,
            "charge_type": data.get("charge_type", "other"),
            "charge_type_id": data.get("charge_type_id") or None,
            "created_by": actor_id,
        },
    )
    if charge is None:
        raise RuntimeError("add_misc_charge returned None unexpectedly")
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
    ctx: Any,
) -> list[dict[str, Any]]:
    billing = repo.get_billing_by_id(tenant_id, billing_id)
    if not billing:
        raise ResourceNotFoundError("billing", billing_id)

    if ctx.role == UserRole.CUSTOMER:
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
    ctx: Any,
) -> list[dict[str, Any]]:
    billing = repo.get_billing_by_id(tenant_id, billing_id)
    if not billing:
        raise ResourceNotFoundError("billing", billing_id)

    if ctx.role == UserRole.CUSTOMER:
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
) -> dict[str, Any]:
    """Waive all storage fees on a billing record.

    Removes the misc_charge rows created by the daily storage-fee job and
    resets the log entries so the scheduler will not re-accrue them. Returns
    the refreshed billing record so the UI can update totals immediately.

    Roles allowed: tenant_admin, nigeria_office_staff (checked in handler).
    """
    billing = repo.get_billing_by_id(tenant_id, billing_id)
    if not billing:
        raise ResourceNotFoundError("billing", billing_id)

    payment_status = billing.get("payment_status") or billing.get("status")
    if payment_status in {"cancelled", "waived"}:
        raise BusinessRuleViolationError(
            f"Cannot waive storage fees on a billing record with status '{payment_status}'.",
            rule_id="BILLING_NOT_WAIVEABLE",
        )

    updated = repo.waive_storage_fees_for_billing(tenant_id, billing_id, actor_id, reason)
    if not updated:
        raise ResourceNotFoundError("billing", billing_id)

    log_audit(
        tenant_id=tenant_id,
        entity_type="billing",
        entity_id=billing_id,
        action="WAIVE_STORAGE_FEES",
        actor_id=actor_id,
        actor_role="staff",
        before_state={"storage_fees_ngn": str(billing.get("storage_fees_ngn", 0))},
        after_state={"storage_fees_ngn": "0", "reason": reason},
        ip_address=ip_address,
    )

    return _enrich_billing(tenant_id, dict(updated))


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
    if ctx is not None and ctx.role == UserRole.CUSTOMER:
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


def generate_billing(
    tenant_id: str,
    body: dict[str, Any],
    actor_id: str,
    ctx: Any,
) -> dict[str, Any]:
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


def apply_carryover(
    tenant_id: str,
    billing_id: str,
    carryover_id: str,
    actor_id: str,
    ip_address: str | None = None,
) -> dict[str, Any]:
    """Manually apply an outstanding carryover to a billing record.

    Guards:
      - Billing must exist and not be cancelled or waived.
      - Carryover must be 'outstanding' and belong to the same customer as the billing.
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

    carryover_amount = Decimal(str(carryover["carryover_amount_ngn"]))

    # Apply: mark carryover as applied, add amount to billing total
    repo.mark_carryovers_applied(tenant_id, [carryover_id], billing_id)
    updated = repo.increment_billing_misc_fees(tenant_id, billing_id, carryover_amount)
    if updated is None:
        raise RuntimeError("increment_billing_misc_fees returned None unexpectedly")

    # Adding carried-forward debt raises the total, so the balance (a generated
    # column) grows — recompute the money status from it so a previously 'paid'
    # record doesn't stay 'paid' while now owing more. Only the four money
    # statuses are recomputed; 'released_with_outstanding' is a release state
    # left untouched ('cancelled'/'waived' are already blocked above).
    if billing["status"] in {"unpaid", "partially_paid", "paid", "overpaid"}:
        new_balance = Decimal(str(updated["balance_ngn"]))
        paid = Decimal(str(updated["amount_paid_ngn"]))
        if abs(new_balance) <= _CARRYOVER_TOLERANCE:
            new_status = "paid"
        elif new_balance < -_CARRYOVER_TOLERANCE:
            new_status = "overpaid"
        elif paid > 0:
            new_status = "partially_paid"
        else:
            new_status = "unpaid"
        if new_status != billing["status"]:
            restatused = repo.set_billing_status(tenant_id, billing_id, new_status)
            if restatused is not None:
                updated = restatused

    log_audit(
        tenant_id=tenant_id,
        entity_type="billing",
        entity_id=billing_id,
        action="APPLY_CARRYOVER",
        actor_id=actor_id,
        actor_role=str(UserRole.TENANT_ADMIN),
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
) -> dict[str, Any]:
    """Void an unpaid billing record.

    Guards:
      - Billing must be in 'unpaid' status (no partial/full payments).
      - No active (non-terminal) release notes may reference this billing.
    """
    billing = repo.get_billing_by_id(tenant_id, billing_id)
    if not billing:
        raise ResourceNotFoundError("billing", billing_id)

    if billing["status"] != "unpaid":
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

    updated = repo.cancel_billing(tenant_id, billing_id, actor_id, cancel_reason)
    if not updated:
        raise ResourceNotFoundError("billing", billing_id)

    log_audit(
        tenant_id=tenant_id,
        entity_type="billing",
        entity_id=billing_id,
        action="CANCEL",
        actor_id=actor_id,
        actor_role=str(UserRole.TENANT_ADMIN),
        before_state={"status": billing["status"]},
        after_state={"status": "cancelled", "cancel_reason": cancel_reason},
        ip_address=ip_address,
    )

    return dict(updated)


# ---------------------------------------------------------------------------
# Top-level dispute listing / management
# ---------------------------------------------------------------------------


def list_disputes(
    tenant_id: str,
    filters: dict[str, Any],
    limit: int,
    cursor: dict[str, Any] | None,
) -> tuple[list[dict[str, Any]], str | None, bool]:
    """Top-level paginated list of all disputes for a tenant."""
    rows, next_cursor, has_more = repo.list_all_disputes(tenant_id, filters, limit, cursor)
    return [_fmt_dispute(r) for r in rows], next_cursor, has_more


# Keep old name as alias for backwards compatibility
list_all_disputes = list_disputes


def create_dispute(
    tenant_id: str,
    body: dict[str, Any],
    actor_id: str,
    ctx: Any,
    request_id: str = "",
) -> dict[str, Any]:
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
    ctx: Any,
) -> dict[str, Any]:
    """Reject a CBM dispute."""
    dispute = repo.get_cbm_dispute_by_id(tenant_id, dispute_id)
    if not dispute:
        raise ResourceNotFoundError("cbm_dispute", dispute_id)
    updated = repo.set_dispute_status(tenant_id, dispute_id, "rejected", {"resolution_notes": reason, "resolved_by": actor_id})
    if updated is None:
        raise RuntimeError("set_dispute_status returned None unexpectedly")

    # Ground-truth gap found while auditing log coverage: every other
    # dispute-status transition (acknowledge/escalate/resolve) logs this —
    # reject was the one silently missing.
    log_audit(
        tenant_id=tenant_id,
        entity_type="cbm_dispute",
        entity_id=dispute_id,
        action="STATUS_CHANGE",
        actor_id=actor_id,
        actor_role=str(ctx.role),
        before_state={"status": dispute["status"]},
        after_state={"status": "rejected", "resolution_notes": reason},
    )
    return _fmt_dispute(updated)


def escalate_dispute(
    tenant_id: str,
    dispute_id: str,
    ctx: Any,
) -> dict[str, Any]:
    """Escalate a CBM dispute."""
    dispute = repo.get_dispute_by_id(tenant_id, dispute_id)
    if not dispute:
        raise ResourceNotFoundError("cbm_dispute", dispute_id)
    updated = repo.update_dispute_status(tenant_id, dispute_id, "escalated", {})
    if updated is None:
        raise RuntimeError("update_dispute_status returned None unexpectedly")
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
    req: Any,
    actor_id: str,
    ctx: Any,
    request_id: str = "",
) -> dict[str, Any]:
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
            raise InsufficientPermissionsError("Customers may only dispute their own billing records")

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
    if ctx.role == UserRole.CUSTOMER:
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
        raise RuntimeError("set_dispute_acknowledged returned None unexpectedly")
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

        cbm_rate_usd = Decimal(str(billing["cbm_rate_usd"]))
        exchange_rate = Decimal(str(billing["exchange_rate_ngn"]))

        new_cbm = Decimal(str(req.corrected_cbm))
        new_subtotal_usd = (new_cbm * cbm_rate_usd).quantize(Decimal("0.01"), ROUND_HALF_UP)
        new_subtotal_ngn = (new_subtotal_usd * exchange_rate).quantize(Decimal("0.01"), ROUND_HALF_UP)
        delta_ngn = new_subtotal_ngn - Decimal(str(billing["subtotal_ngn"]))
        new_total_ngn = (Decimal(str(billing["total_ngn"])) + delta_ngn).quantize(Decimal("0.01"), ROUND_HALF_UP)

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
                        "tenant_id": tenant_id,
                        "customer_id": str(billing["customer_id"]),
                        "billing_id": str(billing["id"]),
                        "amount_ngn": overpayment,
                        "reason": f"CBM dispute overpayment — dispute {dispute_id}",
                    },
                )
            except Exception:
                logger.exception("Failed to create overpayment refund for dispute %s", dispute_id)

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

        extra["agreed_cbm"] = new_cbm

    if is_terminal:
        extra["resolution_notes"] = req.resolution_notes
        extra["resolved_by"] = actor_id
        extra["resolved_at"] = datetime.now(UTC)

    updated = repo.set_dispute_status(tenant_id, dispute_id, target, extra)
    if updated is None:
        raise RuntimeError("set_dispute_status returned None unexpectedly")

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
