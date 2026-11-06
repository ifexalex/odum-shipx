"""042 — customer_invite table + phone uniqueness.

Manifest import creates customer rows with only name + phone — no login,
no email. This migration adds the account-creation-invite mechanism (an
expiring, single-use token, delivered by SMS/WhatsApp) and makes `phone`
a real per-tenant identifier so imported, self-registered, and
admin-created customer rows for the same person converge on one row
instead of silently duplicating.

1. **customer_invite** — one unconsumed row per customer at a time
   (service layer deletes any prior unconsumed invite before minting a
   new one — "resend invalidates the old link"). Only a SHA-256 hash of
   the token is ever stored; `sent_to_masked` holds a masked phone/email
   hint, never the raw contact. RLS on, standard tenant-isolation policy.

2. **customer(tenant_id, phone) uniqueness** — phone normalisation
   (`shared/phone.py`) is a prerequisite of this migration, not
   introduced by it: application code must already be canonicalising to
   E.164 before this index is added, or the index creation below fails
   on pre-existing duplicates. That failure is deliberate — see the
   pre-flight check.

   Pre-flight: reports any (tenant_id, phone) pairs that already collide
   under E.164-equivalence and ABORTS the migration rather than merging
   customer records — merging is a data decision for the tenant, not
   something a migration should decide silently. Operators must resolve
   reported duplicates (merge or clear one side's phone) and re-run.

Revision ID: 042
Revises: 041
Create Date: 2026-08-28 00:00:00
"""

import logging

from alembic import op
from sqlalchemy import text

revision = "042"
down_revision = "041"
branch_labels = None
depends_on = None

logger = logging.getLogger(__name__)


def upgrade() -> None:
    # -------------------------------------------------------------------
    # 1. customer_invite
    # -------------------------------------------------------------------
    op.execute(
        """
        CREATE TABLE customer_invite (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id UUID NOT NULL REFERENCES tenant(id) ON DELETE RESTRICT,
            customer_id UUID NOT NULL REFERENCES customer(id) ON DELETE CASCADE,
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
    op.execute("CREATE UNIQUE INDEX idx_customer_invite_token_hash ON customer_invite(token_hash)")
    op.execute("CREATE INDEX idx_customer_invite_customer ON customer_invite(tenant_id, customer_id)")
    op.execute("ALTER TABLE customer_invite ENABLE ROW LEVEL SECURITY")
    op.execute(
        """
        CREATE POLICY customer_invite_tenant_isolation ON customer_invite
        USING (tenant_id::text = current_setting('app.current_tenant_id', TRUE))
        """
    )

    # -------------------------------------------------------------------
    # 2. customer(tenant_id, phone) uniqueness — report duplicates, stop.
    # -------------------------------------------------------------------
    conn = op.get_bind()
    duplicates = (
        conn.execute(
            text(
                """
            SELECT tenant_id, phone, COUNT(*) AS n, array_agg(id) AS customer_ids
            FROM customer
            WHERE phone IS NOT NULL AND anonymised_at IS NULL
            GROUP BY tenant_id, phone
            HAVING COUNT(*) > 1
            """
            )
        )
        .mappings()
        .fetchall()
    )

    if duplicates:
        details = "\n".join(
            f"  tenant_id={row['tenant_id']} phone={row['phone']} count={row['n']} customer_ids={row['customer_ids']}"
            for row in duplicates
        )
        raise RuntimeError(
            "Migration 042 aborted: customer(tenant_id, phone) has "
            f"{len(duplicates)} duplicate group(s) that must be resolved before the "
            "unique index can be created. Merging is a data decision, not something "
            "this migration will do silently. Resolve each group (merge the "
            "customer records or clear one side's phone) and re-run:\n" + details
        )

    # Named distinctly from migration 002's pre-existing plain (non-unique)
    # idx_customer_tenant_phone — that index stays in place (redundant but
    # harmless; not worth editing an already-applied historical migration
    # for) and this one adds the actual uniqueness constraint.
    op.execute("CREATE UNIQUE INDEX idx_customer_tenant_phone_unique ON customer(tenant_id, phone) WHERE phone IS NOT NULL")


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS idx_customer_tenant_phone_unique")
    op.execute("DROP TABLE IF EXISTS customer_invite CASCADE")
