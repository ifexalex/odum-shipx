"""068 — an invoice records where its exchange rate came from (audit BE-11).

When the live rate could not be fetched, invoicing used the last stored rate, or a hard-coded one if none had ever
been fetched, and the invoice kept no trace of which. Two columns record it:

* ``billing.exchange_rate_source``: ``live``, ``last_known`` or ``hardcoded`` (``shared.fx_rate.RATE_SOURCE_*``).
  Invoicing now refuses ``hardcoded``, so new invoices carry only the first two; the CHECK still lists it so a
  historical value could be written if one were ever reconstructed.
* ``billing.exchange_rate_fetched_at``: when the rate the invoice used was fetched from the market.

Both are NULL for invoices issued before this migration: nothing recorded where their rate came from.

Revision ID: 068
Revises: 067
Create Date: 2026-11-17 22:00:00
"""

from alembic import op

revision = "068"
down_revision = "067"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE billing
            ADD COLUMN IF NOT EXISTS exchange_rate_source VARCHAR(20)
                CONSTRAINT ck_billing_exchange_rate_source
                CHECK (exchange_rate_source IN ('live', 'last_known', 'hardcoded')),
            ADD COLUMN IF NOT EXISTS exchange_rate_fetched_at TIMESTAMPTZ
        """
    )
    op.execute(
        "COMMENT ON COLUMN billing.exchange_rate_source IS "
        "'Where exchange_rate_ngn came from: live, last_known or hardcoded (audit BE-11). NULL before migration 068.'"
    )
    op.execute(
        "COMMENT ON COLUMN billing.exchange_rate_fetched_at IS "
        "'When the market rate behind exchange_rate_ngn was fetched. NULL before migration 068 and for hardcoded.'"
    )


def downgrade() -> None:
    op.execute(
        """
        ALTER TABLE billing
            DROP COLUMN IF EXISTS exchange_rate_fetched_at,
            DROP COLUMN IF EXISTS exchange_rate_source
        """
    )
