"""Add 'resolved' to manifest.verification_status CHECK constraint.

Allows PATCH /v1/manifests/{id}/resolve-discrepancy to close out a
discrepancies_found manifest once staff have documented the resolution.

Revision ID: 021
Revises: 020
Create Date: 2026-05-05 00:00:00
"""

from alembic import op

revision = "021"
down_revision = "020"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE manifest DROP CONSTRAINT manifest_verification_status_check")
    op.execute(
        """
        ALTER TABLE manifest ADD CONSTRAINT manifest_verification_status_check
        CHECK (verification_status IN (
            'pending',
            'verified',
            'discrepancies_found',
            'resolved'
        ))
        """
    )


def downgrade() -> None:
    op.execute("ALTER TABLE manifest DROP CONSTRAINT manifest_verification_status_check")
    op.execute(
        """
        ALTER TABLE manifest ADD CONSTRAINT manifest_verification_status_check
        CHECK (verification_status IN (
            'pending',
            'verified',
            'discrepancies_found'
        ))
        """
    )
