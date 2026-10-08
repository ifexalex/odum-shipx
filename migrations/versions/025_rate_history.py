"""Add rate_history table for append-only audit of dollar_rate and cbm_rate changes.

Provides a full history of rate changes for billing reconciliation and compliance.
Falls outside the normal tenant_config update cycle which only stores current values.
RLS-enabled: tenant staff can only see their own rate history.

Revision ID: 025
Revises: 024
Create Date: 2026-05-05 00:00:00
"""

from alembic import op

revision = "025"
down_revision = "024"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE rate_history (
            id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id     UUID NOT NULL REFERENCES tenant(id) ON DELETE CASCADE,
            rate_type     VARCHAR(50) NOT NULL,
            rate_value    JSONB NOT NULL,
            previous_value JSONB,
            changed_by    VARCHAR(255),
            effective_from TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            created_at    TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
        """
    )
    op.execute("CREATE INDEX idx_rate_history_tenant ON rate_history(tenant_id, created_at DESC)")
    op.execute("ALTER TABLE rate_history ENABLE ROW LEVEL SECURITY")
    op.execute(
        """
        CREATE POLICY rate_history_tenant_isolation ON rate_history
        USING (tenant_id::text = current_setting('app.tenant_id', TRUE))
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS rate_history CASCADE")
