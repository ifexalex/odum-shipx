"""Generate a branded A4 cash receipt PDF using reportlab.

Mirrors export_release_note_pdf.py's layout:
  - Header strip (brand colour): company name  |  QR code (top-right)
  - Title: "CASH RECEIPT"
  - Receipt number badge
  - Meta block: Payer, Amount, Payment Method, Bank/Cheque, Warehouse, Date
  - Amount-in-words line ("Being payment of...")
  - Signature block
  - Footer
"""
from datetime import date, datetime
from decimal import Decimal
from io import BytesIO
from typing import Any

from .naira_words import naira_amount_to_words


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
    # rejects it), which was silently crashing every receipt PDF export.
    drawing = Drawing(size_pt, size_pt)
    drawing.transform = [scale, 0, 0, scale, 0, 0]
    drawing.add(qr)
    return drawing


def generate_receipt_pdf(
    branding: dict[str, Any],
    payment: dict[str, Any],
) -> BytesIO:
    """Return a BytesIO buffer containing the branded cash receipt PDF."""
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
        "rctitle",
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
    words_style = ParagraphStyle(
        "words",
        parent=styles["Normal"],
        fontSize=10,
        fontName="Helvetica-Oblique",
        textColor=colors.HexColor("#111827"),
        spaceAfter=6,
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

    receipt_number = str(payment.get("receipt_number") or str(payment.get("id") or ""))
    payer_name = str(payment.get("payer_name") or payment.get("customer_name") or "")
    amount_ngn = Decimal(str(payment.get("amount_ngn") or "0"))
    payment_method = str(payment.get("payment_method") or "").replace("_", " ").title()
    bank_name = str(payment.get("bank_name") or "")
    cheque_number = str(payment.get("cheque_number") or "")
    warehouse_name = str(payment.get("warehouse_name") or "")
    billing_reference = str(payment.get("billing_reference") or payment.get("billing_id") or "")

    payment_date_raw = payment.get("payment_date")
    if isinstance(payment_date_raw, date | datetime):
        payment_date_str = payment_date_raw.strftime("%d %B %Y")
    else:
        payment_date_str = str(payment_date_raw or datetime.utcnow().strftime("%d %B %Y"))

    qr_data = f"RECEIPT:{receipt_number}"
    qr_size = 3.5  # cm

    header_data = [[Paragraph(company_name, company_style), _qr_image(qr_data, qr_size)]]
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

    meta_pairs = [
        ("Payer", payer_name),
        ("Amount (NGN)", f"{amount_ngn:,.2f}"),
        ("Payment Method", payment_method),
        ("Bank Name", bank_name),
        ("Cheque No", cheque_number),
        ("Warehouse", warehouse_name),
        ("Payment Reference", billing_reference),
        ("Date", payment_date_str),
    ]
    meta_rows = [[Paragraph(k, meta_key_style), Paragraph(v, meta_val_style)] for k, v in meta_pairs if v]
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

    amount_words = naira_amount_to_words(amount_ngn)

    sig_line = HRFlowable(width="100%", thickness=0.5, color=colors.HexColor("#9ca3af"), spaceAfter=2)
    sig_data = [
        [sig_line, sig_line],
        [
            Paragraph("Authorized Signature", sig_label_style),
            Paragraph("Name (Print)", sig_label_style),
        ],
    ]
    col_w = page_width / 2
    sig_table = Table(sig_data, colWidths=[col_w, col_w])
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
        Paragraph("CASH RECEIPT", title_style),
        Paragraph(f"Receipt No: {receipt_number}", ref_style),
        meta_table,
        Spacer(1, 0.5 * cm),
        Paragraph(f"Being payment of: {amount_words}", words_style),
        Spacer(1, 1.0 * cm),
        sig_table,
        Spacer(1, 0.8 * cm),
        HRFlowable(width="100%", thickness=0.5, color=colors.HexColor("#d1d5db")),
        Spacer(1, 0.2 * cm),
        Paragraph(
            "This receipt confirms payment received as stated above. Please retain for your records.",
            footer_style,
        ),
    ]

    doc.build(elements)
    buf.seek(0)
    return buf
