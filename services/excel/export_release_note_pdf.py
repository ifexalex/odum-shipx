"""Generate a branded A4 release note PDF using reportlab.

Layout:
  - Header strip (brand colour): company name  |  QR code (top-right)
  - Title: "RELEASE NOTE"
  - Reference badge
  - Meta block: Customer, Phone, Container, Payment Ref, Carton Count, Status,
    Valid From, plus (when present on the note) Warehouse, Document No.,
    Invoice No(s)., Cartons Balance, and either ON CREDIT / granted-by or the
    Amount Paid / Balance Outstanding / Receipt No. — mirrors the field
    completeness of PrintReleaseNote.tsx.
  - Signature block: 4 named lines (Customer's Rep, Customer Service Officer,
    Accounting Officer, Warehouse Attendant), matching the paper form.
  - Footer, including the "goods must be confirmed before leaving" disclaimer.
"""
from datetime import datetime
from io import BytesIO
from typing import Any


def _qr_image(data: str, size_cm: float) -> Any:
    """Return a reportlab Flowable that renders a QR code for *data*."""
    from reportlab.graphics.barcode.qr import QrCodeWidget
    from reportlab.graphics.shapes import Drawing
    from reportlab.lib.units import cm

    size_pt = size_cm * cm
    qr = QrCodeWidget(data)
    bounds = qr.getBounds()
    qr_w = bounds[2] - bounds[0]
    qr_h = bounds[3] - bounds[1]
    scale = size_pt / max(qr_w, qr_h)

    # The transform must be set on the Drawing, not the widget — QrCodeWidget
    # has no settable `transform` attribute (reportlab's AttrMap validation
    # rejects it), which was silently crashing every release-note PDF export.
    drawing = Drawing(size_pt, size_pt)
    drawing.transform = [scale, 0, 0, scale, 0, 0]
    drawing.add(qr)
    return drawing


def build_meta_pairs(note: dict[str, Any]) -> list[tuple[str, str]]:
    """Return the ordered (label, value) pairs shown in the PDF's meta block.

    Pure/reportlab-free so the field-completeness logic — which fields from
    get_release_note_for_pdf's join actually reach the document — is directly
    unit-testable without rendering a PDF.
    """
    customer_name = str(note.get("customer_name") or "")
    container_number = str(note.get("container_number") or "")
    billing_ref = str(note.get("billing_reference") or note.get("billing_id") or "")
    carton_count = str(note.get("carton_count") or "")
    status = str(note.get("status") or "active").replace("_", " ").title()
    created_raw = note.get("created_at")
    if isinstance(created_raw, datetime):
        valid_from = created_raw.strftime("%d %B %Y")
    else:
        valid_from = str(created_raw or datetime.utcnow().strftime("%d %B %Y"))

    # Ground-truth gap found live, audited against a real paper "Goods
    # Release Note": get_release_note_for_pdf's query already joins every
    # one of these — customer phone, warehouse name/address/city/state, the
    # billing totals, payment status, receipt number — plus rn.* gives
    # is_on_credit/credit_granted_by_name/physical_document_number/
    # packing_list_invoice_numbers/packages_balance for free. None of it
    # ever reached the PDF; only 7 of the ~20 available fields were read.
    customer_phone = str(note.get("customer_phone") or "")
    warehouse_name = str(note.get("warehouse_name") or "")
    warehouse_address = str(note.get("warehouse_address") or "")
    warehouse_city = str(note.get("warehouse_city") or "")
    warehouse_state = str(note.get("warehouse_state") or "")
    warehouse_line = ", ".join(p for p in (warehouse_name, warehouse_address, warehouse_city, warehouse_state) if p)
    physical_document_number = str(note.get("physical_document_number") or "")
    packing_list_invoice_numbers = ", ".join(note.get("packing_list_invoice_numbers") or [])
    packages_balance = note.get("packages_balance")
    is_on_credit = bool(note.get("is_on_credit", False))
    credit_granted_by_name = str(note.get("credit_granted_by_name") or "")
    receipt_number = str(note.get("receipt_number") or "")
    amount_paid_ngn = note.get("billing_amount_paid_ngn")
    balance_ngn = note.get("billing_balance_ngn")
    total_ngn = note.get("billing_total_ngn")

    meta_pairs = [
        ("Customer", customer_name),
        ("Phone", customer_phone),
        ("Container", container_number),
        ("Payment Reference", billing_ref),
        ("Carton Count", carton_count),
        ("Status", status),
        ("Valid From", valid_from),
    ]
    if warehouse_line:
        meta_pairs.append(("Warehouse", warehouse_line))
    if physical_document_number:
        meta_pairs.append(("Document No.", physical_document_number))
    if packing_list_invoice_numbers:
        meta_pairs.append(("Invoice No(s).", packing_list_invoice_numbers))
    if packages_balance:
        meta_pairs.append(("Cartons Balance", str(packages_balance)))
    if is_on_credit:
        meta_pairs.append(("Payment Status", f"ON CREDIT — granted by {credit_granted_by_name}"))
        if receipt_number:
            meta_pairs.append(("Receipt No.", receipt_number))
    elif amount_paid_ngn is not None or balance_ngn is not None:
        meta_pairs.append(("Amount Paid", f"NGN {amount_paid_ngn or '0.00'} of NGN {total_ngn or '0.00'}"))
        if balance_ngn and str(balance_ngn) != "0.00":
            meta_pairs.append(("Balance Outstanding", f"NGN {balance_ngn}"))
        if receipt_number:
            meta_pairs.append(("Receipt No.", receipt_number))
    return meta_pairs


def generate_release_note_pdf(
    branding: dict[str, Any],
    note: dict[str, Any],
) -> BytesIO:
    """Return a BytesIO buffer containing the branded release note PDF."""
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
    from reportlab.lib.units import cm
    from reportlab.platypus import (
        HRFlowable,
        Paragraph,
        SimpleDocTemplate,
        Spacer,
        Table,
        TableStyle,
    )

    company_name: str = branding.get("company_display_name") or branding.get("company_name") or "ShipX"
    brand_color_hex: str = branding.get("primary_color") or "#1a56db"
    try:
        brand_color = colors.HexColor(brand_color_hex)
    except Exception:
        brand_color = colors.HexColor("#1a56db")

    buf = BytesIO()
    doc = SimpleDocTemplate(
        buf,
        pagesize=A4,
        leftMargin=1.5 * cm,
        rightMargin=1.5 * cm,
        topMargin=1.5 * cm,
        bottomMargin=1.5 * cm,
    )
    styles = getSampleStyleSheet()
    page_width = A4[0] - 3 * cm  # usable width after margins

    company_style = ParagraphStyle(
        "company",
        parent=styles["Heading1"],
        textColor=colors.white,
        fontSize=16,
        leading=20,
    )
    title_style = ParagraphStyle(
        "rntitle",
        parent=styles["Heading2"],
        textColor=colors.HexColor("#111827"),
        fontSize=14,
        spaceAfter=4,
    )
    ref_style = ParagraphStyle(
        "ref",
        parent=styles["Normal"],
        textColor=brand_color,
        fontSize=11,
        fontName="Helvetica-Bold",
        spaceAfter=10,
    )
    meta_key_style = ParagraphStyle(
        "mk",
        parent=styles["Normal"],
        fontSize=9,
        textColor=colors.HexColor("#6b7280"),
    )
    meta_val_style = ParagraphStyle(
        "mv",
        parent=styles["Normal"],
        fontSize=9,
        fontName="Helvetica-Bold",
        textColor=colors.HexColor("#111827"),
    )
    footer_style = ParagraphStyle(
        "footer",
        parent=styles["Normal"],
        fontSize=8,
        textColor=colors.HexColor("#6b7280"),
        alignment=1,
    )
    sig_label_style = ParagraphStyle(
        "siglabel",
        parent=styles["Normal"],
        fontSize=8,
        textColor=colors.HexColor("#9ca3af"),
    )

    reference_number = str(note.get("reference_number") or str(note.get("id") or ""))
    qr_data = f"RELEASE:{reference_number}"
    qr_size = 3.5  # cm

    # Header table: company name (left) | QR code (right)
    qr_flowable = _qr_image(qr_data, qr_size)
    header_data = [[Paragraph(company_name, company_style), qr_flowable]]
    header_table = Table(
        header_data,
        colWidths=[page_width - (qr_size * cm) - 0.5 * cm, qr_size * cm],
        rowHeights=[qr_size * cm],
    )
    header_table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, -1), brand_color),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("LEFTPADDING", (0, 0), (0, -1), 10),
                ("RIGHTPADDING", (-1, 0), (-1, -1), 6),
                ("TOPPADDING", (0, 0), (-1, -1), 6),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
            ]
        )
    )

    # Meta table: two-column key/value pairs
    meta_rows = [[Paragraph(k, meta_key_style), Paragraph(v, meta_val_style)] for k, v in build_meta_pairs(note)]
    meta_table = Table(
        meta_rows,
        colWidths=[4.0 * cm, page_width - 4.0 * cm],
    )
    meta_table.setStyle(
        TableStyle(
            [
                ("TOPPADDING", (0, 0), (-1, -1), 3),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
                ("ROWBACKGROUNDS", (0, 0), (-1, -1), [colors.white, colors.HexColor("#f9fafb")]),
                ("LINEBELOW", (0, -1), (-1, -1), 0.5, colors.HexColor("#e5e7eb")),
            ]
        )
    )

    # Signature block: four named lines matching the paper form (parity with
    # PrintReleaseNote.tsx — Customer's Rep, CSO, Accounting Officer, Warehouse
    # Attendant — rather than the previous three generic "Authorized Signature"
    # columns that named no one).
    sig_labels = [
        "Customer's Rep — name, signature & date",
        "Customer Service Officer — name, signature & date",
        "Accounting Officer — name, signature & date",
        "Warehouse Attendant — name, signature & date",
    ]
    sig_rows = []
    for label in sig_labels:
        sig_rows.append([HRFlowable(width="100%", thickness=0.5, color=colors.HexColor("#9ca3af"))])
        sig_rows.append([Paragraph(label, sig_label_style)])
        sig_rows.append([Spacer(1, 0.4 * cm)])
    sig_table = Table(sig_rows, colWidths=[page_width])
    sig_table.setStyle(
        TableStyle(
            [
                ("TOPPADDING", (0, 0), (-1, -1), 2),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
            ]
        )
    )

    elements = [
        header_table,
        Spacer(1, 0.5 * cm),
        Paragraph("RELEASE NOTE", title_style),
        Paragraph(f"Reference: {reference_number}", ref_style),
        meta_table,
        Spacer(1, 1.2 * cm),
        sig_table,
        Spacer(1, 0.8 * cm),
        HRFlowable(width="100%", thickness=0.5, color=colors.HexColor("#d1d5db")),
        Spacer(1, 0.2 * cm),
        Paragraph(
            "This release note is valid only for the above-mentioned goods. "
            "Please present it at the warehouse to collect your cartons.",
            footer_style,
        ),
        Spacer(1, 0.2 * cm),
        Paragraph(
            "<b>All goods released must be confirmed by the customer before leaving our "
            "warehouse — management will not be held responsible for any shortage or "
            "damage thereafter.</b>",
            footer_style,
        ),
    ]

    doc.build(elements)
    buf.seek(0)
    return buf
