"""Fix damage_claim, claim_resolution, missing_item, and seized_item schemas
to match the claims service models.py enums.

Adds missing columns required by the claims service:
  damage_claim.inspection_method
  claim_resolution.refund_request_id, claim_resolution.discount_percentage
  missing_item.carton_tags TEXT[]
  seized_item.carton_tags TEXT[]

Revision ID: 007
Revises: 006
Create Date: 2024-01-01 00:00:06
"""

from alembic import op

revision = "007"
down_revision = "006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ---------------------------------------------------------------------------
    # damage_claim — replace status CHECK + add inspection_method
    # ---------------------------------------------------------------------------
    op.execute("ALTER TABLE damage_claim DROP CONSTRAINT damage_claim_status_check")
    op.execute(
        """
        ALTER TABLE damage_claim ADD CONSTRAINT damage_claim_status_check
        CHECK (status IN (
            'filed',
            'under_inspection',
            'inspection_complete',
            'pending_resolution',
            'resolved',
            'closed'
        ))
    """
    )
    op.execute("ALTER TABLE damage_claim ALTER COLUMN status SET DEFAULT 'filed'")
    op.execute("ALTER TABLE damage_claim ADD COLUMN inspection_method VARCHAR(30)")

    # ---------------------------------------------------------------------------
    # claim_resolution — replace approval_level CHECK + add columns
    # ---------------------------------------------------------------------------
    op.execute("ALTER TABLE claim_resolution DROP CONSTRAINT " "claim_resolution_approval_level_check")
    op.execute(
        """
        ALTER TABLE claim_resolution ADD CONSTRAINT claim_resolution_approval_level_check
        CHECK (approval_level IN ('nigeria_staff', 'tenant_admin', 'head_of_finance'))
    """
    )
    op.execute("ALTER TABLE claim_resolution ADD COLUMN " "refund_request_id UUID REFERENCES refund_request(id)")
    op.execute("ALTER TABLE claim_resolution ADD COLUMN discount_percentage DECIMAL(5, 2)")

    # ---------------------------------------------------------------------------
    # missing_item — replace status CHECK + add carton_tags column
    # ---------------------------------------------------------------------------
    op.execute("ALTER TABLE missing_item DROP CONSTRAINT missing_item_status_check")
    op.execute(
        """
        ALTER TABLE missing_item ADD CONSTRAINT missing_item_status_check
        CHECK (status IN (
            'reported',
            'investigating',
            'found_and_shipping',
            'confirmed_lost',
            'resolved'
        ))
    """
    )
    op.execute("ALTER TABLE missing_item ADD COLUMN " "carton_tags TEXT[] NOT NULL DEFAULT '{}'")

    # ---------------------------------------------------------------------------
    # seized_item — replace recovery_status CHECK + add carton_tags column
    # ---------------------------------------------------------------------------
    op.execute("ALTER TABLE seized_item DROP CONSTRAINT " "seized_item_recovery_status_check")
    op.execute(
        """
        ALTER TABLE seized_item ADD CONSTRAINT seized_item_recovery_status_check
        CHECK (recovery_status IN (
            'seized',
            'recovery_in_progress',
            'recovered',
            'permanently_lost'
        ))
    """
    )
    op.execute("ALTER TABLE seized_item ADD COLUMN " "carton_tags TEXT[] NOT NULL DEFAULT '{}'")


def downgrade() -> None:
    # seized_item
    op.execute("ALTER TABLE seized_item DROP COLUMN IF EXISTS carton_tags")
    op.execute("ALTER TABLE seized_item DROP CONSTRAINT seized_item_recovery_status_check")
    op.execute(
        """
        ALTER TABLE seized_item ADD CONSTRAINT seized_item_recovery_status_check
        CHECK (recovery_status IN (
            'seized', 'under_review', 'recovered', 'forfeited'
        ))
    """
    )

    # missing_item
    op.execute("ALTER TABLE missing_item DROP COLUMN IF EXISTS carton_tags")
    op.execute("ALTER TABLE missing_item DROP CONSTRAINT missing_item_status_check")
    op.execute(
        """
        ALTER TABLE missing_item ADD CONSTRAINT missing_item_status_check
        CHECK (status IN (
            'reported', 'investigating', 'found', 'confirmed_missing', 'compensated'
        ))
    """
    )

    # claim_resolution
    op.execute("ALTER TABLE claim_resolution DROP COLUMN IF EXISTS discount_percentage")
    op.execute("ALTER TABLE claim_resolution DROP COLUMN IF EXISTS refund_request_id")
    op.execute("ALTER TABLE claim_resolution DROP CONSTRAINT " "claim_resolution_approval_level_check")
    op.execute(
        """
        ALTER TABLE claim_resolution ADD CONSTRAINT claim_resolution_approval_level_check
        CHECK (approval_level IN ('staff', 'manager', 'admin'))
    """
    )

    # damage_claim
    op.execute("ALTER TABLE damage_claim DROP COLUMN IF EXISTS inspection_method")
    op.execute("ALTER TABLE damage_claim DROP CONSTRAINT damage_claim_status_check")
    op.execute(
        """
        ALTER TABLE damage_claim ADD CONSTRAINT damage_claim_status_check
        CHECK (status IN (
            'submitted', 'under_review', 'approved', 'rejected', 'resolved', 'escalated'
        ))
    """
    )
    op.execute("ALTER TABLE damage_claim ALTER COLUMN status SET DEFAULT 'submitted'")
