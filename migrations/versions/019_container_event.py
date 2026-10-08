"""Add container_event table for container status audit trail.

Revision ID: 019
Revises: 018
Create Date: 2024-01-01 00:00:18
"""
from alembic import op

revision = "019"
down_revision = "018"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE container_event (
            id           UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id    UUID        NOT NULL REFERENCES tenant(id) ON DELETE RESTRICT,
            container_id UUID        NOT NULL REFERENCES container(id) ON DELETE RESTRICT,
            from_status  VARCHAR(30) NOT NULL,
            to_status    VARCHAR(30) NOT NULL,
            actor_id     VARCHAR(255),
            notes        TEXT,
            created_at   TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
        """
    )
    op.execute("CREATE INDEX idx_container_event_tenant_container" " ON container_event(tenant_id, container_id)")
    op.execute("CREATE INDEX idx_container_event_created" " ON container_event(created_at DESC)")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS container_event")
