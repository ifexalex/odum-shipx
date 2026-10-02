"""040 — schema support for flexible manifest import.

Adds the fields needed to ingest a China-side freight-forwarder manifest
export (container-level PARTIAL NO manifest + per-customer packing list
rows) without requiring the container/customers/packing lists to already
exist in ShipX. Powers the new `POST /v1/manifests/import` flow
(`services/excel/import_manifest.py`), parallel to the existing
`POST /v1/packing-lists/import`.

container.departure_date: real source documents distinguish LOADING DATE
from DEPARTURE DATE (when the vessel actually leaves port). `ship_date`
keeps meaning "loading date" — no change there. `estimated_arrival_date`
already matches ARRIVAL DATE — no change. The manifest's secondary numeric
reference (e.g. "4287252") reuses the existing `container.parcel_number` —
no new column needed for it.

packing_list_item gets a bulk-quantity model (`quantity` + `package_unit`)
instead of forcing one row per physical carton — real manifest rows are
often a bulk count under one delivery note ("17CTNS", "3BAGS"). Also adds
`delivery_note_number` (the natural per-parcel business reference and the
new importer's re-import dedupe key), `bale_no`, `original_receipt_number`,
`delivery_zone`, and an on-hold flag/reason for red-marked rows in the
source.

`quantity_raw` keeps the verbatim source quantity cell ("1PALLET(61items)",
"3bags2ctns1pallet") alongside the parsed integer, so a mixed parcel that
normalizes to quantity=6/package_unit='mixed' does not lose what was actually
written. `bale_type` keeps the verbatim BALE TYPE value ("BIG BALE" / "LONG
BALE") while `package_unit` collapses to 'bale', so "count all bales" queries
stay correct without discarding a distinction the trade prices differently.

`original_receipt_number` (not `supplier_reference` — corrected before this
migration was ever committed) maps the manifest's "OG NO." column, which
is short for "Original Receipt Number" per the source packing-list
document's own spelled-out header, not a supplier concept at all.

All new columns nullable or defaulted — existing rows, the existing
importer, and all manual/spreadsheet packing-list flows are unaffected.

Revision ID: 040
Revises: 039
Create Date: 2026-08-23 00:00:00
"""

from alembic import op

revision = "040"
down_revision = "039"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE container
        ADD COLUMN IF NOT EXISTS departure_date DATE
        """
    )
    op.execute(
        """
        ALTER TABLE packing_list_item
          ADD COLUMN IF NOT EXISTS delivery_note_number VARCHAR(50),
          ADD COLUMN IF NOT EXISTS quantity INTEGER NOT NULL DEFAULT 1,
          ADD COLUMN IF NOT EXISTS package_unit VARCHAR(20),
          ADD COLUMN IF NOT EXISTS quantity_raw VARCHAR(50),
          ADD COLUMN IF NOT EXISTS bale_type VARCHAR(30),
          ADD COLUMN IF NOT EXISTS bale_no VARCHAR(20),
          ADD COLUMN IF NOT EXISTS original_receipt_number VARCHAR(100),
          ADD COLUMN IF NOT EXISTS delivery_zone VARCHAR(100),
          ADD COLUMN IF NOT EXISTS on_hold BOOLEAN NOT NULL DEFAULT FALSE,
          ADD COLUMN IF NOT EXISTS hold_reason TEXT
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_packing_list_item_delivery_note
            ON packing_list_item(delivery_note_number)
            WHERE delivery_note_number IS NOT NULL
        """
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS idx_packing_list_item_delivery_note")
    op.execute(
        """
        ALTER TABLE packing_list_item
          DROP COLUMN IF EXISTS delivery_note_number,
          DROP COLUMN IF EXISTS quantity,
          DROP COLUMN IF EXISTS package_unit,
          DROP COLUMN IF EXISTS quantity_raw,
          DROP COLUMN IF EXISTS bale_type,
          DROP COLUMN IF EXISTS bale_no,
          DROP COLUMN IF EXISTS original_receipt_number,
          DROP COLUMN IF EXISTS delivery_zone,
          DROP COLUMN IF EXISTS on_hold,
          DROP COLUMN IF EXISTS hold_reason
        """
    )
    op.execute("ALTER TABLE container DROP COLUMN IF EXISTS departure_date")
