"""The invoice PDF (audit FD-39, FD-40, FD-41): the customer's invoice, built on ``pdf_theme``.

It replaced a landscape table of database column names ("Cbm Rate Usd", ``released_with_outstanding``, ``2.000000``)
that the generic export produced for "Download invoice".

Contents: invoice number, issue date and status; the customer and phone; container, cartons and total CBM; line items
(shipping as CBM × rate at the exchange rate, each extra charge, storage fees, carryover from earlier invoices, credits);
total due, paid and outstanding; how to pay.
"""

from collections.abc import Sequence
from decimal import Decimal
from io import BytesIO
from typing import Any

from . import pdf_theme as t


def _decimal(value: object) -> Decimal:
    return Decimal(str(value or 0))


def shipping_detail(billing: dict[str, Any]) -> str:
    """How the shipping line was worked out: "2.500 CBM × $45.00 per CBM × ₦1,550 per $"."""
    # cbm_rate_usd is always the dollar figure (a tenant pricing in naira has it converted at billing), and
    # subtotal_ngn is CBM × that rate × the exchange rate, so this line always adds up.
    volume = f"{t.cbm(billing.get('total_cbm'))} CBM"
    rate = f"{t.usd(billing.get('cbm_rate_usd'))} per CBM"
    exchange = billing.get("exchange_rate_ngn")
    return f"{volume} × {rate}" + (f" × {t.money(exchange)} per $" if exchange not in (None, "") else "")


def line_items(billing: dict[str, Any], charges: Sequence[dict[str, Any]]) -> list[list[str]]:
    """The invoice's lines: what was charged, how, and how much."""
    lines = [["Shipping", shipping_detail(billing), t.money(billing.get("subtotal_ngn"))]]
    lines += [
        [str(charge.get("description") or "Charge"), "Extra charge", t.money(charge.get("amount_ngn"))] for charge in charges
    ]
    if _decimal(billing.get("storage_fees_ngn")) > 0:
        lines.append(["Storage fees", "Days stored past the free period", t.money(billing.get("storage_fees_ngn"))])
    if _decimal(billing.get("carryover_ngn")) > 0:
        lines.append(["Carried over", "Unpaid balance from an earlier invoice", t.money(billing.get("carryover_ngn"))])
    if _decimal(billing.get("credits_applied_ngn")) > 0:
        lines.append(
            ["Credit applied", "Credit you held, taken off this invoice", t.money(-_decimal(billing.get("credits_applied_ngn")))]
        )
    return lines


def how_to_pay(billing: dict[str, Any], bank: dict[str, Any] | None, online: bool, brand: t.Brand) -> list[str]:
    """Payment instructions, from the tenant's own bank details and gateway; never invented."""
    reference = str(billing.get("invoice_number") or "")
    lines: list[str] = []
    if bank and bank.get("account_number"):
        account = " · ".join(str(bank[key]) for key in ("bank_name", "account_name", "account_number") if bank.get(key))
        lines.append(f"Bank transfer: {account}" + (f" (sort code {bank['sort_code']})" if bank.get("sort_code") else ""))
        lines.append(str(bank.get("instructions") or f"Use {reference} as the payment description."))
    if online:
        lines.append("Card or bank payment online: open this invoice in your account and choose Pay.")
    if not lines:
        contact = " or ".join(p for p in (brand.phone, brand.email) if p)
        lines.append(f"Contact us to pay{f': {contact}' if contact else ''}. Quote {reference}.")
    return lines


def generate_invoice_pdf(
    brand: t.Brand,
    billing: dict[str, Any],
    charges: Sequence[dict[str, Any]],
    bank: dict[str, Any] | None = None,
    online: bool = False,
) -> BytesIO:
    """Render the invoice.

    Args:
        brand: The tenant's branding (``pdf_theme.Brand``).
        billing: The billing row as ``get_billing_for_export`` returns it.
        charges: Its extra charges (description, amount).
        bank: The tenant's ``bank_transfer_config``, if set.
        online: Whether the tenant takes payment online (Paystack).
    """
    reference = str(billing.get("invoice_number") or billing.get("id") or "")
    outstanding = _decimal(billing.get("balance_ngn"))
    cancelled = str(billing.get("status") or "") == "cancelled" or bool(billing.get("cancelled_at"))
    body = [
        t.facts_grid(
            [
                ("Bill to", str(billing.get("customer_name") or t.MISSING)),
                ("Phone", str(billing.get("customer_phone") or t.MISSING)),
                ("Container", str(billing.get("container_number") or t.MISSING)),
                ("Cartons", t.count(billing.get("total_cartons"))),
                ("Total CBM", t.cbm(billing.get("total_cbm"))),
                *([("Due", t.day(billing["due_date"]))] if billing.get("due_date") else []),
            ]
        ),
        *t.section("Charges"),
        t.DataTable(
            [t.Column("Item", 2.2), t.Column("Detail", 4.6), t.Column("Amount", 1.6, "right")],
            line_items(billing, charges),
            brand=brand.color,
        ).build(),
        t.summary_lines(
            [
                ("Total due", t.money(billing.get("total_ngn"))),
                ("Paid", t.money(billing.get("amount_paid_ngn") or 0)),
                ("Outstanding", t.money(max(outstanding, Decimal(0)))),
            ],
            emphasise=("Total due",) + (() if outstanding > 0 else ("Outstanding",)),
            alarm=("Outstanding",) if outstanding > 0 and not cancelled else (),
        ),
    ]
    if cancelled:
        body += [*t.section("Cancelled"), t.para(str(billing.get("cancel_reason") or "This invoice was cancelled."), "body")]
    elif outstanding > 0:
        body += [*t.section("How to pay"), *[t.para(line, "body") for line in how_to_pay(billing, bank, online, brand)]]
    return t.render(
        brand,
        "Invoice",
        reference,
        body,
        facts=[
            ("Issued", t.day(billing.get("billed_at") or billing.get("created_at"))),
            ("Status", t.humanise(billing.get("status"))),
        ],
        subject=f"Invoice for {billing.get('customer_name') or 'a customer'}",
    )
