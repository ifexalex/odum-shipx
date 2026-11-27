"""Modern bilingual Loading Receipt PDF (ENG-4 / ENG-5, built on ``pdf_theme``).

Implemented using the **Executive Brand-Banner Ticket** layout:
- Full-width tenant-branded top header banner with white logo tile, bilingual origin warehouse
  identity, document title, and high-contrast white ``NO. LR-…`` receipt pill.
- Clean two-column bordered info card pairing Customer + Tracking Code (left) with
  Destination Warehouse (`Country · City — Warehouse` + full street address & phone, right).
- Dedicated horizontal 4-column Load & Dates bar (Container / Parcel, Packing List Ref,
  Received Date, Loading Date).
- Zebra-striped cargo table with full dimensions (``L × W × H cm``), optional per-item
  Received / Loaded date columns when items vary, and an inline bold Totals row.
- Bottom verification + Remarks strip paired with a brand-bordered QR summary ticket,
  compact terms box, and dual signature lines.

Defaults to Chinese (``lang="zh"``) with full English support (``lang="en"``).
"""

from collections.abc import Sequence
from datetime import date, datetime
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
        "title_secondary": "OFFICIAL LOADING RECEIPT",
        "receipt_no_prefix": "NO.",
        "party_heading": "客户信息 · CUSTOMER",
        "tracking_code": "追踪号 TRACKING CODE",
        "dest_heading": "目的港仓库 · DESTINATION WAREHOUSE",
        "warehouse_phone": "仓库电话",
        "container": "柜号 / 分单",
        "packing_list_ref": "关联装箱单",
        "delivery_date": "收货日期",
        "loading_date": "装柜日期",
        "col_tag": "编号 Tag",
        "col_desc": "货物名称 Description",
        "col_pkg": "包装 Pkg",
        "col_qty": "数量",
        "col_dims": "尺寸 L×W×H cm",
        "col_cbm": "体积 CBM",
        "col_weight": "重量 kg",
        "col_delivered": "收货日",
        "col_loaded": "装柜日",
        "total_label": "合计 Total",
        "pkg_unit": "件",
        "remarks_label": "备注 / 压包要求",
        "handling_heading": "仓库经办确认",
        "received_by": "开单收货人",
        "approved_by": "装柜审核",
        "qr_caption": "扫码查物流",
        "qr_subcaption": "Scan to track",
        "notice_prefix": "请注意以下信息",
        "notices": [
            "1. 货物入仓须提供准确货物名称、联系方式及目的港，装柜确认后24小时内如无异议即视为确认无误。",
            "2. 严禁夹带仿牌、违禁品、易燃易爆物品，海关查验或扣货产生的一切责任由货主自行承担。",
            "3. 本仓库按外包装件数及尺寸体积 (CBM) 核收，不拆箱清点内件数量，请发货人自行核对。",
            "4. 货物抵达目的港仓库后享有免费仓储期，逾期未提将按规定收取仓储及保管费。",
            "5. 请妥善保管本收据及追踪号，查询物流进度及目的港提货时均需出示。",
        ],
        "sig_sender": "送货人 / 客户签名",
        "sig_warehouse": "仓库收货人签名",
        "subject_prefix": "入仓装柜收据 -",
        "default_customer": "客户",
    },
    "en": {
        "title": "LOADING RECEIPT",
        "title_secondary": "入仓装柜收据 · OFFICIAL RECEIPT",
        "receipt_no_prefix": "NO.",
        "party_heading": "CUSTOMER",
        "tracking_code": "TRACKING CODE",
        "dest_heading": "DESTINATION WAREHOUSE",
        "warehouse_phone": "Warehouse phone",
        "container": "Container / Parcel",
        "packing_list_ref": "Packing list",
        "delivery_date": "Received date",
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
        "total_label": "Total",
        "pkg_unit": "pkg",
        "remarks_label": "Remarks / Packing instructions",
        "handling_heading": "Warehouse verification",
        "received_by": "Received by",
        "approved_by": "Loaded by",
        "qr_caption": "Scan to track",
        "qr_subcaption": "扫码查物流",
        "notice_prefix": "Important notice",
        "notices": [
            "1. Please verify item descriptions, dimensions, CBM, and destination warehouse before container sealing.",
            "2. Counterfeit, fragile, flammable, explosive, or contraband goods are shipped strictly at the owner's risk.",
            "3. Cargo is verified by outer package count and measured dimensions (CBM); inner piece counts are not verified.",
            "4. Free storage applies during the arrival grace period; overdue goods attract daily warehouse storage fees.",
            "5. Keep this Loading Receipt and tracking code safe for shipment tracking and pickup verification.",
        ],
        "sig_sender": "Sender / Customer Signature",
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


def _sort_key_for_date(raw: Any) -> tuple[int, str]:
    if isinstance(raw, datetime):
        return (0, raw.date().isoformat())
    if isinstance(raw, date):
        return (0, raw.isoformat())
    return (1, str(raw))


def _unique_dates(values: Sequence[Any]) -> list[str]:
    pairs: list[tuple[tuple[int, str], str]] = []
    seen: set[str] = set()
    for raw in values:
        formatted = t.day(raw)
        if formatted != t.MISSING and formatted not in seen:
            seen.add(formatted)
            pairs.append((_sort_key_for_date(raw), formatted))
    pairs.sort(key=lambda item: item[0])
    return [formatted for _, formatted in pairs]


def _compact_date_range(first: str, last: str) -> str:
    """Format two ``t.day()`` strings (``DD Mon YYYY``) compactly when month/year match."""
    first_parts = first.split()
    last_parts = last.split()
    if len(first_parts) == 3 and len(last_parts) == 3:
        if first_parts[1:] == last_parts[1:]:
            return f"{first_parts[0]} – {last}"
        if first_parts[2] == last_parts[2]:
            return f"{first_parts[0]} {first_parts[1]} – {last}"
    return f"{first} – {last}"


def _date_summary(header_val: Any, item_vals: Sequence[Any]) -> str:
    unique = _unique_dates(item_vals)
    if len(unique) > 1:
        return _compact_date_range(unique[0], unique[-1])
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


def _build_hero_banner(
    raw_brand: t.Brand,
    eff_brand: t.Brand,
    s: dict[str, Any],
    lang: Lang,
    receipt_number: str,
) -> Table:
    """Full-width tenant-colored executive banner with white logo tile and ``NO. LR-…`` pill."""
    accent = t.brand_color(eff_brand.color)
    soft_white = colors.Color(1, 1, 1, 0.88)
    muted_white = colors.Color(1, 1, 1, 0.82)

    logo_white_box = Table(
        [[t.logo_mark(eff_brand, size=1.35 * cm)]],
        colWidths=[1.55 * cm],
        rowHeights=[1.55 * cm],
    )
    logo_white_box.setStyle(
        t.TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, -1), colors.white),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("ALIGN", (0, 0), (-1, -1), "CENTER"),
                ("TOPPADDING", (0, 0), (-1, -1), 2),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
                ("LEFTPADDING", (0, 0), (-1, -1), 2),
                ("RIGHTPADDING", (0, 0), (-1, -1), 2),
            ]
        )
    )

    company_lines: list[Flowable] = []
    if raw_brand.chinese_name:
        if lang == "zh":
            company_lines.append(_p(raw_brand.chinese_name, size=12.5, bold=True, color=colors.white, leading=1.18))
            company_lines.append(_p(raw_brand.name, size=8.5, color=soft_white, leading=1.24))
        else:
            company_lines.append(_p(raw_brand.name, size=12.0, bold=True, color=colors.white, leading=1.18))
            company_lines.append(_p(raw_brand.chinese_name, size=8.5, color=soft_white, leading=1.24))
    else:
        company_lines.append(_p(raw_brand.name, size=12.5, bold=True, color=colors.white, leading=1.18))
        if raw_brand.tagline:
            company_lines.append(_p(raw_brand.tagline, size=8.2, color=soft_white, leading=1.24))

    origin_parts = [p for p in (eff_brand.address, eff_brand.phone) if p]
    if not origin_parts and eff_brand.email:
        origin_parts.append(eff_brand.email)
    if origin_parts:
        company_lines.append(_p("  ·  ".join(origin_parts), size=7.2, color=muted_white, leading=1.26))

    left_col_w = t.CONTENT_WIDTH * 0.63
    right_col_w = t.CONTENT_WIDTH * 0.37

    banner_left = Table(
        [[logo_white_box, company_lines]],
        colWidths=[1.85 * cm, left_col_w - 1.85 * cm - 0.55 * cm],
    )
    banner_left.setStyle(
        t.TableStyle(
            [
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("LEFTPADDING", (0, 0), (-1, -1), 0),
                ("RIGHTPADDING", (0, 0), (-1, -1), 4),
                ("TOPPADDING", (0, 0), (-1, -1), 0),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
            ]
        )
    )

    pill_w = right_col_w - 18  # flush inside hero's 11pt right padding + small inner gutter
    no_pill = Table(
        [[_p(f"{s['receipt_no_prefix']} {receipt_number}", size=9.6, bold=True, color=accent, align=TA_CENTER)]],
        colWidths=[pill_w],
    )
    no_pill.setStyle(
        t.TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, -1), colors.white),
                ("TOPPADDING", (0, 0), (-1, -1), 4),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
                ("LEFTPADDING", (0, 0), (-1, -1), 6),
                ("RIGHTPADDING", (0, 0), (-1, -1), 6),
            ]
        )
    )

    title_size = 14.0 if lang == "zh" else 13.0
    banner_right: list[Flowable] = [
        _p(s["title"], size=title_size, bold=True, color=colors.white, align=TA_RIGHT, leading=1.15),
        _p(s["title_secondary"], size=7.0, bold=True, color=soft_white, align=TA_RIGHT, leading=1.24),
        Spacer(1, 0.14 * cm),
        no_pill,
    ]

    hero = Table([[banner_left, banner_right]], colWidths=[left_col_w, right_col_w])
    hero.setStyle(
        t.TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, -1), accent),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("TOPPADDING", (0, 0), (-1, -1), 11),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 11),
                ("LEFTPADDING", (0, 0), (0, 0), 11),
                ("RIGHTPADDING", (0, 0), (0, 0), 6),
                ("LEFTPADDING", (1, 0), (1, 0), 6),
                ("RIGHTPADDING", (1, 0), (1, 0), 11),
            ]
        )
    )
    return hero


def _build_parties_card(
    brand: t.Brand,
    s: dict[str, Any],
    pl: dict[str, Any],
    tracking_label: str,
) -> Table:
    """Spacious bordered 2-zone card: Customer + Tracking on left, Destination Warehouse on right."""
    accent = t.brand_color(brand.color)
    dest_headline, dest_address = format_destination_warehouse(pl)
    wh_phone = str(pl.get("arrival_warehouse_phone") or "").strip()

    left_flow: list[Flowable] = [
        _p(s["party_heading"], size=7.0, bold=True, color=t.INK_3),
        Spacer(1, 0.06 * cm),
        _p(str(pl.get("customer_name") or t.MISSING), size=10.5, bold=True, color=t.INK),
        _p(str(pl.get("customer_phone") or t.MISSING), size=8.4, color=t.INK_2),
        Spacer(1, 0.12 * cm),
        _p(s["tracking_code"], size=6.8, color=t.INK_3),
        _p(tracking_label, size=9.2, bold=True, color=accent),
    ]

    right_flow: list[Flowable] = [
        _p(s["dest_heading"], size=7.0, bold=True, color=t.INK_3),
        Spacer(1, 0.06 * cm),
        _p(dest_headline, size=10.2, bold=True, color=t.INK),
    ]
    if dest_address:
        right_flow.append(_p(dest_address, size=8.2, color=t.INK_2, leading=1.3))
    if wh_phone:
        right_flow.append(_p(f"{s['warehouse_phone']}: {wh_phone}", size=7.8, color=t.INK_3))

    card = Table(
        [[left_flow, right_flow]],
        colWidths=[t.CONTENT_WIDTH * 0.42, t.CONTENT_WIDTH * 0.58],
    )
    card.setStyle(
        t.TableStyle(
            [
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("BOX", (0, 0), (-1, -1), 0.6, t.LINE),
                ("LINEBEFORE", (1, 0), (1, -1), 0.6, t.LINE_SOFT),
                ("BACKGROUND", (0, 0), (-1, -1), colors.white),
                ("TOPPADDING", (0, 0), (-1, -1), 8),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
                ("LEFTPADDING", (0, 0), (-1, -1), 10),
                ("RIGHTPADDING", (0, 0), (-1, -1), 10),
            ]
        )
    )
    return card


def _build_load_bar(
    s: dict[str, Any],
    container_label: str,
    pl_ref: str,
    delivery_str: str,
    loading_str: str,
) -> Table:
    """Dedicated 4-column horizontal Load & Dates strip underneath the parties card."""
    bar = Table(
        [
            [
                [_p(s["container"], size=6.8, color=t.INK_3), _p(container_label, size=8.4, bold=True)],
                [_p(s["packing_list_ref"], size=6.8, color=t.INK_3), _p(pl_ref, size=8.4, bold=True)],
                [_p(s["delivery_date"], size=6.8, color=t.INK_3), _p(delivery_str, size=8.4, bold=True)],
                [_p(s["loading_date"], size=6.8, color=t.INK_3), _p(loading_str, size=8.4, bold=True)],
            ]
        ],
        colWidths=[
            t.CONTENT_WIDTH * 0.32,
            t.CONTENT_WIDTH * 0.24,
            t.CONTENT_WIDTH * 0.24,
            t.CONTENT_WIDTH * 0.20,
        ],
    )
    bar.setStyle(
        t.TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, -1), t.SURFACE_MUTED),
                ("BOX", (0, 0), (-1, -1), 0.6, t.LINE),
                ("INNERGRID", (0, 0), (-1, -1), 0.4, t.LINE_SOFT),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("TOPPADDING", (0, 0), (-1, -1), 5),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
                ("LEFTPADDING", (0, 0), (-1, -1), 8),
                ("RIGHTPADDING", (0, 0), (-1, -1), 6),
            ]
        )
    )
    return bar


def generate_loading_receipt_pdf_with_meta(
    brand: t.Brand,
    pl: dict[str, Any],
    items: Sequence[dict[str, Any]],
    *,
    lang: Lang = "zh",
) -> t.RenderedPdf:
    """Render the Executive Brand-Banner Loading Receipt PDF and return buffer + page count."""
    norm_lang: Lang = "en" if lang == "en" else "zh"
    s = _STRINGS[norm_lang]
    eff_brand = _effective_brand(brand, norm_lang)
    accent = t.brand_color(eff_brand.color)
    tint = t.brand_tint(eff_brand.color, weight=0.06)

    receipt_number = str(pl.get("loading_receipt_number") or pl.get("reference") or pl.get("id") or "")
    pl_ref = str(pl.get("reference") or t.MISSING)

    packages = sum(int(item.get("quantity") or 1) for item in items)
    total_cbm = _sum(items, "cbm")
    total_weight = _sum(items, "weight_actual_kg") or _sum(items, "weight_dispatch_kg")

    container_num = str(pl.get("container_number") or "")
    parcel_num = str(pl.get("container_parcel_number") or "")
    container_label = f"{container_num} / {parcel_num}" if (container_num and parcel_num) else (container_num or t.MISSING)

    tracking_codes = list(dict.fromkeys(str(i["tracking_code"]) for i in items if i.get("tracking_code")))
    primary_tracking = tracking_codes[0] if tracking_codes else receipt_number
    tracking_label = ", ".join(tracking_codes) if tracking_codes else t.MISSING

    delivery_str = _date_summary(pl.get("delivery_date"), [i.get("received_date") for i in items])
    loading_str = _date_summary(pl.get("loading_date"), [i.get("loading_date") or pl.get("loading_date") for i in items])

    show_delivered = pl.get("delivery_date_mode") == "multiple_days" or _has_varying_dates(
        items, "received_date", pl.get("delivery_date")
    )
    show_loaded = any(item.get("loading_date") for item in items) or _has_varying_dates(
        items, "loading_date", pl.get("loading_date")
    )

    date_col_count = int(show_delivered) + int(show_loaded)
    desc_weight = 3.95 if date_col_count == 0 else (3.0 if date_col_count == 1 else 2.5)
    columns = [
        t.Column(s["col_tag"], 2.5),
        t.Column(s["col_desc"], desc_weight),
        t.Column(s["col_pkg"], 1.2),
        t.Column(s["col_qty"], 0.65, "right"),
        t.Column(s["col_dims"], 1.9, "right"),
        t.Column(s["col_cbm"], 1.2, "right"),
        t.Column(s["col_weight"], 1.25, "right"),
    ]
    if show_delivered:
        columns.append(t.Column(s["col_delivered"], 1.5))
    if show_loaded:
        columns.append(t.Column(s["col_loaded"], 1.5))

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

    totals_row = [
        s["total_label"],
        "",
        "",
        t.count(packages),
        "",
        t.cbm(total_cbm),
        t.kg(total_weight),
        *([""] * date_col_count),
    ]

    cargo_table = t.DataTable(
        columns,
        rows,
        totals=totals_row,
        brand=eff_brand.color,
        zebra=True,
        extra_style=[
            ("BOX", (0, 0), (-1, -1), 0.6, t.LINE),
            ("BACKGROUND", (0, 0), (-1, 0), t.SURFACE_MUTED),
            ("TOPPADDING", (0, 0), (-1, -1), 5),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        ],
    ).build()

    # Bottom verification & remarks (left) + bordered QR summary ticket (right)
    remarks = str(pl.get("remarks") or "").strip()
    created_by = str(pl.get("created_by_name") or t.MISSING)
    approved_by = str(pl.get("approved_by_name") or t.MISSING)
    confirmed_at = t.moment(pl.get("loaded_at") or pl.get("approved_at"))

    verify_left: list[Flowable] = []
    if remarks:
        verify_left.extend(
            [
                _p(s["remarks_label"], size=7.2, bold=True, color=accent),
                _p(remarks, size=8.4, color=t.INK),
                Spacer(1, 0.2 * cm),
                _p(
                    f"{s['received_by']}: {created_by}   |   {s['approved_by']}: {approved_by}   |   {confirmed_at}",
                    size=7.8,
                    color=t.INK_2,
                ),
            ]
        )
    else:
        verify_left.extend(
            [
                _p(s["handling_heading"], size=7.2, bold=True, color=accent),
                Spacer(1, 0.06 * cm),
                _p(f"{s['received_by']}: {created_by}   |   {s['approved_by']}: {approved_by}", size=8.2, color=t.INK),
                _p(confirmed_at, size=7.8, color=t.INK_3),
            ]
        )

    qr_ticket = Table(
        [
            [
                t.qr_code(primary_tracking, size=1.9 * cm),
                [
                    _p(s["qr_caption"], size=8.0, bold=True, color=accent),
                    _p(s["qr_subcaption"], size=7.0, color=t.INK_3),
                    Spacer(1, 0.08 * cm),
                    _p(f"{t.count(packages)} {s['pkg_unit']} · {t.cbm(total_cbm)} m³", size=8.6, bold=True),
                    _p(f"{t.kg(total_weight)} kg", size=8.0, color=t.INK_2),
                ],
            ]
        ],
        colWidths=[2.2 * cm, 3.4 * cm],
    )
    qr_ticket.setStyle(
        t.TableStyle(
            [
                ("BOX", (0, 0), (-1, -1), 0.8, accent),
                ("BACKGROUND", (0, 0), (-1, -1), tint),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("TOPPADDING", (0, 0), (-1, -1), 5),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
                ("LEFTPADDING", (0, 0), (-1, -1), 6),
                ("RIGHTPADDING", (0, 0), (-1, -1), 6),
            ]
        )
    )

    bottom_strip = Table(
        [[verify_left, qr_ticket]],
        colWidths=[t.CONTENT_WIDTH - 5.9 * cm, 5.9 * cm],
    )
    bottom_strip.setStyle(
        t.TableStyle(
            [
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("LEFTPADDING", (0, 0), (-1, -1), 0),
                ("RIGHTPADDING", (0, 0), (-1, -1), 0),
                ("RIGHTPADDING", (0, 0), (0, 0), 10),
                ("TOPPADDING", (0, 0), (-1, -1), 0),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
            ]
        )
    )

    terms_box = Table(
        [[_p(f"{s['notice_prefix']}: " + " ".join(s["notices"]), size=6.9, color=t.INK_3, leading=1.32)]],
        colWidths=[t.CONTENT_WIDTH],
    )
    terms_box.setStyle(
        t.TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, -1), t.SURFACE_MUTED),
                ("TOPPADDING", (0, 0), (-1, -1), 6),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
                ("LEFTPADDING", (0, 0), (-1, -1), 8),
                ("RIGHTPADDING", (0, 0), (-1, -1), 8),
            ]
        )
    )

    body: list[Flowable] = [
        _build_hero_banner(brand, eff_brand, s, norm_lang, receipt_number),
        Spacer(1, 0.3 * cm),
        _build_parties_card(eff_brand, s, pl, tracking_label),
        Spacer(1, 0.16 * cm),
        _build_load_bar(s, container_label, pl_ref, delivery_str, loading_str),
        Spacer(1, 0.3 * cm),
        cargo_table,
        Spacer(1, 0.3 * cm),
        bottom_strip,
        Spacer(1, 0.25 * cm),
        terms_box,
        Spacer(1, 0.25 * cm),
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
