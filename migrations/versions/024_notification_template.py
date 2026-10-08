"""Create notification_template table for tenant-customisable message copy.

Stores per-tenant overrides for SMS, WhatsApp, and email templates.
Falls back to hardcoded defaults when no row exists.
UNIQUE (tenant_id, event_type, channel) enforced at DB level.

Revision ID: 024
Revises: 023
Create Date: 2026-05-05 00:00:00
"""

from alembic import op

revision = "024"
down_revision = "023"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE notification_template (
            id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id     UUID NOT NULL REFERENCES tenant(id) ON DELETE CASCADE,
            event_type    VARCHAR(100) NOT NULL,
            channel       VARCHAR(20)  NOT NULL CHECK (channel IN ('sms', 'email', 'whatsapp')),
            template_body TEXT NOT NULL,
            subject       VARCHAR(500),
            updated_by    VARCHAR(255),
            created_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            UNIQUE (tenant_id, event_type, channel)
        )
        """
    )
    op.execute("CREATE INDEX idx_notif_template_tenant ON notification_template(tenant_id)")

    op.execute("ALTER TABLE notification_template ENABLE ROW LEVEL SECURITY")
    op.execute(
        """
        CREATE POLICY notif_template_tenant_isolation ON notification_template
        USING (tenant_id::text = current_setting('app.tenant_id', TRUE))
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS notification_template CASCADE")
