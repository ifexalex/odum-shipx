"""Add gateway_transaction_id to payment_record; expand payment_method CHECK.

Supports automated payment confirmation via Paystack/Flutterwave webhooks.

  payment_record.gateway_transaction_id  — nullable unique gateway TX ID
  payment_record.payment_method CHECK    — adds 'paystack', 'flutterwave'

Revision ID: 018
Revises: 017
Create Date: 2024-01-01 00:00:17
"""

from alembic import op

revision = "018"
down_revision = "017"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # gateway_transaction_id: unique so duplicate webhook deliveries can be detected
    op.execute("ALTER TABLE payment_record ADD COLUMN IF NOT EXISTS gateway_transaction_id VARCHAR(255)")
    op.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS idx_payment_record_gateway_tx"
        " ON payment_record(tenant_id, gateway_transaction_id)"
        " WHERE gateway_transaction_id IS NOT NULL"
    )

    # Expand payment_method allowlist
    op.execute("ALTER TABLE payment_record DROP CONSTRAINT IF EXISTS payment_record_payment_method_check")
    op.execute(
        """
        ALTER TABLE payment_record ADD CONSTRAINT payment_record_payment_method_check
        CHECK (payment_method IN (
            'bank_transfer',
            'cash',
            'pos',
            'online',
            'paystack',
            'flutterwave'
        ))
    """
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS idx_payment_record_gateway_tx")
    op.execute("ALTER TABLE payment_record DROP COLUMN IF EXISTS gateway_transaction_id")
    op.execute("ALTER TABLE payment_record DROP CONSTRAINT IF EXISTS payment_record_payment_method_check")
    op.execute(
        """
        ALTER TABLE payment_record ADD CONSTRAINT payment_record_payment_method_check
        CHECK (payment_method IN (
            'bank_transfer',
            'cash',
            'pos',
            'online'
        ))
    """
    )
