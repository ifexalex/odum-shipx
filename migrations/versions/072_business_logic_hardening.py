"""072 — business logic & security hardening (RLS on claim_resolution, SLA breach tracking, ledger & banner invariants).

1. ``claim_resolution`` was created with a ``tenant_id`` column but without ``ENABLE ROW LEVEL SECURITY``, so migration
   059's catalog loop (``WHERE c.relrowsecurity``) skipped it. Enable and force RLS with the canonical PLATFORM-aware
   ``tenant_isolation`` policy.
2. ``cbm_dispute.sla_breached_at`` records when the 24-hour unacknowledged SLA breach job (``services/scheduled/sla_check.py``)
   processed a dispute so the 4-hour schedule logs and notifies once per dispute rather than on every run.
3. ``misc_charge.ck_misc_charge_amount_positive`` enforces ``amount_ngn > 0`` at the database layer (``NOT VALID`` so
   historical rows are not rewritten during DDL).
4. ``uq_staff_notification_active_banner_per_role`` enforces that at most one announcement banner is active per
   ``(tenant_id, target_role)`` at any time.
5. ``uq_carryover_active_per_source_billing`` prevents concurrent partial release notes on the same invoice from
   creating duplicate active (``outstanding`` / ``applied``) carryover ledger rows for the same ``source_billing_id``.

Revision ID: 072
Revises: 071
Create Date: 2026-11-23 18:30:00
"""

from alembic import op
from sqlalchemy import text

revision = "072"
down_revision = "071"
branch_labels = None
depends_on = None

_TENANT_SETTING = "app.current_tenant_id"


def upgrade() -> None:
    bind = op.get_bind()
    previous = bind.execute(text("SELECT current_setting(:name, TRUE)"), {"name": _TENANT_SETTING}).scalar()
    bind.execute(text("SELECT set_config(:name, 'PLATFORM', TRUE)"), {"name": _TENANT_SETTING})

    # 1. Canonical RLS on claim_resolution
    op.execute("ALTER TABLE claim_resolution ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE claim_resolution FORCE ROW LEVEL SECURITY")
    op.execute("DROP POLICY IF EXISTS tenant_isolation ON claim_resolution")
    op.execute(
        """
        CREATE POLICY tenant_isolation ON claim_resolution FOR ALL
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

    # 2. SLA breach timestamp on cbm_dispute
    op.execute("ALTER TABLE cbm_dispute ADD COLUMN IF NOT EXISTS sla_breached_at TIMESTAMPTZ")

    # 3. Positive miscellaneous charge invariant
    op.execute(
        """
        ALTER TABLE misc_charge
            ADD CONSTRAINT ck_misc_charge_amount_positive CHECK (amount_ngn > 0) NOT VALID
        """
    )

    # 4. Deactivate any older duplicate active banners per (tenant_id, target_role) before adding unique index
    op.execute(
        """
        WITH ranked AS (
            SELECT id,
                   ROW_NUMBER() OVER (
                       PARTITION BY tenant_id, target_role
                       ORDER BY created_at DESC, id DESC
                   ) AS rn
              FROM staff_notification
             WHERE banner_active = TRUE
               AND target_role IS NOT NULL
        )
        UPDATE staff_notification sn
           SET banner_active = FALSE
          FROM ranked r
         WHERE sn.id = r.id
           AND r.rn > 1
        """
    )
    op.execute(
        """
        CREATE UNIQUE INDEX IF NOT EXISTS uq_staff_notification_active_banner_per_role
            ON staff_notification (tenant_id, target_role)
            WHERE banner_active = TRUE AND target_role IS NOT NULL
        """
    )

    # 5. Unique active carryover per (tenant_id, source_billing_id)
    op.execute(
        """
        CREATE UNIQUE INDEX IF NOT EXISTS uq_carryover_active_per_source_billing
            ON carryover_ledger (tenant_id, source_billing_id)
            WHERE status IN ('outstanding', 'applied')
        """
    )

    bind.execute(text("SELECT set_config(:name, :value, TRUE)"), {"name": _TENANT_SETTING, "value": previous or ""})


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS uq_carryover_active_per_source_billing")
    op.execute("DROP INDEX IF EXISTS uq_staff_notification_active_banner_per_role")
    op.execute("ALTER TABLE misc_charge DROP CONSTRAINT IF EXISTS ck_misc_charge_amount_positive")
    op.execute("ALTER TABLE cbm_dispute DROP COLUMN IF EXISTS sla_breached_at")
    op.execute("DROP POLICY IF EXISTS tenant_isolation ON claim_resolution")
    op.execute("ALTER TABLE claim_resolution NO FORCE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE claim_resolution DISABLE ROW LEVEL SECURITY")
