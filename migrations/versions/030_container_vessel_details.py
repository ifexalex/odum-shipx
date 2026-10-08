"""030 — container vessel/voyage details.

Adds shipping-manifest fields to the container table that the China Office
create-container form and packing-list wizard surface: vessel name, voyage
number, shipping line, seal number, and container type. All nullable — they
are captured at create time when known, or left blank and filled in later.

Backfills nothing (existing containers keep NULLs). No CHECK on container_type
so tenants aren't locked to a fixed ISO type vocabulary.
"""

from alembic import op

revision = "030"
down_revision = "029"


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE container
            ADD COLUMN IF NOT EXISTS vessel_name    VARCHAR(255),
            ADD COLUMN IF NOT EXISTS voyage_number  VARCHAR(50),
            ADD COLUMN IF NOT EXISTS shipping_line  VARCHAR(255),
            ADD COLUMN IF NOT EXISTS seal_number    VARCHAR(50),
            ADD COLUMN IF NOT EXISTS container_type VARCHAR(50);
        """
    )


def downgrade() -> None:
    op.execute(
        """
        ALTER TABLE container
            DROP COLUMN IF EXISTS vessel_name,
            DROP COLUMN IF EXISTS voyage_number,
            DROP COLUMN IF EXISTS shipping_line,
            DROP COLUMN IF EXISTS seal_number,
            DROP COLUMN IF EXISTS container_type;
        """
    )
