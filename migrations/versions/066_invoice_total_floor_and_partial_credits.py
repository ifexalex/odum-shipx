"""066 — an invoice total cannot be negative, and a credit is spent only as far as it is needed (audit BE-07).

Invoice generation subtracted every credit the customer held from the new invoice, in full. A customer holding more
credit than the invoice came to got a negative total, and the whole credit was marked used, so the difference was
neither owed by them nor kept for them.

This migration adds what the fix needs:

* ``refund_request.credit_applied_ngn``: how much of a credit invoices have used so far. A credit stays
  ``applied_as_credit`` until this reaches its approved amount, then becomes ``completed``. Existing ``completed``
  credits were spent whole under the old rule and are backfilled to their full value.
* ``billing.credits_applied_ngn``: the credit an invoice absorbed when it was issued, so the parts of an invoice add
  up to its total. Unknown for invoices issued before this migration (left at 0): the old rule did not record it.
* ``ck_billing_total_not_negative``: ``CHECK (total_ngn >= 0)``.

The CHECK is added ``NOT VALID`` first, which enforces it for every new and changed row at once without reading the
table. It is then validated only if no existing invoice breaks it. If some do, the migration still succeeds and says
how many: those rows are money decisions for a person to make (see ``docs/runbook.md``, "Invoices with a negative
total"), not something to rewrite here. Until they are repaired they cannot be updated, and the constraint stays
unvalidated; run ``ALTER TABLE billing VALIDATE CONSTRAINT ck_billing_total_not_negative`` afterwards.

Revision ID: 066
Revises: 065
Create Date: 2026-11-17 12:00:00
"""

import logging

from alembic import op
from sqlalchemy import text

revision = "066"
down_revision = "065"
branch_labels = None
depends_on = None

logger = logging.getLogger("alembic.runtime.migration")

_TENANT_SETTING = "app.current_tenant_id"


def upgrade() -> None:
    bind = op.get_bind()
    # The backfill and the count below must see every tenant's rows. Both tables force row-level security, which
    # applies to the table owner too, so read as PLATFORM for the length of this migration and then put back
    # whatever was set.
    previous = bind.execute(text("SELECT current_setting(:name, TRUE)"), {"name": _TENANT_SETTING}).scalar()
    bind.execute(text("SELECT set_config(:name, 'PLATFORM', TRUE)"), {"name": _TENANT_SETTING})

    op.execute(
        """
        ALTER TABLE refund_request
            ADD COLUMN credit_applied_ngn DECIMAL(15, 2) NOT NULL DEFAULT 0
                CONSTRAINT ck_refund_request_credit_applied_not_negative CHECK (credit_applied_ngn >= 0)
        """
    )
    # A credit already marked completed was subtracted whole from an invoice under the old rule.
    op.execute(
        """
        UPDATE refund_request
           SET credit_applied_ngn = COALESCE(amount_approved_ngn, amount_ngn)
         WHERE status = 'completed' AND customer_choice = 'credit_next_shipment'
           AND COALESCE(amount_approved_ngn, amount_ngn) >= 0
        """
    )
    op.execute(
        """
        ALTER TABLE billing
            ADD COLUMN credits_applied_ngn DECIMAL(15, 2) NOT NULL DEFAULT 0
                CONSTRAINT ck_billing_credits_applied_not_negative CHECK (credits_applied_ngn >= 0)
        """
    )
    op.execute("ALTER TABLE billing ADD CONSTRAINT ck_billing_total_not_negative CHECK (total_ngn >= 0) NOT VALID")

    negative = bind.execute(text("SELECT COUNT(*) FROM billing WHERE total_ngn < 0")).scalar_one()
    if negative:
        logger.warning(
            "066: %d invoice(s) have a negative total. ck_billing_total_not_negative is enforced for new and changed "
            "rows but left NOT VALID. Repair them (docs/runbook.md, 'Invoices with a negative total'), then run "
            "ALTER TABLE billing VALIDATE CONSTRAINT ck_billing_total_not_negative.",
            negative,
        )
    else:
        op.execute("ALTER TABLE billing VALIDATE CONSTRAINT ck_billing_total_not_negative")

    bind.execute(text("SELECT set_config(:name, :value, TRUE)"), {"name": _TENANT_SETTING, "value": previous or ""})


def downgrade() -> None:
    op.execute("ALTER TABLE billing DROP CONSTRAINT ck_billing_total_not_negative")
    op.execute("ALTER TABLE billing DROP COLUMN credits_applied_ngn")
    op.execute("ALTER TABLE refund_request DROP COLUMN credit_applied_ngn")
