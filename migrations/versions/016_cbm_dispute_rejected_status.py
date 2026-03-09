"""Add 'rejected' to cbm_dispute.status CHECK constraint.

The billing service's reject_dispute() sets status = 'rejected', but the
CHECK constraint added in migration 006 omitted this value.

Revision ID: 016
Revises: 015
Create Date: 2024-01-01 00:00:15
"""

from alembic import op

revision = "016"
down_revision = "015"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE cbm_dispute DROP CONSTRAINT cbm_dispute_status_check")
    op.execute(
        """
        ALTER TABLE cbm_dispute ADD CONSTRAINT cbm_dispute_status_check
        CHECK (status IN (
            'submitted',
            'acknowledged',
            'investigating',
            'escalated_china',
            'resolved_adjusted',
            'resolved_no_change',
            'rejected',
            'closed'
        ))
    """
    )


def downgrade() -> None:
    op.execute("ALTER TABLE cbm_dispute DROP CONSTRAINT cbm_dispute_status_check")
    op.execute(
        """
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
    """
    )
