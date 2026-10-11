"""054 — tenant onboarding requests (shipping-company leads).

Admin / sales-led onboarding for shipping companies (tenants): the public
`POST /v1/onboarding-requests` endpoint captures a company's details as a lead,
a platform admin reviews it, then provisions the tenant via the existing
`create_tenant` flow (which links `tenant_id` back here and flips the status to
'provisioned'). Distinct from customer onboarding, which stays invite / slug
based — this table is for *companies*, not customers.

Platform-scoped, like `platform_settings` — no tenant_id ownership, no RLS;
read/written by platform_admin (and the public create path) via the PLATFORM
scope. `tenant_id` is set only once a lead is provisioned into a real tenant.
"""

from alembic import op

revision = "054"
down_revision = "053"


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS tenant_onboarding_request (
            id                   UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            company_name         VARCHAR(200) NOT NULL,
            contact_name         VARCHAR(200) NOT NULL,
            contact_email        VARCHAR(320) NOT NULL,
            contact_phone        VARCHAR(40),
            origin_country       VARCHAR(100) NOT NULL DEFAULT 'China',
            destination_country  VARCHAR(100) NOT NULL DEFAULT 'Nigeria',
            monthly_volume       VARCHAR(100),
            notes                TEXT,
            status               VARCHAR(20) NOT NULL DEFAULT 'new'
                                   CHECK (status IN ('new', 'contacted', 'approved', 'rejected', 'provisioned')),
            rejection_reason     TEXT,
            reviewed_by          UUID,
            reviewed_at          TIMESTAMPTZ,
            tenant_id            UUID REFERENCES tenant(id) ON DELETE SET NULL,
            created_at           TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """
    )
    # Console lists newest-first and filters by status; dedupe lookups by email.
    op.execute("CREATE INDEX IF NOT EXISTS idx_onboarding_request_status ON tenant_onboarding_request(status, created_at DESC)")
    op.execute("CREATE INDEX IF NOT EXISTS idx_onboarding_request_email ON tenant_onboarding_request(lower(contact_email))")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS tenant_onboarding_request")
