"""The payment receipt PDF (audit FD-40, FD-41): the one receipt document, built on ``pdf_theme``.

Contents: receipt number and date; who paid; the amount in figures and in words; payment method and reference (bank,
cheque number where given); the invoice it pays and the balance left after this payment; who received it.
"""

from decimal import Decimal
from io import BytesIO
from typing import Any

from reportlab.lib.units import cm
from reportlab.platypus import Spacer, Table

from . import pdf_theme as t
from .naira_words import naira_amount_to_words


def generate_receipt_pdf(brand: t.Brand, payment: dict[str, Any]) -> BytesIO:
    """Render the receipt.

    Args:
        brand: The tenant's branding (``pdf_theme.Brand``).
        payment: The payment row as ``get_payment_for_receipt_pdf`` returns it (with ``billing_total_ngn``,
            ``balance_after_ngn`` and ``received_by_name``).
    """
    receipt_number = str(payment.get("receipt_number") or payment.get("id") or "")
    paid = Decimal(str(payment.get("amount_ngn") or "0"))
    payer = str(payment.get("payer_name") or payment.get("customer_name") or t.MISSING)

    amount_block = Table(
        [[t.para("Amount received", "label")], [t.para(t.money(paid), "figure")], [t.para(naira_amount_to_words(paid), "small")]],
        colWidths=[t.CONTENT_WIDTH],
    )
    amount_block.setStyle(
        t.TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, -1), t.SURFACE_MUTED),
                ("LEFTPADDING", (0, 0), (-1, -1), 10),
                ("RIGHTPADDING", (0, 0), (-1, -1), 10),
                ("TOPPADDING", (0, 0), (-1, 0), 8),
                ("BOTTOMPADDING", (0, -1), (-1, -1), 8),
                ("ALIGN", (0, 0), (-1, -1), "LEFT"),
            ]
        )
    )

    payment_facts = [
        ("Received from", payer),
        ("Phone", str(payment.get("customer_phone") or t.MISSING)),
        ("Payment method", t.humanise(payment.get("payment_method"))),
        ("Payment reference", str(payment.get("reference_number") or payment.get("gateway_transaction_id") or t.MISSING)),
    ]
    if payment.get("bank_name"):
        payment_facts.append(("Bank", str(payment["bank_name"])))
    if payment.get("cheque_number"):
        payment_facts.append(("Cheque No.", str(payment["cheque_number"])))
    if payment.get("warehouse_name"):
        payment_facts.append(("Received at", str(payment["warehouse_name"])))
    if payment.get("physical_receipt_number"):
        payment_facts.append(("Paper receipt No.", str(payment["physical_receipt_number"])))

    balance = payment.get("balance_after_ngn")
    summary = [
        ("Invoice", str(payment.get("billing_reference") or t.MISSING)),
        ("Invoice total", t.money(payment.get("billing_total_ngn"))),
        ("This payment", t.money(paid)),
        ("Balance after this payment", t.money(max(Decimal(str(balance)), Decimal(0)) if balance is not None else None)),
    ]
    owing = balance is not None and Decimal(str(balance)) > 0
    body = [
        amount_block,
        Spacer(1, 0.4 * cm),
        t.facts_grid(payment_facts, columns=2),
        *t.section("Applied to"),
        t.summary_lines(
            summary,
            emphasise=() if owing else ("Balance after this payment",),
            alarm=("Balance after this payment",) if owing else (),
        ),
        *t.section("Received by"),
        t.facts_grid([("Name", str(payment.get("received_by_name") or t.MISSING))], columns=2),
        t.signature_lines(["Received by: signature", "Customer: signature"]),
    ]
    return t.render(
        brand,
        "Receipt",
        receipt_number,
        body,
        facts=[("Date", t.day(payment.get("payment_date") or payment.get("created_at")))],
        subject=f"Payment receipt for {payer}",
    )
