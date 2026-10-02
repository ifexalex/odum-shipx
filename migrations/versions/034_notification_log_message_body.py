"""034 — notification_log message_body.

Adds a message_body column to notification_log so the rendered message text
is stored alongside the delivery metadata — used to show a preview in the
Notification Delivery Log UI and the full body in the detail modal.
"""

from alembic import op

revision = "034"
down_revision = "033"


def upgrade() -> None:
    op.execute("ALTER TABLE notification_log ADD COLUMN IF NOT EXISTS message_body TEXT")


def downgrade() -> None:
    op.execute("ALTER TABLE notification_log DROP COLUMN IF EXISTS message_body")
