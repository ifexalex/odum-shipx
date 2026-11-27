"""Modern bilingual Loading Receipt PDF (ENG-4 / ENG-5, built on ``pdf_theme``).

Visually designed as a distinct **Warehouse Loading Receipt Voucher** — clearly differentiated
from the Packing List with a top brand accent bar, bordered receipt ticket badge (``NO. LR-…``),
two-column framed Consignee / Destination-Warehouse card (showing Country · City · Warehouse +
street address), framed itemized voucher grid retaining full dimensions (``L × W × H cm``),
split verification + highlighted totals/QR ticket strip, compact terms box, and signatures.

Defaults to Chinese (``lang="zh"``) with full English support (``lang="en"``).
"""

from collections.abc import Sequence
from io import BytesIO
from typing import Any, Literal

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_RIGHT
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import cm
from reportlab.platypus import Flowable, Paragraph, Spacer, Table

from . import pdf_theme as t
from .export_packing_list_pdf import format_destination_warehouse

Lang = Literal["zh", "en"]

_STRINGS: dict[Lang, dict[str, Any]] = {
    "zh": {
        "title": "入仓装柜收据",
        "title_secondary": "LOADING RECEIPT",
        "receipt_no_prefix": "NO.",
        "subtitle_ref": "装箱单",
        "issued_at": "签发",
        "party_heading": "客户与收货信息",
        "route_heading": "目的港仓库与装柜",
        "customer": "客户名字",
        "phone": "客户电话",
        "supplier": "供应商",
        "destination": "目的港 / 到达仓库",
        "container": "柜号 / 分单号",
        "tracking_code": "追踪号",
        "delivery_date": "收货日期",
        "loading_date": "装柜日期",
        "col_tag": "编号",
        "col_desc": "货物名称",
        "col_pkg": "包装",
        "col_qty": "数量",
        "col_dims": "尺寸 (cm)",
        "col_cbm": "体积 (CBM)",
        "col_weight": "重量 (kg)",
        "col_delivered": "收货日",
        "col_loaded": "装柜日",
        "summary_heading": "收据汇总",
        "total_packages": "总件数",
        "total_cbm": "总体积",
        "total_weight": "总重量",
        "pkg_unit": "件",
        "remarks_label": "备注 / 压包要求",
        "qr_caption": "扫码查询物流",
        "handling_heading": "仓库经办确认",
        "received_by": "开单收货人",
        "approved_by": "装柜审核人",
        "loaded_time": "装柜确认时间",
        "notice_heading": "请注意以下信息 · Important Notice",
        "notices": [
            "1. 货物入仓须提供准确货物名称、联系方式及目的港，装柜确认后24小时内如无异议即视为确认无误。",
            "2. 严禁夹带仿牌、违禁品、易燃易爆物品，海关查验或扣货产生的一切责任由货主自行承担。",
            "3. 本仓库按外包装件数及尺寸体积 (CBM) 核收，不拆箱清点内件数量，请发货人自行核对。",
            "4. 货物抵达目的港仓库后享有免费仓储期，逾期未提将按规定收取仓储及保管费。",
            "5. 请妥善保管本收据及追踪号，查询物流进度及目的港提货时均需出示。",
        ],
        "sig_sender": "送货人 / 供应商签名",
        "sig_warehouse": "仓库收货人签名",
        "subject_prefix": "入仓装柜收据 -",
        "default_customer": "客户",
    },
    "en": {
        "title": "LOADING RECEIPT",
        "title_secondary": "入仓装柜收据",
        "receipt_no_prefix": "NO.",
        "subtitle_ref": "Packing list",
        "issued_at": "Issued",
        "party_heading": "Consignee & Sender",
        "route_heading": "Destination Warehouse & Load",
        "customer": "Customer",
        "phone": "Phone",
        "supplier": "Supplier",
        "destination": "Destination / Warehouse",
        "container": "Container / Parcel No.",
        "tracking_code": "Tracking code",
        "delivery_date": "Delivery date",
        "loading_date": "Loading date",
        "col_tag": "Tag",
        "col_desc": "Description",
        "col_pkg": "Pkg",
        "col_qty": "Qty",
        "col_dims": "L × W × H cm",
        "col_cbm": "CBM",
        "col_weight": "Weight kg",
        "col_delivered": "Delivered",
        "col_loaded": "Loaded",
        "summary_heading": "Receipt totals",
        "total_packages": "Total packages",
        "total_cbm": "Total CBM",
        "total_weight": "Total weight",
        "pkg_unit": "pkg",
        "remarks_label": "Remarks / Packing instructions",
        "qr_caption": "Scan to track",
        "handling_heading": "Warehouse verification",
        "received_by": "Received by",
        "approved_by": "Verified / Loaded by",
        "loaded_time": "Loaded at",
        "notice_heading": "Important warehouse terms",
        "notices": [
            "1. Please verify item descriptions, dimensions, CBM, and destination warehouse before container sealing.",
            "2. Counterfeit, fragile, flammable, explosive, or contraband goods are shipped strictly at the owner's risk.",
            "3. Cargo is verified by outer package count and measured dimensions (CBM); inner piece counts are not verified.",
            "4. Free storage applies during the arrival grace period; overdue goods attract daily warehouse storage fees.",
            "5. Keep this Loading Receipt and tracking code safe for shipment tracking and dispute resolution.",
        ],
        "sig_sender": "Sender / Supplier Signature",
        "sig_warehouse": "Warehouse Receiver Signature",
        "subject_prefix": "Loading receipt for",
        "default_customer": "a customer",
    },
}


def _dimensions(item: dict[str, Any]) -> str:
    sides = [item.get("length_cm"), item.get("width_cm"), item.get("height_cm")]
    if any(side in (None, "") for side in sides):
        return t.MISSING
    return " × ".join(t.measure(side) for side in sides)


def _sum(items: Sequence[dict[str, Any]], key: str) -> float:
    return sum(float(item.get(key) or 0) for item in items)


def _unique_dates(values: Sequence[Any]) -> list[str]:
    seen: list[str] = []
    for raw in values:
        formatted = t.day(raw)
        if formatted != t.MISSING and formatted not in seen:
            seen.append(formatted)
    return seen


def _date_summary(header_val: Any, item_vals: Sequence[Any]) -> str:
    unique = _unique_dates(item_vals)
    if len(unique) > 1:
        return f"{unique[0]} – {unique[-1]}"
    if len(unique) == 1:
        return unique[0]
    return t.day(header_val)


def _has_varying_dates(items: Sequence[dict[str, Any]], key: str, header_val: Any) -> bool:
    return len(_unique_dates([item.get(key) or header_val for item in items])) > 1


def _effective_brand(brand: t.Brand, lang: Lang) -> t.Brand:
    name = brand.name
    if brand.chinese_name:
        name = f"{brand.chinese_name} · {brand.name}" if lang == "zh" else f"{brand.name} · {brand.chinese_name}"
    return t.Brand(
        name=name,
        tagline=brand.tagline,
        address=brand.china_warehouse_address or brand.address,
        phone=brand.china_warehouse_phone or brand.phone,
        email=brand.email,
        footer=brand.footer,
        color=brand.color,
        logo=brand.logo,
        chinese_name=brand.chinese_name,
        china_warehouse_address=brand.china_warehouse_address,
        china_warehouse_phone=brand.china_warehouse_phone,
    )


def _p(
    text: object,
    *,
    size: float = 8.5,
    bold: bool = False,
    color: Any = t.INK,
    align: int = TA_LEFT,
    leading: float = 1.32,
) -> Paragraph:
    style = ParagraphStyle(
        f"lr_{size}_{bold}_{align}",
        fontName=t.BOLD_FONT if bold else t.BODY_FONT,
        fontSize=size,
        leading=size * leading,
        textColor=color,
        alignment=align,
    )
    return Paragraph(t.markup(text), style)


def _kv_row(label: str, value: str, *, bold_value: bool = True, value_color: Any = t.INK) -> list[Flowable]:
    return [
        _p(label, size=7.2, color=t.INK_3),
        _p(value, size=8.6, bold=bold_value, color=value_color),
    ]


def _build_receipt_header(
    brand: t.Brand,
    s: dict[str, Any],
    receipt_number: str,
    pl_ref: str,
    issued_label: str,
) -> list[Flowable]:
    """Distinctive receipt voucher header: solid top accent bar + company origin info + framed ticket stamp."""
    accent = t.brand_color(brand.color)
    tint = t.brand_tint(brand.color, weight=0.08)

    # Slim full-width brand accent bar at top of voucher
    accent_bar = Table([[""]], colWidths=[t.CONTENT_WIDTH], rowHeights=[0.16 * cm])
    accent_bar.setStyle(
        t.TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, -1), accent),
                ("TOPPADDING", (0, 0), (-1, -1), 0),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
            ]
        )
    )

    # Left: Logo + Bilingual Origin Warehouse Identity
    contact = " · ".join(p for p in (brand.phone, brand.email) if p)
    company_lines: list[Flowable] = [_p(brand.name, size=12.0, bold=True, color=t.INK, leading=1.2)]
    for line in (brand.address, contact):
        if line:
            company_lines.append(_p(line, size=7.6, color=t.INK_3, leading=1.28))

    left_inner = Table(
        [[t.logo_mark(brand, size=1.45 * cm), company_lines]],
        colWidths=[1.75 * cm, t.CONTENT_WIDTH * 0.58 - 1.75 * cm],
    )
    left_inner.setStyle(
        t.TableStyle(
            [
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("LEFTPADDING", (0, 0), (-1, -1), 0),
                ("RIGHTPADDING", (0, 0), (-1, -1), 6),
                ("TOPPADDING", (0, 0), (-1, -1), 0),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
            ]
        )
    )

    # Right: Bordered Receipt Ticket Stamp Box
    ticket_rows = [
        [_p(s["title"], size=13.0, bold=True, color=accent, align=TA_CENTER, leading=1.15)],
        [_p(s["title_secondary"], size=7.2, bold=True, color=t.INK_3, align=TA_CENTER, leading=1.2)],
        [_p(f"{s['receipt_no_prefix']} {receipt_number}", size=10.5, bold=True, color=t.INK, align=TA_CENTER, leading=1.25)],
        [
            _p(
                f"{s['subtitle_ref']}: {pl_ref}  ·  {s['issued_at']}: {issued_label}",
                size=6.8,
                color=t.INK_3,
                align=TA_CENTER,
                leading=1.25,
            )
        ],
    ]
    ticket_width = t.CONTENT_WIDTH * 0.42
    ticket = Table(ticket_rows, colWidths=[ticket_width])
    ticket.setStyle(
        t.TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, -1), tint),
                ("BOX", (0, 0), (-1, -1), 1.0, accent),
                ("LINEABOVE", (0, 2), (-1, 2), 0.5, accent),
                ("TOPPADDING", (0, 0), (-1, -1), 3),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
                ("LEFTPADDING", (0, 0), (-1, -1), 6),
                ("RIGHTPADDING", (0, 0), (-1, -1), 6),
            ]
        )
    )

    header = Table([[left_inner, ticket]], colWidths=[t.CONTENT_WIDTH * 0.58, ticket_width])
    header.setStyle(
        t.TableStyle(
            [
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("LEFTPADDING", (0, 0), (-1, -1), 0),
                ("RIGHTPADDING", (0, 0), (-1, -1), 0),
                ("TOPPADDING", (0, 0), (-1, -1), 6),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
            ]
        )
    )
    return [accent_bar, header]


def _build_voucher_parties_card(
    brand: t.Brand,
    s: dict[str, Any],
    pl: dict[str, Any],
    items: Sequence[dict[str, Any]],
    tracking_label: str,
    container_label: str,
) -> Table:
    """Framed two-column receipt box: Consignee/Sender on left, Destination Warehouse + Container/Dates on right."""
    accent = t.brand_color(brand.color)
    dest_headline, dest_address = format_destination_warehouse(pl)
    wh_phone = str(pl.get("arrival_warehouse_phone") or "").strip()

    left_flow: list[Flowable] = [
        _p(s["party_heading"], size=7.5, bold=True, color=accent),
        Spacer(1, 0.1 * cm),
        *_kv_row(s["customer"], str(pl.get("customer_name") or t.MISSING)),
        Spacer(1, 0.08 * cm),
        *_kv_row(s["phone"], str(pl.get("customer_phone") or t.MISSING), bold_value=False),
    ]
    if pl.get("supplier_name") or pl.get("supplier_phone"):
        supplier_str = " · ".join(str(p).strip() for p in (pl.get("supplier_name"), pl.get("supplier_phone")) if p)
        left_flow.extend([Spacer(1, 0.08 * cm), *_kv_row(s["supplier"], supplier_str, bold_value=False)])
    left_flow.extend(
        [
            Spacer(1, 0.1 * cm),
            *_kv_row(s["tracking_code"], tracking_label, bold_value=True, value_color=accent),
        ]
    )

    delivery_str = _date_summary(pl.get("delivery_date"), [i.get("received_date") for i in items])
    loading_str = _date_summary(pl.get("loading_date"), [i.get("loading_date") or pl.get("loading_date") for i in items])

    right_flow: list[Flowable] = [
        _p(s["route_heading"], size=7.5, bold=True, color=accent),
        Spacer(1, 0.1 * cm),
        _p(s["destination"], size=7.2, color=t.INK_3),
        _p(dest_headline, size=9.0, bold=True, color=t.INK),
    ]
    if dest_address:
        addr_line = f"{dest_address} · {wh_phone}" if wh_phone else dest_address
        right_flow.append(_p(addr_line, size=7.6, color=t.INK_2, leading=1.25))
    elif wh_phone:
        right_flow.append(_p(wh_phone, size=7.6, color=t.INK_2))

    dates_sub = Table(
        [
            [
                [_p(s["container"], size=7.2, color=t.INK_3), _p(container_label, size=8.4, bold=True)],
                [_p(s["delivery_date"], size=7.2, color=t.INK_3), _p(delivery_str, size=8.4, bold=True)],
                [_p(s["loading_date"], size=7.2, color=t.INK_3), _p(loading_str, size=8.4, bold=True)],
            ]
        ],
        colWidths=[t.CONTENT_WIDTH * 0.21, t.CONTENT_WIDTH * 0.16, t.CONTENT_WIDTH * 0.16],
    )
    dates_sub.setStyle(
        t.TableStyle(
            [
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LEFTPADDING", (0, 0), (-1, -1), 0),
                ("RIGHTPADDING", (0, 0), (-1, -1), 4),
                ("TOPPADDING", (0, 0), (-1, -1), 4),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
            ]
        )
    )
    right_flow.extend([Spacer(1, 0.08 * cm), dates_sub])

    card = Table(
        [[left_flow, right_flow]],
        colWidths=[t.CONTENT_WIDTH * 0.43, t.CONTENT_WIDTH * 0.57],
    )
    card.setStyle(
        t.TableStyle(
            [
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("BOX", (0, 0), (-1, -1), 0.75, t.LINE),
                ("LINEBEFORE", (1, 0), (1, -1), 0.6, t.LINE_SOFT),
                ("BACKGROUND", (0, 0), (0, -1), t.SURFACE_MUTED),
                ("BACKGROUND", (1, 0), (1, -1), colors.white),
                ("TOPPADDING", (0, 0), (-1, -1), 7),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 7),
                ("LEFTPADDING", (0, 0), (-1, -1), 8),
                ("RIGHTPADDING", (0, 0), (-1, -1), 8),
            ]
        )
    )
    return card


def generate_loading_receipt_pdf_with_meta(
    brand: t.Brand,
    pl: dict[str, Any],
    items: Sequence[dict[str, Any]],
    *,
    lang: Lang = "zh",
) -> t.RenderedPdf:
    """Render the redesigned Loading Receipt PDF and return both buffer and exact page count."""
    norm_lang: Lang = "en" if lang == "en" else "zh"
    s = _STRINGS[norm_lang]
    eff_brand = _effective_brand(brand, norm_lang)
    accent = t.brand_color(eff_brand.color)
    tint = t.brand_tint(eff_brand.color, weight=0.07)

    receipt_number = str(pl.get("loading_receipt_number") or pl.get("reference") or pl.get("id") or "")
    pl_ref = str(pl.get("reference") or t.MISSING)
    issued_str = t.day(pl.get("loaded_at") or pl.get("approved_at") or t.now())

    packages = sum(int(item.get("quantity") or 1) for item in items)
    total_cbm = _sum(items, "cbm")
    total_weight = _sum(items, "weight_actual_kg") or _sum(items, "weight_dispatch_kg")

    container_num = str(pl.get("container_number") or "")
    parcel_num = str(pl.get("container_parcel_number") or "")
    container_label = f"{container_num} / {parcel_num}" if (container_num and parcel_num) else (container_num or t.MISSING)

    tracking_codes = list(dict.fromkeys(str(i["tracking_code"]) for i in items if i.get("tracking_code")))
    primary_tracking = tracking_codes[0] if tracking_codes else receipt_number
    tracking_label = ", ".join(tracking_codes) if tracking_codes else t.MISSING

    show_delivered = pl.get("delivery_date_mode") == "multiple_days" or _has_varying_dates(
        items, "received_date", pl.get("delivery_date")
    )
    show_loaded = any(item.get("loading_date") for item in items) or _has_varying_dates(
        items, "loading_date", pl.get("loading_date")
    )

    columns = [
        t.Column(s["col_tag"], 2.3),
        t.Column(s["col_desc"], 3.9 if (show_delivered or show_loaded) else 4.6),
        t.Column(s["col_pkg"], 1.25),
        t.Column(s["col_qty"], 0.75, "right"),
        t.Column(s["col_dims"], 2.1, "right"),
        t.Column(s["col_cbm"], 1.25, "right"),
        t.Column(s["col_weight"], 1.35, "right"),
    ]
    if show_delivered:
        columns.append(t.Column(s["col_delivered"], 1.4))
    if show_loaded:
        columns.append(t.Column(s["col_loaded"], 1.4))

    rows: list[list[str]] = []
    for item in items:
        weight_val = item.get("weight_actual_kg")
        if weight_val is None:
            weight_val = item.get("weight_dispatch_kg")
        row = [
            str(item.get("carton_tag") or t.MISSING),
            str(item.get("description") or ""),
            t.humanise(item.get("bale_type") or item.get("package_unit") or "carton"),
            t.count(item.get("quantity") or 1),
            _dimensions(item),
            t.cbm(item.get("cbm")),
            t.kg(weight_val),
        ]
        if show_delivered:
            row.append(t.day(item.get("received_date")))
        if show_loaded:
            row.append(t.day(item.get("loading_date") or pl.get("loading_date")))
        rows.append(row)

    # Framed voucher cargo grid (distinct boxed style vs open Packing List table)
    cargo_table = t.DataTable(
        columns,
        rows,
        brand=eff_brand.color,
        zebra=False,
        extra_style=[
            ("BOX", (0, 0), (-1, -1), 0.75, t.LINE),
            ("BACKGROUND", (0, 0), (-1, 0), t.SURFACE_MUTED),
            ("INNERGRID", (0, 1), (-1, -1), 0.35, t.LINE_SOFT),
            ("TOPPADDING", (0, 0), (-1, -1), 4),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ],
    ).build()

    # Split Receipt Bottom Strip: Verification + Remarks (Left) | Highlighted Totals + QR (Right)
    left_bottom: list[Flowable] = [
        _p(s["handling_heading"], size=7.5, bold=True, color=accent),
        Spacer(1, 0.1 * cm),
        _p(f"{s['received_by']}: {pl.get('created_by_name') or t.MISSING}", size=8.2, color=t.INK),
        _p(f"{s['approved_by']}: {pl.get('approved_by_name') or t.MISSING}", size=8.2, color=t.INK),
        _p(
            f"{s['loaded_time']}: {t.moment(pl.get('loaded_at') or pl.get('approved_at'))}",
            size=7.8,
            color=t.INK_3,
        ),
    ]
    remarks = str(pl.get("remarks") or "").strip()
    if remarks:
        left_bottom.extend(
            [
                Spacer(1, 0.15 * cm),
                _p(s["remarks_label"], size=7.3, bold=True, color=t.INK_2),
                _p(remarks, size=8.0, color=t.INK),
            ]
        )

    totals_rows = [
        [_p(s["summary_heading"], size=7.5, bold=True, color=accent), ""],
        [
            _p(s["total_packages"], size=8.0, color=t.INK_2),
            _p(f"{t.count(packages)} {s['pkg_unit']}", size=9.5, bold=True, align=TA_RIGHT),
        ],
        [
            _p(s["total_cbm"], size=8.0, color=t.INK_2),
            _p(f"{t.cbm(total_cbm)} m³", size=10.5, bold=True, color=accent, align=TA_RIGHT),
        ],
        [_p(s["total_weight"], size=8.0, color=t.INK_2), _p(f"{t.kg(total_weight)} kg", size=9.0, bold=True, align=TA_RIGHT)],
    ]
    totals_width = t.CONTENT_WIDTH * 0.34
    totals_card = Table(totals_rows, colWidths=[totals_width * 0.52, totals_width * 0.48])
    totals_card.setStyle(
        t.TableStyle(
            [
                ("SPAN", (0, 0), (1, 0)),
                ("BACKGROUND", (0, 0), (-1, -1), tint),
                ("BOX", (0, 0), (-1, -1), 0.9, accent),
                ("LINEBELOW", (0, 0), (-1, 0), 0.5, accent),
                ("TOPPADDING", (0, 0), (-1, -1), 3),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
                ("LEFTPADDING", (0, 0), (-1, -1), 6),
                ("RIGHTPADDING", (0, 0), (-1, -1), 6),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ]
        )
    )

    qr_width = 2.4 * cm
    qr_box: list[Flowable] = [
        t.qr_code(primary_tracking, size=2.05 * cm),
        Spacer(1, 0.06 * cm),
        _p(s["qr_caption"], size=6.6, color=t.INK_3, align=TA_CENTER),
    ]

    bottom_strip = Table(
        [[left_bottom, totals_card, qr_box]],
        colWidths=[t.CONTENT_WIDTH - totals_width - qr_width - 0.3 * cm, totals_width + 0.3 * cm, qr_width],
    )
    bottom_strip.setStyle(
        t.TableStyle(
            [
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LEFTPADDING", (0, 0), (-1, -1), 0),
                ("RIGHTPADDING", (0, 0), (-1, -1), 0),
                ("RIGHTPADDING", (0, 0), (0, 0), 8),
                ("RIGHTPADDING", (1, 0), (1, 0), 8),
                ("TOPPADDING", (0, 0), (-1, -1), 2),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
            ]
        )
    )

    # Compact boxed warehouse terms
    terms_box = Table(
        [
            [_p(s["notice_heading"], size=7.4, bold=True, color=t.INK_2)],
            [_p("\n".join(s["notices"]), size=7.1, color=t.INK_3, leading=1.3)],
        ],
        colWidths=[t.CONTENT_WIDTH],
    )
    terms_box.setStyle(
        t.TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, -1), t.SURFACE_MUTED),
                ("BOX", (0, 0), (-1, -1), 0.5, t.LINE),
                ("TOPPADDING", (0, 0), (-1, -1), 4),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
                ("LEFTPADDING", (0, 0), (-1, -1), 7),
                ("RIGHTPADDING", (0, 0), (-1, -1), 7),
            ]
        )
    )

    body: list[Flowable] = [
        *_build_receipt_header(eff_brand, s, receipt_number, pl_ref, issued_str),
        Spacer(1, 0.25 * cm),
        _build_voucher_parties_card(eff_brand, s, pl, items, tracking_label, container_label),
        Spacer(1, 0.3 * cm),
        cargo_table,
        Spacer(1, 0.3 * cm),
        bottom_strip,
        Spacer(1, 0.28 * cm),
        terms_box,
        Spacer(1, 0.2 * cm),
        t.signature_lines([s["sig_sender"], s["sig_warehouse"]]),
    ]

    return t.render_with_meta(
        eff_brand,
        s["title"],
        receipt_number,
        body,
        subject=f"{s['subject_prefix']} {pl.get('customer_name') or s['default_customer']}",
        include_brand_block=False,
    )


def generate_loading_receipt_pdf(
    brand: t.Brand,
    pl: dict[str, Any],
    items: Sequence[dict[str, Any]],
    *,
    lang: Lang = "zh",
) -> BytesIO:
    """Render the Loading Receipt PDF as a BytesIO buffer."""
    return generate_loading_receipt_pdf_with_meta(brand, pl, items, lang=lang).buf
