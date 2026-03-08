"""Fix release_note, shipment_tracking, payment_record, and pickup_record schemas
to match the payment_release service models.py enums and optional fields.

Adds/fixes:
  release_note.status CHECK  → active, picked_up, expired, cancelled
  release_note.status DEFAULT → 'active'
  shipment_tracking.status CHECK → add 'picked_up'
  payment_record.payment_method → make nullable
  pickup_record.collected_by_name → make nullable

Revision ID: 008
Revises: 007
Create Date: 2024-01-01 00:00:07
"""

from alembic import op

revision = "008"
down_revision = "007"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ---------------------------------------------------------------------------
    # release_note — replace status CHECK + update default
    # ---------------------------------------------------------------------------
    op.execute(
        "ALTER TABLE release_note DROP CONSTRAINT release_note_status_check"
    )
    op.execute("""
        ALTER TABLE release_note ADD CONSTRAINT release_note_status_check
        CHECK (status IN (
            'active',
            'picked_up',
            'expired',
            'cancelled'
        ))
    """)
    op.execute(
        "ALTER TABLE release_note ALTER COLUMN status SET DEFAULT 'active'"
    )

    # ---------------------------------------------------------------------------
    # shipment_tracking — add 'picked_up' to status CHECK
    # ---------------------------------------------------------------------------
    op.execute(
        "ALTER TABLE shipment_tracking DROP CONSTRAINT shipment_tracking_status_check"
    )
    op.execute("""
        ALTER TABLE shipment_tracking ADD CONSTRAINT shipment_tracking_status_check
        CHECK (status IN (
            'received',
            'in_transit',
            'arrived_port',
            'customs_clearance',
            'at_warehouse',
            'ready_for_pickup',
            'released',
            'picked_up'
        ))
    """)

    # ---------------------------------------------------------------------------
    # payment_record — make payment_method nullable
    # ---------------------------------------------------------------------------
    op.execute(
        "ALTER TABLE payment_record ALTER COLUMN payment_method DROP NOT NULL"
    )

    # ---------------------------------------------------------------------------
    # pickup_record — make collected_by_name nullable
    # ---------------------------------------------------------------------------
    op.execute(
        "ALTER TABLE pickup_record ALTER COLUMN collected_by_name DROP NOT NULL"
    )


def downgrade() -> None:
    # pickup_record
    op.execute(
        "ALTER TABLE pickup_record ALTER COLUMN collected_by_name SET NOT NULL"
    )

    # payment_record
    op.execute(
        "ALTER TABLE payment_record ALTER COLUMN payment_method SET NOT NULL"
    )

    # shipment_tracking
    op.execute(
        "ALTER TABLE shipment_tracking DROP CONSTRAINT shipment_tracking_status_check"
    )
    op.execute("""
        ALTER TABLE shipment_tracking ADD CONSTRAINT shipment_tracking_status_check
        CHECK (status IN (
            'received',
            'in_transit',
            'arrived_port',
            'customs_clearance',
            'at_warehouse',
            'ready_for_pickup',
            'released'
        ))
    """)

    # release_note
    op.execute(
        "ALTER TABLE release_note DROP CONSTRAINT release_note_status_check"
    )
    op.execute("""
        ALTER TABLE release_note ADD CONSTRAINT release_note_status_check
        CHECK (status IN (
            'issued',
            'partially_picked_up',
            'fully_picked_up',
            'expired',
            'cancelled'
        ))
    """)
    op.execute(
        "ALTER TABLE release_note ALTER COLUMN status SET DEFAULT 'issued'"
    )
