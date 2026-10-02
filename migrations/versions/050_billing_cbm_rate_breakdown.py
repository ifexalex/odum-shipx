"""050 — billing.cbm_rate_currency + cbm_rate_mode + cbm_breakdown.

User: "For CMB rate, let's allow the tenant admin to have multiple options
for the rate: 1. One Single rate with options of either Naira or Dollar.
2. Rates targeted to Bags, Cartons and Bales." Previously `cbm_rate_usd` was
the only pricing field on `billing` — one flat USD number, snapshotted per
invoice. It now stays as the single USD-equivalent rate other code (CBM
dispute resolution, exports, staff/customer UI) already treats as ground
truth via `total_cbm * cbm_rate_usd == subtotal_usd`, and three new columns
record *how* that number was actually derived:

- `cbm_rate_currency` — the tenant's configured currency at billing time
  ('USD' or 'NGN'). `cbm_rate_usd` is always USD-equivalent regardless —
  when the tenant's config is NGN-denominated, it's back-derived via the
  effective dollar rate, same as `subtotal_usd` already is today.
- `cbm_rate_mode` — 'flat' or 'per_package_type', purely descriptive/audit
  (which form the tenant admin used) — billing computation itself never
  branches on this; a "flat" rate is just the case where the tenant's
  carton/bag/bale rates all happen to be equal.
- `cbm_breakdown` — the actual per-package-type CBM/rate/subtotal used, in
  the tenant's configured currency, always populated (not just for
  per_package_type invoices) for full transparency. Becomes historical
  record only — not reconciled — if a later CBM dispute adjusts the
  invoice's total_cbm, since disputes are whole-invoice, never per-type.

Revision ID: 050
Revises: 049
Create Date: 2026-09-20 00:00:00
"""

from alembic import op

revision = "050"
down_revision = "049"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE billing ADD COLUMN cbm_rate_currency VARCHAR(3) NOT NULL DEFAULT 'USD'")
    op.execute("ALTER TABLE billing ADD COLUMN cbm_rate_mode VARCHAR(20) NOT NULL DEFAULT 'flat'")
    op.execute("ALTER TABLE billing ADD COLUMN cbm_breakdown JSONB")


def downgrade() -> None:
    op.execute("ALTER TABLE billing DROP COLUMN cbm_breakdown")
    op.execute("ALTER TABLE billing DROP COLUMN cbm_rate_mode")
    op.execute("ALTER TABLE billing DROP COLUMN cbm_rate_currency")
