"""052 — packing-list loading/delivery dates.

Shipment-level dates captured in the create/edit packing-list wizard: when the
cargo is loaded (`loading_date`) and the expected customer delivery
(`delivery_date`). Both nullable — optional at create time. Per packing list,
not per item (every item in a list loads/delivers together).
"""

from alembic import op

revision = "052"
down_revision = "051"


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE packing_list
            ADD COLUMN IF NOT EXISTS loading_date  DATE,
            ADD COLUMN IF NOT EXISTS delivery_date DATE
        """
    )


def downgrade() -> None:
    op.execute(
        """
        ALTER TABLE packing_list
            DROP COLUMN IF EXISTS loading_date,
            DROP COLUMN IF EXISTS delivery_date
        """
    )
