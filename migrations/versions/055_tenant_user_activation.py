"""055 — tenant_user_activation table.

Account activation for provisioned staff/admins. Unlike customers (who set
their own password at self-registration via create_user_with_password), staff
and the initial tenant admin are created by an operator with a random password
and no login. This table backs the ShipX-branded "set your password" flow: on
provisioning we mint a single-use, 48-hour, hashed token and email the user a
`/activate/{token}` link; accepting it sets their chosen password in the IdP
(via the Graph provisioning app on Entra) and marks the row consumed.

Mirrors `customer_invite` (migration 042): opaque token, only its SHA-256 hash
stored, one unconsumed row per user at a time (service deletes prior unconsumed
rows on resend), tenant-isolated by RLS. Keyed to tenant_user instead of
customer.
"""

import logging

from alembic import op

# revision identifiers, used by Alembic.
revision = "055"
down_revision = "054"
branch_labels = None
depends_on = None

logger = logging.getLogger(__name__)


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE tenant_user_activation (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id UUID NOT NULL REFERENCES tenant(id) ON DELETE RESTRICT,
            user_id UUID NOT NULL REFERENCES tenant_user(id) ON DELETE CASCADE,
            token_hash CHAR(64) NOT NULL,
            expires_at TIMESTAMPTZ NOT NULL,
            consumed_at TIMESTAMPTZ,
            sent_channel VARCHAR(20),
            sent_to_masked VARCHAR(64),
            created_by UUID REFERENCES tenant_user(id),
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
        """
    )
    op.execute("CREATE UNIQUE INDEX idx_tenant_user_activation_token_hash ON tenant_user_activation(token_hash)")
    op.execute("CREATE INDEX idx_tenant_user_activation_user ON tenant_user_activation(tenant_id, user_id)")
    op.execute("ALTER TABLE tenant_user_activation ENABLE ROW LEVEL SECURITY")
    op.execute(
        """
        CREATE POLICY tenant_user_activation_tenant_isolation ON tenant_user_activation
        USING (tenant_id::text = current_setting('app.current_tenant_id', TRUE))
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS tenant_user_activation")
