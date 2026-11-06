"""044 — payment_claim table.

Bug found live (reported by the user): the "Manual bank transfer" payment
option only ever showed static bank details — there was no way for a
customer to tell the platform they had actually sent the money, and no
required proof of payment. Staff had no queue to review; a transfer only
ever got recorded if a staff member happened to notice it in the bank
account and manually keyed it in via the existing `payment_record` flow,
with no paper trail connecting that record back to what the customer sent.

`payment_claim` is the customer-submitted "I've made this payment" record:
one row per submission, with a required evidence file (receipt/screenshot)
and a `pending -> confirmed / rejected` review by staff. Confirming a claim
creates the real `payment_record` (the source of truth for the billing
total-paid calculation) and links back to it — the claim is a queue/audit
trail, not a second ledger.

Revision ID: 044
Revises: 043
Create Date: 2026-09-06 00:00:00
"""

from alembic import op

revision = "044"
down_revision = "043"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE payment_claim (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id UUID NOT NULL REFERENCES tenant(id) ON DELETE RESTRICT,
            billing_id UUID NOT NULL REFERENCES billing(id) ON DELETE CASCADE,
            customer_id UUID NOT NULL REFERENCES customer(id) ON DELETE RESTRICT,
            amount_ngn NUMERIC(14, 2) NOT NULL CHECK (amount_ngn > 0),
            evidence_file_key TEXT NOT NULL,
            evidence_file_name VARCHAR(255) NOT NULL,
            customer_note TEXT,
            status VARCHAR(20) NOT NULL DEFAULT 'pending' CHECK (status IN (
                'pending', 'confirmed', 'rejected'
            )),
            rejection_reason TEXT,
            reviewed_by UUID REFERENCES tenant_user(id),
            reviewed_at TIMESTAMPTZ,
            payment_record_id UUID REFERENCES payment_record(id),
            submitted_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
        """
    )
    op.execute("CREATE INDEX idx_payment_claim_tenant_billing ON payment_claim(tenant_id, billing_id)")
    op.execute("CREATE INDEX idx_payment_claim_tenant_status ON payment_claim(tenant_id, status)")
    op.execute("ALTER TABLE payment_claim ENABLE ROW LEVEL SECURITY")
    op.execute(
        """
        CREATE POLICY payment_claim_tenant_isolation ON payment_claim
        USING (tenant_id::text = current_setting('app.current_tenant_id', TRUE))
        """
    )
    # Only one pending claim per billing at a time — a customer resubmitting
    # (e.g. wrong evidence) should replace, not pile up, an open claim.
    op.execute(
        "CREATE UNIQUE INDEX idx_payment_claim_one_pending_per_billing ON payment_claim(billing_id) WHERE status = 'pending'"
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS payment_claim CASCADE")
