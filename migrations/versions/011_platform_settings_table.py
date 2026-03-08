"""Add platform_settings table, carryover exemption columns, and relax misc_charge CHECK.

Changes:
  platform_settings   — new key/value table for platform-wide configuration
  carryover_ledger    — add 'exempted' status, exempted_by, exempted_at columns
  misc_charge         — drop charge_type CHECK to allow free-form charge types

Revision ID: 011
Revises: 010
Create Date: 2024-01-01 00:00:10
"""

from alembic import op

revision = "011"
down_revision = "010"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ---------------------------------------------------------------------------
    # platform_settings — platform-wide configuration key/value store
    # ---------------------------------------------------------------------------
    op.execute("""
        CREATE TABLE platform_settings (
            key        VARCHAR(100) PRIMARY KEY,
            value      JSONB NOT NULL,
            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_by UUID
        )
    """)
    op.execute("""
        INSERT INTO platform_settings (key, value) VALUES
            ('default_subscription_tier', '"starter"'),
            ('max_tenants', '50'),
            ('maintenance_mode', 'false'),
            ('platform_email_from', '"notifications@logistics.example.com"')
    """)

    # ---------------------------------------------------------------------------
    # carryover_ledger — add 'exempted' status + exemption audit columns
    # ---------------------------------------------------------------------------
    op.execute("ALTER TABLE carryover_ledger DROP CONSTRAINT carryover_ledger_status_check")
    op.execute("""
        ALTER TABLE carryover_ledger ADD CONSTRAINT carryover_ledger_status_check
        CHECK (status IN ('outstanding', 'applied', 'waived', 'written_off', 'exempted'))
    """)
    op.execute(
        "ALTER TABLE carryover_ledger ADD COLUMN exempted_by UUID REFERENCES tenant_user(id)"
    )
    op.execute(
        "ALTER TABLE carryover_ledger ADD COLUMN exempted_at TIMESTAMPTZ"
    )

    # ---------------------------------------------------------------------------
    # misc_charge — drop charge_type CHECK to allow free-form charge types
    # ---------------------------------------------------------------------------
    op.execute(
        "ALTER TABLE misc_charge DROP CONSTRAINT IF EXISTS misc_charge_charge_type_check"
    )
    # Add amount_usd column for USD tracking on misc charges
    op.execute(
        "ALTER TABLE misc_charge ADD COLUMN IF NOT EXISTS amount_usd DECIMAL(15, 2)"
    )


def downgrade() -> None:
    op.execute("ALTER TABLE misc_charge DROP COLUMN IF EXISTS amount_usd")
    op.execute("""
        ALTER TABLE misc_charge ADD CONSTRAINT misc_charge_charge_type_check
        CHECK (charge_type IN (
            'storage_fee', 'handling', 'customs', 'delivery',
            'cbm_dispute_adjustment', 'other'
        ))
    """)

    op.execute("ALTER TABLE carryover_ledger DROP COLUMN IF EXISTS exempted_at")
    op.execute("ALTER TABLE carryover_ledger DROP COLUMN IF EXISTS exempted_by")
    op.execute("ALTER TABLE carryover_ledger DROP CONSTRAINT carryover_ledger_status_check")
    op.execute("""
        ALTER TABLE carryover_ledger ADD CONSTRAINT carryover_ledger_status_check
        CHECK (status IN ('outstanding', 'applied', 'waived', 'written_off'))
    """)

    op.execute("DROP TABLE IF EXISTS platform_settings")
