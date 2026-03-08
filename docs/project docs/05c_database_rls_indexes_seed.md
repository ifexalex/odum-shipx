# Task 05c — Database: Row-Level Security Policies, Indexes & Seed Data

## Objective

Apply PostgreSQL Row-Level Security (RLS) policies on all tenant-scoped tables (the 3rd layer of the 4-layer tenant isolation defense), and create seed data for development.

## Depends On

- Tasks 05a, 05b (all tables exist)

## Deliverables

### File: `migrations/versions/005_rls_policies.py`

Apply RLS to ALL tenant-scoped tables using a loop:

```sql
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
        EXECUTE format('ALTER TABLE %I ENABLE ROW LEVEL SECURITY', tbl);
        -- SELECT/UPDATE/DELETE policy
        EXECUTE format(
            'CREATE POLICY tenant_isolation ON %I USING (tenant_id = current_setting(''app.current_tenant_id'')::uuid)',
            tbl
        );
        -- INSERT policy
        EXECUTE format(
            'CREATE POLICY tenant_insert ON %I FOR INSERT WITH CHECK (tenant_id = current_setting(''app.current_tenant_id'')::uuid)',
            tbl
        );
    END LOOP;
END $$;
```

**Tables WITHOUT RLS (not tenant-scoped):**
- `tenant` — only accessible by Platform Admin
- `platform_audit_log` — only Platform Admin
- `platform_settings` — platform-wide config, not tenant-scoped (added migration 011)
- `packing_list_item`, `tracking_event`, `claim_evidence`, `claim_resolution`, `misc_charge` — inherit isolation through parent FK JOINs

**Create an application database role for Lambda connections:**
```sql
CREATE ROLE logistics_app LOGIN PASSWORD '...' ;
-- Grant usage on all tables but RLS will filter rows
GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO logistics_app;
GRANT USAGE ON ALL SEQUENCES IN SCHEMA public TO logistics_app;

-- Ensure RLS applies to this role (NOT the table owner)
-- RLS does not apply to superusers or table owners by default
ALTER TABLE customer FORCE ROW LEVEL SECURITY;
-- ... repeat for all tenant-scoped tables
```

### File: `scripts/seed.py`

Create seed data for development with **two test tenants**:

**Tenant A: "Acme Shipping Ltd"**
- subscription_tier: starter
- Users: 1 tenant_admin, 1 china_office_staff, 1 nigeria_office_staff, 1 warehouse_attendant, 2 customers
- Config: dollar_rate=1550, cbm_rate=45, storage_fee enabled
- 2 containers with packing lists, manifests
- Billing records in various payment states — use status values: `unpaid`, `partially_paid`, `paid` (not `draft`/`sent` — changed in migration 006)

**Tenant B: "Global Cargo Co"**
- subscription_tier: business
- Users: 1 tenant_admin, 2 china_office_staff, 1 customer
- Config: dollar_rate=1580, cbm_rate=50, storage_fee disabled
- 1 container with packing lists

**Platform Admin user:** `custom:tenant_id = PLATFORM`

The seed script should:
1. Connect to the database
2. Create tenants (bypassing RLS as superuser)
3. Create tenant users
4. Create tenant configs with default values
5. Create customers, containers, packing lists with items
6. Create manifests and tracking records
7. Create billing records
8. Print summary of created data

### File: `scripts/onboard_tenant.py`

CLI script for manual tenant onboarding:
```bash
python scripts/onboard_tenant.py \
  --company-name "New Shipping Co" \
  --email "admin@newshipping.com" \
  --tier starter
```

Steps:
1. Insert tenant record in DB
2. Create Cognito user with `custom:tenant_id`
3. Create tenant_user record
4. Insert default tenant_config records
5. Print tenant_id and temporary password

## Acceptance Criteria

- [x] RLS enabled on all 21 tenant-scoped tables
- [x] Both SELECT and INSERT policies created
- [x] `FORCE ROW LEVEL SECURITY` applied so RLS works for table owner too
- [x] Application role `logistics_app` created with appropriate grants
- [x] Seed data creates 2 tenants with realistic data
- [x] Seed data uses correct billing status values (`unpaid`, `partially_paid`, `paid` — not `draft`/`sent`)
- [x] Seed data includes data in various states (draft packing lists, approved ones, paid/unpaid billing)
- [x] Cross-tenant query test: connecting as `logistics_app` with Tenant A's ID returns zero Tenant B rows
- [x] `onboard_tenant.py` creates all required records
