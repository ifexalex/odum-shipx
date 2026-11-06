"""Add locale to notification_log.

`get_log_for_fallback` has always selected `notification_log.locale` so that an
SMS falling back from a failed WhatsApp send is rendered in the recipient's
language (`_SMS_TEMPLATES_ZH` for `zh`). The column was never created, so every
fallback raised `UndefinedColumn` and no SMS was ever queued — WhatsApp-first
had no working fallback at all. Caught by draining a real queued notification
locally; unit tests missed it because they stub the repository.

Nullable with no default: rows written before this migration genuinely have no
recorded locale, and `trigger_sms_fallback` already coalesces to "en".

Revision ID: 043
Revises: 042
"""

import sqlalchemy as sa
from alembic import op

revision = "043"
down_revision = "042"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("notification_log", sa.Column("locale", sa.String(5), nullable=True))


def downgrade() -> None:
    op.drop_column("notification_log", "locale")
