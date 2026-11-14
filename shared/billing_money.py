"""Changing what an invoice owes, in one place.

Every operation that moves an invoice's total (a misc charge, an applied
carryover, a storage fee, a corrected CBM, a refund that reduces what is owed)
has to do three things together: change the total, keep the stored status
honest, and notice when the customer is now owed money. Before this module each
call site did the first and left the others to chance, so a `paid` invoice that
gained a charge stayed `paid` while owing, and a reduction that left the customer
overpaid created no refund.

These helpers are built on `execute_write_with_tenant`, so inside a
`shared.db.tenant_transaction` block they join that transaction and commit or
roll back with everything else in it.
"""

from decimal import Decimal
from typing import Any

from shared.db import execute_with_tenant, execute_write_with_tenant

#: Sub-kobo noise treated as settled, matching the payment path.
TOLERANCE = Decimal("0.01")

#: Statuses that are *computed from the balance*. Others (`waived`, `cancelled`,
#: `released_with_outstanding`) are decisions a person made and are left alone.
MONEY_STATUSES = ("unpaid", "partially_paid", "paid", "overpaid")


def lock_billing(tenant_id: str, billing_id: str) -> dict[str, Any] | None:
    """Read the invoice and lock its row until the surrounding transaction ends.

    Serialises changes to one invoice, so a check made on the row stays true until
    the transaction finishes.
    """
    rows = execute_with_tenant(
        tenant_id,
        "SELECT * FROM billing WHERE tenant_id = %s AND id = %s FOR UPDATE",
        (tenant_id, billing_id),
    )
    return rows[0] if rows else None


def adjust_billing(
    tenant_id: str,
    billing_id: str,
    total_delta: Decimal,
    misc_delta: Decimal = Decimal("0"),
    tolerance: Decimal = TOLERANCE,
) -> dict[str, Any] | None:
    """Add ``total_delta`` to the invoice total and recompute its status.

    The change is relative (``total_ngn + delta``), so a payment or charge that
    landed after the caller read the row is not overwritten. Status is
    recomputed from the stored amounts for the four money statuses only.

    Args:
        tenant_id: Tenant scope.
        billing_id: Invoice to change.
        total_delta: Amount to add to ``total_ngn``; negative to reduce it.
        misc_delta: Amount to add to ``misc_charges_ngn`` (misc charges, carryovers).
        tolerance: Balance within this of zero counts as settled.

    Returns:
        The updated row (including the generated ``balance_ngn``), or ``None`` if
        the invoice is not in this tenant.
    """
    return execute_write_with_tenant(
        tenant_id,
        """
        UPDATE billing
           SET total_ngn        = total_ngn + %(total_delta)s,
               misc_charges_ngn = misc_charges_ngn + %(misc_delta)s,
               status = CASE
                   WHEN status IN ('unpaid', 'partially_paid', 'paid', 'overpaid') THEN
                       CASE
                           WHEN ABS(total_ngn + %(total_delta)s - amount_paid_ngn) <= %(tol)s THEN 'paid'
                           WHEN total_ngn + %(total_delta)s - amount_paid_ngn < -%(tol)s THEN 'overpaid'
                           WHEN amount_paid_ngn > 0 THEN 'partially_paid'
                           ELSE 'unpaid'
                       END
                   ELSE status
               END,
               updated_at = NOW()
         WHERE tenant_id = %(tenant_id)s AND id = %(id)s
        RETURNING *
        """,
        {
            "tenant_id": tenant_id,
            "id": billing_id,
            "total_delta": total_delta,
            "misc_delta": misc_delta,
            "tol": tolerance,
        },
    )


def new_overpayment(billing_after: dict[str, Any], total_delta: Decimal, tolerance: Decimal = TOLERANCE) -> Decimal:
    """How much *more* the customer is owed because the total moved by ``total_delta``.

    Only the increase counts. An invoice that was already overpaid has its earlier
    excess refunded separately and must not be refunded twice.

    Args:
        billing_after: The row returned by `adjust_billing`.
        total_delta: The delta that produced it.
        tolerance: Increases within this are ignored.

    Returns:
        The new excess, or ``0`` when there is none worth a refund.
    """
    paid = Decimal(str(billing_after["amount_paid_ngn"]))
    total_after = Decimal(str(billing_after["total_ngn"]))
    total_before = total_after - total_delta
    increase = max(paid - total_after, Decimal("0")) - max(paid - total_before, Decimal("0"))
    return increase if increase > tolerance else Decimal("0")


def create_overpayment_refund(
    tenant_id: str,
    billing: dict[str, Any],
    amount_ngn: Decimal,
    reason: str,
) -> dict[str, Any] | None:
    """Open a ``pending_review`` refund request for money the customer overpaid."""
    return execute_write_with_tenant(
        tenant_id,
        """
        INSERT INTO refund_request (tenant_id, customer_id, billing_id, amount_ngn, reason, status)
        VALUES (%(tenant_id)s, %(customer_id)s, %(billing_id)s, %(amount)s, %(reason)s, 'pending_review')
        RETURNING *
        """,
        {
            "tenant_id": tenant_id,
            "customer_id": billing["customer_id"],
            "billing_id": billing["id"],
            "amount": amount_ngn,
            "reason": reason,
        },
    )


def adjust_billing_and_refund_overpayment(
    tenant_id: str,
    billing_id: str,
    total_delta: Decimal,
    reason: str,
    misc_delta: Decimal = Decimal("0"),
) -> tuple[dict[str, Any], Decimal]:
    """`adjust_billing`, plus a refund request if it left the customer newly overpaid.

    Returns:
        ``(updated_invoice, overpayment_refunded)``; the amount is ``0`` when none.

    Raises:
        RuntimeError: The invoice is not in this tenant. Inside a transaction this
            rolls everything back.
    """
    billing = adjust_billing(tenant_id, billing_id, total_delta, misc_delta)
    if billing is None:
        raise RuntimeError(f"billing {billing_id} not found in tenant")
    overpayment = new_overpayment(billing, total_delta)
    if overpayment > 0:
        create_overpayment_refund(tenant_id, billing, overpayment, reason)
    return billing, overpayment
