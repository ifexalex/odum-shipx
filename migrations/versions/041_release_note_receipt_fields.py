"""041 — warehouse table, release-note/receipt fields, and credit-release tracking.

Audit against real paper documents (Goods Release Note x2, blank release note,
Cash Receipt) found missing data the platform never captured and several
pre-existing bugs (fixed in application code alongside this migration, see
services/payment_release/service.py and services/excel/repository.py):

1. **warehouse** — new per-tenant table. The letterhead lists ~9 branches
   (Onitsha HQ, Lagos, Oshodi, Tejuosho Yaba, Trade Fair, Mandilas, Aba…) and
   every release note records one. ShipX previously only had a single
   `tenant_config.warehouse_address` JSON blob per tenant — this migration
   backfills exactly one default warehouse per tenant from that blob so no
   tenant is left without one.
2. **release_note** — warehouse_id, payment_record_id ("Reciept No" on the
   form; NULL means "ON CREDIT"), is_on_credit, credit_granted_by(_name),
   count-based release fields (packages_released/package_unit/packages_balance,
   same package_unit vocabulary as packing_list_item from migration 040),
   physical_document_number (pre-printed booklet serial),
   packing_list_invoice_numbers. carton_tags is made nullable — count-based
   releases (the real source data from manifest import, 7.41) don't have
   per-carton tags.
3. **pickup_record** — warehouse_id + the three additional handover
   signatories (customer_service_officer, accounting_officer,
   warehouse_attendant); collected_by_name already exists and is already
   nullable (migration 008) — it was simply never written by the application,
   fixed alongside this migration.
4. **payment_record** — receipt_number (generated, e.g. ACM-RCT-20260822-0001),
   payer_name/address, bank_name, cheque_number, warehouse_id,
   physical_receipt_number (pre-printed booklet serial, e.g. "04742").
   'cheque' added to the payment_method allowlist.
5. **carryover_ledger** — due_date (the form's "Debt Payment Date"),
   granted_by (who authorised the credit release), release_note_id (link
   back to the release note that created the carryover).

All new columns nullable or defaulted — existing rows, flows, and the
existing 527-test unit suite are unaffected. carton_tags has 58 non-test call
sites across claims/manifest/excel/payment_release; this migration is purely
additive there (DROP NOT NULL only) — nothing existing breaks.

Revision ID: 041
Revises: 040
Create Date: 2026-08-23 00:00:00
"""

from alembic import op

revision = "041"
down_revision = "040"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # -------------------------------------------------------------------
    # 1. warehouse — new tenant-scoped, RLS-enabled table
    # -------------------------------------------------------------------
    op.execute(
        """
        CREATE TABLE warehouse (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id UUID NOT NULL REFERENCES tenant(id) ON DELETE RESTRICT,
            name VARCHAR(120) NOT NULL,
            address TEXT,
            city VARCHAR(100),
            state VARCHAR(100),
            phone VARCHAR(50),
            is_default BOOLEAN NOT NULL DEFAULT FALSE,
            is_active BOOLEAN NOT NULL DEFAULT TRUE,
            created_by UUID REFERENCES tenant_user(id),
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            UNIQUE (tenant_id, name)
        )
        """
    )
    op.execute("CREATE INDEX idx_warehouse_tenant ON warehouse(tenant_id)")
    op.execute("CREATE UNIQUE INDEX idx_warehouse_one_default ON warehouse(tenant_id) WHERE is_default")
    op.execute("ALTER TABLE warehouse ENABLE ROW LEVEL SECURITY")
    op.execute(
        """
        CREATE POLICY warehouse_tenant_isolation ON warehouse
        USING (tenant_id::text = current_setting('app.tenant_id', TRUE))
        """
    )

    # Backfill: exactly one default warehouse per tenant, derived from the
    # existing tenant_config.warehouse_address JSON blob where present, else
    # a bare "Main Warehouse" placeholder — every tenant must end up with at
    # least one warehouse or release-note generation breaks.
    op.execute(
        """
        INSERT INTO warehouse (tenant_id, name, address, city, state, is_default)
        SELECT t.id,
               'Main Warehouse',
               tc.config_value ->> 'address',
               tc.config_value ->> 'city',
               tc.config_value ->> 'state',
               TRUE
        FROM tenant t
        LEFT JOIN tenant_config tc
               ON tc.tenant_id = t.id AND tc.config_key = 'warehouse_address'
        ON CONFLICT (tenant_id, name) DO NOTHING
        """
    )

    # -------------------------------------------------------------------
    # 2. release_note
    # -------------------------------------------------------------------
    op.execute(
        """
        ALTER TABLE release_note
          ADD COLUMN IF NOT EXISTS warehouse_id UUID REFERENCES warehouse(id),
          ADD COLUMN IF NOT EXISTS payment_record_id UUID REFERENCES payment_record(id),
          ADD COLUMN IF NOT EXISTS is_on_credit BOOLEAN NOT NULL DEFAULT FALSE,
          ADD COLUMN IF NOT EXISTS credit_granted_by UUID REFERENCES tenant_user(id),
          ADD COLUMN IF NOT EXISTS credit_granted_by_name VARCHAR(255),
          ADD COLUMN IF NOT EXISTS packages_released INTEGER,
          ADD COLUMN IF NOT EXISTS package_unit VARCHAR(20),
          ADD COLUMN IF NOT EXISTS packages_balance INTEGER,
          ADD COLUMN IF NOT EXISTS physical_document_number VARCHAR(50),
          ADD COLUMN IF NOT EXISTS packing_list_invoice_numbers TEXT[] NOT NULL DEFAULT '{}'
        """
    )
    op.execute("ALTER TABLE release_note ALTER COLUMN carton_tags DROP NOT NULL")

    # -------------------------------------------------------------------
    # 3. pickup_record — additional handover signatories
    # -------------------------------------------------------------------
    op.execute(
        """
        ALTER TABLE pickup_record
          ADD COLUMN IF NOT EXISTS warehouse_id UUID REFERENCES warehouse(id),
          ADD COLUMN IF NOT EXISTS customer_service_officer_id UUID REFERENCES tenant_user(id),
          ADD COLUMN IF NOT EXISTS accounting_officer_id UUID REFERENCES tenant_user(id),
          ADD COLUMN IF NOT EXISTS warehouse_attendant_id UUID REFERENCES tenant_user(id)
        """
    )

    # -------------------------------------------------------------------
    # 4. payment_record — cash receipt fields
    # -------------------------------------------------------------------
    op.execute(
        """
        ALTER TABLE payment_record
          ADD COLUMN IF NOT EXISTS receipt_number VARCHAR(50),
          ADD COLUMN IF NOT EXISTS payer_name VARCHAR(255),
          ADD COLUMN IF NOT EXISTS payer_address TEXT,
          ADD COLUMN IF NOT EXISTS bank_name VARCHAR(120),
          ADD COLUMN IF NOT EXISTS cheque_number VARCHAR(50),
          ADD COLUMN IF NOT EXISTS warehouse_id UUID REFERENCES warehouse(id),
          ADD COLUMN IF NOT EXISTS physical_receipt_number VARCHAR(50)
        """
    )
    op.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS idx_payment_record_receipt_number"
        " ON payment_record(tenant_id, receipt_number) WHERE receipt_number IS NOT NULL"
    )
    op.execute("ALTER TABLE payment_record DROP CONSTRAINT IF EXISTS payment_record_payment_method_check")
    op.execute(
        """
        ALTER TABLE payment_record ADD CONSTRAINT payment_record_payment_method_check
        CHECK (payment_method IN (
            'bank_transfer',
            'cash',
            'pos',
            'online',
            'paystack',
            'flutterwave',
            'cheque'
        ))
        """
    )

    # -------------------------------------------------------------------
    # 5. carryover_ledger — debt authorisation tracking
    # -------------------------------------------------------------------
    op.execute(
        """
        ALTER TABLE carryover_ledger
          ADD COLUMN IF NOT EXISTS due_date DATE,
          ADD COLUMN IF NOT EXISTS granted_by UUID REFERENCES tenant_user(id),
          ADD COLUMN IF NOT EXISTS release_note_id UUID REFERENCES release_note(id)
        """
    )


def downgrade() -> None:
    op.execute(
        """
        ALTER TABLE carryover_ledger
          DROP COLUMN IF EXISTS due_date,
          DROP COLUMN IF EXISTS granted_by,
          DROP COLUMN IF EXISTS release_note_id
        """
    )
    op.execute("DROP INDEX IF EXISTS idx_payment_record_receipt_number")
    op.execute("ALTER TABLE payment_record DROP CONSTRAINT IF EXISTS payment_record_payment_method_check")
    op.execute(
        """
        ALTER TABLE payment_record ADD CONSTRAINT payment_record_payment_method_check
        CHECK (payment_method IN (
            'bank_transfer',
            'cash',
            'pos',
            'online',
            'paystack',
            'flutterwave'
        ))
        """
    )
    op.execute(
        """
        ALTER TABLE payment_record
          DROP COLUMN IF EXISTS receipt_number,
          DROP COLUMN IF EXISTS payer_name,
          DROP COLUMN IF EXISTS payer_address,
          DROP COLUMN IF EXISTS bank_name,
          DROP COLUMN IF EXISTS cheque_number,
          DROP COLUMN IF EXISTS warehouse_id,
          DROP COLUMN IF EXISTS physical_receipt_number
        """
    )
    op.execute(
        """
        ALTER TABLE pickup_record
          DROP COLUMN IF EXISTS warehouse_id,
          DROP COLUMN IF EXISTS customer_service_officer_id,
          DROP COLUMN IF EXISTS accounting_officer_id,
          DROP COLUMN IF EXISTS warehouse_attendant_id
        """
    )
    op.execute("ALTER TABLE release_note ALTER COLUMN carton_tags SET NOT NULL")
    op.execute(
        """
        ALTER TABLE release_note
          DROP COLUMN IF EXISTS warehouse_id,
          DROP COLUMN IF EXISTS payment_record_id,
          DROP COLUMN IF EXISTS is_on_credit,
          DROP COLUMN IF EXISTS credit_granted_by,
          DROP COLUMN IF EXISTS credit_granted_by_name,
          DROP COLUMN IF EXISTS packages_released,
          DROP COLUMN IF EXISTS package_unit,
          DROP COLUMN IF EXISTS packages_balance,
          DROP COLUMN IF EXISTS physical_document_number,
          DROP COLUMN IF EXISTS packing_list_invoice_numbers
        """
    )
    op.execute("DROP TABLE IF EXISTS warehouse CASCADE")
