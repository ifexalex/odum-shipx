"""073 — transit dates, delivery date modes, loading receipts & per-item loading dates (ENG-2/3/4).

Adds:
1. ``packing_list.ship_date`` & ``packing_list.estimated_arrival_date`` — stamped automatically when
   the parent container transitions to ``in_transit`` (``ship_date + tenant default_transit_days``).
2. ``packing_list.delivery_date_mode`` (``same_day`` | ``multiple_days``) — governs whether one
   header delivery date or per-line-item delivery dates are captured.
3. ``packing_list.loading_receipt_number`` (``LR-YYYYMMDD-NNN``, unique per tenant when set) &
   ``packing_list.loaded_at`` — stamped automatically when a packing list is approved.
4. ``packing_list.supplier_name``, ``supplier_phone``, ``remarks`` — optional origin warehouse
   intake metadata reflected on Loading Receipts and Packing Lists.
5. ``packing_list_item.loading_date`` — optional per-item loading date override (falls back to
   ``packing_list.loading_date``).

Revision ID: 073
Revises: 072
Create Date: 2026-11-27 19:10:00
"""

from alembic import op
from sqlalchemy import text

revision = "073"
down_revision = "072"
branch_labels = None
depends_on = None

_TENANT_SETTING = "app.current_tenant_id"


def upgrade() -> None:
    bind = op.get_bind()
    previous = bind.execute(text("SELECT current_setting(:name, TRUE)"), {"name": _TENANT_SETTING}).scalar()
    bind.execute(text("SELECT set_config(:name, 'PLATFORM', TRUE)"), {"name": _TENANT_SETTING})

    op.execute("ALTER TABLE packing_list ADD COLUMN IF NOT EXISTS ship_date DATE")
    op.execute("ALTER TABLE packing_list ADD COLUMN IF NOT EXISTS estimated_arrival_date DATE")
    op.execute(
        """
        ALTER TABLE packing_list
            ADD COLUMN IF NOT EXISTS delivery_date_mode VARCHAR(20) NOT NULL DEFAULT 'same_day'
        """
    )
    op.execute(
        """
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM pg_constraint WHERE conname = 'ck_packing_list_delivery_date_mode'
            ) THEN
                ALTER TABLE packing_list
                    ADD CONSTRAINT ck_packing_list_delivery_date_mode
                    CHECK (delivery_date_mode IN ('same_day', 'multiple_days'));
            END IF;
        END $$;
        """
    )
    op.execute("ALTER TABLE packing_list ADD COLUMN IF NOT EXISTS loading_receipt_number VARCHAR(40)")
    op.execute("ALTER TABLE packing_list ADD COLUMN IF NOT EXISTS loaded_at TIMESTAMPTZ")
    op.execute("ALTER TABLE packing_list ADD COLUMN IF NOT EXISTS supplier_name VARCHAR(200)")
    op.execute("ALTER TABLE packing_list ADD COLUMN IF NOT EXISTS supplier_phone VARCHAR(40)")
    op.execute("ALTER TABLE packing_list ADD COLUMN IF NOT EXISTS remarks TEXT")
    op.execute(
        """
        CREATE UNIQUE INDEX IF NOT EXISTS uq_packing_list_loading_receipt_number
            ON packing_list (tenant_id, loading_receipt_number)
            WHERE loading_receipt_number IS NOT NULL
        """
    )

    op.execute("ALTER TABLE packing_list_item ADD COLUMN IF NOT EXISTS loading_date DATE")

    bind.execute(text("SELECT set_config(:name, :value, TRUE)"), {"name": _TENANT_SETTING, "value": previous or ""})


def downgrade() -> None:
    op.execute("ALTER TABLE packing_list_item DROP COLUMN IF EXISTS loading_date")
    op.execute("DROP INDEX IF EXISTS uq_packing_list_loading_receipt_number")
    op.execute("ALTER TABLE packing_list DROP CONSTRAINT IF EXISTS ck_packing_list_delivery_date_mode")
    op.execute("ALTER TABLE packing_list DROP COLUMN IF EXISTS remarks")
    op.execute("ALTER TABLE packing_list DROP COLUMN IF EXISTS supplier_phone")
    op.execute("ALTER TABLE packing_list DROP COLUMN IF EXISTS supplier_name")
    op.execute("ALTER TABLE packing_list DROP COLUMN IF EXISTS loaded_at")
    op.execute("ALTER TABLE packing_list DROP COLUMN IF EXISTS loading_receipt_number")
    op.execute("ALTER TABLE packing_list DROP COLUMN IF EXISTS delivery_date_mode")
    op.execute("ALTER TABLE packing_list DROP COLUMN IF EXISTS estimated_arrival_date")
    op.execute("ALTER TABLE packing_list DROP COLUMN IF EXISTS ship_date")
