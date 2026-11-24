"""067 — the tenant data export made at offboarding (audit BE-10).

The PRD (FR-TN-004) promises a tenant a full export of its data when it leaves. Only the per-customer GDPR export
existed, and the cleanup job deletes everything 90 days after offboarding, so a tenant's records could be destroyed
without ever having been handed over.

``tenant_offboarding_export`` holds one row per export: offboarding queues it (``pending``), an hourly job writes the
archive to ``{tenant_id}/exports/offboarding/{id}.zip`` and marks it ``completed`` (or ``failed``, retried a few times),
and the cleanup job refuses to delete a tenant until one has completed. A tenant reactivated before its export ran has
the export ``cancelled``.

Only platform admins read it, through PLATFORM scope; it still has the canonical tenant RLS policy, like every table
with a ``tenant_id``, so a tenant-scoped connection sees only its own rows. It cascades with the tenant: the archive
itself is deleted with the tenant's storage prefix.

Revision ID: 067
Revises: 066
Create Date: 2026-11-17 18:00:00
"""

from alembic import op

revision = "067"
down_revision = "066"
branch_labels = None
depends_on = None

_PREDICATE = """
    current_setting('app.current_tenant_id', TRUE) = 'PLATFORM'
    OR tenant_id::text = current_setting('app.current_tenant_id', TRUE)
"""


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE tenant_offboarding_export (
            id             UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id      UUID NOT NULL REFERENCES tenant(id) ON DELETE CASCADE,
            status         VARCHAR(20) NOT NULL DEFAULT 'pending'
                CHECK (status IN ('pending', 'running', 'completed', 'failed', 'cancelled')),
            requested_by   VARCHAR(255),
            requested_at   TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            started_at     TIMESTAMPTZ,
            completed_at   TIMESTAMPTZ,
            attempts       INTEGER NOT NULL DEFAULT 0 CHECK (attempts >= 0),
            object_key     TEXT,
            size_bytes     BIGINT CHECK (size_bytes IS NULL OR size_bytes >= 0),
            sha256         CHAR(64),
            row_counts     JSONB,
            last_error     TEXT,
            updated_at     TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            CHECK (status <> 'completed' OR (object_key IS NOT NULL AND completed_at IS NOT NULL))
        )
        """
    )
    # The hourly job looks for work; the platform page and the cleanup read a tenant's latest export.
    op.execute(
        "CREATE INDEX idx_tenant_offboarding_export_open ON tenant_offboarding_export (requested_at) "
        "WHERE status IN ('pending', 'running', 'failed')"
    )
    op.execute("CREATE INDEX idx_tenant_offboarding_export_tenant ON tenant_offboarding_export (tenant_id, requested_at DESC)")
    # At most one export in flight per tenant, so offboarding twice (or a retry) cannot queue a second.
    op.execute(
        "CREATE UNIQUE INDEX idx_tenant_offboarding_export_one_open ON tenant_offboarding_export (tenant_id) "
        "WHERE status IN ('pending', 'running')"
    )

    op.execute("ALTER TABLE tenant_offboarding_export ENABLE ROW LEVEL SECURITY")
    op.execute(
        f"CREATE POLICY tenant_isolation ON tenant_offboarding_export FOR ALL USING ({_PREDICATE}) WITH CHECK ({_PREDICATE})"
    )
    op.execute("ALTER TABLE tenant_offboarding_export FORCE ROW LEVEL SECURITY")


def downgrade() -> None:
    op.execute("DROP TABLE tenant_offboarding_export")
