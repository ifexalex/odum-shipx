"""032 — container cancelled status.

Adds 'cancelled' to the container.status CHECK constraint so China staff can
void containers created by mistake. A cancelled container is terminal — no
further status transitions are allowed.
"""

from alembic import op

revision = "032"
down_revision = "031"


def upgrade() -> None:
    op.execute("ALTER TABLE container DROP CONSTRAINT IF EXISTS container_status_check")
    op.execute(
        """
        ALTER TABLE container ADD CONSTRAINT container_status_check CHECK (status IN (
            'loading', 'sealed', 'in_transit', 'arrived', 'customs_clearance',
            'cleared', 'at_warehouse', 'fully_released', 'cancelled'
        ))
        """
    )


def downgrade() -> None:
    op.execute("ALTER TABLE container DROP CONSTRAINT IF EXISTS container_status_check")
    op.execute(
        """
        ALTER TABLE container ADD CONSTRAINT container_status_check CHECK (status IN (
            'loading', 'sealed', 'in_transit', 'arrived', 'customs_clearance',
            'cleared', 'at_warehouse', 'fully_released'
        ))
        """
    )
