"""048 — announcement_request table (staff announcements need admin approval).

Direct user follow-up to the just-shipped announcement feature: "Tenant admin
can send announcement to all staffs and all customers. But the staff can
only send to customers, which should be approved by the tenant admins, this
is to ensure that a compromised staff does not misinformation the
customers." Two changes to the trust model:

1. `nigeria_office_staff` may no longer target `all_staff` at all (only
   `tenant_admin` can reach the whole staff body) — enforced in
   `services/notification/handler.py`, no schema involvement.
2. A staff-composed `all_customers` announcement is no longer created
   immediately. It is held here as a `pending` request until a
   `tenant_admin` approves or rejects it — a compromised staff account can
   no longer broadcast misinformation straight to every customer.

`tenant_admin`-composed announcements (either audience) still go out
immediately via the existing `staff_notification` insert path — this table
only queues the one path that needed a second set of eyes.

Revision ID: 048
Revises: 047
Create Date: 2026-09-12 00:00:00
"""

from alembic import op

revision = "048"
down_revision = "047"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE announcement_request (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id UUID NOT NULL REFERENCES tenant(id) ON DELETE CASCADE,
            title VARCHAR(200) NOT NULL,
            body TEXT,
            audience VARCHAR(20) NOT NULL,
            status VARCHAR(20) NOT NULL DEFAULT 'pending',
            requested_by UUID NOT NULL REFERENCES tenant_user(id),
            reviewed_by UUID REFERENCES tenant_user(id),
            reviewed_at TIMESTAMPTZ,
            rejection_reason VARCHAR(500),
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
        """
    )
    op.execute(
        "CREATE INDEX idx_announcement_request_tenant_status " "ON announcement_request(tenant_id, status, created_at DESC)"
    )
    op.execute("ALTER TABLE announcement_request ENABLE ROW LEVEL SECURITY")
    op.execute(
        """
        CREATE POLICY announcement_request_tenant_isolation ON announcement_request
        USING (tenant_id::text = current_setting('app.current_tenant_id', TRUE))
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS announcement_request CASCADE")
