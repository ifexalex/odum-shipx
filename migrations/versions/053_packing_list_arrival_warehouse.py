"""053 — arrival warehouse on packing list.

A shipping company can operate multiple destination warehouses (migration 041's
`warehouse` table, same rows the release-note/pickup flow already uses). This
lets a packing list record *which* warehouse the customer's goods are bound for,
chosen at create/edit time from the tenant's warehouses (defaulting to the one
flagged `is_default`).

`arrival_warehouse_id` is nullable — existing packing lists keep NULL and read
back with no arrival warehouse. ON DELETE SET NULL is belt-and-braces; warehouses
are soft-deactivated (`is_active = FALSE`), never hard-deleted, so the FK target
normally survives and the join still resolves the name.
"""

from alembic import op

revision = "053"
down_revision = "052"


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE packing_list
            ADD COLUMN IF NOT EXISTS arrival_warehouse_id UUID
                REFERENCES warehouse(id) ON DELETE SET NULL
        """
    )
    op.execute("CREATE INDEX IF NOT EXISTS idx_packing_list_arrival_warehouse " "ON packing_list(arrival_warehouse_id)")


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS idx_packing_list_arrival_warehouse")
    op.execute("ALTER TABLE packing_list DROP COLUMN IF EXISTS arrival_warehouse_id")
