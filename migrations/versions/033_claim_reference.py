"""033 — damage claim reference number.

Adds a human-readable reference column (e.g. DC-20260728-001) to damage_claim.
Same pattern as packing_list.reference (migration 031).
Backfilled from created_at + row-number within tenant.
"""

from alembic import op

revision = "033"
down_revision = "032"


def upgrade() -> None:
    op.execute("ALTER TABLE damage_claim ADD COLUMN IF NOT EXISTS reference VARCHAR(30)")

    op.execute(
        """
        UPDATE damage_claim
        SET reference = sub.ref
        FROM (
            SELECT id,
                   'DC-' ||
                   TO_CHAR(created_at AT TIME ZONE 'UTC', 'YYYYMMDD') || '-' ||
                   LPAD(CAST(
                       ROW_NUMBER() OVER (PARTITION BY tenant_id ORDER BY created_at) AS TEXT
                   ), 3, '0') AS ref
            FROM damage_claim
        ) sub
        WHERE damage_claim.id = sub.id AND damage_claim.reference IS NULL
        """
    )

    op.execute("ALTER TABLE damage_claim ALTER COLUMN reference SET NOT NULL")
    op.execute(
        """
        CREATE UNIQUE INDEX IF NOT EXISTS idx_damage_claim_tenant_reference
            ON damage_claim(tenant_id, reference)
        """
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS idx_damage_claim_tenant_reference")
    op.execute("ALTER TABLE damage_claim DROP COLUMN IF EXISTS reference")
