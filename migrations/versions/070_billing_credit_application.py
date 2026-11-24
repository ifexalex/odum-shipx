"""070 — which credits an invoice used, so cancelling it can give them back.

Invoice generation takes part or all of a customer's credits (``refund_request`` rows approved as credit for the
next shipment) and records only running totals: ``refund_request.credit_applied_ngn`` per credit and
``billing.credits_applied_ngn`` per invoice. Nothing said which invoice used how much of which credit, so cancelling
an invoice left its credit spent: the customer lost it.

``billing_credit_application`` is that record: one row per credit an invoice used, written in the invoice's own
transaction. Cancelling the invoice reverses each row (``reversed_at``) and returns the amount to the credit.

Invoices issued before this migration have no rows. Cancelling one that used credit is refused with
``CREDIT_NOT_TRACEABLE`` rather than guessed at (``docs/runbook.md``, "Cancelling an invoice that used credit").

Revision ID: 070
Revises: 069
Create Date: 2026-11-19 14:00:00
"""

from alembic import op

revision = "070"
down_revision = "069"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE billing_credit_application (
            id                UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id         UUID NOT NULL REFERENCES tenant(id) ON DELETE RESTRICT,
            billing_id        UUID NOT NULL REFERENCES billing(id) ON DELETE RESTRICT,
            refund_request_id UUID NOT NULL REFERENCES refund_request(id) ON DELETE RESTRICT,
            amount_ngn        DECIMAL(15, 2) NOT NULL CHECK (amount_ngn > 0),
            created_at        TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            reversed_at       TIMESTAMPTZ
        )
        """
    )
    op.execute("CREATE INDEX idx_billing_credit_application_billing ON billing_credit_application(tenant_id, billing_id)")
    op.execute("CREATE INDEX idx_billing_credit_application_refund ON billing_credit_application(tenant_id, refund_request_id)")
    op.execute("ALTER TABLE billing_credit_application ENABLE ROW LEVEL SECURITY")
    op.execute(
        """
        CREATE POLICY tenant_isolation ON billing_credit_application FOR ALL
        USING (
            current_setting('app.current_tenant_id', TRUE) = 'PLATFORM'
            OR tenant_id::text = current_setting('app.current_tenant_id', TRUE)
        )
        WITH CHECK (
            current_setting('app.current_tenant_id', TRUE) = 'PLATFORM'
            OR tenant_id::text = current_setting('app.current_tenant_id', TRUE)
        )
        """
    )
    op.execute("ALTER TABLE billing_credit_application FORCE ROW LEVEL SECURITY")
    op.execute(
        "COMMENT ON TABLE billing_credit_application IS "
        "'One row per credit an invoice used (migration 070). Cancelling the invoice reverses it and returns the amount.'"
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS billing_credit_application")
