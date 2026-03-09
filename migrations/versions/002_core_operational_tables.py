"""Create core operational tables.

Revision ID: 002
Revises: 001
Create Date: 2024-01-01 00:00:01
"""

from alembic import op

revision = "002"
down_revision = "001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ---------------------------------------------------------------------------
    # 5. customer — end customers belonging to a tenant
    # ---------------------------------------------------------------------------
    op.execute(
        """
        CREATE TABLE customer (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id UUID NOT NULL REFERENCES tenant(id) ON DELETE RESTRICT,
            user_id UUID REFERENCES tenant_user(id),
            name VARCHAR(255) NOT NULL,
            contract_details TEXT,
            phone VARCHAR(50),
            email VARCHAR(255),
            whatsapp VARCHAR(50),
            address TEXT,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
    """
    )
    op.execute("CREATE INDEX idx_customer_tenant ON customer(tenant_id)")
    op.execute("CREATE INDEX idx_customer_tenant_name ON customer(tenant_id, name)")
    op.execute("CREATE INDEX idx_customer_tenant_phone ON customer(tenant_id, phone)")

    # ---------------------------------------------------------------------------
    # 6. container — shipping containers from origin to destination
    # ---------------------------------------------------------------------------
    op.execute(
        """
        CREATE TABLE container (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id UUID NOT NULL REFERENCES tenant(id) ON DELETE RESTRICT,
            container_number VARCHAR(50) NOT NULL,
            parcel_number VARCHAR(50),
            origin VARCHAR(100) NOT NULL DEFAULT 'China',
            destination VARCHAR(100) NOT NULL DEFAULT 'Nigeria',
            ship_date DATE,
            estimated_arrival_date DATE,
            actual_arrival_date DATE,
            status VARCHAR(30) NOT NULL DEFAULT 'loading' CHECK (status IN (
                'loading',
                'sealed',
                'in_transit',
                'arrived',
                'customs_clearance',
                'cleared',
                'at_warehouse',
                'fully_released'
            )),
            notes TEXT,
            created_by UUID REFERENCES tenant_user(id),
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            UNIQUE (tenant_id, container_number)
        )
    """
    )
    op.execute("CREATE INDEX idx_container_tenant ON container(tenant_id)")
    op.execute("CREATE INDEX idx_container_tenant_status ON container(tenant_id, status)")

    # ---------------------------------------------------------------------------
    # 7. manifest — aggregate summary of a container's contents
    # ---------------------------------------------------------------------------
    op.execute(
        """
        CREATE TABLE manifest (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id UUID NOT NULL REFERENCES tenant(id) ON DELETE RESTRICT,
            container_id UUID NOT NULL REFERENCES container(id) ON DELETE RESTRICT,
            total_customers INTEGER NOT NULL DEFAULT 0,
            total_cartons INTEGER NOT NULL DEFAULT 0,
            total_weight_kg DECIMAL(12, 3) NOT NULL DEFAULT 0,
            total_cbm DECIMAL(12, 6) NOT NULL DEFAULT 0,
            verification_status VARCHAR(20) NOT NULL DEFAULT 'pending' CHECK (verification_status IN (
                'pending',
                'verified',
                'discrepancies_found'
            )),
            verified_by UUID REFERENCES tenant_user(id),
            verified_at TIMESTAMPTZ,
            notes TEXT,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            UNIQUE (tenant_id, container_id)
        )
    """
    )
    op.execute("CREATE INDEX idx_manifest_tenant ON manifest(tenant_id)")
    op.execute("CREATE INDEX idx_manifest_tenant_container ON manifest(tenant_id, container_id)")

    # ---------------------------------------------------------------------------
    # 8. packing_list — per-customer list of items in a container
    # ---------------------------------------------------------------------------
    op.execute(
        """
        CREATE TABLE packing_list (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id UUID NOT NULL REFERENCES tenant(id) ON DELETE RESTRICT,
            container_id UUID NOT NULL REFERENCES container(id) ON DELETE RESTRICT,
            manifest_id UUID REFERENCES manifest(id),
            customer_id UUID NOT NULL REFERENCES customer(id) ON DELETE RESTRICT,
            status VARCHAR(20) NOT NULL DEFAULT 'draft' CHECK (status IN (
                'draft',
                'pending_approval',
                'approved',
                'rejected'
            )),
            approval_comments JSONB,
            approved_by UUID REFERENCES tenant_user(id),
            approved_at TIMESTAMPTZ,
            rejected_by UUID REFERENCES tenant_user(id),
            rejected_at TIMESTAMPTZ,
            created_by UUID REFERENCES tenant_user(id),
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
    """
    )
    op.execute("CREATE INDEX idx_packing_list_tenant_customer ON packing_list(tenant_id, customer_id)")
    op.execute("CREATE INDEX idx_packing_list_tenant_container ON packing_list(tenant_id, container_id)")
    op.execute("CREATE INDEX idx_packing_list_tenant_status ON packing_list(tenant_id, status)")

    # ---------------------------------------------------------------------------
    # 9. packing_list_item — individual cartons within a packing list
    # ---------------------------------------------------------------------------
    op.execute(
        """
        CREATE TABLE packing_list_item (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            packing_list_id UUID NOT NULL REFERENCES packing_list(id) ON DELETE CASCADE,
            description TEXT NOT NULL,
            weight_dispatch_kg DECIMAL(10, 3),
            weight_actual_kg DECIMAL(10, 3),
            carton_tag VARCHAR(100) NOT NULL,
            tracking_code VARCHAR(100) NOT NULL,
            cbm DECIMAL(10, 6) NOT NULL DEFAULT 0,
            length_cm DECIMAL(8, 2),
            width_cm DECIMAL(8, 2),
            height_cm DECIMAL(8, 2),
            received_date DATE NOT NULL DEFAULT CURRENT_DATE,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
    """
    )
    op.execute("CREATE INDEX idx_packing_list_item_list ON packing_list_item(packing_list_id)")
    op.execute("CREATE INDEX idx_packing_list_item_tracking ON packing_list_item(tracking_code)")
    op.execute("CREATE INDEX idx_packing_list_item_carton ON packing_list_item(carton_tag)")

    # ---------------------------------------------------------------------------
    # 10. shipment_tracking — public-facing tracking record per carton
    # ---------------------------------------------------------------------------
    op.execute(
        """
        CREATE TABLE shipment_tracking (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id UUID NOT NULL REFERENCES tenant(id) ON DELETE RESTRICT,
            packing_list_item_id UUID REFERENCES packing_list_item(id) ON DELETE SET NULL,
            tracking_code VARCHAR(100) NOT NULL,
            status VARCHAR(30) NOT NULL DEFAULT 'received' CHECK (status IN (
                'received',
                'in_transit',
                'arrived_port',
                'customs_clearance',
                'at_warehouse',
                'ready_for_pickup',
                'released'
            )),
            current_location VARCHAR(255),
            estimated_delivery_date DATE,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            UNIQUE (tenant_id, tracking_code)
        )
    """
    )
    op.execute("CREATE INDEX idx_shipment_tracking_tenant ON shipment_tracking(tenant_id)")
    op.execute("CREATE INDEX idx_shipment_tracking_code ON shipment_tracking(tracking_code)")

    # ---------------------------------------------------------------------------
    # 11. tracking_event — append-only audit log of shipment status changes
    # ---------------------------------------------------------------------------
    op.execute(
        """
        CREATE TABLE tracking_event (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            shipment_tracking_id UUID NOT NULL REFERENCES shipment_tracking(id) ON DELETE CASCADE,
            from_status VARCHAR(30),
            to_status VARCHAR(30) NOT NULL,
            description TEXT,
            location VARCHAR(255),
            created_by UUID REFERENCES tenant_user(id),
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
    """
    )
    op.execute("CREATE INDEX idx_tracking_event_shipment ON tracking_event(shipment_tracking_id)")

    # ---------------------------------------------------------------------------
    # 12. billing — CBM-based invoice per customer per container
    # ---------------------------------------------------------------------------
    op.execute(
        """
        CREATE TABLE billing (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id UUID NOT NULL REFERENCES tenant(id) ON DELETE RESTRICT,
            customer_id UUID NOT NULL REFERENCES customer(id) ON DELETE RESTRICT,
            container_id UUID NOT NULL REFERENCES container(id) ON DELETE RESTRICT,
            packing_list_id UUID REFERENCES packing_list(id),
            invoice_number VARCHAR(100) NOT NULL,
            total_cartons INTEGER NOT NULL DEFAULT 0,
            total_cbm DECIMAL(12, 6) NOT NULL DEFAULT 0,
            cbm_rate_usd DECIMAL(10, 4) NOT NULL,
            subtotal_usd DECIMAL(15, 2) NOT NULL DEFAULT 0,
            exchange_rate_ngn DECIMAL(15, 4) NOT NULL,
            subtotal_ngn DECIMAL(15, 2) NOT NULL DEFAULT 0,
            misc_charges_ngn DECIMAL(15, 2) NOT NULL DEFAULT 0,
            total_ngn DECIMAL(15, 2) NOT NULL DEFAULT 0,
            amount_paid_ngn DECIMAL(15, 2) NOT NULL DEFAULT 0,
            balance_ngn DECIMAL(15, 2) GENERATED ALWAYS AS (total_ngn - amount_paid_ngn) STORED,
            status VARCHAR(20) NOT NULL DEFAULT 'draft' CHECK (status IN (
                'draft',
                'sent',
                'partially_paid',
                'paid',
                'overdue',
                'cancelled'
            )),
            due_date DATE,
            notes TEXT,
            created_by UUID REFERENCES tenant_user(id),
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            UNIQUE (tenant_id, invoice_number)
        )
    """
    )
    op.execute("CREATE INDEX idx_billing_tenant ON billing(tenant_id)")
    op.execute("CREATE INDEX idx_billing_tenant_customer ON billing(tenant_id, customer_id)")
    op.execute("CREATE INDEX idx_billing_tenant_status ON billing(tenant_id, status)")

    # ---------------------------------------------------------------------------
    # 13. misc_charge — additional line items on a billing invoice
    # ---------------------------------------------------------------------------
    op.execute(
        """
        CREATE TABLE misc_charge (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            billing_id UUID NOT NULL REFERENCES billing(id) ON DELETE CASCADE,
            description VARCHAR(255) NOT NULL,
            amount_ngn DECIMAL(15, 2) NOT NULL,
            charge_type VARCHAR(50) NOT NULL CHECK (charge_type IN (
                'storage_fee',
                'handling',
                'customs',
                'delivery',
                'cbm_dispute_adjustment',
                'other'
            )),
            created_by UUID REFERENCES tenant_user(id),
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
    """
    )
    op.execute("CREATE INDEX idx_misc_charge_billing ON misc_charge(billing_id)")

    # ---------------------------------------------------------------------------
    # 14. payment_record — cash / transfer payments recorded against a billing
    # ---------------------------------------------------------------------------
    op.execute(
        """
        CREATE TABLE payment_record (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            billing_id UUID NOT NULL REFERENCES billing(id) ON DELETE RESTRICT,
            tenant_id UUID NOT NULL REFERENCES tenant(id) ON DELETE RESTRICT,
            amount_ngn DECIMAL(15, 2) NOT NULL,
            payment_method VARCHAR(30) NOT NULL CHECK (payment_method IN (
                'bank_transfer',
                'cash',
                'pos',
                'online'
            )),
            reference_number VARCHAR(100),
            payment_date DATE NOT NULL,
            recorded_by UUID REFERENCES tenant_user(id),
            notes TEXT,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
    """
    )
    op.execute("CREATE INDEX idx_payment_record_billing ON payment_record(billing_id)")
    op.execute("CREATE INDEX idx_payment_record_tenant ON payment_record(tenant_id)")


def downgrade() -> None:
    # Drop in strict reverse FK dependency order
    op.execute("DROP TABLE IF EXISTS payment_record")
    op.execute("DROP TABLE IF EXISTS misc_charge")
    op.execute("DROP TABLE IF EXISTS billing")
    op.execute("DROP TABLE IF EXISTS tracking_event")
    op.execute("DROP TABLE IF EXISTS shipment_tracking")
    op.execute("DROP TABLE IF EXISTS packing_list_item")
    op.execute("DROP TABLE IF EXISTS packing_list")
    op.execute("DROP TABLE IF EXISTS manifest")
    op.execute("DROP TABLE IF EXISTS container")
    op.execute("DROP TABLE IF EXISTS customer")
