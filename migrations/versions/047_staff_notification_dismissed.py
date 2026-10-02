"""047 — staff_notification_read.dismissed_at (clearing a notification).

Ground-truth follow-up, reported by the user right after the notification
bell shipped: "the notification should allow clearing." Mark-as-read (migration
046) left a read notification permanently in the list — there was no way to
remove it from view. `dismissed_at` lives on the same per-viewer
`staff_notification_read` row as `read_at`, so clearing a role-broadcast
notification for one viewer never affects what any other viewer sees, same
"one event, many viewers, per-viewer state" design as the read tracking it
sits next to. Clearing always implies read (a cleared notification was, by
definition, seen), so the existing unread-count query needs no change —
`read_at` is set alongside `dismissed_at` in the same write.

Revision ID: 047
Revises: 046
Create Date: 2026-09-15 00:00:00
"""

from alembic import op

revision = "047"
down_revision = "046"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE staff_notification_read ADD COLUMN dismissed_at TIMESTAMPTZ")


def downgrade() -> None:
    op.execute("ALTER TABLE staff_notification_read DROP COLUMN dismissed_at")
