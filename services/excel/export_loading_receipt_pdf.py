"""Modern bilingual Loading Receipt PDF (ENG-4 / ENG-5, built on ``pdf_theme``).

Issued automatically when a packing list is approved (``LR-YYYYMMDD-NNN``).
Defaults to Chinese (``lang="zh"``) because goods are received and loaded at the
China origin warehouse, with full English support (``lang="en"``) via the language switch.
Retains full item dimensions (``L × W × H cm``) alongside the Packing List for verification
and dispute resolution across the shipping chain.
"""

from collections.abc import Sequence
from io import BytesIO
from typing import Any, Literal

from reportlab.lib.units import cm
from reportlab.platypus import Flowable, Spacer, Table

from . import pdf_theme as t

Lang = Literal["zh", "en"]

_STRINGS: dict[Lang, dict[str, Any]] = {
    "zh": {
        "title": "入仓装柜收据",
        "subtitle_ref": "装箱单号",
        "issued_at": "签发时间",
        "customer": "客户名字",
        "phone": "客户电话",
        "supplier": "供应商",
        "destination": "目的港 / 到达仓库",
        "container": "柜号 / 分单号",
        "tracking_code": "追踪号",
        "delivery_date": "收货日期",
        "loading_date": "装柜日期",
        "cargo_section": "货物明细",
        "col_tag": "编号",
        "col_desc": "货物名称",
        "col_type": "包装类型",
        "col_qty": "数量",
        "col_dims": "尺寸 (cm)",
        "col_cbm": "体积 (CBM)",
        "col_weight": "重量 (kg)",
        "col_delivered": "收货日期",
        "col_loaded": "装柜日期",
        "total_packages": "总件数",
        "total_cbm": "总体积",
        "total_weight": "总重量",
        "pkg_unit": "件",
        "remarks_section": "备注 / 压包要求",
        "qr_caption": "扫码查询物流追踪",
        "notice_section": "请注意以下信息",
        "notices": [
            "1. 货物入仓须提供准确货物名称、联系方式及目的港，装柜确认后24小时内如无异议即视为确认无误。",
            "2. 严禁夹带仿牌、违禁品、易燃易爆物品，海关查验或扣货产生的一切责任由货主自行承担。",
            "3. 本仓库按外包装件数及尺寸体积 (CBM) 核收，不拆箱清点内件数量，请发货人自行核对。",
            "4. 货物抵达目的港仓库后享有免费仓储期，逾期未提将按规定收取仓储及保管费。",
            "5. 请妥善保管本收据及追踪号，查询物流进度及目的港提货时均需出示。",
        ],
        "signoff_section": "签收与经办",
        "received_by": "开单收货人",
        "approved_by": "装柜审核人",
        "loaded_time": "装柜确认时间",
        "sig_sender": "送货人 / 供应商签名",
        "sig_warehouse": "仓库收货人签名",
        "subject_prefix": "入仓装柜收据 -",
        "default_customer": "客户",
    },
    "en": {
        "title": "Loading Receipt",
        "subtitle_ref": "Packing list",
        "issued_at": "Issued",
        "customer": "Customer name",
        "phone": "Customer phone",
        "supplier": "Supplier",
        "destination": "Destination / Warehouse",
        "container": "Container / Parcel No.",
        "tracking_code": "Tracking code",
        "delivery_date": "Delivery date",
        "loading_date": "Loading date",
        "cargo_section": "Loaded cargo",
        "col_tag": "Tag",
        "col_desc": "Description",
        "col_type": "Package",
        "col_qty": "Qty",
        "col_dims": "L × W × H cm",
        "col_cbm": "CBM",
        "col_weight": "Weight (kg)",
        "col_delivered": "Delivered",
        "col_loaded": "Loaded",
        "total_packages": "Total packages",
        "total_cbm": "Total CBM",
        "total_weight": "Total weight",
        "pkg_unit": "pkg",
        "remarks_section": "Remarks / Packing instructions",
        "qr_caption": "Scan to track shipment",
        "notice_section": "Important warehouse notice",
        "notices": [
            "1. Please verify item descriptions, dimensions, CBM, and destination port before container sealing.",
            "2. Counterfeit, fragile, flammable, explosive, or contraband goods are shipped strictly at the owner's risk.",
            "3. Cargo is verified by outer package count and measured dimensions (CBM); inner piece counts are not verified.",
            "4. Free storage applies during the arrival grace period; overdue goods attract daily warehouse storage fees.",
            "5. Keep this Loading Receipt and tracking code safe for shipment status inquiries and dispute resolution.",
        ],
        "signoff_section": "Warehouse sign-off",
        "received_by": "Received by",
        "approved_by": "Approved / Loaded by",
        "loaded_time": "Loaded at",
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


def generate_loading_receipt_pdf_with_meta(
    brand: t.Brand,
    pl: dict[str, Any],
    items: Sequence[dict[str, Any]],
    *,
    lang: Lang = "zh",
) -> t.RenderedPdf:
    """Render the Loading Receipt PDF and return both buffer and exact page count."""
    norm_lang: Lang = "en" if lang == "en" else "zh"
    s = _STRINGS[norm_lang]

    receipt_number = str(pl.get("loading_receipt_number") or pl.get("reference") or pl.get("id") or "")
    pl_ref = str(pl.get("reference") or t.MISSING)
    packages = sum(int(item.get("quantity") or 1) for item in items)
    total_cbm = _sum(items, "cbm")
    total_weight = _sum(items, "weight_actual_kg") or _sum(items, "weight_dispatch_kg")

    container_num = str(pl.get("container_number") or "")
    parcel_num = str(pl.get("container_parcel_number") or "")
    container_label = f"{container_num} / {parcel_num}" if (container_num and parcel_num) else (container_num or t.MISSING)

    dest_parts = [str(p).strip() for p in (pl.get("destination"), pl.get("arrival_warehouse_name")) if p]
    destination_label = " · ".join(dict.fromkeys(dest_parts)) or t.MISSING

    tracking_codes = list(dict.fromkeys(str(i["tracking_code"]) for i in items if i.get("tracking_code")))
    primary_tracking = tracking_codes[0] if tracking_codes else receipt_number
    tracking_label = ", ".join(tracking_codes) if tracking_codes else t.MISSING

    show_delivered = pl.get("delivery_date_mode") == "multiple_days" or _has_varying_dates(
        items, "received_date", pl.get("delivery_date")
    )
    show_loaded = any(item.get("loading_date") for item in items) or _has_varying_dates(
        items, "loading_date", pl.get("loading_date")
    )

    facts_pairs: list[tuple[str, str]] = [
        (s["customer"], str(pl.get("customer_name") or t.MISSING)),
        (s["phone"], str(pl.get("customer_phone") or t.MISSING)),
        (s["destination"], destination_label),
        (s["container"], container_label),
        (s["tracking_code"], tracking_label),
        (s["delivery_date"], _date_summary(pl.get("delivery_date"), [i.get("received_date") for i in items])),
        (
            s["loading_date"],
            _date_summary(pl.get("loading_date"), [i.get("loading_date") or pl.get("loading_date") for i in items]),
        ),
    ]
    if pl.get("supplier_name") or pl.get("supplier_phone"):
        supplier_str = " · ".join(str(p).strip() for p in (pl.get("supplier_name"), pl.get("supplier_phone")) if p)
        facts_pairs.append((s["supplier"], supplier_str))

    columns = [
        t.Column(s["col_tag"], 2.3),
        t.Column(s["col_desc"], 3.9 if (show_delivered or show_loaded) else 4.6),
        t.Column(s["col_type"], 1.3),
        t.Column(s["col_qty"], 0.75, "right"),
        t.Column(s["col_dims"], 2.1, "right"),
        t.Column(s["col_cbm"], 1.25, "right"),
        t.Column(s["col_weight"], 1.35, "right"),
    ]
    if show_delivered:
        columns.append(t.Column(s["col_delivered"], 1.45))
    if show_loaded:
        columns.append(t.Column(s["col_loaded"], 1.45))

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

    totals: list[object] = [
        f"{t.count(packages)} {s['pkg_unit']}",
        "",
        "",
        t.count(packages),
        "",
        t.cbm(total_cbm),
        t.kg(total_weight),
    ]
    if show_delivered:
        totals.append("")
    if show_loaded:
        totals.append("")

    # Compact totals + QR code strip
    summary_left = t.facts_grid(
        [
            (s["total_packages"], f"{t.count(packages)} {s['pkg_unit']}"),
            (s["total_cbm"], f"{t.cbm(total_cbm)} m³"),
            (s["total_weight"], f"{t.kg(total_weight)} kg"),
        ],
        columns=3,
    )
    qr_box: list[Flowable] = [t.qr_code(primary_tracking, size=2.1 * cm), t.para(s["qr_caption"], "label")]
    summary_strip = Table(
        [[summary_left, qr_box]],
        colWidths=[t.CONTENT_WIDTH - 2.8 * cm, 2.8 * cm],
    )
    summary_strip.setStyle(
        t.TableStyle(
            [
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("LEFTPADDING", (0, 0), (-1, -1), 0),
                ("RIGHTPADDING", (0, 0), (-1, -1), 0),
                ("TOPPADDING", (0, 0), (-1, -1), 6),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
            ]
        )
    )

    body: list[Flowable] = [
        t.facts_grid(facts_pairs),
        *t.section(s["cargo_section"]),
        t.DataTable(columns, rows, totals=totals, brand=brand.color).build(),
        Spacer(1, 0.2 * cm),
        summary_strip,
    ]

    remarks = str(pl.get("remarks") or "").strip()
    if remarks:
        body.extend([*t.section(s["remarks_section"]), t.para(remarks, "body")])

    body.extend(
        [
            *t.section(s["notice_section"]),
            t.para("\n".join(s["notices"]), "small"),
            *t.section(s["signoff_section"]),
            t.facts_grid(
                [
                    (s["received_by"], str(pl.get("created_by_name") or t.MISSING)),
                    (s["approved_by"], str(pl.get("approved_by_name") or t.MISSING)),
                    (s["loaded_time"], t.moment(pl.get("loaded_at") or pl.get("approved_at"))),
                ],
                columns=3,
            ),
            Spacer(1, 0.2 * cm),
            t.signature_lines([s["sig_sender"], s["sig_warehouse"]]),
        ]
    )

    header_facts = [
        (s["subtitle_ref"], pl_ref),
        (s["issued_at"], t.moment(pl.get("loaded_at") or pl.get("approved_at") or t.now())),
    ]
    return t.render_with_meta(
        _effective_brand(brand, norm_lang),
        s["title"],
        receipt_number,
        body,
        facts=header_facts,
        subject=f"{s['subject_prefix']} {pl.get('customer_name') or s['default_customer']}",
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
