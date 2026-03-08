"""Enable Row-Level Security on all tenant-scoped tables.

Revision ID: 005
Revises: 004
Create Date: 2024-01-01 00:00:04
"""

from alembic import op

revision = "005"
down_revision = "004"
branch_labels = None
depends_on = None

# Tables that ARE tenant-scoped and require RLS.
# Excludes: tenant, platform_audit_log (platform-admin only),
#           packing_list_item, tracking_event, claim_evidence,
#           claim_resolution, misc_charge (inherit isolation via parent FK JOIN).
_RLS_TABLES = [
    "customer",
    "container",
    "manifest",
    "packing_list",
    "shipment_tracking",
    "billing",
    "cbm_dispute",
    "damage_claim",
    "missing_item",
    "seized_item",
    "release_note",
    "pickup_record",
    "refund_request",
    "storage_fee_log",
    "carryover_ledger",
    "charge_type",
    "tenant_user",
    "tenant_config",
    "usage_record",
    "audit_log",
    "payment_record",
]


def upgrade() -> None:
    # ---------------------------------------------------------------------------
    # 1. Application database role used by all Lambda functions.
    #    Password is intentionally a placeholder — rotate via Secrets Manager.
    # ---------------------------------------------------------------------------
    op.execute("""
        DO $$
        BEGIN
            IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'logistics_app') THEN
                CREATE ROLE logistics_app LOGIN PASSWORD 'CHANGE_ME_IN_SECRETS_MANAGER';
            END IF;
        END $$
    """)

    # Grant table-level and sequence-level privileges.
    # Row visibility is controlled by RLS policies, not by GRANT.
    op.execute("GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO logistics_app")
    op.execute("GRANT USAGE ON ALL SEQUENCES IN SCHEMA public TO logistics_app")

    # ---------------------------------------------------------------------------
    # 2. Enable RLS + create USING and WITH CHECK policies on all tenant-scoped
    #    tables in a single PL/pgSQL block.
    #
    #    FORCE ROW LEVEL SECURITY ensures policies apply even to the table owner
    #    (e.g. when running migrations or admin scripts as the DB owner).
    # ---------------------------------------------------------------------------
    op.execute("""
        DO $$
        DECLARE
            tbl TEXT;
        BEGIN
            FOR tbl IN
                SELECT unnest(ARRAY[
                    'customer', 'container', 'manifest', 'packing_list',
                    'shipment_tracking', 'billing', 'cbm_dispute', 'damage_claim',
                    'missing_item', 'seized_item', 'release_note', 'pickup_record',
                    'refund_request', 'storage_fee_log', 'carryover_ledger',
                    'charge_type', 'tenant_user', 'tenant_config', 'usage_record',
                    'audit_log', 'payment_record'
                ])
            LOOP
                -- Enable RLS on the table
                EXECUTE format('ALTER TABLE %I ENABLE ROW LEVEL SECURITY', tbl);

                -- Force RLS even for the table owner / superuser sessions
                EXECUTE format('ALTER TABLE %I FORCE ROW LEVEL SECURITY', tbl);

                -- SELECT / UPDATE / DELETE policy — checks tenant_id on existing rows
                EXECUTE format(
                    $sql$CREATE POLICY tenant_isolation ON %I
                         USING (tenant_id = current_setting('app.current_tenant_id')::uuid)$sql$,
                    tbl
                );

                -- INSERT policy — checks tenant_id on new rows
                EXECUTE format(
                    $sql$CREATE POLICY tenant_insert ON %I FOR INSERT
                         WITH CHECK (tenant_id = current_setting('app.current_tenant_id')::uuid)$sql$,
                    tbl
                );
            END LOOP;
        END $$
    """)


def downgrade() -> None:
    # ---------------------------------------------------------------------------
    # Drop policies, disable RLS, and revoke grants — in reverse order.
    # ---------------------------------------------------------------------------
    op.execute("""
        DO $$
        DECLARE
            tbl TEXT;
        BEGIN
            FOR tbl IN
                SELECT unnest(ARRAY[
                    'customer', 'container', 'manifest', 'packing_list',
                    'shipment_tracking', 'billing', 'cbm_dispute', 'damage_claim',
                    'missing_item', 'seized_item', 'release_note', 'pickup_record',
                    'refund_request', 'storage_fee_log', 'carryover_ledger',
                    'charge_type', 'tenant_user', 'tenant_config', 'usage_record',
                    'audit_log', 'payment_record'
                ])
            LOOP
                EXECUTE format('DROP POLICY IF EXISTS tenant_isolation ON %I', tbl);
                EXECUTE format('DROP POLICY IF EXISTS tenant_insert ON %I', tbl);
                EXECUTE format('ALTER TABLE %I NO FORCE ROW LEVEL SECURITY', tbl);
                EXECUTE format('ALTER TABLE %I DISABLE ROW LEVEL SECURITY', tbl);
            END LOOP;
        END $$
    """)

    op.execute("REVOKE SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public FROM logistics_app")
    op.execute("REVOKE USAGE ON ALL SEQUENCES IN SCHEMA public FROM logistics_app")
    op.execute("DROP ROLE IF EXISTS logistics_app")
