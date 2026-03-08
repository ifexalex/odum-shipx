# Task 05a — Database DDL: Platform, Tenant & Core Operational Tables

## Objective

Create the Alembic migration for the first set of database tables: platform/tenant tables and core operational tables (customer, container, manifest, packing list, shipment tracking, billing).

## Depends On

- Task 04a (Aurora Serverless v2 available)

## Deliverables

### File: `migrations/versions/001_platform_tenant_tables.py`

Create these tables in order (respecting foreign key dependencies):

#### 1. `tenant` table
```sql
CREATE TABLE tenant (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    company_name VARCHAR(255) NOT NULL,
    primary_contact_email VARCHAR(255) NOT NULL,
    primary_contact_phone VARCHAR(50),
    origin_country VARCHAR(100) NOT NULL DEFAULT 'China',
    destination_country VARCHAR(100) NOT NULL DEFAULT 'Nigeria',
    subscription_tier VARCHAR(20) NOT NULL CHECK (subscription_tier IN ('starter', 'business', 'enterprise')),
    status VARCHAR(20) NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'suspended', 'offboarded')),
    branding_config JSONB NOT NULL DEFAULT '{}'::jsonb,
    notification_preferences JSONB NOT NULL DEFAULT '{}'::jsonb,
    data_exported_at TIMESTAMPTZ,
    offboarded_at TIMESTAMPTZ,
    deletion_scheduled_at TIMESTAMPTZ,
    reactivated_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX idx_tenant_status ON tenant(status);
```

#### 2. `tenant_user` table
```sql
CREATE TABLE tenant_user (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id UUID NOT NULL REFERENCES tenant(id) ON DELETE RESTRICT,
    cognito_sub VARCHAR(255) UNIQUE,
    email VARCHAR(255) NOT NULL,
    full_name VARCHAR(255) NOT NULL,
    role VARCHAR(30) NOT NULL CHECK (role IN (
        'tenant_admin', 'china_office_staff', 'nigeria_office_staff',
        'warehouse_attendant', 'customer'
    )),
    status VARCHAR(20) NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'deactivated')),
    created_by UUID REFERENCES tenant_user(id),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (tenant_id, email)
);
CREATE INDEX idx_tenant_user_tenant ON tenant_user(tenant_id);
CREATE INDEX idx_tenant_user_email ON tenant_user(email);
```

#### 3. `tenant_config` table
```sql
CREATE TABLE tenant_config (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id UUID NOT NULL REFERENCES tenant(id) ON DELETE CASCADE,
    config_key VARCHAR(100) NOT NULL,
    config_value JSONB NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_by UUID REFERENCES tenant_user(id),
    UNIQUE (tenant_id, config_key)
);
CREATE INDEX idx_tenant_config_tenant ON tenant_config(tenant_id);
```

**Predefined config_key values (document for seed data):**
- `dollar_rate` → `{ "rate": 1550.00, "currency_pair": "USD_NGN", "effective_from": "..." }`
- `storage_fee` → `{ "enabled": true, "grace_period_days": 14, "daily_fee_per_carton_ngn": 500 }`
- `warehouse_address` → `{ "address": "...", "city": "Lagos", "state": "Lagos" }`
- `refund_threshold_usd` → `{ "staff_limit": 50, "requires_manager_above": 50 }`
- `dispute_escalation` → `{ "enabled": true, "auto_escalate_days": 5 }`
- `cbm_rate_per_unit` → `{ "rate_usd": 45.00 }`
- `reminder_days` → `{ "storage_first_reminder": 7, "storage_final_reminder": 13 }`

> **Schema note (migration 014):** The `updated_by` column on `tenant_config` references a Cognito sub UUID which does not exist in the `tenant_user` table. The FK constraint was dropped in migration 014 — the column is retained for auditing but without an enforced FK.

> **Schema note (migration 015):** `reactivated_at TIMESTAMPTZ` added to `tenant`. Set when a previously offboarded tenant is re-onboarded via `PATCH /v1/platform/tenants/{id}/reactivate`. Acts as the GDPR audit boundary — data processed after this timestamp operates under the new contract. `deletion_scheduled_at` is cleared on reactivation.

#### 4. `usage_record` table
```sql
CREATE TABLE usage_record (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id UUID NOT NULL REFERENCES tenant(id) ON DELETE CASCADE,
    metric_type VARCHAR(50) NOT NULL CHECK (metric_type IN (
        'api_calls', 'containers_processed', 'storage_bytes', 'users_active',
        'sms_sent', 'whatsapp_sent', 'emails_sent'
    )),
    value DECIMAL(15, 4) NOT NULL,
    period_start DATE NOT NULL,
    period_end DATE NOT NULL,
    recorded_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX idx_usage_record_tenant_period ON usage_record(tenant_id, period_start);
CREATE INDEX idx_usage_record_tenant_metric ON usage_record(tenant_id, metric_type, period_start);
```

### File: `migrations/versions/002_core_operational_tables.py`

#### 5. `customer` table
```sql
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
    -- GDPR fields (migration 012)
    anonymised_at TIMESTAMPTZ,                    -- Art. 17: set on erasure; PII columns nulled
    consent_given_at TIMESTAMPTZ,                 -- when data processing consent was recorded
    notification_consent TEXT[] DEFAULT '{}',     -- allowed channels: 'sms', 'whatsapp', 'email'
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX idx_customer_tenant ON customer(tenant_id);
CREATE INDEX idx_customer_tenant_name ON customer(tenant_id, name);
CREATE INDEX idx_customer_tenant_phone ON customer(tenant_id, phone);
```

> **GDPR erasure (Art. 17):** `DELETE /v1/customers/{id}` does not physically delete the row. It nulls all PII columns (`name`, `email`, `phone`, `whatsapp`, `address`, `contract_details`) and sets `anonymised_at`. The UUID is preserved for foreign key integrity with billing and shipment records.
>
> **Data portability (Art. 20):** `GET /v1/customers/{id}/export` returns a full JSON bundle of all data held for the customer (billing, shipments, damage claims).

#### 6. `container` table
```sql
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
        'loading', 'sealed', 'in_transit', 'arrived', 'customs_clearance',
        'cleared', 'at_warehouse', 'fully_released'
    )),
    notes TEXT,
    created_by UUID REFERENCES tenant_user(id),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (tenant_id, container_number)
);
CREATE INDEX idx_container_tenant ON container(tenant_id);
CREATE INDEX idx_container_tenant_status ON container(tenant_id, status);
```

#### 7. `manifest` table
```sql
CREATE TABLE manifest (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id UUID NOT NULL REFERENCES tenant(id) ON DELETE RESTRICT,
    container_id UUID NOT NULL REFERENCES container(id) ON DELETE RESTRICT,
    total_customers INTEGER NOT NULL DEFAULT 0,
    total_cartons INTEGER NOT NULL DEFAULT 0,
    total_weight_kg DECIMAL(12, 3) NOT NULL DEFAULT 0,
    total_cbm DECIMAL(12, 6) NOT NULL DEFAULT 0,
    verification_status VARCHAR(20) NOT NULL DEFAULT 'pending' CHECK (verification_status IN (
        'pending', 'verified', 'discrepancies_found'
    )),
    verified_by UUID REFERENCES tenant_user(id),
    verified_at TIMESTAMPTZ,
    notes TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (tenant_id, container_id)
);
CREATE INDEX idx_manifest_tenant ON manifest(tenant_id);
CREATE INDEX idx_manifest_tenant_container ON manifest(tenant_id, container_id);
```

#### 8. `packing_list` table
```sql
CREATE TABLE packing_list (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id UUID NOT NULL REFERENCES tenant(id) ON DELETE RESTRICT,
    container_id UUID NOT NULL REFERENCES container(id) ON DELETE RESTRICT,
    manifest_id UUID REFERENCES manifest(id),
    customer_id UUID NOT NULL REFERENCES customer(id) ON DELETE RESTRICT,
    status VARCHAR(20) NOT NULL DEFAULT 'draft' CHECK (status IN (
        'draft', 'pending_approval', 'approved', 'rejected'
    )),
    approval_comments JSONB,
    approved_by UUID REFERENCES tenant_user(id),
    approved_at TIMESTAMPTZ,
    rejected_by UUID REFERENCES tenant_user(id),
    rejected_at TIMESTAMPTZ,
    created_by UUID REFERENCES tenant_user(id),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX idx_packing_list_tenant_customer ON packing_list(tenant_id, customer_id);
CREATE INDEX idx_packing_list_tenant_container ON packing_list(tenant_id, container_id);
CREATE INDEX idx_packing_list_tenant_status ON packing_list(tenant_id, status);
```

#### 9. `packing_list_item` table
```sql
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
);
CREATE INDEX idx_packing_list_item_list ON packing_list_item(packing_list_id);
CREATE INDEX idx_packing_list_item_tracking ON packing_list_item(tracking_code);
CREATE INDEX idx_packing_list_item_carton ON packing_list_item(carton_tag);
```

#### 10. `shipment_tracking` + `tracking_event` tables
(Include full DDL from backend spec §1.2)

#### 11. `billing` + `misc_charge` + `payment_record` tables
(Include full DDL from backend spec §1.2)

## Also Create

### File: `migrations/alembic.ini`
### File: `migrations/env.py`

Standard Alembic setup with:
- Database URL from environment variable
- Auto-generate migration support disabled (we write migrations manually)

### File: `scripts/migrate.py`

Simple wrapper that runs `alembic upgrade head`.

## Schema Changes Applied Post-Initial Migration

### Migration 006 — Billing & CBM Dispute Status Fix

**`billing.status`** CHECK constraint replaced:
- Old: `draft`, `sent`, `partially_paid`, `paid`, `overdue`, `cancelled`
- **New:** `unpaid`, `partially_paid`, `paid`, `overpaid`, `waived`, `released_with_outstanding`

Additional `billing` columns added:
- `billed_at TIMESTAMPTZ` — when the invoice was generated
- `released_with_outstanding BOOLEAN` — true if cartons were released despite an outstanding balance

**`cbm_dispute.status`** CHECK constraint replaced:
- Old: `open`, `under_review`, `evidence_submitted`, `agreed`, `rejected`, `resolved`, `escalated`
- **New:** `submitted`, `acknowledged`, `investigating`, `escalated_china`, `resolved_adjusted`, `resolved_no_change`, `closed`

Additional `cbm_dispute` columns: `acknowledged_at TIMESTAMPTZ`, `customer_measured_cbm DECIMAL`.

> **Seed data note:** Use `"unpaid"` (not `"draft"` or `"sent"`) when seeding billing records.

## Acceptance Criteria

- [x] All tables created with correct data types and constraints
- [x] CHECK constraints match exactly the enums defined in backend spec
- [x] Foreign keys use ON DELETE RESTRICT (prevent accidental data loss) except where CASCADE is specified
- [x] All indexes created as specified
- [x] UNIQUE constraints match spec (tenant_id + container_number, tenant_id + email, etc.)
- [x] Alembic migrations run successfully against a fresh PostgreSQL database
- [x] `alembic upgrade head` is idempotent
- [x] GDPR fields added to customer (migration 012)
- [x] Billing status values corrected (migration 006)
- [x] `tenant.reactivated_at` added (migration 015) — GDPR audit boundary for re-onboarding
