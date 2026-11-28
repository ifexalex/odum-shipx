"""076 — Platform admin directory, two-person approvals, and richer platform audit rows (platform audit Phase 1).

1. ``platform_user``: the directory of platform admins. Every platform request resolves its caller to an active row
   here and takes its role from it (owner, admin, support, finance; decision D2). An invited admin's ``subject`` is
   bound on their first signed-in request.
2. ``platform_approval``: two-person requests for the irreversible or platform-wide actions in decision D4. The
   requester can never decide their own request (a CHECK, not just application code). Secret values in a request
   (a gateway key) are held encrypted in ``secret_payload``; ``payload`` holds them masked.
3. ``platform_audit_log`` gains ``before_state``, ``after_state`` and ``request_id``.

Both new tables are platform-only under RLS, like ``platform_audit_log``. The app role may not delete from either:
admins are disabled, and approvals end in a terminal status, so the record of who could act and who agreed stays.

Revision ID: 076
Revises: 075
"""

from alembic import op

revision = "076"
down_revision = "075"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE platform_user (
            id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            subject         TEXT UNIQUE,
            email           TEXT NOT NULL,
            name            TEXT NOT NULL,
            role            TEXT NOT NULL CHECK (role IN ('owner', 'admin', 'support', 'finance')),
            status          TEXT NOT NULL DEFAULT 'invited' CHECK (status IN ('invited', 'active', 'disabled')),
            invited_by      UUID REFERENCES platform_user(id),
            last_seen_at    TIMESTAMPTZ,
            disabled_at     TIMESTAMPTZ,
            created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            CONSTRAINT platform_user_active_has_subject CHECK (status <> 'active' OR subject IS NOT NULL)
        );
        CREATE UNIQUE INDEX uq_platform_user_email ON platform_user (lower(email));

        CREATE TABLE platform_approval (
            id               UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            action           TEXT NOT NULL CHECK (action IN (
                                 'offboard_tenant', 'gateway_secret_change', 'maintenance_on',
                                 'plan_price_change', 'data_cleanup_rerun', 'admin_transfer')),
            target_tenant_id UUID REFERENCES tenant(id) ON DELETE SET NULL,
            target_label     TEXT NOT NULL,
            payload          JSONB NOT NULL DEFAULT '{}'::jsonb,
            secret_payload   TEXT,
            payload_hash     TEXT NOT NULL,
            reason           TEXT,
            status           TEXT NOT NULL DEFAULT 'pending' CHECK (status IN (
                                 'pending', 'scheduled', 'approved', 'executed', 'failed', 'rejected', 'cancelled',
                                 'expired')),
            requested_by     UUID NOT NULL REFERENCES platform_user(id),
            requested_at     TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            decided_by       UUID REFERENCES platform_user(id),
            decided_at       TIMESTAMPTZ,
            decision_note    TEXT,
            expires_at       TIMESTAMPTZ NOT NULL,
            execute_after    TIMESTAMPTZ,
            executed_at      TIMESTAMPTZ,
            error            TEXT,
            CONSTRAINT platform_approval_not_self_decided CHECK (decided_by IS NULL OR decided_by <> requested_by),
            CONSTRAINT platform_approval_scheduled_has_time CHECK (status <> 'scheduled' OR execute_after IS NOT NULL)
        );
        -- One open request per action and target: a second click joins the first instead of queueing a duplicate.
        CREATE UNIQUE INDEX uq_platform_approval_open
            ON platform_approval (action, target_label)
            WHERE status IN ('pending', 'scheduled');
        CREATE INDEX idx_platform_approval_status ON platform_approval (status, requested_at DESC);
        CREATE INDEX idx_platform_approval_due ON platform_approval (execute_after) WHERE status = 'scheduled';

        ALTER TABLE platform_audit_log
            ADD COLUMN before_state JSONB,
            ADD COLUMN after_state  JSONB,
            ADD COLUMN request_id   TEXT;

        DO $outer$
        DECLARE
            tbl TEXT;
        BEGIN
            FOREACH tbl IN ARRAY ARRAY['platform_user', 'platform_approval']
            LOOP
                EXECUTE format('ALTER TABLE %I ENABLE ROW LEVEL SECURITY', tbl);
                EXECUTE format('ALTER TABLE %I FORCE ROW LEVEL SECURITY', tbl);
                EXECUTE format(
                    $sql$CREATE POLICY platform_only ON %I FOR ALL
                         USING (current_setting('app.current_tenant_id', TRUE) = 'PLATFORM')
                         WITH CHECK (current_setting('app.current_tenant_id', TRUE) = 'PLATFORM')$sql$,
                    tbl
                );
            END LOOP;

            IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'logistics_app') THEN
                GRANT SELECT, INSERT, UPDATE ON platform_user, platform_approval TO logistics_app;
                REVOKE DELETE ON platform_user, platform_approval FROM logistics_app;
            END IF;
        END $outer$;
        """
    )


def downgrade() -> None:
    op.execute(
        """
        ALTER TABLE platform_audit_log
            DROP COLUMN IF EXISTS request_id,
            DROP COLUMN IF EXISTS after_state,
            DROP COLUMN IF EXISTS before_state;
        DROP TABLE IF EXISTS platform_approval;
        DROP TABLE IF EXISTS platform_user;
        """
    )
