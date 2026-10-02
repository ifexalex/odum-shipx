"""039 — Multi-role staff support.

Adds tenant_user_role, a join table letting a single tenant_user hold more
than one role at once (e.g. nigeria_office_staff + warehouse_attendant).
tenant_user.role is kept as-is and continues to mean "primary role" — every
existing read of that column (reports, staff-detail summary, badges) keeps
working unmodified. Application code (repository.set_user_roles) mirrors the
primary role into tenant_user.role whenever it changes, so the two stay in
sync.

Backfill: one row per existing tenant_user, role = tenant_user.role,
is_primary = TRUE. The partial unique index enforces exactly one primary
role per user going forward.

Revision ID: 039
Revises: 038
Create Date: 2026-07-20 00:00:00
"""

from alembic import op

revision = "039"
down_revision = "038"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS tenant_user_role (
            tenant_user_id UUID NOT NULL REFERENCES tenant_user(id) ON DELETE CASCADE,
            tenant_id      UUID NOT NULL REFERENCES tenant(id) ON DELETE RESTRICT,
            role           VARCHAR(30) NOT NULL CHECK (role IN (
                'tenant_admin', 'china_office_staff', 'nigeria_office_staff',
                'warehouse_attendant', 'customer'
            )),
            is_primary     BOOLEAN NOT NULL DEFAULT FALSE,
            assigned_by    UUID REFERENCES tenant_user(id),
            assigned_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            PRIMARY KEY (tenant_user_id, role)
        );

        CREATE UNIQUE INDEX IF NOT EXISTS idx_tenant_user_role_one_primary
            ON tenant_user_role(tenant_user_id) WHERE is_primary;

        CREATE INDEX IF NOT EXISTS idx_tenant_user_role_tenant
            ON tenant_user_role(tenant_id);

        ALTER TABLE tenant_user_role ENABLE ROW LEVEL SECURITY;
        ALTER TABLE tenant_user_role FORCE ROW LEVEL SECURITY;

        CREATE POLICY tenant_isolation ON tenant_user_role
            USING (tenant_id = current_setting('app.current_tenant_id')::uuid);

        CREATE POLICY tenant_insert ON tenant_user_role FOR INSERT
            WITH CHECK (tenant_id = current_setting('app.current_tenant_id')::uuid);

        GRANT SELECT, INSERT, UPDATE, DELETE ON tenant_user_role TO logistics_app;

        -- Backfill: one primary-role row per existing tenant_user.
        INSERT INTO tenant_user_role (tenant_user_id, tenant_id, role, is_primary)
        SELECT id, tenant_id, role, TRUE FROM tenant_user
        ON CONFLICT (tenant_user_id, role) DO NOTHING;
        """
    )


def downgrade() -> None:
    op.execute(
        """
        DROP POLICY IF EXISTS tenant_insert    ON tenant_user_role;
        DROP POLICY IF EXISTS tenant_isolation ON tenant_user_role;
        ALTER TABLE tenant_user_role NO FORCE ROW LEVEL SECURITY;
        ALTER TABLE tenant_user_role DISABLE ROW LEVEL SECURITY;
        DROP TABLE IF EXISTS tenant_user_role;
        """
    )
