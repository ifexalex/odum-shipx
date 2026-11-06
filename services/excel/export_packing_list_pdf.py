"""Generate a branded A4 packing list PDF using reportlab.

Layout:
  - Header: company name + "PACKING LIST" title
  - Meta block: Customer, Container, Status, Generated date
  - APPROVED stamp when status in ('approved', 'recorded')
  - Line-item table: Carton Tag | Description | Dispatch kg | Actual kg | CBM | Tracking Code
  - Totals row
"""

from datetime import datetime
from io import BytesIO
from typing import Any


def generate_packing_list_pdf(
    branding: dict[str, Any],
    pl: dict[str, Any],
    items: list[dict[str, Any]],
) -> BytesIO:
    """Return a BytesIO buffer containing the branded packing list PDF."""
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
    from reportlab.lib.units import cm
    from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

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
    company_style = ParagraphStyle(
        "company",
        parent=styles["Heading1"],
        textColor=brand_color,
        fontSize=16,
        spaceAfter=2,
    )
    title_style = ParagraphStyle(
        "title",
        parent=styles["Heading2"],
        textColor=colors.HexColor("#111827"),
        fontSize=12,
        spaceAfter=6,
    )
    meta_style = ParagraphStyle(
        "meta",
        parent=styles["Normal"],
        fontSize=9,
        textColor=colors.HexColor("#374151"),
        spaceAfter=2,
    )
    stamp_style = ParagraphStyle(
        "stamp",
        parent=styles["Normal"],
        fontSize=18,
        textColor=colors.HexColor("#15803d"),
        borderColor=colors.HexColor("#15803d"),
        borderWidth=2,
        borderPadding=4,
        spaceAfter=8,
    )

    status = str(pl.get("status") or "")
    container_number = str(pl.get("container_number") or "")
    customer_name = str(pl.get("customer_name") or "")
    generated = datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC")

    elements = [
        Paragraph(company_name, company_style),
        Paragraph("PACKING LIST", title_style),
        Paragraph(f"Customer: <b>{customer_name}</b>", meta_style),
        Paragraph(f"Container: <b>{container_number}</b>", meta_style),
        Paragraph(f"Status: {status.replace('_', ' ').title()}", meta_style),
        Paragraph(f"Generated: {generated}", meta_style),
    ]

    if status in ("approved", "recorded"):
        elements.append(Spacer(1, 0.3 * cm))
        elements.append(Paragraph("✓  APPROVED", stamp_style))

    elements.append(Spacer(1, 0.4 * cm))

    headers = ["Carton Tag", "Description", "Dispatch\nkg", "Actual\nkg", "CBM", "Tracking Code"]
    col_widths = [2.8 * cm, 6.0 * cm, 1.8 * cm, 1.8 * cm, 1.8 * cm, 4.3 * cm]

    data = [headers]
    total_dispatch = 0.0
    total_actual = 0.0
    total_cbm = 0.0

    for item in items:
        dispatch_kg = float(item.get("weight_dispatch_kg") or 0)
        actual_kg = float(item.get("weight_actual_kg") or 0)
        cbm = float(item.get("cbm") or 0)
        total_dispatch += dispatch_kg
        total_actual += actual_kg
        total_cbm += cbm
        data.append(
            [
                str(item.get("carton_tag") or ""),
                str(item.get("description") or ""),
                f"{dispatch_kg:.2f}",
                f"{actual_kg:.2f}",
                f"{cbm:.4f}",
                str(item.get("tracking_code") or ""),
            ]
        )

    data.append(
        [
            "TOTALS",
            "",
            f"{total_dispatch:.2f}",
            f"{total_actual:.2f}",
            f"{total_cbm:.4f}",
            "",
        ]
    )

    table = Table(data, colWidths=col_widths, repeatRows=1)
    table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), brand_color),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                ("FONTSIZE", (0, 0), (-1, -1), 8),
                ("FONTNAME", (0, -1), (-1, -1), "Helvetica-Bold"),
                ("BACKGROUND", (0, -1), (-1, -1), colors.HexColor("#f3f4f6")),
                ("ROWBACKGROUNDS", (0, 1), (-1, -2), [colors.white, colors.HexColor("#f9fafb")]),
                ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#d1d5db")),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("TOPPADDING", (0, 0), (-1, -1), 4),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
                ("ALIGN", (2, 0), (4, -1), "RIGHT"),
            ]
        )
    )
    elements.append(table)

    doc.build(elements)
    buf.seek(0)
    return buf
