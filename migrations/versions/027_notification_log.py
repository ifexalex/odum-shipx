"""027 — Notification delivery log.

Creates notification_log table for persisting every outbound notification
so the Notification Delivery Log UI can show status, gateway response, and
offer a retry. Enables RLS with the standard tenant-isolation policy.

Revision ID: 027
Revises: 026
"""

from alembic import op

revision = "027"
down_revision = "026"


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS notification_log (
            id                  UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id           UUID        NOT NULL REFERENCES tenant(id),
            event_type          VARCHAR(100) NOT NULL,
            channel             VARCHAR(20) NOT NULL CHECK (channel IN ('sms', 'email', 'whatsapp')),
            recipient_masked    VARCHAR(100),
            recipient_name      VARCHAR(200),
            customer_id         UUID,
            status              VARCHAR(20) NOT NULL DEFAULT 'queued'
                                CHECK (status IN ('queued', 'sent', 'delivered', 'read', 'failed')),
            provider            VARCHAR(50),
            provider_message_id VARCHAR(255),
            gateway_response    JSONB,
            error_detail        TEXT,
            retry_of            UUID REFERENCES notification_log(id),
            template_data       JSONB,
            created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
        );

        CREATE INDEX IF NOT EXISTS idx_notification_log_tenant_created
            ON notification_log (tenant_id, created_at DESC);

        CREATE INDEX IF NOT EXISTS idx_notification_log_status
            ON notification_log (status);

        CREATE INDEX IF NOT EXISTS idx_notification_log_channel
            ON notification_log (channel);

        CREATE INDEX IF NOT EXISTS idx_notification_log_customer
            ON notification_log (customer_id)
            WHERE customer_id IS NOT NULL;

        CREATE INDEX IF NOT EXISTS idx_notification_log_provider_msg_id
            ON notification_log (provider_message_id)
            WHERE provider_message_id IS NOT NULL;

        ALTER TABLE notification_log ENABLE ROW LEVEL SECURITY;
        ALTER TABLE notification_log FORCE ROW LEVEL SECURITY;

        CREATE POLICY tenant_isolation ON notification_log
            USING (tenant_id = current_setting('app.current_tenant_id')::uuid);

        CREATE POLICY tenant_insert ON notification_log FOR INSERT
            WITH CHECK (tenant_id = current_setting('app.current_tenant_id')::uuid);

        GRANT SELECT, INSERT, UPDATE, DELETE ON notification_log TO logistics_app;
        """
    )


def downgrade() -> None:
    op.execute(
        """
        DROP POLICY IF EXISTS tenant_insert    ON notification_log;
        DROP POLICY IF EXISTS tenant_isolation ON notification_log;
        ALTER TABLE notification_log NO FORCE ROW LEVEL SECURITY;
        ALTER TABLE notification_log DISABLE ROW LEVEL SECURITY;
        DROP TABLE IF EXISTS notification_log;
        """
    )
