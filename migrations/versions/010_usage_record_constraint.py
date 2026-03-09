"""Add UNIQUE constraint to usage_record for ON CONFLICT UPSERT support.

Required by the Metering service SQS consumer, which uses:
  INSERT ... ON CONFLICT (tenant_id, metric_type, period_start)
  DO UPDATE SET value = usage_record.value + EXCLUDED.value

Revision ID: 010
Revises: 009
Create Date: 2024-01-01 00:00:09
"""

from alembic import op

revision = "010"
down_revision = "009"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE usage_record
        ADD CONSTRAINT uq_usage_tenant_metric_period
        UNIQUE (tenant_id, metric_type, period_start)
        """
    )


def downgrade() -> None:
    op.execute("ALTER TABLE usage_record DROP CONSTRAINT IF EXISTS uq_usage_tenant_metric_period")
