"""Create platform and tenant management tables.

Revision ID: 001
Revises:
Create Date: 2024-01-01 00:00:00
"""

from alembic import op

revision = "001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ---------------------------------------------------------------------------
    # 1. tenant — top-level multi-tenant entity
    # ---------------------------------------------------------------------------
    op.execute(
        """
        CREATE TABLE tenant (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            company_name VARCHAR(255) NOT NULL,
            primary_contact_email VARCHAR(255) NOT NULL,
            primary_contact_phone VARCHAR(50),
            origin_country VARCHAR(100) NOT NULL DEFAULT 'China',
            destination_country VARCHAR(100) NOT NULL DEFAULT 'Nigeria',
            subscription_tier VARCHAR(20) NOT NULL CHECK (subscription_tier IN ('starter', 'business', 'enterprise')),
            status VARCHAR(20) NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'suspended', 'offboarded')),
            branding_config JSONB NOT NULL DEFAULT '{}'::jsonb,
            notification_preferences JSONB NOT NULL DEFAULT '{}'::jsonb,
            data_exported_at TIMESTAMPTZ,
            offboarded_at TIMESTAMPTZ,
            deletion_scheduled_at TIMESTAMPTZ,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
    """
    )
    op.execute("CREATE INDEX idx_tenant_status ON tenant(status)")

    # ---------------------------------------------------------------------------
    # 2. tenant_user — staff and customer accounts scoped to a tenant
    # ---------------------------------------------------------------------------
    op.execute(
        """
        CREATE TABLE tenant_user (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id UUID NOT NULL REFERENCES tenant(id) ON DELETE RESTRICT,
            cognito_sub VARCHAR(255) UNIQUE,
            email VARCHAR(255) NOT NULL,
            full_name VARCHAR(255) NOT NULL,
            role VARCHAR(30) NOT NULL CHECK (role IN (
                'tenant_admin',
                'china_office_staff',
                'nigeria_office_staff',
                'warehouse_attendant',
                'customer'
            )),
            status VARCHAR(20) NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'deactivated')),
            created_by UUID REFERENCES tenant_user(id),
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            UNIQUE (tenant_id, email)
        )
    """
    )
    op.execute("CREATE INDEX idx_tenant_user_tenant ON tenant_user(tenant_id)")
    op.execute("CREATE INDEX idx_tenant_user_email ON tenant_user(email)")

    # ---------------------------------------------------------------------------
    # 3. tenant_config — key-value configuration store per tenant
    #
    # Predefined config_key values and their JSONB shapes:
    #   dollar_rate         → { "rate": 1550.00, "currency_pair": "USD_NGN", "effective_from": "..." }
    #   storage_fee         → { "enabled": true, "grace_period_days": 14, "daily_fee_per_carton_ngn": 500 }
    #   warehouse_address   → { "address": "...", "city": "Lagos", "state": "Lagos" }
    #   refund_threshold_usd→ { "staff_limit": 50, "requires_manager_above": 50 }
    #   dispute_escalation  → { "enabled": true, "auto_escalate_days": 5 }
    #   cbm_rate_per_unit   → { "rate_usd": 45.00 }
    #   reminder_days       → { "storage_first_reminder": 7, "storage_final_reminder": 13 }
    # ---------------------------------------------------------------------------
    op.execute(
        """
        CREATE TABLE tenant_config (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id UUID NOT NULL REFERENCES tenant(id) ON DELETE CASCADE,
            config_key VARCHAR(100) NOT NULL,
            config_value JSONB NOT NULL,
            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_by UUID REFERENCES tenant_user(id),
            UNIQUE (tenant_id, config_key)
        )
    """
    )
    op.execute("CREATE INDEX idx_tenant_config_tenant ON tenant_config(tenant_id)")

    # ---------------------------------------------------------------------------
    # 4. usage_record — metering data aggregated per tenant per period
    # ---------------------------------------------------------------------------
    op.execute(
        """
        CREATE TABLE usage_record (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id UUID NOT NULL REFERENCES tenant(id) ON DELETE CASCADE,
            metric_type VARCHAR(50) NOT NULL CHECK (metric_type IN (
                'api_calls',
                'containers_processed',
                'storage_bytes',
                'users_active',
                'sms_sent',
                'whatsapp_sent',
                'emails_sent'
            )),
            value DECIMAL(15, 4) NOT NULL,
            period_start DATE NOT NULL,
            period_end DATE NOT NULL,
            recorded_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
    """
    )
    op.execute("CREATE INDEX idx_usage_record_tenant_period ON usage_record(tenant_id, period_start)")
    op.execute("CREATE INDEX idx_usage_record_tenant_metric ON usage_record(tenant_id, metric_type, period_start)")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS usage_record")
    op.execute("DROP TABLE IF EXISTS tenant_config")
    op.execute("DROP TABLE IF EXISTS tenant_user")
    op.execute("DROP TABLE IF EXISTS tenant")
