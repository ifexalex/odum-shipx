"""The packing list PDF (audit FD-40, FD-41): the one packing-list document, built on ``pdf_theme``.

Contents: reference, status, customer and phone, container, arrival warehouse, loading and delivery dates; one row
per item (tag, description, package type, quantity, dimensions, CBM, dispatch and actual weight) with totals; who packed
it and who approved it, with dates.
"""

from collections.abc import Sequence
from io import BytesIO
from typing import Any

from . import pdf_theme as t

_COLUMNS = [
    t.Column("Tag", 2.6),
    t.Column("Description", 4.4),
    t.Column("Type", 1.3),
    t.Column("Qty", 0.8, "right"),
    t.Column("L × W × H cm", 2.0, "right"),
    t.Column("CBM", 1.3, "right"),
    t.Column("Dispatch kg", 1.4, "right"),
    t.Column("Actual kg", 1.4, "right"),
]


def _dimensions(item: dict[str, Any]) -> str:
    sides = [item.get("length_cm"), item.get("width_cm"), item.get("height_cm")]
    if any(side in (None, "") for side in sides):
        return t.MISSING
    return " × ".join(t.measure(side) for side in sides)


def _sum(items: Sequence[dict[str, Any]], key: str) -> float:
    return sum(float(item.get(key) or 0) for item in items)


def item_rows(items: Sequence[dict[str, Any]]) -> list[list[str]]:
    """One row per item, formatted as the app formats it."""
    return [
        [
            str(item.get("carton_tag") or t.MISSING),
            str(item.get("description") or ""),
            t.humanise(item.get("package_unit") or "carton"),
            t.count(item.get("quantity") or 1),
            _dimensions(item),
            t.cbm(item.get("cbm")),
            t.kg(item.get("weight_dispatch_kg")),
            t.kg(item.get("weight_actual_kg")),
        ]
        for item in items
    ]


def generate_packing_list_pdf(brand: t.Brand, pl: dict[str, Any], items: Sequence[dict[str, Any]]) -> BytesIO:
    """Render the packing list.

    Args:
        brand: The tenant's branding (``pdf_theme.Brand``).
        pl: The packing list row with ``customer_name``, ``customer_phone``, ``container_number``,
            ``arrival_warehouse_name``, ``created_by_name`` and ``approved_by_name``.
        items: Its items.
    """
    reference = str(pl.get("reference") or pl.get("id") or "")
    packages = sum(int(item.get("quantity") or 1) for item in items)
    body = [
        t.facts_grid(
            [
                ("Customer", str(pl.get("customer_name") or t.MISSING)),
                ("Phone", str(pl.get("customer_phone") or t.MISSING)),
                ("Container", str(pl.get("container_number") or "Not assigned yet")),
                ("Arrival warehouse", str(pl.get("arrival_warehouse_name") or t.MISSING)),
                ("Delivery date", t.day(pl.get("delivery_date"))),
                ("Loading date", t.day(pl.get("loading_date"))),
            ]
        ),
        *t.section("Items"),
        t.DataTable(
            _COLUMNS,
            item_rows(items),
            totals=[
                f"{t.count(packages)} {'package' if packages == 1 else 'packages'}",
                "",
                "",
                t.count(packages),
                "",
                t.cbm(_sum(items, "cbm")),
                t.kg(_sum(items, "weight_dispatch_kg")),
                t.kg(_sum(items, "weight_actual_kg")),
            ],
            brand=brand.color,
        ).build(),
        *t.section("Sign-off"),
        t.facts_grid(
            [
                ("Packed by", str(pl.get("created_by_name") or t.MISSING)),
                ("Packed on", t.day(pl.get("created_at"))),
                ("", ""),
                ("Approved by", str(pl.get("approved_by_name") or "Not approved yet")),
                ("Approved on", t.day(pl.get("approved_at"))),
                ("", ""),
            ]
        ),
    ]
    return t.render(
        brand,
        "Packing list",
        reference,
        body,
        facts=[("Status", t.humanise(pl.get("status"))), ("Printed", t.moment(t.now()))],
        subject=f"Packing list for {pl.get('customer_name') or 'a customer'}",
    )
