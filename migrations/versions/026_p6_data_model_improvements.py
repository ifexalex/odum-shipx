"""026 — P6 data model improvements.

Adds:
  - customer.delivery_address JSONB   — per-customer last-mile address
  - packing_list_item.declared_value_usd DECIMAL(15,2) — insurance / customs valuation
  - tenant_user.locale VARCHAR(10) DEFAULT 'en'         — EN/ZH notification locale
"""

from alembic import op

revision = "026"
down_revision = "025"


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE customer
            ADD COLUMN IF NOT EXISTS delivery_address JSONB;

        ALTER TABLE packing_list_item
            ADD COLUMN IF NOT EXISTS declared_value_usd DECIMAL(15, 2);

        ALTER TABLE tenant_user
            ADD COLUMN IF NOT EXISTS locale VARCHAR(10) NOT NULL DEFAULT 'en';
        """
    )


def downgrade() -> None:
    op.execute(
        """
        ALTER TABLE customer DROP COLUMN IF EXISTS delivery_address;
        ALTER TABLE packing_list_item DROP COLUMN IF EXISTS declared_value_usd;
        ALTER TABLE tenant_user DROP COLUMN IF EXISTS locale;
        """
    )
