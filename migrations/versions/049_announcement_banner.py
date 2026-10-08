"""049 — announcement banner: staff_notification.announcement_group_id + banner_active.

Direct user follow-up, sent mid-review of the announcement-approval feature:
"annoucement should be a banner on the target user's web page, with this
they won't miss it. It can be enabled or disabled, more can be created but
only one can be visible per time. with this. we can add amination to it, so
that it is obvious to the target user."

Two new columns on `staff_notification`, meaningful only for
`entity_type = 'announcement'` rows (every other event type leaves them at
their defaults and never reads them):

- `announcement_group_id` — one "all_staff" send fans out to 4 rows (one per
  staff role, same reasoning as migration 046/048's comments on why a bare
  NULL/NULL broadcast row is unsafe); all 4 share one group id so an
  enable/disable action toggles the banner for every targeted role at once,
  and the admin-facing history list can show one entry per send instead of
  four near-duplicates.
- `banner_active` — whether this row's audience should currently see it as a
  page banner (not just a bell entry). Enforced from the service layer, not
  a DB constraint: creating a new banner-eligible announcement first flips
  `banner_active` false on every currently-active row targeting the same
  audience (the staff roles for an "all_staff" send, or "customer" for an
  "all_customers" send) before inserting the new group — "only one can be
  visible per time" per audience. A tenant_admin can also flip it directly
  via PATCH .../activate|deactivate.

Revision ID: 049
Revises: 048
Create Date: 2026-09-12 00:00:00
"""

from alembic import op

revision = "049"
down_revision = "048"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE staff_notification ADD COLUMN announcement_group_id UUID")
    op.execute("ALTER TABLE staff_notification ADD COLUMN banner_active BOOLEAN NOT NULL DEFAULT FALSE")
    op.execute(
        "CREATE INDEX idx_staff_notification_banner_active "
        "ON staff_notification(tenant_id, target_role) WHERE banner_active = TRUE"
    )
    op.execute(
        "CREATE INDEX idx_staff_notification_announcement_group " "ON staff_notification(tenant_id, announcement_group_id)"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS idx_staff_notification_announcement_group")
    op.execute("DROP INDEX IF EXISTS idx_staff_notification_banner_active")
    op.execute("ALTER TABLE staff_notification DROP COLUMN banner_active")
    op.execute("ALTER TABLE staff_notification DROP COLUMN announcement_group_id")
