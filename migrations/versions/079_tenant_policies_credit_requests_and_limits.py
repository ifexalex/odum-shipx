"""079 — Tenant policy history, credit release requests, and customer credit limits (Tenant Admin Phase 1).

1. ``tenant_policy_history``: append-only log of tenant policy changes (storage fees, refund/claim approval limit,
   credit defaults, dispute escalation, storage reminders) with an ``effective_date`` (default tomorrow, decision D4)
   so historical storage-fee accrual days are never repriced.
2. ``credit_release_request``: staff request to release goods with an unpaid balance (decision D2 / D5). Reviewed
   and approved/rejected by a ``tenant_admin`` in the Approvals inbox; approval atomically creates the release note
   under the approving admin's identity.
3. ``customer.credit_limit_ngn`` and ``customer.credit_terms_days``: per-customer credit limit and payment terms
   (decision D3), falling back to the tenant's ``credit_defaults`` policy when NULL.

Revision ID: 079
Revises: 078
"""

from alembic import op

revision = "079"
down_revision = "078"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE tenant_policy_history (
            id             UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id      UUID        NOT NULL REFERENCES tenant(id) ON DELETE CASCADE,
            policy_key     TEXT        NOT NULL CHECK (
                policy_key IN (
                    'storage_fee',
                    'refund_threshold_usd',
                    'credit_defaults',
                    'dispute_escalation',
                    'reminder_days'
                )
            ),
            old_value      JSONB,
            new_value      JSONB       NOT NULL,
            effective_date DATE        NOT NULL,
            changed_by     UUID        REFERENCES tenant_user(id) ON DELETE SET NULL,
            created_at     TIMESTAMPTZ NOT NULL DEFAULT NOW()
        );
        CREATE INDEX idx_tenant_policy_history_lookup
            ON tenant_policy_history (tenant_id, policy_key, effective_date DESC, created_at DESC);

        CREATE TABLE credit_release_request (
            id                           UUID           PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id                    UUID           NOT NULL REFERENCES tenant(id) ON DELETE CASCADE,
            billing_id                   UUID           NOT NULL REFERENCES billing(id) ON DELETE CASCADE,
            customer_id                  UUID           NOT NULL REFERENCES customer(id) ON DELETE CASCADE,
            carton_tags                  TEXT[]         NOT NULL DEFAULT '{}',
            packages_released            INTEGER,
            package_unit                 TEXT,
            warehouse_id                 UUID           REFERENCES warehouse(id) ON DELETE SET NULL,
            physical_document_number     TEXT,
            packing_list_invoice_numbers TEXT[]         NOT NULL DEFAULT '{}',
            due_date                     DATE,
            amount_ngn                   NUMERIC(14, 2) NOT NULL DEFAULT 0,
            customer_credit_limit_ngn    NUMERIC(14, 2),
            customer_current_exposure_ngn NUMERIC(14, 2) NOT NULL DEFAULT 0,
            exceeds_credit_limit         BOOLEAN        NOT NULL DEFAULT FALSE,
            reason                       TEXT           NOT NULL,
            requested_by                 UUID           REFERENCES tenant_user(id) ON DELETE SET NULL,
            status                       TEXT           NOT NULL DEFAULT 'pending'
                                                        CHECK (status IN ('pending', 'approved', 'rejected')),
            decided_by                   UUID           REFERENCES tenant_user(id) ON DELETE SET NULL,
            decided_at                   TIMESTAMPTZ,
            decision_notes               TEXT,
            release_note_id              UUID           REFERENCES release_note(id) ON DELETE SET NULL,
            created_at                   TIMESTAMPTZ    NOT NULL DEFAULT NOW(),
            updated_at                   TIMESTAMPTZ    NOT NULL DEFAULT NOW()
        );
        CREATE INDEX idx_credit_release_request_tenant_status
            ON credit_release_request (tenant_id, status, created_at DESC);
        CREATE INDEX idx_credit_release_request_tenant_billing
            ON credit_release_request (tenant_id, billing_id);

        ALTER TABLE customer
            ADD COLUMN IF NOT EXISTS credit_limit_ngn  NUMERIC(14, 2),
            ADD COLUMN IF NOT EXISTS credit_terms_days INTEGER;

        ALTER TABLE tenant_policy_history ENABLE ROW LEVEL SECURITY;
        ALTER TABLE tenant_policy_history FORCE ROW LEVEL SECURITY;
        CREATE POLICY tenant_isolation ON tenant_policy_history FOR ALL
            USING (
                current_setting('app.current_tenant_id', TRUE) = 'PLATFORM'
                OR tenant_id::text = current_setting('app.current_tenant_id', TRUE)
            )
            WITH CHECK (
                current_setting('app.current_tenant_id', TRUE) = 'PLATFORM'
                OR tenant_id::text = current_setting('app.current_tenant_id', TRUE)
            );

        ALTER TABLE credit_release_request ENABLE ROW LEVEL SECURITY;
        ALTER TABLE credit_release_request FORCE ROW LEVEL SECURITY;
        CREATE POLICY tenant_isolation ON credit_release_request FOR ALL
            USING (
                current_setting('app.current_tenant_id', TRUE) = 'PLATFORM'
                OR tenant_id::text = current_setting('app.current_tenant_id', TRUE)
            )
            WITH CHECK (
                current_setting('app.current_tenant_id', TRUE) = 'PLATFORM'
                OR tenant_id::text = current_setting('app.current_tenant_id', TRUE)
            );

        DO $outer$
        BEGIN
            IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'logistics_app') THEN
                GRANT SELECT, INSERT, UPDATE, DELETE ON tenant_policy_history, credit_release_request TO logistics_app;
            END IF;
        END $outer$;
        """
    )


def downgrade() -> None:
    op.execute(
        """
        ALTER TABLE customer
            DROP COLUMN IF EXISTS credit_terms_days,
            DROP COLUMN IF EXISTS credit_limit_ngn;
        DROP TABLE IF EXISTS credit_release_request;
        DROP TABLE IF EXISTS tenant_policy_history;
        """
    )
