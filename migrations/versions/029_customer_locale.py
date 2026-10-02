"""029 — customer.locale column.

Adds locale preference to the customer table. Locale is determined by location/region
(not user-settable by customers — see PATCH /v1/tenant/me for staff self-service).
Defaults to 'en'; set at registration or via admin update.

Also documents: tenant_user.locale was added in migration 026.
"""

from alembic import op

revision = "029"
down_revision = "028"


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE customer
            ADD COLUMN IF NOT EXISTS locale VARCHAR(10) NOT NULL DEFAULT 'en';
        """
    )


def downgrade() -> None:
    op.execute(
        """
        ALTER TABLE customer DROP COLUMN IF EXISTS locale;
        """
    )
