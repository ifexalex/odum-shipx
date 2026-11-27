"""The packing list PDF (audit FD-40, FD-41; upgraded for ENG-2 / ENG-3 / ENG-4 / ENG-5).

Supports English (``lang="en"``, default) and Chinese (``lang="zh"``) rendering, finalized
post-shipment metadata (Shipping Date, dynamically calculated ETA, Container & Parcel No.,
Shipping Line / Vessel / Voyage), per-item delivery dates & loading dates when items vary,
item dimensions (L × W × H cm), linked Loading Receipt reference, remarks, and sign-off.
"""

from collections.abc import Sequence
from io import BytesIO
from typing import Any, Literal

from reportlab.platypus import Flowable, Spacer

from . import pdf_theme as t

Lang = Literal["en", "zh"]

_STRINGS: dict[Lang, dict[str, str]] = {
    "en": {
        "title": "Packing list",
        "status": "Status",
        "printed": "Printed",
        "stage_finalized": "Finalized (In transit)",
        "stage_preliminary": "Preliminary",
        "pending_departure": "Pending departure",
        "not_assigned": "Not assigned yet",
        "not_approved": "Not approved yet",
        "customer": "Customer",
        "phone": "Phone",
        "supplier": "Supplier",
        "destination": "Destination / Warehouse",
        "container": "Container / Parcel No.",
        "tracking_code": "Tracking code",
        "loading_receipt": "Loading receipt",
        "ship_date": "Shipping date",
        "eta": "Estimated arrival (ETA)",
        "vessel_line": "Shipping line / Vessel",
        "delivery_date": "Delivery date",
        "loading_date": "Loading date",
        "items_section": "Items",
        "col_tag": "Tag",
        "col_desc": "Description",
        "col_type": "Type",
        "col_qty": "Qty",
        "col_dims": "L × W × H cm",
        "col_cbm": "CBM",
        "col_dispatch_kg": "Dispatch kg",
        "col_actual_kg": "Actual kg",
        "col_delivered": "Delivered",
        "col_loaded": "Loaded",
        "package_singular": "package",
        "package_plural": "packages",
        "remarks_section": "Remarks",
        "terms_section": "Terms & Conditions",
        "terms_body": (
            "1. Please quote your tracking code or loading receipt number when inquiring about this shipment. "
            "2. Confirm CBM and item details at the origin warehouse; adjustments cannot be made after loading. "
            "3. Prohibited, counterfeit, flammable, or undeclared goods are shipped strictly at the owner's risk. "
            "4. Free storage applies during the grace period after arrival; late collection attracts storage fees."
        ),
        "signoff_section": "Sign-off",
        "packed_by": "Packed by",
        "packed_on": "Packed on",
        "approved_by": "Approved by",
        "approved_on": "Approved on",
        "sig_customer": "Customer / Supplier Signature",
        "sig_company": "Authorized Warehouse Representative",
        "subject_prefix": "Packing list for",
        "default_customer": "a customer",
    },
    "zh": {
        "title": "装箱单 Packing List",
        "status": "状态",
        "printed": "打印时间",
        "stage_finalized": "已发运（最终版）",
        "stage_preliminary": "预备单",
        "pending_departure": "待发运",
        "not_assigned": "未分配",
        "not_approved": "未批准",
        "customer": "客户姓名",
        "phone": "联系电话",
        "supplier": "供应商",
        "destination": "目的港 / 到达仓库",
        "container": "柜号 / 分单号",
        "tracking_code": "追踪号",
        "loading_receipt": "装柜收据号",
        "ship_date": "开船日期",
        "eta": "预计到达 (ETA)",
        "vessel_line": "船司 / 船名航次",
        "delivery_date": "收货日期",
        "loading_date": "装柜日期",
        "items_section": "货物明细",
        "col_tag": "编号",
        "col_desc": "货物名称",
        "col_type": "包装",
        "col_qty": "数量",
        "col_dims": "尺寸 (cm)",
        "col_cbm": "体积 CBM",
        "col_dispatch_kg": "出货重量 kg",
        "col_actual_kg": "实重 kg",
        "col_delivered": "收货日期",
        "col_loaded": "装柜日期",
        "package_singular": "件",
        "package_plural": "件",
        "remarks_section": "备注",
        "terms_section": "注意事项",
        "terms_body": (
            "1. 查询或提货时请提供追踪号或装柜收据号。"
            "2. 请在装柜前核对体积 (CBM) 与货物信息，装柜后不予更改。"
            "3. 严禁夹带违禁品、仿牌、易燃易爆物品，由此产生的一切责任由货主承担。"
            "4. 货物抵达目的仓库后享有免租期，逾期提货将按规定收取仓储费。"
        ),
        "signoff_section": "签收确认",
        "packed_by": "开单人",
        "packed_on": "开单日期",
        "approved_by": "审核人",
        "approved_on": "审核日期",
        "sig_customer": "客户 / 供应商签名",
        "sig_company": "仓库经办人签名",
        "subject_prefix": "装箱单 -",
        "default_customer": "客户",
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
    unique = _unique_dates([item.get(key) or header_val for item in items])
    return len(unique) > 1


def _columns_for(lang: Lang, *, show_delivered: bool, show_loaded: bool) -> list[t.Column]:
    s = _STRINGS[lang]
    cols = [
        t.Column(s["col_tag"], 2.3),
        t.Column(s["col_desc"], 3.45 if (show_delivered and show_loaded) else (3.8 if (show_delivered or show_loaded) else 4.4)),
        t.Column(s["col_type"], 1.15),
        t.Column(s["col_qty"], 0.7, "right"),
        t.Column(s["col_dims"], 1.9, "right"),
        t.Column(s["col_cbm"], 1.15, "right"),
        t.Column(s["col_dispatch_kg"], 1.45, "right"),
        t.Column(s["col_actual_kg"], 1.35, "right"),
    ]
    if show_delivered:
        cols.append(t.Column(s["col_delivered"], 1.45))
    if show_loaded:
        cols.append(t.Column(s["col_loaded"], 1.45))
    return cols


_COLUMNS = _columns_for("en", show_delivered=False, show_loaded=False)


def item_rows(
    items: Sequence[dict[str, Any]],
    *,
    show_delivered: bool = False,
    show_loaded: bool = False,
    default_loading_date: Any = None,
) -> list[list[str]]:
    """One row per item, formatted as the app formats it."""
    rows: list[list[str]] = []
    for item in items:
        row = [
            str(item.get("carton_tag") or t.MISSING),
            str(item.get("description") or ""),
            t.humanise(item.get("bale_type") or item.get("package_unit") or "carton"),
            t.count(item.get("quantity") or 1),
            _dimensions(item),
            t.cbm(item.get("cbm")),
            t.kg(item.get("weight_dispatch_kg")),
            t.kg(item.get("weight_actual_kg")),
        ]
        if show_delivered:
            row.append(t.day(item.get("received_date")))
        if show_loaded:
            row.append(t.day(item.get("loading_date") or default_loading_date))
        rows.append(row)
    return rows


def format_destination_warehouse(pl: dict[str, Any]) -> tuple[str, str]:
    """Return ``(headline, address_line)`` formatted as ``Nigeria · Lagos — Warehouse`` + street address.

    Deduplicates country / state / city / container destination tokens case-insensitively so
    fields like ``destination="Nigeria"`` + ``country="Nigeria"`` or ``city="Lagos"`` + ``state="Lagos"``
    never repeat awkwardly.
    """

    def _clean(key: str) -> str:
        val = pl.get(key)
        return str(val).strip() if val not in (None, "") else ""

    country = _clean("arrival_warehouse_country")
    dest = _clean("destination")
    city = _clean("arrival_warehouse_city")
    state = _clean("arrival_warehouse_state")
    wh_name = _clean("arrival_warehouse_name")
    wh_addr = _clean("arrival_warehouse_address")

    loc_parts: list[str] = []
    seen_lower: set[str] = set()

    def _add_loc(part: str) -> None:
        if not part:
            return
        low = part.lower()
        if low not in seen_lower and all(low not in existing for existing in seen_lower):
            loc_parts.append(part)
            seen_lower.add(low)

    # Order: Country → City/State → Container destination fallback
    _add_loc(country)
    if not country and dest:
        _add_loc(dest)
    _add_loc(city)
    _add_loc(state)
    if country and dest:
        _add_loc(dest)

    loc_str = " · ".join(loc_parts)
    if wh_name and wh_name.lower() not in seen_lower:
        headline = f"{loc_str} — {wh_name}" if loc_str else wh_name
    else:
        headline = loc_str or t.MISSING

    return headline, wh_addr


def _effective_brand(brand: t.Brand, lang: Lang) -> t.Brand:
    """Enrich brand with bilingual name & origin warehouse info when configured."""
    name = brand.name
    if brand.chinese_name:
        name = f"{brand.chinese_name} · {brand.name}" if lang == "zh" else f"{brand.name} · {brand.chinese_name}"
    address = brand.china_warehouse_address or brand.address
    phone = brand.china_warehouse_phone or brand.phone
    return t.Brand(
        name=name,
        tagline=brand.tagline,
        address=address,
        phone=phone,
        email=brand.email,
        footer=brand.footer,
        color=brand.color,
        logo=brand.logo,
        chinese_name=brand.chinese_name,
        china_warehouse_address=brand.china_warehouse_address,
        china_warehouse_phone=brand.china_warehouse_phone,
    )


def generate_packing_list_pdf_with_meta(
    brand: t.Brand,
    pl: dict[str, Any],
    items: Sequence[dict[str, Any]],
    *,
    lang: Lang = "en",
) -> t.RenderedPdf:
    """Render the packing list and return both PDF bytes and exact page count."""
    norm_lang: Lang = "zh" if lang == "zh" else "en"
    s = _STRINGS[norm_lang]
    reference = str(pl.get("reference") or pl.get("id") or "")
    packages = sum(int(item.get("quantity") or 1) for item in items)

    ship_date_raw = pl.get("ship_date") or pl.get("container_ship_date")
    eta_raw = pl.get("estimated_arrival_date") or pl.get("container_eta")
    is_finalized = bool(ship_date_raw)

    container_num = str(pl.get("container_number") or "")
    parcel_num = str(pl.get("container_parcel_number") or "")
    if container_num and parcel_num:
        container_label = f"{container_num} / {parcel_num}"
    else:
        container_label = container_num or parcel_num or s["not_assigned"]

    dest_headline, dest_address = format_destination_warehouse(pl)
    destination_label = f"{dest_headline}\n{dest_address}" if dest_address else dest_headline

    vessel_parts = [str(p).strip() for p in (pl.get("shipping_line"), pl.get("vessel_name"), pl.get("voyage_number")) if p]
    vessel_label = " / ".join(vessel_parts)

    tracking_codes = list(dict.fromkeys(str(i["tracking_code"]) for i in items if i.get("tracking_code")))
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
        (s["ship_date"], t.day(ship_date_raw) if ship_date_raw else s["pending_departure"]),
        (s["eta"], t.day(eta_raw) if eta_raw else s["pending_departure"]),
        (s["delivery_date"], _date_summary(pl.get("delivery_date"), [i.get("received_date") for i in items])),
        (
            s["loading_date"],
            _date_summary(pl.get("loading_date"), [i.get("loading_date") or pl.get("loading_date") for i in items]),
        ),
        (s["tracking_code"], tracking_label),
    ]
    if pl.get("loading_receipt_number"):
        facts_pairs.append((s["loading_receipt"], str(pl["loading_receipt_number"])))
    if vessel_label:
        facts_pairs.append((s["vessel_line"], vessel_label))

    columns = _columns_for(norm_lang, show_delivered=show_delivered, show_loaded=show_loaded)
    totals: list[object] = [
        f"{t.count(packages)} {s['package_singular'] if packages == 1 else s['package_plural']}",
        "",
        "",
        t.count(packages),
        "",
        t.cbm(_sum(items, "cbm")),
        t.kg(_sum(items, "weight_dispatch_kg")),
        t.kg(_sum(items, "weight_actual_kg")),
    ]
    if show_delivered:
        totals.append("")
    if show_loaded:
        totals.append("")

    body: list[Flowable] = [
        t.facts_grid(facts_pairs),
        *t.section(s["items_section"]),
        t.DataTable(
            columns,
            item_rows(
                items,
                show_delivered=show_delivered,
                show_loaded=show_loaded,
                default_loading_date=pl.get("loading_date"),
            ),
            totals=totals,
            brand=brand.color,
        ).build(),
    ]

    remarks = str(pl.get("remarks") or "").strip()
    if remarks:
        body.extend([*t.section(s["remarks_section"]), t.para(remarks, "body")])

    body.extend(
        [
            *t.section(s["terms_section"]),
            t.para(s["terms_body"], "small"),
            *t.section(s["signoff_section"]),
            t.facts_grid(
                [
                    (s["packed_by"], str(pl.get("created_by_name") or t.MISSING)),
                    (s["packed_on"], t.day(pl.get("created_at"))),
                    ("", ""),
                    (s["approved_by"], str(pl.get("approved_by_name") or s["not_approved"])),
                    (s["approved_on"], t.day(pl.get("approved_at"))),
                    ("", ""),
                ]
            ),
            Spacer(1, 0.25 * cm_unit()),
            t.signature_lines([s["sig_customer"], s["sig_company"]]),
        ]
    )

    header_facts = [
        (s["status"], s["stage_finalized"] if is_finalized else t.humanise(pl.get("status"))),
        (s["printed"], t.moment(t.now())),
    ]
    return t.render_with_meta(
        _effective_brand(brand, norm_lang),
        s["title"],
        reference,
        body,
        facts=header_facts,
        subject=f"{s['subject_prefix']} {pl.get('customer_name') or s['default_customer']}",
    )


def cm_unit() -> float:
    from reportlab.lib.units import cm

    return float(cm)


def generate_packing_list_pdf(
    brand: t.Brand,
    pl: dict[str, Any],
    items: Sequence[dict[str, Any]],
    *,
    lang: Lang = "en",
) -> BytesIO:
    """Render the packing list PDF as a BytesIO buffer."""
    return generate_packing_list_pdf_with_meta(brand, pl, items, lang=lang).buf
