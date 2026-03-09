"""Add reactivated_at column to tenant table for re-onboarding support.

When an offboarded tenant re-onboards via PATCH /v1/platform/tenants/{id}/reactivate,
this column records the timestamp of re-onboarding. deletion_scheduled_at is also
cleared on reactivation (the scheduled purge no longer applies).

GDPR note: reactivated_at provides an unambiguous audit boundary — data processed
after this timestamp operates under the new subscription agreement.

Revision ID: 015
Revises: 014
Create Date: 2026-03-05 00:00:00
"""

from alembic import op

revision = "015"
down_revision = "014"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE tenant ADD COLUMN IF NOT EXISTS reactivated_at TIMESTAMPTZ")


def downgrade() -> None:
    op.execute("ALTER TABLE tenant DROP COLUMN IF EXISTS reactivated_at")
