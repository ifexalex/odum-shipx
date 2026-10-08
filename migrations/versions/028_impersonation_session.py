"""028 — Platform Admin impersonation sessions.

Creates impersonation_session (platform-scoped, no tenant RLS) for tracking
read-only, audited, 30-minute impersonation sessions started by platform admins.

Revision ID: 028
Revises: 027
"""

from alembic import op

revision = "028"
down_revision = "027"


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS impersonation_session (
            id                  UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
            platform_admin_id   VARCHAR(255) NOT NULL,
            target_tenant_id    UUID        NOT NULL REFERENCES tenant(id),
            target_user_id      VARCHAR(255) NOT NULL,
            target_role         VARCHAR(50) NOT NULL DEFAULT 'tenant_admin',
            read_only           BOOLEAN     NOT NULL DEFAULT TRUE,
            started_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            expires_at          TIMESTAMPTZ NOT NULL,
            ended_at            TIMESTAMPTZ,
            end_reason          VARCHAR(255)
        );

        -- Fast lookup for active sessions by ID. expires_at > NOW() is checked
        -- at query time, not baked into the predicate — NOW() is STABLE, not
        -- IMMUTABLE, so Postgres rejects it in a partial index predicate.
        CREATE INDEX IF NOT EXISTS idx_impersonation_session_active
            ON impersonation_session (id)
            WHERE ended_at IS NULL;

        -- Lookup by platform admin
        CREATE INDEX IF NOT EXISTS idx_impersonation_session_admin
            ON impersonation_session (platform_admin_id, started_at DESC);

        -- Lookup by target tenant
        CREATE INDEX IF NOT EXISTS idx_impersonation_session_tenant
            ON impersonation_session (target_tenant_id, started_at DESC);

        GRANT SELECT, INSERT, UPDATE ON impersonation_session TO logistics_app;
        """
    )


def downgrade() -> None:
    op.execute(
        """
        DROP TABLE IF EXISTS impersonation_session;
        """
    )
