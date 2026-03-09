"""Drop the FK constraint on tenant_config.updated_by.

tenant_config.updated_by stores the Cognito sub of the user who last changed
the config. The Cognito sub is a UUID but it lives in Cognito, not in the
tenant_user table — so the FK constraint causes a ForeignKeyViolation for
every valid PUT /v1/tenant/config or PUT /v1/tenant/dollar-rate request.

The column is kept as UUID (it is still informative for auditing); it simply
no longer has a FK constraint. This is consistent with how audit_log.actor_id
is stored: as a plain identifier rather than a DB FK.

Revision ID: 014
Revises: 013
Create Date: 2026-03-01 00:00:00
"""

from alembic import op

revision = "014"
down_revision = "013"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE tenant_config DROP CONSTRAINT IF EXISTS tenant_config_updated_by_fkey")


def downgrade() -> None:
    # Re-adding the FK is only safe if all existing updated_by values exist in
    # tenant_user. In practice this is not guaranteed, so downgrade is a no-op.
    pass
