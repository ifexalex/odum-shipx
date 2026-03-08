"""Create extended operational tables (claims, release, refunds, storage, audit support).

Revision ID: 003
Revises: 002
Create Date: 2024-01-01 00:00:02
"""

from alembic import op

revision = "003"
down_revision = "002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ---------------------------------------------------------------------------
    # 1. cbm_dispute — disputes against CBM measurements on a billing invoice (7 statuses)
    # ---------------------------------------------------------------------------
    op.execute("""
        CREATE TABLE cbm_dispute (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id UUID NOT NULL REFERENCES tenant(id) ON DELETE RESTRICT,
            billing_id UUID NOT NULL REFERENCES billing(id) ON DELETE RESTRICT,
            customer_id UUID NOT NULL REFERENCES customer(id) ON DELETE RESTRICT,
            packing_list_id UUID REFERENCES packing_list(id),
            disputed_cbm DECIMAL(12, 6) NOT NULL,
            agreed_cbm DECIMAL(12, 6),
            status VARCHAR(30) NOT NULL DEFAULT 'open' CHECK (status IN (
                'open',
                'under_review',
                'evidence_submitted',
                'agreed',
                'rejected',
                'resolved',
                'escalated'
            )),
            dispute_reason TEXT,
            resolution_notes TEXT,
            raised_by UUID REFERENCES tenant_user(id),
            resolved_by UUID REFERENCES tenant_user(id),
            resolved_at TIMESTAMPTZ,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
    """)
    op.execute("CREATE INDEX idx_cbm_dispute_tenant ON cbm_dispute(tenant_id)")
    op.execute("CREATE INDEX idx_cbm_dispute_billing ON cbm_dispute(billing_id)")
    op.execute("CREATE INDEX idx_cbm_dispute_tenant_status ON cbm_dispute(tenant_id, status)")

    # ---------------------------------------------------------------------------
    # 2. damage_claim — physical damage claims; cartons_affected stored as TEXT[] (6 statuses)
    # ---------------------------------------------------------------------------
    op.execute("""
        CREATE TABLE damage_claim (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id UUID NOT NULL REFERENCES tenant(id) ON DELETE RESTRICT,
            customer_id UUID NOT NULL REFERENCES customer(id) ON DELETE RESTRICT,
            container_id UUID NOT NULL REFERENCES container(id) ON DELETE RESTRICT,
            packing_list_id UUID REFERENCES packing_list(id),
            cartons_affected TEXT[] NOT NULL DEFAULT '{}',
            description TEXT NOT NULL,
            claimed_amount_ngn DECIMAL(15, 2),
            status VARCHAR(20) NOT NULL DEFAULT 'submitted' CHECK (status IN (
                'submitted',
                'under_review',
                'approved',
                'rejected',
                'resolved',
                'escalated'
            )),
            submitted_by UUID REFERENCES tenant_user(id),
            reviewed_by UUID REFERENCES tenant_user(id),
            reviewed_at TIMESTAMPTZ,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
    """)
    op.execute("CREATE INDEX idx_damage_claim_tenant ON damage_claim(tenant_id)")
    op.execute("CREATE INDEX idx_damage_claim_tenant_customer ON damage_claim(tenant_id, customer_id)")
    op.execute("CREATE INDEX idx_damage_claim_tenant_status ON damage_claim(tenant_id, status)")

    # ---------------------------------------------------------------------------
    # 3. claim_evidence — S3-backed photos / supporting documents for damage claims
    # ---------------------------------------------------------------------------
    op.execute("""
        CREATE TABLE claim_evidence (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            damage_claim_id UUID NOT NULL REFERENCES damage_claim(id) ON DELETE CASCADE,
            file_key VARCHAR(500) NOT NULL,
            file_name VARCHAR(255) NOT NULL,
            file_type VARCHAR(50) NOT NULL,
            file_size_bytes INTEGER,
            uploaded_by UUID REFERENCES tenant_user(id),
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
    """)
    op.execute("CREATE INDEX idx_claim_evidence_claim ON claim_evidence(damage_claim_id)")

    # ---------------------------------------------------------------------------
    # 4. claim_resolution — outcome record for a damage claim with approval level
    # ---------------------------------------------------------------------------
    op.execute("""
        CREATE TABLE claim_resolution (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            damage_claim_id UUID NOT NULL REFERENCES damage_claim(id) ON DELETE RESTRICT,
            tenant_id UUID NOT NULL REFERENCES tenant(id) ON DELETE RESTRICT,
            resolution_type VARCHAR(30) NOT NULL CHECK (resolution_type IN (
                'refund',
                'discount',
                'no_action',
                'compensation'
            )),
            resolution_amount_ngn DECIMAL(15, 2),
            approval_level VARCHAR(20) NOT NULL CHECK (approval_level IN ('staff', 'manager', 'admin')),
            approved_by UUID NOT NULL REFERENCES tenant_user(id),
            notes TEXT,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
    """)
    op.execute("CREATE INDEX idx_claim_resolution_claim ON claim_resolution(damage_claim_id)")
    op.execute("CREATE INDEX idx_claim_resolution_tenant ON claim_resolution(tenant_id)")

    # ---------------------------------------------------------------------------
    # 5. missing_item — items that cannot be located in the warehouse (5 statuses)
    # ---------------------------------------------------------------------------
    op.execute("""
        CREATE TABLE missing_item (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id UUID NOT NULL REFERENCES tenant(id) ON DELETE RESTRICT,
            manifest_id UUID NOT NULL REFERENCES manifest(id) ON DELETE RESTRICT,
            customer_id UUID NOT NULL REFERENCES customer(id) ON DELETE RESTRICT,
            packing_list_id UUID REFERENCES packing_list(id),
            carton_tag VARCHAR(100),
            tracking_code VARCHAR(100),
            description TEXT NOT NULL,
            status VARCHAR(20) NOT NULL DEFAULT 'reported' CHECK (status IN (
                'reported',
                'investigating',
                'found',
                'confirmed_missing',
                'compensated'
            )),
            reported_by UUID REFERENCES tenant_user(id),
            resolved_by UUID REFERENCES tenant_user(id),
            resolved_at TIMESTAMPTZ,
            notes TEXT,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
    """)
    op.execute("CREATE INDEX idx_missing_item_tenant ON missing_item(tenant_id)")
    op.execute("CREATE INDEX idx_missing_item_manifest ON missing_item(manifest_id)")
    op.execute("CREATE INDEX idx_missing_item_tenant_status ON missing_item(tenant_id, status)")

    # ---------------------------------------------------------------------------
    # 6. seized_item — items confiscated by customs or other authorities (4 recovery states)
    # ---------------------------------------------------------------------------
    op.execute("""
        CREATE TABLE seized_item (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id UUID NOT NULL REFERENCES tenant(id) ON DELETE RESTRICT,
            container_id UUID NOT NULL REFERENCES container(id) ON DELETE RESTRICT,
            customer_id UUID REFERENCES customer(id),
            packing_list_item_id UUID REFERENCES packing_list_item(id),
            carton_tag VARCHAR(100),
            tracking_code VARCHAR(100),
            description TEXT NOT NULL,
            seizure_date DATE NOT NULL,
            seizure_authority VARCHAR(255),
            seizure_reference VARCHAR(100),
            recovery_status VARCHAR(20) NOT NULL DEFAULT 'seized' CHECK (recovery_status IN (
                'seized',
                'under_review',
                'recovered',
                'forfeited'
            )),
            recovery_date DATE,
            notes TEXT,
            created_by UUID REFERENCES tenant_user(id),
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
    """)
    op.execute("CREATE INDEX idx_seized_item_tenant ON seized_item(tenant_id)")
    op.execute("CREATE INDEX idx_seized_item_container ON seized_item(container_id)")
    op.execute("CREATE INDEX idx_seized_item_tenant_status ON seized_item(tenant_id, recovery_status)")

    # ---------------------------------------------------------------------------
    # 7. release_note — authorisation document for warehouse carton pickup
    #    Supports partial release via self-referential parent_release_note_id FK
    # ---------------------------------------------------------------------------
    op.execute("""
        CREATE TABLE release_note (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id UUID NOT NULL REFERENCES tenant(id) ON DELETE RESTRICT,
            billing_id UUID NOT NULL REFERENCES billing(id) ON DELETE RESTRICT,
            customer_id UUID NOT NULL REFERENCES customer(id) ON DELETE RESTRICT,
            container_id UUID NOT NULL REFERENCES container(id) ON DELETE RESTRICT,
            reference_number VARCHAR(100) NOT NULL,
            carton_tags TEXT[] NOT NULL DEFAULT '{}',
            total_cartons INTEGER NOT NULL DEFAULT 0,
            is_partial BOOLEAN NOT NULL DEFAULT FALSE,
            parent_release_note_id UUID REFERENCES release_note(id),
            status VARCHAR(30) NOT NULL DEFAULT 'issued' CHECK (status IN (
                'issued',
                'partially_picked_up',
                'fully_picked_up',
                'expired',
                'cancelled'
            )),
            valid_until DATE,
            issued_by UUID REFERENCES tenant_user(id),
            notes TEXT,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            UNIQUE (tenant_id, reference_number)
        )
    """)
    op.execute("CREATE INDEX idx_release_note_tenant ON release_note(tenant_id)")
    op.execute("CREATE INDEX idx_release_note_tenant_billing ON release_note(tenant_id, billing_id)")
    op.execute("CREATE INDEX idx_release_note_tenant_customer ON release_note(tenant_id, customer_id)")
    op.execute("CREATE INDEX idx_release_note_tenant_status ON release_note(tenant_id, status)")

    # ---------------------------------------------------------------------------
    # 8. pickup_record — records who collected cartons and identity verification
    # ---------------------------------------------------------------------------
    op.execute("""
        CREATE TABLE pickup_record (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id UUID NOT NULL REFERENCES tenant(id) ON DELETE RESTRICT,
            release_note_id UUID NOT NULL REFERENCES release_note(id) ON DELETE RESTRICT,
            customer_id UUID NOT NULL REFERENCES customer(id) ON DELETE RESTRICT,
            carton_tags_picked TEXT[] NOT NULL DEFAULT '{}',
            cartons_count INTEGER NOT NULL DEFAULT 0,
            pickup_date DATE NOT NULL DEFAULT CURRENT_DATE,
            collected_by_name VARCHAR(255) NOT NULL,
            collected_by_phone VARCHAR(50),
            id_type VARCHAR(50),
            id_number VARCHAR(100),
            is_delegate BOOLEAN NOT NULL DEFAULT FALSE,
            delegate_name VARCHAR(255),
            delegate_phone VARCHAR(50),
            received_by UUID REFERENCES tenant_user(id),
            notes TEXT,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
    """)
    op.execute("CREATE INDEX idx_pickup_record_tenant ON pickup_record(tenant_id)")
    op.execute("CREATE INDEX idx_pickup_record_release_note ON pickup_record(release_note_id)")
    op.execute("CREATE INDEX idx_pickup_record_customer ON pickup_record(customer_id)")

    # ---------------------------------------------------------------------------
    # 9. refund_request — full refund workflow including debt check + payout details (7 statuses)
    # ---------------------------------------------------------------------------
    op.execute("""
        CREATE TABLE refund_request (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id UUID NOT NULL REFERENCES tenant(id) ON DELETE RESTRICT,
            customer_id UUID NOT NULL REFERENCES customer(id) ON DELETE RESTRICT,
            billing_id UUID REFERENCES billing(id),
            amount_ngn DECIMAL(15, 2) NOT NULL,
            reason TEXT NOT NULL,
            status VARCHAR(20) NOT NULL DEFAULT 'pending' CHECK (status IN (
                'pending',
                'debt_check',
                'approved',
                'rejected',
                'processing',
                'completed',
                'cancelled'
            )),
            customer_choice VARCHAR(20) CHECK (customer_choice IN ('cash', 'bank_transfer', 'credit_note')),
            bank_name VARCHAR(100),
            account_number VARCHAR(50),
            account_name VARCHAR(255),
            has_outstanding_debt BOOLEAN,
            outstanding_debt_ngn DECIMAL(15, 2),
            approval_level VARCHAR(20) CHECK (approval_level IN ('staff', 'manager', 'admin')),
            approved_by UUID REFERENCES tenant_user(id),
            approved_at TIMESTAMPTZ,
            rejected_by UUID REFERENCES tenant_user(id),
            rejection_reason TEXT,
            processed_by UUID REFERENCES tenant_user(id),
            processed_at TIMESTAMPTZ,
            requested_by UUID REFERENCES tenant_user(id),
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
    """)
    op.execute("CREATE INDEX idx_refund_request_tenant ON refund_request(tenant_id)")
    op.execute("CREATE INDEX idx_refund_request_tenant_customer ON refund_request(tenant_id, customer_id)")
    op.execute("CREATE INDEX idx_refund_request_tenant_status ON refund_request(tenant_id, status)")

    # ---------------------------------------------------------------------------
    # 10. storage_fee_log — daily storage accrual; UNIQUE (billing_id, accrual_date)
    #     Partial index on is_billed for efficient unbilled accrual queries
    # ---------------------------------------------------------------------------
    op.execute("""
        CREATE TABLE storage_fee_log (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id UUID NOT NULL REFERENCES tenant(id) ON DELETE RESTRICT,
            billing_id UUID NOT NULL REFERENCES billing(id) ON DELETE RESTRICT,
            customer_id UUID NOT NULL REFERENCES customer(id) ON DELETE RESTRICT,
            container_id UUID NOT NULL REFERENCES container(id) ON DELETE RESTRICT,
            accrual_date DATE NOT NULL,
            cartons_in_storage INTEGER NOT NULL DEFAULT 0,
            daily_rate_ngn DECIMAL(10, 2) NOT NULL,
            amount_ngn DECIMAL(15, 2) NOT NULL,
            grace_period_days INTEGER NOT NULL DEFAULT 14,
            days_in_storage INTEGER NOT NULL DEFAULT 0,
            is_billed BOOLEAN NOT NULL DEFAULT FALSE,
            misc_charge_id UUID REFERENCES misc_charge(id),
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            UNIQUE (billing_id, accrual_date)
        )
    """)
    op.execute("CREATE INDEX idx_storage_fee_log_tenant ON storage_fee_log(tenant_id)")
    op.execute("CREATE INDEX idx_storage_fee_log_billing ON storage_fee_log(billing_id)")
    op.execute("CREATE INDEX idx_storage_fee_log_accrual ON storage_fee_log(tenant_id, accrual_date)")
    op.execute(
        "CREATE INDEX idx_storage_fee_log_unbilled ON storage_fee_log(tenant_id, is_billed) "
        "WHERE is_billed = FALSE"
    )

    # ---------------------------------------------------------------------------
    # 11. carryover_ledger — outstanding balance carried forward to the next shipment
    # ---------------------------------------------------------------------------
    op.execute("""
        CREATE TABLE carryover_ledger (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id UUID NOT NULL REFERENCES tenant(id) ON DELETE RESTRICT,
            customer_id UUID NOT NULL REFERENCES customer(id) ON DELETE RESTRICT,
            source_billing_id UUID NOT NULL REFERENCES billing(id) ON DELETE RESTRICT,
            target_billing_id UUID REFERENCES billing(id),
            carryover_amount_ngn DECIMAL(15, 2) NOT NULL,
            status VARCHAR(20) NOT NULL DEFAULT 'outstanding' CHECK (status IN (
                'outstanding',
                'applied',
                'waived',
                'written_off'
            )),
            applied_at TIMESTAMPTZ,
            notes TEXT,
            created_by UUID REFERENCES tenant_user(id),
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
    """)
    op.execute("CREATE INDEX idx_carryover_ledger_tenant ON carryover_ledger(tenant_id)")
    op.execute("CREATE INDEX idx_carryover_ledger_customer ON carryover_ledger(tenant_id, customer_id)")
    op.execute("CREATE INDEX idx_carryover_ledger_status ON carryover_ledger(tenant_id, status)")

    # ---------------------------------------------------------------------------
    # 12. charge_type — tenant-configurable catalogue of miscellaneous charge types
    # ---------------------------------------------------------------------------
    op.execute("""
        CREATE TABLE charge_type (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id UUID NOT NULL REFERENCES tenant(id) ON DELETE CASCADE,
            name VARCHAR(100) NOT NULL,
            description TEXT,
            default_amount_ngn DECIMAL(15, 2),
            is_active BOOLEAN NOT NULL DEFAULT TRUE,
            created_by UUID REFERENCES tenant_user(id),
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            UNIQUE (tenant_id, name)
        )
    """)
    op.execute("CREATE INDEX idx_charge_type_tenant ON charge_type(tenant_id)")


def downgrade() -> None:
    # Drop in strict reverse FK dependency order
    op.execute("DROP TABLE IF EXISTS charge_type")
    op.execute("DROP TABLE IF EXISTS carryover_ledger")
    op.execute("DROP TABLE IF EXISTS storage_fee_log")
    op.execute("DROP TABLE IF EXISTS refund_request")
    op.execute("DROP TABLE IF EXISTS pickup_record")
    op.execute("DROP TABLE IF EXISTS release_note")
    op.execute("DROP TABLE IF EXISTS seized_item")
    op.execute("DROP TABLE IF EXISTS missing_item")
    op.execute("DROP TABLE IF EXISTS claim_resolution")
    op.execute("DROP TABLE IF EXISTS claim_evidence")
    op.execute("DROP TABLE IF EXISTS damage_claim")
    op.execute("DROP TABLE IF EXISTS cbm_dispute")
