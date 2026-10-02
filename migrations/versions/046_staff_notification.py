"""046 — staff_notification + staff_notification_read tables.

Ground-truth gap found live, reported by the user: "a staff rejected a
payment marked as paid, but no notification was showing when I logged into
the staff account." Investigation (see 15_api_notifications.md) found the
TopBar bell icon and unread badge were fully built in the frontend but never
fed any data — `StaffLayout.tsx` never passed `notifications`/
`onNotificationsClick` to `TopBar`, and no backing table or API existed at
all. The user asked to build the real thing: a full read/unread feed, not
just a live count.

`staff_notification` is a broadcast-or-targeted event row: `target_user_id`
set means "only this person", `target_role` set (with `target_user_id`
NULL) means "every staff member with this role", both NULL means "every
staff member in the tenant". Read state is tracked per-viewer in the
separate `staff_notification_read` table so a role-broadcast notification
can be independently marked read by each recipient without affecting what
anyone else sees — the same "one event, many viewers, per-viewer state"
shape as `notification_log` is to a single delivery, just inverted (many
viewers here instead of many channels).

Revision ID: 046
Revises: 045
Create Date: 2026-09-12 00:00:00
"""

from alembic import op

revision = "046"
down_revision = "045"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE staff_notification (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id UUID NOT NULL REFERENCES tenant(id) ON DELETE CASCADE,
            target_role VARCHAR(30),
            target_user_id UUID REFERENCES tenant_user(id) ON DELETE CASCADE,
            event_type VARCHAR(50) NOT NULL,
            entity_type VARCHAR(30) NOT NULL,
            entity_id UUID,
            title VARCHAR(200) NOT NULL,
            body TEXT,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
        """
    )
    op.execute("CREATE INDEX idx_staff_notification_tenant_created ON staff_notification(tenant_id, created_at DESC)")
    op.execute("CREATE INDEX idx_staff_notification_tenant_role ON staff_notification(tenant_id, target_role)")
    op.execute("CREATE INDEX idx_staff_notification_tenant_user ON staff_notification(tenant_id, target_user_id)")
    op.execute("ALTER TABLE staff_notification ENABLE ROW LEVEL SECURITY")
    op.execute(
        """
        CREATE POLICY staff_notification_tenant_isolation ON staff_notification
        USING (tenant_id::text = current_setting('app.current_tenant_id', TRUE))
        """
    )

    op.execute(
        """
        CREATE TABLE staff_notification_read (
            tenant_id UUID NOT NULL REFERENCES tenant(id) ON DELETE CASCADE,
            notification_id UUID NOT NULL REFERENCES staff_notification(id) ON DELETE CASCADE,
            user_id UUID NOT NULL REFERENCES tenant_user(id) ON DELETE CASCADE,
            read_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            PRIMARY KEY (notification_id, user_id)
        )
        """
    )
    op.execute("CREATE INDEX idx_staff_notification_read_user ON staff_notification_read(tenant_id, user_id)")
    op.execute("ALTER TABLE staff_notification_read ENABLE ROW LEVEL SECURITY")
    op.execute(
        """
        CREATE POLICY staff_notification_read_tenant_isolation ON staff_notification_read
        USING (tenant_id::text = current_setting('app.current_tenant_id', TRUE))
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS staff_notification_read CASCADE")
    op.execute("DROP TABLE IF EXISTS staff_notification CASCADE")
