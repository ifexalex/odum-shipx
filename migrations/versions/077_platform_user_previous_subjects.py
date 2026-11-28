"""077 — Keep a platform admin's earlier identity subjects (platform audit Phase 1b).

Platform admins move from the tenant Cognito pool to the platform pool, which requires MFA
(``scripts/platform_admins.py move-to-platform-pool``). A new pool means a new ``sub``, so the move rebinds
``platform_user.subject`` and appends the old one to ``previous_subjects``. The platform audit log names an actor by
matching ``actor_id`` against either, so rows written before the move keep their name.

Revision ID: 077
Revises: 076
"""

from alembic import op

revision = "077"
down_revision = "076"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE platform_user ADD COLUMN previous_subjects TEXT[] NOT NULL DEFAULT '{}';
        CREATE INDEX idx_platform_user_previous_subjects ON platform_user USING GIN (previous_subjects);
        """
    )


def downgrade() -> None:
    op.execute(
        """
        DROP INDEX IF EXISTS idx_platform_user_previous_subjects;
        ALTER TABLE platform_user DROP COLUMN IF EXISTS previous_subjects;
        """
    )
