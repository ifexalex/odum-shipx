"""038 — widen billing.status to fit 'released_with_outstanding'.

billing.status has been VARCHAR(20) since migration 002, but migration 006's
CHECK constraint added 'released_with_outstanding' (26 chars) as an allowed
value without ever widening the column. Every write attempting to set that
status — payment_release/repository.py::mark_billing_released_with_outstanding(),
the real code path behind "release container with outstanding balance" —
has always failed with StringDataRightTruncation. Discovered while seeding
stress-test data that exercises every billing status.

Revision ID: 038
Revises: 037
Create Date: 2026-07-19 00:00:00
"""

from alembic import op

revision = "038"
down_revision = "037"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE billing ALTER COLUMN status TYPE VARCHAR(30)")


def downgrade() -> None:
    op.execute("ALTER TABLE billing ALTER COLUMN status TYPE VARCHAR(20)")
