"""031 — packing list reference number.

Adds a human-readable reference column (e.g. PL-20260725-001) to packing_list.
Generated at creation time by the service layer using a per-tenant daily
counter. Unique per tenant.

Existing rows are backfilled with a reference derived from their created_at
date and their row-number within the tenant, so the column can be made NOT NULL
immediately.
"""

from alembic import op

revision = "031"
down_revision = "030"


def upgrade() -> None:
    op.execute("ALTER TABLE packing_list ADD COLUMN IF NOT EXISTS reference VARCHAR(30)")

    # Window functions are not allowed in a bare UPDATE — use a subquery to
    # compute the ranked reference first, then join back to update.
    op.execute(
        """
        UPDATE packing_list pl
        SET reference = sub.ref
        FROM (
            SELECT id,
                   'PL-' ||
                   TO_CHAR(created_at AT TIME ZONE 'UTC', 'YYYYMMDD') || '-' ||
                   LPAD(CAST(
                       ROW_NUMBER() OVER (PARTITION BY tenant_id ORDER BY created_at) AS TEXT
                   ), 3, '0') AS ref
            FROM packing_list
        ) sub
        WHERE pl.id = sub.id AND pl.reference IS NULL
        """
    )

    op.execute("ALTER TABLE packing_list ALTER COLUMN reference SET NOT NULL")
    op.execute(
        """
        CREATE UNIQUE INDEX IF NOT EXISTS idx_packing_list_tenant_reference
            ON packing_list(tenant_id, reference)
        """
    )


def downgrade() -> None:
    op.execute(
        """
        DROP INDEX IF EXISTS idx_packing_list_tenant_reference;
        ALTER TABLE packing_list DROP COLUMN IF EXISTS reference;
        """
    )
