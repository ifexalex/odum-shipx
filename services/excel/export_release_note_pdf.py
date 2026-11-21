"""The release note PDF (audit FD-40, FD-41, FD-42): the one release-note document, built on ``pdf_theme``.

Contents: reference, issue date and valid-until date; customer and phone; container; cartons authorised and whether
the release is partial; every carton tag with a box to tick as it is collected; payment status and amounts; the pickup
address; a QR code; four signature lines; the terms.

The QR code holds the bare reference (owner decision, 2026-11-21): the warehouse screen's lookup takes exactly what a
scanner types, so scanning the printed note opens it. It used to hold ``RELEASE:{reference}``, which found nothing.
"""

from collections.abc import Sequence
from io import BytesIO
from typing import Any

from reportlab.lib.units import cm
from reportlab.platypus import Spacer, Table

from . import pdf_theme as t

TERMS = (
    "This release note authorises collection of the goods listed above only, until the valid-until date.",
    "All goods released must be checked by the customer before leaving the warehouse. Management will not be held "
    "responsible for any shortage or damage thereafter.",
)

SIGNATURES = (
    "Customer or representative: name, signature, date",
    "Customer service officer: name, signature, date",
    "Accounting officer: name, signature, date",
    "Warehouse attendant: name, signature, date",
)


def qr_payload(note: dict[str, Any]) -> str:
    """What the QR code holds: the bare reference, as the warehouse scanner looks it up."""
    return str(note.get("reference_number") or note.get("id") or "")


def build_meta_pairs(note: dict[str, Any]) -> list[tuple[str, str]]:
    """The note's facts in print order. Pure, so which fields reach the document is testable without rendering."""
    warehouse_line = ", ".join(
        str(note[key]) for key in ("warehouse_name", "warehouse_address", "warehouse_city", "warehouse_state") if note.get(key)
    )
    cartons = t.count(note.get("carton_count") or note.get("total_cartons"))
    if note.get("is_partial"):
        cartons = f"{cartons} (partial release)"
    pairs: list[tuple[str, str]] = [
        ("Customer", str(note.get("customer_name") or t.MISSING)),
        ("Phone", str(note.get("customer_phone") or t.MISSING)),
        ("Container", str(note.get("container_number") or t.MISSING)),
        ("Invoice", str(note.get("billing_reference") or t.MISSING)),
        ("Cartons authorised", cartons),
    ]
    if warehouse_line:
        pick_up = warehouse_line + (f" · {note['warehouse_phone']}" if note.get("warehouse_phone") else "")
        pairs.append(("Pick up at", pick_up))
    if note.get("physical_document_number"):
        pairs.append(("Document no.", str(note["physical_document_number"])))
    invoice_numbers = ", ".join(note.get("packing_list_invoice_numbers") or [])
    if invoice_numbers:
        pairs.append(("Packing list invoices", invoice_numbers))
    if note.get("packages_balance"):
        pairs.append(("Cartons still to collect", t.count(note["packages_balance"])))

    if note.get("is_on_credit"):
        pairs.append(("Payment status", f"On credit, granted by {note.get('credit_granted_by_name') or 'staff'}"))
    elif note.get("billing_amount_paid_ngn") is not None or note.get("billing_balance_ngn") is not None:
        pairs.append(("Payment status", t.humanise(note.get("payment_status"))))
        pairs.append(
            (
                "Amount paid",
                f"{t.money(note.get('billing_amount_paid_ngn') or 0)} of {t.money(note.get('billing_total_ngn') or 0)}",
            )
        )
        balance = note.get("billing_balance_ngn")
        if balance is not None and float(balance) > 0:
            pairs.append(("Balance outstanding", t.money(balance)))
    if note.get("receipt_number"):
        pairs.append(("Receipt no.", str(note["receipt_number"])))
    return pairs


def _tags_table(tags: Sequence[str], brand_color: str) -> Table:
    """Every authorised carton tag, with an empty box the attendant ticks as it leaves."""
    table = t.DataTable(
        [t.Column("#", 0.6, "right"), t.Column("Carton tag", 6.0), t.Column("Collected", 1.4)],
        [[str(i), tag, ""] for i, tag in enumerate(tags, start=1)],
        brand=brand_color,
        zebra=False,
    ).build()
    # A drawn box in the last column (the fonts carry no ballot-box glyph).
    table.setStyle(t.TableStyle([("BOX", (2, i), (2, i), 0.6, t.INK_3) for i in range(1, len(tags) + 1)]))
    return table


def generate_release_note_pdf(brand: t.Brand, note: dict[str, Any]) -> BytesIO:
    """Render the release note.

    Args:
        brand: The tenant's branding (``pdf_theme.Brand``).
        note: The release note row as ``get_release_note_for_pdf`` returns it.
    """
    reference = qr_payload(note)
    tags = [str(tag) for tag in (note.get("carton_tags") or [])]
    scan = Table(
        [[t.qr_code(reference), [t.para("Scan at the warehouse counter", "small"), t.para(reference, "value")]]],
        colWidths=[3.0 * cm, t.CONTENT_WIDTH - 3.0 * cm],
    )
    scan.setStyle(t.TableStyle([("VALIGN", (0, 0), (-1, -1), "MIDDLE"), ("LEFTPADDING", (0, 0), (-1, -1), 0)]))
    body = [
        t.facts_grid(build_meta_pairs(note), columns=2),
        *t.section(f"Cartons ({t.count(len(tags))})" if tags else "Cartons"),
        _tags_table(tags, brand.color) if tags else t.para("No carton tags recorded on this note.", "small"),
        Spacer(1, 0.4 * cm),
        scan,
        *t.section("Signatures"),
        t.signature_lines(SIGNATURES),
        *t.section("Terms"),
        *[t.para(term, "small") for term in TERMS],
    ]
    return t.render(
        brand,
        "Release note",
        reference,
        body,
        facts=[
            ("Issued", t.day(note.get("created_at"))),
            ("Valid until", t.day(note.get("valid_until"))),
            ("Status", t.humanise(note.get("status") or "active")),
        ],
        subject=f"Release note for {note.get('customer_name') or 'a customer'}",
    )
