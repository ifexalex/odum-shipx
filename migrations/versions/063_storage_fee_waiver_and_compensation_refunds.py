"""063 — record waived storage fees on the fee log; allow compensation refund types.

Waiving storage fees never worked, for two reasons found while making invoice
changes atomic.

1. `waive_storage_fees_for_billing` deleted ``misc_charge`` rows by ``tenant_id``,
   a column that table does not have, so every waive raised and returned a server
   error.
2. It was never reachable from the UI. The invoice page shows storage fees from
   ``storage_fees_ngn``, which was summed from ``misc_charge`` rows of type
   ``storage_fee`` -- but the daily accrual job writes only to ``storage_fee_log``
   and adds the fee to ``billing.total_ngn``, never creating a misc charge. So
   ``storage_fees_ngn`` was always 0, the storage banner never showed accrued
   fees, and the waive button, which needs it above 0, was never offered.

The fee log is the one record that exists for every accrued fee, so it becomes the
source of truth: ``storage_fees_ngn`` is the sum of its un-waived rows, and a waiver
marks rows waived and takes their total off the invoice, in one transaction.

``is_billed`` (default false, set by nothing) stays as it is; it never carried the
meaning the old waive code gave it.

Compensating a missing or seized item never worked either
---------------------------------------------------------
``update_missing_item`` / ``update_seized_item`` open a refund request with
``refund_type`` ``'missing_item'`` / ``'seized_item'``, but the CHECK on
``refund_request.refund_type`` (migration 009) allows only ``overpayment``,
``cbm_correction`` and ``damage_or_loss``. Every compensation therefore failed with
a constraint violation -- after the item's new status had already been committed, so
the item showed as compensated with no refund behind it. Unit tests mock the
repository, so none of them could see it. The constraint now allows both values.

Revision ID: 063
Revises: 062
Create Date: 2026-11-14 12:00:00
"""

from alembic import op

revision = "063"
down_revision = "062"
branch_labels = None
depends_on = None


_REFUND_TYPES_BEFORE = "'overpayment', 'cbm_correction', 'damage_or_loss'"
_REFUND_TYPES_AFTER = _REFUND_TYPES_BEFORE + ", 'missing_item', 'seized_item'"


def upgrade() -> None:
    op.execute("ALTER TABLE refund_request DROP CONSTRAINT refund_request_refund_type_check")
    op.execute(
        "ALTER TABLE refund_request ADD CONSTRAINT refund_request_refund_type_check "
        f"CHECK (refund_type IN ({_REFUND_TYPES_AFTER}))"
    )
    op.execute(
        """
        ALTER TABLE storage_fee_log
            ADD COLUMN waived_at   TIMESTAMPTZ,
            ADD COLUMN waive_reason TEXT
        """
    )
    # Un-waived rows are what an invoice is charged for; index the common read.
    op.execute(
        """
        CREATE INDEX idx_storage_fee_log_billing_unwaived
            ON storage_fee_log (billing_id) WHERE waived_at IS NULL
        """
    )


def downgrade() -> None:
    # Rows already using the new types would violate the old constraint; remove the
    # constraint's new values only if none exist, otherwise fail loudly.
    op.execute("ALTER TABLE refund_request DROP CONSTRAINT refund_request_refund_type_check")
    op.execute(
        "ALTER TABLE refund_request ADD CONSTRAINT refund_request_refund_type_check "
        f"CHECK (refund_type IN ({_REFUND_TYPES_BEFORE}))"
    )
    op.execute("DROP INDEX IF EXISTS idx_storage_fee_log_billing_unwaived")
    op.execute("ALTER TABLE storage_fee_log DROP COLUMN IF EXISTS waive_reason, DROP COLUMN IF EXISTS waived_at")
