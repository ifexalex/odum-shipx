"""051 — container capacity presets + per-container capacity snapshot.

Adds a `container_capacity` table for tenant-defined *custom* capacity presets
(the ten well-known capacities are code constants in
services/tenant_management/service.py, merged in on read — no per-tenant seed,
no backfill). Each preset carries a usable volume (`capacity_cbm`) and a
`recommended_cbm` load target.

Also snapshots the chosen capacity onto `container` (`capacity_cbm`,
`recommended_cbm`) at create time — denormalised on purpose so a container's
utilization bar keeps working even if the preset is later edited or deleted.
The capacity's display name continues to live in the existing
`container.container_type` column (migration 030). All columns nullable;
existing containers keep NULLs and fall back to the type-name volume estimate.
"""

from alembic import op

revision = "051"
down_revision = "050"


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS container_capacity (
            id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id       UUID NOT NULL REFERENCES tenant(id) ON DELETE CASCADE,
            name            VARCHAR(100) NOT NULL,
            capacity_cbm    NUMERIC(8, 2) NOT NULL CHECK (capacity_cbm > 0),
            recommended_cbm NUMERIC(8, 2) CHECK (recommended_cbm IS NULL OR recommended_cbm > 0),
            created_by      UUID,
            created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
            UNIQUE (tenant_id, name)
        )
        """
    )
    op.execute("CREATE INDEX IF NOT EXISTS idx_container_capacity_tenant ON container_capacity(tenant_id)")
    op.execute("ALTER TABLE container_capacity ENABLE ROW LEVEL SECURITY")
    op.execute(
        """
        CREATE POLICY container_capacity_tenant_isolation ON container_capacity
        USING (tenant_id::text = current_setting('app.current_tenant_id', TRUE))
        """
    )

    op.execute(
        """
        ALTER TABLE container
            ADD COLUMN IF NOT EXISTS capacity_cbm    NUMERIC(8, 2),
            ADD COLUMN IF NOT EXISTS recommended_cbm NUMERIC(8, 2)
        """
    )


def downgrade() -> None:
    op.execute(
        """
        ALTER TABLE container
            DROP COLUMN IF EXISTS capacity_cbm,
            DROP COLUMN IF EXISTS recommended_cbm
        """
    )
    op.execute("DROP POLICY IF EXISTS container_capacity_tenant_isolation ON container_capacity")
    op.execute("DROP TABLE IF EXISTS container_capacity")
