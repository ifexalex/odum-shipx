"""GDPR compliance additions.

Changes:
  customer            — add anonymised_at TIMESTAMPTZ (right to erasure tracking)
  customer            — add consent_given_at TIMESTAMPTZ
  customer            — add notification_consent TEXT[] (channels: 'sms','whatsapp','email')
  tenant_user         — add consent_given_at TIMESTAMPTZ
  tenant_user         — add marketing_consent BOOLEAN DEFAULT FALSE

Revision ID: 012
Revises: 011
Create Date: 2024-01-01 00:00:11
"""

from alembic import op

revision = "012"
down_revision = "011"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ---------------------------------------------------------------------------
    # customer — right to erasure + consent tracking
    # ---------------------------------------------------------------------------
    op.execute(
        "ALTER TABLE customer ADD COLUMN IF NOT EXISTS anonymised_at TIMESTAMPTZ"
    )
    op.execute(
        "ALTER TABLE customer ADD COLUMN IF NOT EXISTS consent_given_at TIMESTAMPTZ"
    )
    op.execute(
        "ALTER TABLE customer ADD COLUMN IF NOT EXISTS notification_consent TEXT[] DEFAULT '{}'"
    )

    # ---------------------------------------------------------------------------
    # tenant_user — consent tracking
    # ---------------------------------------------------------------------------
    op.execute(
        "ALTER TABLE tenant_user ADD COLUMN IF NOT EXISTS consent_given_at TIMESTAMPTZ"
    )
    op.execute(
        "ALTER TABLE tenant_user ADD COLUMN IF NOT EXISTS marketing_consent BOOLEAN DEFAULT FALSE"
    )


def downgrade() -> None:
    op.execute(
        "ALTER TABLE tenant_user DROP COLUMN IF EXISTS marketing_consent"
    )
    op.execute(
        "ALTER TABLE tenant_user DROP COLUMN IF EXISTS consent_given_at"
    )
    op.execute(
        "ALTER TABLE customer DROP COLUMN IF EXISTS notification_consent"
    )
    op.execute(
        "ALTER TABLE customer DROP COLUMN IF EXISTS consent_given_at"
    )
    op.execute(
        "ALTER TABLE customer DROP COLUMN IF EXISTS anonymised_at"
    )
