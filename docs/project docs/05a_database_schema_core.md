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

> **Schema note (migration 023):** `slug VARCHAR(63) NOT NULL UNIQUE` and `custom_domain VARCHAR(255) UNIQUE` added to `tenant`. `slug` is auto-derived from `company_name` (lowercase, non-alphanumeric → hyphen) at tenant creation. Used for subdomain routing (`{slug}.shipx.com`). `custom_domain` is nullable and reserved for enterprise white-label (e.g. `track.acmelogistics.com`).

```sql
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

> **Schema note (migration 039 — multi-role staff support):** `tenant_user.role` is kept and now means **primary role** — every existing query that reads it directly (reports, staff-detail summary, badges) keeps working unmodified. The full set of roles a user holds lives in the new `tenant_user_role` join table (below); `role` is written by `services/tenant_management/repository.py::set_user_roles()` transactionally alongside `tenant_user_role`, so the two never drift. See "Migration 039" under **Schema Changes Applied Post-Initial Migration**.

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
- `dollar_rate` → **superseded (2026-09-19), no longer read.** Was `{ "rate": 1550.00, "currency_pair": "USD_NGN", "effective_from": "..." }`. Existing rows are harmless legacy data — nothing reads this key anymore. The base rate now comes from Bybit's live P2P order book (`shared/fx_rate.py`), not a stored value; see `dollar_rate_markup` below and `07_api_tenant_management.md`'s Dollar Rate section.
- `dollar_rate_markup` → `{ "markup_type": "percentage" | "flat", "markup_value": 0, "updated_at": "..." }` — the only rate-related tenant config left. `markup_type: "flat"` means a plain ₦ amount added directly to the Bybit base rate; `"percentage"` multiplies it. `markup_value: 0` (the default for new tenants) passes the base rate through unchanged.
- `storage_fee` → `{ "enabled": true, "grace_period_days": 14, "daily_fee_per_carton_ngn": 500 }`
- `warehouse_address` → `{ "address": "...", "city": "Lagos", "state": "Lagos" }`
- `refund_threshold_usd` → `{ "staff_limit": 50, "requires_manager_above": 50 }`
- `dispute_escalation` → `{ "enabled": true, "auto_escalate_days": 5 }`
- `cbm_rate_per_unit` → `{ "rate_usd": 45.00 }`
- `reminder_days` → `{ "storage_first_reminder": 7, "storage_final_reminder": 13 }`
- `webhook_config` → `{ "enabled": false, "url": "", "secret": "", "events": [...] }` — outbound integration HMAC secret, plaintext (low blast radius — see `07_api_tenant_management.md`)
- `paystack_config` → `{ "enabled": false, "secret_key_encrypted": null, "last4": null, "environment": null, "configured_by": null, "configured_at": null }` — per-tenant payment gateway key, **encrypted** via `shared/encryption.py` (2026-07-19, see `07_api_tenant_management.md`'s "Multi-Tenant Paystack" design note for why this one is encrypted and `webhook_config` isn't)

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
    departure_date DATE, -- migration 040; loading date (ship_date) vs. actual vessel departure date
    estimated_arrival_date DATE,
    actual_arrival_date DATE,
    status VARCHAR(30) NOT NULL DEFAULT 'loading' CHECK (status IN (
        'loading', 'sealed', 'in_transit', 'arrived', 'customs_clearance',
        'cleared', 'at_warehouse', 'fully_released'
    )),
    notes TEXT,
    -- Vessel/voyage manifest details (migration 030) — all nullable, captured
    -- at create time when known or filled in later.
    vessel_name VARCHAR(255),
    voyage_number VARCHAR(50),
    shipping_line VARCHAR(255),
    seal_number VARCHAR(50),
    container_type VARCHAR(50),
    created_by UUID REFERENCES tenant_user(id),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (tenant_id, container_number)
);
CREATE INDEX idx_container_tenant ON container(tenant_id);
CREATE INDEX idx_container_tenant_status ON container(tenant_id, status);
```

> **Derived field:** `GET /v1/containers` and `GET /v1/containers/{id}` also return a computed `packing_list_count` (correlated `COUNT(*)` over `packing_list` for the container) — not a stored column.

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
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    -- Manifest import fields (migration 040) — bulk-quantity model + per-parcel
    -- business references from China-side freight-forwarder manifest exports.
    -- All nullable/defaulted; existing rows and the exact-header packing-list
    -- importer are unaffected. See 19_excel_import_export.md §"Manifest Import".
    delivery_note_number VARCHAR(50), -- re-import dedupe key within a packing list
    quantity INTEGER NOT NULL DEFAULT 1,
    package_unit VARCHAR(20), -- normalized: 'carton' | 'bag' | 'bale' | 'pallet' | 'package' | 'mixed'
    quantity_raw VARCHAR(50), -- verbatim source cell ("1PALLET(61items)", "3bags2ctns1pallet")
    bale_type VARCHAR(30), -- verbatim BALE TYPE ("BIG BALE" / "LONG BALE"); package_unit collapses to 'bale'
    bale_no VARCHAR(20), -- raw source reference, can be non-numeric (e.g. "1(3)")
    original_receipt_number VARCHAR(100), -- source "OG NO." — a receipt reference, not a supplier field
    delivery_zone VARCHAR(100), -- sub-destination delivery area, e.g. "LAGOS-ISLAND"
    on_hold BOOLEAN NOT NULL DEFAULT FALSE, -- red-marked row in the source manifest
    hold_reason TEXT
);
CREATE INDEX idx_packing_list_item_list ON packing_list_item(packing_list_id);
CREATE INDEX idx_packing_list_item_tracking ON packing_list_item(tracking_code);
CREATE INDEX idx_packing_list_item_carton ON packing_list_item(carton_tag);
CREATE INDEX idx_packing_list_item_delivery_note ON packing_list_item(delivery_note_number)
    WHERE delivery_note_number IS NOT NULL;
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

### Migration 039 — Multi-Role Staff Support

A `tenant_user` can now hold more than one role at once (e.g. `nigeria_office_staff` +
`warehouse_attendant`). New join table:

```sql
CREATE TABLE tenant_user_role (
    tenant_user_id UUID NOT NULL REFERENCES tenant_user(id) ON DELETE CASCADE,
    tenant_id      UUID NOT NULL REFERENCES tenant(id) ON DELETE RESTRICT,
    role           VARCHAR(30) NOT NULL CHECK (role IN (
        'tenant_admin', 'china_office_staff', 'nigeria_office_staff',
        'warehouse_attendant', 'customer'
    )),
    is_primary     BOOLEAN NOT NULL DEFAULT FALSE,
    assigned_by    UUID REFERENCES tenant_user(id),
    assigned_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (tenant_user_id, role)
);
CREATE UNIQUE INDEX idx_tenant_user_role_one_primary
    ON tenant_user_role(tenant_user_id) WHERE is_primary;
CREATE INDEX idx_tenant_user_role_tenant ON tenant_user_role(tenant_id);
```

- **Backfill:** one row per pre-existing `tenant_user`, `role = tenant_user.role`,
  `is_primary = TRUE`. Verified locally: 28/28 existing rows backfilled 1:1, each with
  exactly one `is_primary = TRUE` row.
- **Partial unique index** `idx_tenant_user_role_one_primary` enforces exactly one
  primary role per user — a second `INSERT ... is_primary = TRUE` for the same
  `tenant_user_id` raises `duplicate key value violates unique constraint`.
- **RLS:** standard tenant-isolation policy (`tenant_isolation` + `tenant_insert`),
  same pattern as `notification_log` (migration 027) — see
  `migrations/versions/039_tenant_user_multi_role.py`.
- `tenant_user.role` is unaffected by the migration itself (no data migration on that
  column) — it continues to be written on every role change, see the schema note above.
- API/service-layer changes: `07_api_tenant_management.md` (breaking request-shape
  change), `services/tenant_management/repository.py::set_user_roles()` /
  `get_user_roles()`.

### Migration 040 — Manifest Import Fields

Schema support for the new flexible `POST /v1/manifests/import` flow (`services/excel/import_manifest.py`,
`19_excel_import_export.md` §"Manifest Import") — ingesting a China-side freight-forwarder manifest export
without requiring the container/customers/packing lists to already exist.

- `container.departure_date DATE` — the real source documents distinguish LOADING DATE (`ship_date`,
  unchanged) from DEPARTURE DATE (when the vessel actually leaves port). `estimated_arrival_date` already
  matched ARRIVAL DATE — no change there.
- `packing_list_item` gains a bulk-quantity model instead of forcing one row per physical carton:
  `delivery_note_number VARCHAR(50)`, `quantity INTEGER NOT NULL DEFAULT 1`, `package_unit VARCHAR(20)`,
  `bale_no VARCHAR(20)`, `bale_type VARCHAR(30)`, `quantity_raw VARCHAR(50)`,
  `original_receipt_number VARCHAR(100)`, `delivery_zone VARCHAR(100)`,
  `on_hold BOOLEAN NOT NULL DEFAULT FALSE`, `hold_reason TEXT`. (`original_receipt_number` — renamed
  from `supplier_reference` before this migration was ever committed: the source "OG NO." column is
  short for "Original Receipt Number" per the source document's own spelled-out header, not a supplier
  concept — see `19_excel_import_export.md`'s naming note.)
- Partial index `idx_packing_list_item_delivery_note ON packing_list_item(delivery_note_number) WHERE
  delivery_note_number IS NOT NULL` — powers the manifest importer's re-import dedupe lookup.
- All new columns nullable or defaulted — verified locally: applying the migration against the seeded
  local stack left every pre-existing `container`/`packing_list_item` row and the existing exact-header
  importer (`POST /v1/packing-lists/import`) working unmodified; full existing unit suite (517 tests)
  passed unchanged both before and after.
- `carton_tag`/`tracking_code` stay required — the manifest importer auto-generates them using the same
  sequence pattern the existing importer already uses; the source manifest has no natural per-carton tag.
- `customer` table unchanged. Name suffixes seen in source data (e.g. `"(GQL)"`) are imported as-is,
  embedded in `customer.name` — not modeled as a separate agent-code column.

### Migration 042 — Customer Account-Creation Invites + Phone Uniqueness

Manifest import creates `customer` rows with only `name` + `phone` (no login, no email) — this migration
adds the account-creation-invite mechanism (`shared/invites.py`, `07_api_tenant_management.md` §"Customer
account-creation invites") and makes `phone` a real per-tenant identifier.

- New table `customer_invite`:
  ```sql
  CREATE TABLE customer_invite (
      id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
      tenant_id UUID NOT NULL REFERENCES tenant(id) ON DELETE RESTRICT,
      customer_id UUID NOT NULL REFERENCES customer(id) ON DELETE CASCADE,
      token_hash CHAR(64) NOT NULL,        -- sha256 of the token; the token itself is never stored
      expires_at TIMESTAMPTZ NOT NULL,
      consumed_at TIMESTAMPTZ,
      sent_channel VARCHAR(20),            -- sms | whatsapp | email
      sent_to_masked VARCHAR(64),          -- e.g. "+23480****678" — no raw PII in this table
      created_by UUID REFERENCES tenant_user(id),
      created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
  );
  CREATE UNIQUE INDEX idx_customer_invite_token_hash ON customer_invite(token_hash);
  CREATE INDEX idx_customer_invite_customer ON customer_invite(tenant_id, customer_id);
  ```
  RLS on, standard tenant-isolation policy. Only one unconsumed invite exists per customer at a time —
  the service layer (`issue_customer_invite`) deletes any prior unconsumed row before minting a new one,
  so resending invalidates the old link.
- `CREATE UNIQUE INDEX idx_customer_tenant_phone_unique ON customer(tenant_id, phone) WHERE phone IS NOT NULL`
  (named distinctly from migration 002's pre-existing plain `idx_customer_tenant_phone`, found live while
  applying this migration — that older index stays in place, redundant but harmless).
  Phone normalisation (`shared/phone.py::normalize_phone`, E.164 via the tenant's destination-country
  dial code) is a **prerequisite** applied on every customer write path before this migration runs, not
  introduced by it. The migration pre-flight-checks for existing `(tenant_id, phone)` duplicates and
  **aborts with a report** rather than merging customer records — merging is a data decision for the
  tenant, not something a migration should decide silently. Ran clean against the local seeded stack
  (zero duplicates after the normalisation fix landed).
- `services/excel/service.py::_normalize_phone` (excel-only, digit-strip only, no E.164 canonicalisation)
  was retired in favour of the shared `shared/phone.py::normalize_phone`, now called from every customer
  write path: manifest import, `tenant_management.service.create_customer`/`update_customer`, and
  `self_register_customer`/`accept_customer_invite`.

### Migration 055 — `tenant_user_activation`

New table `tenant_user_activation` (account activation for operator-provisioned staff/admins — the
`tenant_user` analogue of `customer_invite`):
```sql
CREATE TABLE tenant_user_activation (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id UUID NOT NULL REFERENCES tenant(id) ON DELETE RESTRICT,
    user_id UUID NOT NULL REFERENCES tenant_user(id) ON DELETE CASCADE,
    token_hash CHAR(64) NOT NULL,
    expires_at TIMESTAMPTZ NOT NULL,
    consumed_at TIMESTAMPTZ,
    sent_channel VARCHAR(20),
    sent_to_masked VARCHAR(64),
    created_by UUID REFERENCES tenant_user(id),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE UNIQUE INDEX idx_tenant_user_activation_token_hash ON tenant_user_activation(token_hash);
CREATE INDEX idx_tenant_user_activation_user ON tenant_user_activation(tenant_id, user_id);
```
RLS on, standard tenant-isolation policy. Single-use, 48h, SHA-256-hashed opaque token; the service
(`issue_activation`) deletes any prior unconsumed row before minting a new one (resend invalidates the
old link). Backs the `/activate/{token}` set-password flow (`shared/activation.py`); the public token
lookup is PLATFORM-scoped, like `customer_invite`. See the activation note in `07_api_tenant_management.md`.

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
- [x] `tenant.slug` (NOT NULL UNIQUE) and `tenant.custom_domain` (nullable UNIQUE) added (migration 023) — subdomain routing and enterprise white-label support
- [x] `customer.delivery_address JSONB` added (migration 026) — per-customer last-mile delivery address
- [x] `packing_list_item.declared_value_usd DECIMAL(15,2)` added (migration 026) — insurance / customs valuation per carton
- [x] `tenant_user.locale VARCHAR(10) DEFAULT 'en'` added (migration 026) — EN/ZH notification language
- [x] `tenant_user_role` join table added (migration 039) — multi-role staff support; `tenant_user.role` kept as primary role, mirrored transactionally by `set_user_roles()`; partial unique index enforces one primary per user; RLS-enabled
- [x] `container.departure_date` and `packing_list_item` manifest-import fields added (migration 040) — nullable/defaulted, zero regressions; powers `POST /v1/manifests/import`

## `packing_list_item.batch_ref` (migration 061, 2026-11-12)

`UUID NULL` — groups the rows produced by one bulk-quantity entry. NULL for rows
keyed or imported individually, which is every row that existed before.

Partial index `ix_packing_list_item_batch_ref (packing_list_id, batch_ref)
WHERE batch_ref IS NOT NULL`: only batched rows are looked up this way and they
are the minority, so the index stays small.

It is a **safeguard, not decoration**. A quantity typed wrongly creates a
hundred rows, and undoing that one row at a time is tedious enough that someone
would reasonably leave it — which is how wrong cargo data survives. The grouping
makes the mistake one action to reverse.

Note this is *not* the same as `packing_list_item.quantity`, which predates it
(migration 040) and means "this row is N packages" for the Excel manifest
import. Manually expanded rows leave `quantity` alone so package counts stay
correct.
