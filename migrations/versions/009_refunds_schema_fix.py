"""Fix refund_request schema to match the refunds service models.py enums,
and add missing columns required by the refunds service workflow.

Changes:
  refund_request.status CHECK   → pending_review, accounts_reviewed, pending_approval,
                                   approved, rejected, processed, applied_as_credit
  refund_request.customer_choice CHECK → immediate_refund, credit_next_shipment
  refund_request.approval_level CHECK  → manager, head_of_finance
  refund_request.refund_type    ADD COLUMN (overpayment, cbm_correction, damage_or_loss)
  refund_request.amount_approved_ngn   ADD COLUMN DECIMAL(15,2)
  refund_request.damage_claim_id       ADD COLUMN UUID FK → damage_claim
  refund_request.debt_check_passed     ADD COLUMN BOOLEAN
  refund_request.debt_check_notes      ADD COLUMN TEXT

Also includes a data migration to rename existing 'pending' status rows to
'pending_review' before the CHECK constraint is replaced.

Revision ID: 009
Revises: 008
Create Date: 2024-01-01 00:00:08
"""

from alembic import op

revision = "009"
down_revision = "008"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ---------------------------------------------------------------------------
    # Data migration: rename existing 'pending' records before CHECK change
    # ---------------------------------------------------------------------------
    op.execute("UPDATE refund_request SET status = 'pending_review' WHERE status = 'pending'")

    # ---------------------------------------------------------------------------
    # refund_request — fix status CHECK + update default
    # ---------------------------------------------------------------------------
    op.execute("ALTER TABLE refund_request DROP CONSTRAINT refund_request_status_check")
    op.execute(
        """
        ALTER TABLE refund_request ADD CONSTRAINT refund_request_status_check
        CHECK (status IN (
            'pending_review',
            'accounts_reviewed',
            'pending_approval',
            'approved',
            'rejected',
            'processed',
            'applied_as_credit'
        ))
    """
    )
    op.execute("ALTER TABLE refund_request ALTER COLUMN status SET DEFAULT 'pending_review'")

    # ---------------------------------------------------------------------------
    # refund_request — fix customer_choice CHECK
    # ---------------------------------------------------------------------------
    op.execute("ALTER TABLE refund_request " "DROP CONSTRAINT IF EXISTS refund_request_customer_choice_check")
    op.execute(
        """
        ALTER TABLE refund_request ADD CONSTRAINT refund_request_customer_choice_check
        CHECK (
            customer_choice IN ('immediate_refund', 'credit_next_shipment')
            OR customer_choice IS NULL
        )
    """
    )

    # ---------------------------------------------------------------------------
    # refund_request — fix approval_level CHECK
    # ---------------------------------------------------------------------------
    op.execute("ALTER TABLE refund_request " "DROP CONSTRAINT IF EXISTS refund_request_approval_level_check")
    op.execute(
        """
        ALTER TABLE refund_request ADD CONSTRAINT refund_request_approval_level_check
        CHECK (
            approval_level IN ('manager', 'head_of_finance')
            OR approval_level IS NULL
        )
    """
    )

    # ---------------------------------------------------------------------------
    # refund_request — add missing columns
    # ---------------------------------------------------------------------------
    op.execute(
        """
        ALTER TABLE refund_request ADD COLUMN refund_type VARCHAR(30)
        CHECK (refund_type IN ('overpayment', 'cbm_correction', 'damage_or_loss'))
    """
    )
    op.execute("ALTER TABLE refund_request ADD COLUMN amount_approved_ngn DECIMAL(15, 2)")
    op.execute("ALTER TABLE refund_request ADD COLUMN damage_claim_id UUID " "REFERENCES damage_claim(id)")
    op.execute("ALTER TABLE refund_request ADD COLUMN debt_check_passed BOOLEAN")
    op.execute("ALTER TABLE refund_request ADD COLUMN debt_check_notes TEXT")


def downgrade() -> None:
    # Remove added columns
    op.execute("ALTER TABLE refund_request DROP COLUMN IF EXISTS debt_check_notes")
    op.execute("ALTER TABLE refund_request DROP COLUMN IF EXISTS debt_check_passed")
    op.execute("ALTER TABLE refund_request DROP COLUMN IF EXISTS damage_claim_id")
    op.execute("ALTER TABLE refund_request DROP COLUMN IF EXISTS amount_approved_ngn")
    op.execute("ALTER TABLE refund_request DROP COLUMN IF EXISTS refund_type")

    # Restore approval_level CHECK
    op.execute("ALTER TABLE refund_request " "DROP CONSTRAINT IF EXISTS refund_request_approval_level_check")
    op.execute(
        """
        ALTER TABLE refund_request ADD CONSTRAINT refund_request_approval_level_check
        CHECK (approval_level IN ('staff', 'manager', 'admin') OR approval_level IS NULL)
    """
    )

    # Restore customer_choice CHECK
    op.execute("ALTER TABLE refund_request " "DROP CONSTRAINT IF EXISTS refund_request_customer_choice_check")
    op.execute(
        """
        ALTER TABLE refund_request ADD CONSTRAINT refund_request_customer_choice_check
        CHECK (
            customer_choice IN ('cash', 'bank_transfer', 'credit_note')
            OR customer_choice IS NULL
        )
    """
    )

    # Restore status CHECK
    op.execute("ALTER TABLE refund_request DROP CONSTRAINT refund_request_status_check")
    op.execute(
        """
        ALTER TABLE refund_request ADD CONSTRAINT refund_request_status_check
        CHECK (status IN (
            'pending', 'debt_check', 'approved', 'rejected',
            'processing', 'completed', 'cancelled'
        ))
    """
    )
    op.execute("ALTER TABLE refund_request ALTER COLUMN status SET DEFAULT 'pending'")
    # Note: data migration back (pending_review → pending) is not safe to auto-reverse
