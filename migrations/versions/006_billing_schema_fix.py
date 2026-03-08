"""Fix billing and cbm_dispute status CHECK constraints to match models.py enums.

Adds missing columns required by the billing service:
  billing.billed_at, billing.released_with_outstanding
  cbm_dispute.acknowledged_at, cbm_dispute.customer_measured_cbm

Revision ID: 006
Revises: 005
Create Date: 2024-01-01 00:00:05
"""

from alembic import op

revision = "006"
down_revision = "005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ---------------------------------------------------------------------------
    # billing — replace status CHECK + add new columns
    # ---------------------------------------------------------------------------
    op.execute("ALTER TABLE billing DROP CONSTRAINT billing_status_check")
    op.execute("""
        ALTER TABLE billing ADD CONSTRAINT billing_status_check
        CHECK (status IN (
            'unpaid',
            'partially_paid',
            'paid',
            'overpaid',
            'waived',
            'released_with_outstanding'
        ))
    """)
    op.execute("ALTER TABLE billing ALTER COLUMN status SET DEFAULT 'unpaid'")
    op.execute("ALTER TABLE billing ADD COLUMN billed_at TIMESTAMPTZ")
    op.execute(
        "ALTER TABLE billing ADD COLUMN released_with_outstanding "
        "BOOLEAN NOT NULL DEFAULT FALSE"
    )

    # ---------------------------------------------------------------------------
    # cbm_dispute — replace status CHECK + add new columns
    # ---------------------------------------------------------------------------
    op.execute("ALTER TABLE cbm_dispute DROP CONSTRAINT cbm_dispute_status_check")
    op.execute("""
        ALTER TABLE cbm_dispute ADD CONSTRAINT cbm_dispute_status_check
        CHECK (status IN (
            'submitted',
            'acknowledged',
            'investigating',
            'escalated_china',
            'resolved_adjusted',
            'resolved_no_change',
            'closed'
        ))
    """)
    op.execute("ALTER TABLE cbm_dispute ALTER COLUMN status SET DEFAULT 'submitted'")
    op.execute("ALTER TABLE cbm_dispute ADD COLUMN acknowledged_at TIMESTAMPTZ")
    op.execute(
        "ALTER TABLE cbm_dispute ADD COLUMN customer_measured_cbm DECIMAL(12, 6)"
    )


def downgrade() -> None:
    # Restore original constraints
    op.execute(
        "ALTER TABLE cbm_dispute DROP COLUMN IF EXISTS customer_measured_cbm"
    )
    op.execute(
        "ALTER TABLE cbm_dispute DROP COLUMN IF EXISTS acknowledged_at"
    )
    op.execute("ALTER TABLE cbm_dispute DROP CONSTRAINT cbm_dispute_status_check")
    op.execute("""
        ALTER TABLE cbm_dispute ADD CONSTRAINT cbm_dispute_status_check
        CHECK (status IN (
            'open', 'under_review', 'evidence_submitted',
            'agreed', 'rejected', 'resolved', 'escalated'
        ))
    """)
    op.execute("ALTER TABLE cbm_dispute ALTER COLUMN status SET DEFAULT 'open'")

    op.execute(
        "ALTER TABLE billing DROP COLUMN IF EXISTS released_with_outstanding"
    )
    op.execute("ALTER TABLE billing DROP COLUMN IF EXISTS billed_at")
    op.execute("ALTER TABLE billing DROP CONSTRAINT billing_status_check")
    op.execute("""
        ALTER TABLE billing ADD CONSTRAINT billing_status_check
        CHECK (status IN (
            'draft', 'sent', 'partially_paid', 'paid', 'overdue', 'cancelled'
        ))
    """)
    op.execute("ALTER TABLE billing ALTER COLUMN status SET DEFAULT 'draft'")
