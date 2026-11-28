"""078 — Daily tenant metrics and scheduled-job runs (platform audit Phase 1c, decision D7).

1. ``tenant_metrics_daily``: one row per tenant per UTC day, counts only (no names, emails or phone numbers). It feeds
   the platform Overview, tenant health and the tenant list's columns in Phase 2. Filled by the hourly usage job, which
   rewrites yesterday's and today's rows, and backfilled from history (``scripts/backfill_tenant_metrics.py``).
   Deleted with the tenant.
2. ``job_run``: one row per scheduled-job run (start, end, status, items, failures, error class), written by
   ``shared/job_runs.py`` around every scheduled handler. The Operations area reads it in Phase 3. Pruned after 180
   days by the usage job.

``tenant_metrics_daily`` is readable by the tenant itself or the platform; ``job_run`` is platform-only.

Revision ID: 078
Revises: 077
"""

from alembic import op

revision = "078"
down_revision = "077"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE tenant_metrics_daily (
            tenant_id            UUID        NOT NULL REFERENCES tenant(id) ON DELETE CASCADE,
            metric_date          DATE        NOT NULL,
            customers_total      INTEGER     NOT NULL DEFAULT 0,
            customers_new        INTEGER     NOT NULL DEFAULT 0,
            containers_created   INTEGER     NOT NULL DEFAULT 0,
            containers_processed INTEGER     NOT NULL DEFAULT 0,
            api_calls            BIGINT      NOT NULL DEFAULT 0,
            storage_bytes        BIGINT      NOT NULL DEFAULT 0,
            sms_sent             INTEGER     NOT NULL DEFAULT 0,
            sms_failed           INTEGER     NOT NULL DEFAULT 0,
            whatsapp_sent        INTEGER     NOT NULL DEFAULT 0,
            whatsapp_failed      INTEGER     NOT NULL DEFAULT 0,
            email_sent           INTEGER     NOT NULL DEFAULT 0,
            email_failed         INTEGER     NOT NULL DEFAULT 0,
            staff_seats          INTEGER     NOT NULL DEFAULT 0,
            last_activity_at     TIMESTAMPTZ,
            computed_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            PRIMARY KEY (tenant_id, metric_date)
        );
        CREATE INDEX idx_tenant_metrics_daily_date ON tenant_metrics_daily (metric_date);

        CREATE TABLE job_run (
            id              UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
            job             TEXT        NOT NULL,
            started_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            finished_at     TIMESTAMPTZ,
            status          TEXT        NOT NULL DEFAULT 'running'
                                        CHECK (status IN ('running', 'succeeded', 'failed')),
            trigger         TEXT        NOT NULL DEFAULT 'schedule' CHECK (trigger IN ('schedule', 'manual')),
            items_processed INTEGER     NOT NULL DEFAULT 0,
            failures        INTEGER     NOT NULL DEFAULT 0,
            result          JSONB,
            error_summary   TEXT,
            request_id      TEXT
        );
        CREATE INDEX idx_job_run_job_started ON job_run (job, started_at DESC);

        ALTER TABLE tenant_metrics_daily ENABLE ROW LEVEL SECURITY;
        ALTER TABLE tenant_metrics_daily FORCE ROW LEVEL SECURITY;
        CREATE POLICY tenant_or_platform ON tenant_metrics_daily FOR ALL
            USING (
                current_setting('app.current_tenant_id', TRUE) = 'PLATFORM'
                OR tenant_id::text = current_setting('app.current_tenant_id', TRUE)
            )
            WITH CHECK (
                current_setting('app.current_tenant_id', TRUE) = 'PLATFORM'
                OR tenant_id::text = current_setting('app.current_tenant_id', TRUE)
            );

        ALTER TABLE job_run ENABLE ROW LEVEL SECURITY;
        ALTER TABLE job_run FORCE ROW LEVEL SECURITY;
        CREATE POLICY platform_only ON job_run FOR ALL
            USING (current_setting('app.current_tenant_id', TRUE) = 'PLATFORM')
            WITH CHECK (current_setting('app.current_tenant_id', TRUE) = 'PLATFORM');

        DO $outer$
        BEGIN
            IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'logistics_app') THEN
                GRANT SELECT, INSERT, UPDATE, DELETE ON tenant_metrics_daily, job_run TO logistics_app;
            END IF;
        END $outer$;
        """
    )


def downgrade() -> None:
    op.execute(
        """
        DROP TABLE IF EXISTS job_run;
        DROP TABLE IF EXISTS tenant_metrics_daily;
        """
    )
