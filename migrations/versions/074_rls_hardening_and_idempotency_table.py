"""074 — RLS hardening (container_event, platform tables, idempotency_key) & audit immutability.

Closes Phase 1 DB isolation gaps (C-1, H-3, L-1):
  1. Creates ``idempotency_key`` as a schema-managed table with canonical
     tenant-scoped RLS so ``logistics_app`` (DML-only) never attempts runtime DDL.
  2. Enables and forces canonical ``tenant_isolation`` RLS on ``container_event``
     (previously omitted despite holding ``tenant_id``).
  3. Enables and forces ``PLATFORM``-only RLS on ``platform_settings``,
     ``platform_audit_log``, ``impersonation_session``, and
     ``tenant_onboarding_request``, and tenant-or-PLATFORM RLS on ``tenant``.
  4. Revokes ``UPDATE`` on ``audit_log`` and ``platform_audit_log`` from
     ``logistics_app`` to protect audit-trail immutability.
"""

from alembic import op

revision = "074"
down_revision = "073"


def upgrade() -> None:
    # 1. Schema-managed idempotency_key table with canonical RLS.
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS idempotency_key (
            tenant_id     VARCHAR(100) NOT NULL,
            key           VARCHAR(100) NOT NULL,
            response_body JSONB        NOT NULL,
            created_at    TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
            PRIMARY KEY (tenant_id, key)
        );

        ALTER TABLE idempotency_key ENABLE ROW LEVEL SECURITY;
        ALTER TABLE idempotency_key FORCE ROW LEVEL SECURITY;
        DROP POLICY IF EXISTS tenant_isolation ON idempotency_key;
        CREATE POLICY tenant_isolation ON idempotency_key FOR ALL
            USING (
                current_setting('app.current_tenant_id', TRUE) = 'PLATFORM'
                OR tenant_id::text = current_setting('app.current_tenant_id', TRUE)
            )
            WITH CHECK (
                current_setting('app.current_tenant_id', TRUE) = 'PLATFORM'
                OR tenant_id::text = current_setting('app.current_tenant_id', TRUE)
            );
        """
    )

    # 2. Enable and force canonical RLS on container_event.
    op.execute(
        """
        ALTER TABLE container_event ENABLE ROW LEVEL SECURITY;
        ALTER TABLE container_event FORCE ROW LEVEL SECURITY;
        DROP POLICY IF EXISTS tenant_isolation ON container_event;
        CREATE POLICY tenant_isolation ON container_event FOR ALL
            USING (
                current_setting('app.current_tenant_id', TRUE) = 'PLATFORM'
                OR tenant_id::text = current_setting('app.current_tenant_id', TRUE)
            )
            WITH CHECK (
                current_setting('app.current_tenant_id', TRUE) = 'PLATFORM'
                OR tenant_id::text = current_setting('app.current_tenant_id', TRUE)
            );
        """
    )

    # 3. Platform-only RLS on platform tables, and tenant-or-PLATFORM RLS on tenant.
    op.execute(
        """
        DO $outer$
        DECLARE
            tbl TEXT;
        BEGIN
            FOREACH tbl IN ARRAY ARRAY[
                'platform_settings',
                'platform_audit_log',
                'impersonation_session',
                'tenant_onboarding_request'
            ]
            LOOP
                EXECUTE format('ALTER TABLE %I ENABLE ROW LEVEL SECURITY', tbl);
                EXECUTE format('ALTER TABLE %I FORCE ROW LEVEL SECURITY', tbl);
                EXECUTE format('DROP POLICY IF EXISTS platform_only ON %I', tbl);
                EXECUTE format(
                    $sql$CREATE POLICY platform_only ON %I FOR ALL
                         USING (current_setting('app.current_tenant_id', TRUE) = 'PLATFORM')
                         WITH CHECK (current_setting('app.current_tenant_id', TRUE) = 'PLATFORM')$sql$,
                    tbl
                );
            END LOOP;
        END $outer$;

        ALTER TABLE tenant ENABLE ROW LEVEL SECURITY;
        ALTER TABLE tenant FORCE ROW LEVEL SECURITY;
        DROP POLICY IF EXISTS tenant_or_platform ON tenant;
        CREATE POLICY tenant_or_platform ON tenant FOR ALL
            USING (
                current_setting('app.current_tenant_id', TRUE) = 'PLATFORM'
                OR id::text = current_setting('app.current_tenant_id', TRUE)
            )
            WITH CHECK (
                current_setting('app.current_tenant_id', TRUE) = 'PLATFORM'
                OR id::text = current_setting('app.current_tenant_id', TRUE)
            );
        """
    )

    # 4. Grant DML on idempotency_key and revoke UPDATE on audit logs for logistics_app.
    op.execute(
        """
        DO $outer$
        BEGIN
            IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'logistics_app') THEN
                RETURN;
            END IF;

            GRANT SELECT, INSERT, UPDATE, DELETE ON idempotency_key TO logistics_app;
            REVOKE UPDATE ON audit_log, platform_audit_log FROM logistics_app;
        END $outer$;
        """
    )


def downgrade() -> None:
    op.execute(
        """
        DO $outer$
        BEGIN
            IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'logistics_app') THEN
                GRANT UPDATE ON audit_log, platform_audit_log TO logistics_app;
            END IF;
        END $outer$;

        DROP POLICY IF EXISTS tenant_or_platform ON tenant;
        ALTER TABLE tenant NO FORCE ROW LEVEL SECURITY;
        ALTER TABLE tenant DISABLE ROW LEVEL SECURITY;

        DO $outer$
        DECLARE
            tbl TEXT;
        BEGIN
            FOREACH tbl IN ARRAY ARRAY[
                'platform_settings',
                'platform_audit_log',
                'impersonation_session',
                'tenant_onboarding_request'
            ]
            LOOP
                EXECUTE format('DROP POLICY IF EXISTS platform_only ON %I', tbl);
                EXECUTE format('ALTER TABLE %I NO FORCE ROW LEVEL SECURITY', tbl);
                EXECUTE format('ALTER TABLE %I DISABLE ROW LEVEL SECURITY', tbl);
            END LOOP;
        END $outer$;

        DROP POLICY IF EXISTS tenant_isolation ON container_event;
        ALTER TABLE container_event NO FORCE ROW LEVEL SECURITY;
        ALTER TABLE container_event DISABLE ROW LEVEL SECURITY;

        DROP POLICY IF EXISTS tenant_isolation ON idempotency_key;
        ALTER TABLE idempotency_key NO FORCE ROW LEVEL SECURITY;
        ALTER TABLE idempotency_key DISABLE ROW LEVEL SECURITY;
        """
    )
