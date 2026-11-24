"""The manifest PDF (audit FD-39, FD-40, FD-41): a container's manifest, built on ``pdf_theme``.

It replaced the generic table export's manifest PDF, whose carton-tag column ran off the page.

Contents: container, vessel, voyage, shipping line, origin and destination, departure and arrival dates; one row per
customer (cartons, weight, CBM) with totals; the verification status and who verified it, when.
"""

from collections.abc import Sequence
from io import BytesIO
from typing import Any

from . import pdf_theme as t


def customer_rows(items: Sequence[dict[str, Any]]) -> list[dict[str, Any]]:
    """One summary per customer, in the order the items arrive (by customer name)."""
    rows: dict[str, dict[str, Any]] = {}
    for item in items:
        name = str(item.get("customer_name") or t.MISSING)
        row = rows.setdefault(name, {"customer_name": name, "cartons": 0, "weight_kg": 0.0, "cbm": 0.0})
        row["cartons"] += int(item.get("quantity") or 1)
        row["weight_kg"] += float(item.get("weight_actual_kg") or item.get("weight_dispatch_kg") or 0)
        row["cbm"] += float(item.get("cbm") or 0)
    return list(rows.values())


def generate_manifest_pdf(brand: t.Brand, manifest: dict[str, Any], items: Sequence[dict[str, Any]]) -> BytesIO:
    """Render the manifest.

    Args:
        brand: The tenant's branding (``pdf_theme.Brand``).
        manifest: The manifest row as ``get_manifest_for_export`` returns it (with the container's details).
        items: Every packing-list item in the container, with ``customer_name``.
    """
    container = str(manifest.get("container_number") or t.MISSING)
    rows = customer_rows(items)
    arrived = manifest.get("actual_arrival_date")
    body = [
        t.facts_grid(
            [
                ("Container", container),
                ("Vessel", str(manifest.get("vessel_name") or t.MISSING)),
                ("Voyage", str(manifest.get("voyage_number") or t.MISSING)),
                ("Shipping line", str(manifest.get("shipping_line") or t.MISSING)),
                ("Route", " to ".join(str(manifest[k]) for k in ("origin", "destination") if manifest.get(k)) or t.MISSING),
                ("Departed", t.day(manifest.get("departure_date") or manifest.get("ship_date"))),
                ("Arrived" if arrived else "Expected", t.day(arrived or manifest.get("estimated_arrival_date"))),
            ]
        ),
        *t.section(f"Customers ({t.count(len(rows))})"),
        t.DataTable(
            [
                t.Column("Customer", 4.0),
                t.Column("Cartons", 1.2, "right"),
                t.Column("Weight kg", 1.4, "right"),
                t.Column("CBM", 1.2, "right"),
            ],
            [[r["customer_name"], t.count(r["cartons"]), t.kg(r["weight_kg"]), t.cbm(r["cbm"])] for r in rows],
            totals=[
                "Total",
                t.count(sum(r["cartons"] for r in rows)),
                t.kg(sum(r["weight_kg"] for r in rows)),
                t.cbm(sum(r["cbm"] for r in rows)),
            ],
            brand=brand.color,
        ).build(),
        *t.section("Verification"),
        t.facts_grid(
            [
                ("Status", t.humanise(manifest.get("verification_status"))),
                ("Verified by", str(manifest.get("verified_by_name") or "Not verified yet")),
                ("Verified on", t.day(manifest.get("verified_at"))),
            ]
        ),
    ]
    return t.render(
        brand,
        "Manifest",
        container,
        body,
        facts=[("Printed", t.moment(t.now()))],
        subject=f"Manifest for container {container}",
    )
