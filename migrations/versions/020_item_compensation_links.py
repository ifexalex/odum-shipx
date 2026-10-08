"""Add refund_request_id FK to missing_item and seized_item.

Revision ID: 020
Revises: 019
Create Date: 2024-01-01 00:00:19
"""
from alembic import op

revision = "020"
down_revision = "019"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE missing_item ADD COLUMN IF NOT EXISTS" " refund_request_id UUID REFERENCES refund_request(id)")
    op.execute("ALTER TABLE seized_item ADD COLUMN IF NOT EXISTS" " refund_request_id UUID REFERENCES refund_request(id)")
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_missing_item_refund"
        " ON missing_item(refund_request_id) WHERE refund_request_id IS NOT NULL"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_seized_item_refund"
        " ON seized_item(refund_request_id) WHERE refund_request_id IS NOT NULL"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS idx_missing_item_refund")
    op.execute("DROP INDEX IF EXISTS idx_seized_item_refund")
    op.execute("ALTER TABLE missing_item DROP COLUMN IF EXISTS refund_request_id")
    op.execute("ALTER TABLE seized_item DROP COLUMN IF EXISTS refund_request_id")
