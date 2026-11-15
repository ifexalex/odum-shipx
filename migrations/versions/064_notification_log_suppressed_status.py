"""064 — let notification_log record a message that was held back.

Customer notification preferences are now consulted before a consent-bound message is sent
(``shared/notification_consent.py``). When one is held back, the reason belongs in the log next to
the messages that were sent, so "why did this customer get nothing?" has an answer. That needs a
status of its own: ``suppressed``, with the reason in ``error_detail``. The CHECK on ``status``
allowed only ``queued``, ``sent``, ``delivered``, ``read`` and ``failed``.

Revision ID: 064
Revises: 063
Create Date: 2026-11-15 12:00:00
"""

from alembic import op

revision = "064"
down_revision = "063"
branch_labels = None
depends_on = None

_STATUSES_BEFORE = "'queued', 'sent', 'delivered', 'read', 'failed'"
_STATUSES_AFTER = _STATUSES_BEFORE + ", 'suppressed'"


def upgrade() -> None:
    op.execute("ALTER TABLE notification_log DROP CONSTRAINT notification_log_status_check")
    op.execute(f"ALTER TABLE notification_log ADD CONSTRAINT notification_log_status_check CHECK (status IN ({_STATUSES_AFTER}))")


def downgrade() -> None:
    # A suppressed row has no equivalent in the old vocabulary, so a downgrade with any present would
    # fail on the CHECK rather than silently rewrite history. Say so plainly instead.
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (SELECT 1 FROM notification_log WHERE status = 'suppressed') THEN
                RAISE EXCEPTION 'Cannot downgrade 064: notification_log has rows with status suppressed';
            END IF;
        END $$;
        """
    )
    op.execute("ALTER TABLE notification_log DROP CONSTRAINT notification_log_status_check")
    op.execute(
        f"ALTER TABLE notification_log ADD CONSTRAINT notification_log_status_check CHECK (status IN ({_STATUSES_BEFORE}))"
    )
