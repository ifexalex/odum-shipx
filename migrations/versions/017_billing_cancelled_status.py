"""Add 'cancelled' to billing.status CHECK constraint.

Supports the PATCH /v1/billing/{id}/cancel endpoint that allows staff to void
incorrect auto-generated invoices that have not yet received any payment and
have no active release notes.

Revision ID: 017
Revises: 016
Create Date: 2024-01-01 00:00:16
"""

from alembic import op

revision = "017"
down_revision = "016"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE billing DROP CONSTRAINT billing_status_check")
    op.execute(
        """
        ALTER TABLE billing ADD CONSTRAINT billing_status_check
        CHECK (status IN (
            'unpaid',
            'partially_paid',
            'paid',
            'overpaid',
            'waived',
            'released_with_outstanding',
            'cancelled'
        ))
    """
    )
    op.execute("ALTER TABLE billing ADD COLUMN IF NOT EXISTS cancel_reason TEXT")
    op.execute("ALTER TABLE billing ADD COLUMN IF NOT EXISTS cancelled_by VARCHAR(255)")
    op.execute("ALTER TABLE billing ADD COLUMN IF NOT EXISTS cancelled_at TIMESTAMPTZ")


def downgrade() -> None:
    op.execute("ALTER TABLE billing DROP COLUMN IF EXISTS cancel_reason")
    op.execute("ALTER TABLE billing DROP COLUMN IF EXISTS cancelled_by")
    op.execute("ALTER TABLE billing DROP COLUMN IF EXISTS cancelled_at")
    op.execute("ALTER TABLE billing DROP CONSTRAINT billing_status_check")
    op.execute(
        """
        ALTER TABLE billing ADD CONSTRAINT billing_status_check
        CHECK (status IN (
            'unpaid',
            'partially_paid',
            'paid',
            'overpaid',
            'waived',
            'released_with_outstanding'
        ))
    """
    )
