"""Create audit log tables.

Revision ID: 004
Revises: 003
Create Date: 2024-01-01 00:00:03
"""

from alembic import op

revision = "004"
down_revision = "003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ---------------------------------------------------------------------------
    # 1. audit_log — tenant-scoped record of every CREATE/UPDATE/DELETE/STATUS_CHANGE
    #    before_state and after_state capture the full row as JSONB snapshots.
    #    Application layer is responsible for populating these fields.
    # ---------------------------------------------------------------------------
    op.execute("""
        CREATE TABLE audit_log (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id UUID NOT NULL REFERENCES tenant(id) ON DELETE RESTRICT,
            entity_type VARCHAR(100) NOT NULL,
            entity_id UUID NOT NULL,
            action VARCHAR(30) NOT NULL CHECK (action IN (
                'CREATE',
                'UPDATE',
                'DELETE',
                'STATUS_CHANGE'
            )),
            actor_id UUID REFERENCES tenant_user(id),
            actor_role VARCHAR(30),
            before_state JSONB,
            after_state JSONB,
            ip_address INET,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
    """)
    op.execute("CREATE INDEX idx_audit_log_entity ON audit_log(tenant_id, entity_type, entity_id)")
    op.execute("CREATE INDEX idx_audit_log_actor ON audit_log(tenant_id, actor_id)")
    op.execute("CREATE INDEX idx_audit_log_created_at ON audit_log(tenant_id, created_at)")

    # ---------------------------------------------------------------------------
    # 2. platform_audit_log — cross-tenant admin actions performed by platform staff
    #    NOT scoped to a single tenant (no tenant_id FK required).
    # ---------------------------------------------------------------------------
    op.execute("""
        CREATE TABLE platform_audit_log (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            action VARCHAR(100) NOT NULL,
            actor_id UUID REFERENCES tenant_user(id),
            target_tenant_id UUID REFERENCES tenant(id),
            details JSONB,
            ip_address INET,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
    """)
    op.execute("CREATE INDEX idx_platform_audit_actor ON platform_audit_log(actor_id)")
    op.execute("CREATE INDEX idx_platform_audit_tenant ON platform_audit_log(target_tenant_id)")
    op.execute("CREATE INDEX idx_platform_audit_created_at ON platform_audit_log(created_at)")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS platform_audit_log")
    op.execute("DROP TABLE IF EXISTS audit_log")
