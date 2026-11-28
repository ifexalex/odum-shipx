"""075 — Make ``platform_audit_log`` append-only for the app role, keeping the 90-day cleanup working.

1. Revokes ``DELETE`` on ``platform_audit_log`` from ``logistics_app``. Migration 074 revoked ``UPDATE`` only, so the
   app could still delete the platform's record of admin actions (audit PA-07).
2. Adds ``anonymise_platform_audit_for_tenant(uuid)``, a ``SECURITY DEFINER`` function that blanks the tenant reference
   and details on that tenant's rows, and nothing else. The 90-day cleanup (``services/scheduled/data_cleanup.py``)
   anonymises a deleted tenant's rows with a plain ``UPDATE``; since 074 revoked ``UPDATE`` and the app started
   connecting as ``logistics_app``, that statement is refused, so offboarded tenants were never deleted. The function
   is the only write path left: it refuses to run outside the ``PLATFORM`` context, and ``PUBLIC`` cannot call it.

Revision ID: 075
Revises: 074
"""

from alembic import op

revision = "075"
down_revision = "074"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE OR REPLACE FUNCTION anonymise_platform_audit_for_tenant(p_tenant_id uuid)
        RETURNS integer
        LANGUAGE plpgsql
        SECURITY DEFINER
        SET search_path = public, pg_temp
        AS $fn$
        DECLARE
            anonymised integer;
        BEGIN
            IF current_setting('app.current_tenant_id', TRUE) IS DISTINCT FROM 'PLATFORM' THEN
                RAISE EXCEPTION 'anonymise_platform_audit_for_tenant runs in the PLATFORM context only';
            END IF;
            UPDATE platform_audit_log
            SET target_tenant_id = NULL,
                details          = NULL
            WHERE target_tenant_id = p_tenant_id;
            GET DIAGNOSTICS anonymised = ROW_COUNT;
            RETURN anonymised;
        END
        $fn$;

        REVOKE ALL ON FUNCTION anonymise_platform_audit_for_tenant(uuid) FROM PUBLIC;

        DO $outer$
        BEGIN
            IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'logistics_app') THEN
                GRANT EXECUTE ON FUNCTION anonymise_platform_audit_for_tenant(uuid) TO logistics_app;
                REVOKE DELETE ON platform_audit_log FROM logistics_app;
            END IF;
        END $outer$;
        """
    )


def downgrade() -> None:
    op.execute(
        """
        DO $outer$
        BEGIN
            IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'logistics_app') THEN
                GRANT DELETE ON platform_audit_log TO logistics_app;
            END IF;
        END $outer$;

        DROP FUNCTION IF EXISTS anonymise_platform_audit_for_tenant(uuid);
        """
    )
