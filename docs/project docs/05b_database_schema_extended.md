# Task 05b — Database DDL: Claims, Refunds, Storage Fees, Release, Audit Tables

## Objective

Create the Alembic migration for remaining tables: CBM disputes, damage claims, claim evidence/resolution, missing items, seized items, release notes, pickup records, refund requests, storage fee logs, carryover ledger, charge types, and audit tables.

## Depends On

- Task 05a (core tables exist for foreign key references)

## Deliverables

### File: `migrations/versions/003_extended_operational_tables.py`

Create these tables (all DDL is copied verbatim from the backend engineering specification §1.2):

1. **`cbm_dispute`** — CBM dispute tracking with 7 status states
2. **`damage_claim`** — Damage claim with 6 status states, cartons_affected as TEXT[]
3. **`claim_evidence`** — Photos/docs linked to damage claims, S3 file_key
4. **`claim_resolution`** — Resolution records (refund/discount/no_action) with approval levels
5. **`missing_item`** — Missing item log linked to manifest, 5 status states
6. **`seized_item`** — Seized item log with recovery_status, 4 states
7. **`release_note`** — Release notes with reference_number, carton_tags TEXT[], partial release support
8. **`pickup_record`** — Warehouse pickup records with delegate details
9. **`refund_request`** — Full refund workflow with 7 status states, debt_check fields, customer_choice
10. **`storage_fee_log`** — Daily storage fee accrual records
11. **`carryover_ledger`** — Outstanding balance carryover tracking between shipments
12. **`charge_type`** — Tenant-configurable miscellaneous charge types

### File: `migrations/versions/004_audit_tables.py`

1. **`audit_log`** — Tenant-scoped operation audit trail
   - entity_type, entity_id, action (CREATE/UPDATE/DELETE/STATUS_CHANGE)
   - actor_id, actor_role, before_state JSONB, after_state JSONB, ip_address INET
   - Indexes: (tenant_id, entity_type, entity_id), (tenant_id, actor_id), (tenant_id, created_at)

2. **`platform_audit_log`** — Cross-tenant admin actions (NOT tenant-scoped). **Migration 037** drops the `actor_id → tenant_user(id)` FK: platform admins are Cognito-only identities with no `tenant_user` row (same rationale as migration 014's `tenant_config.updated_by` drop), and the FK silently blocked every platform audit insert.
   - action, actor_id, target_tenant_id, details JSONB, ip_address INET
   - Indexes: (actor_id), (target_tenant_id), (created_at)

**All table DDL should be copied exactly from the backend engineering specification.** Refer to sections 1.2 and 1.3 of that document.

## Additional Schema Changes (Migrations 010–014)

### Migration 010 — `usage_record` Unique Constraint
Adds `UNIQUE (tenant_id, metric_type, period_start)` on `usage_record` to support `ON CONFLICT DO UPDATE` upserts in the metering SQS consumer.

### Migration 011 — `platform_settings` Table
New table for platform-wide configuration:
```sql
CREATE TABLE platform_settings (
    key   VARCHAR(100) PRIMARY KEY,
    value JSONB NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_by UUID   -- platform admin Cognito sub (no FK — Cognito sub not in DB)
);
```
Seeded with: `default_subscription_tier`, `max_tenants`, `maintenance_mode`, `platform_email_from`.

**New key (2026-09-19, no migration needed — the table is a flexible key/value store):** `fx_bybit_ngn_rate` → `{ "rate": "1373.20", "fetched_at": "2026-09-19T12:27:57Z" }`. The last successfully-fetched Bybit P2P USDT/NGN rate, written by `shared/fx_rate.py` every time a live fetch succeeds — the platform-wide fallback used when Bybit is unreachable and the short-lived Redis cache has also expired. Not tenant data (the black market rate doesn't vary by tenant), which is why it lives here rather than in `tenant_config`. See `07_api_tenant_management.md`'s Dollar Rate section for the full fetch/cache/fallback chain.

Also: `carryover_ledger` gains `exempted` status, `exempted_by UUID`, `exempted_at TIMESTAMPTZ`. `misc_charge.charge_type` CHECK constraint dropped (allows free-form types). `misc_charge.amount_usd` added.

### Migration 035 — Charge-type usage attribution
```sql
ALTER TABLE misc_charge
  ADD COLUMN charge_type_id UUID REFERENCES charge_type(id) ON DELETE SET NULL;
CREATE INDEX idx_misc_charge_charge_type_id ON misc_charge(charge_type_id);
```
Nullable FK linking a misc charge to the configured `charge_type` it was added from.
Powers the `usage_count` on `GET /v1/tenant/charge-types` (§4.4 "Times used"). The
enum `misc_charge.charge_type` stays authoritative for totals; this FK is set only when
a charge originates from a configured type (`ON DELETE SET NULL` so deleting a charge
type never blocks/orphans billing). Pre-migration rows and free-form "other" charges
stay NULL — counts are accurate from this migration forward.

### Migration 036 — Manifest verification evidence
```sql
CREATE TABLE manifest_evidence (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    manifest_id UUID NOT NULL REFERENCES manifest(id) ON DELETE CASCADE,
    file_key VARCHAR(500) NOT NULL,
    file_name VARCHAR(255) NOT NULL,
    file_type VARCHAR(50) NOT NULL,
    file_size_bytes INTEGER,
    label VARCHAR(255),
    uploaded_by UUID REFERENCES tenant_user(id),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX idx_manifest_evidence_manifest ON manifest_evidence(manifest_id);
```
S3-backed photos/docs for the manifest-verify workflow (§6.3, F-D3), mirroring
`claim_evidence`. **No RLS** — tenant isolation is enforced by the tenant-scoped
manifest lookup before insert and the `{tenant_id}/manifests/...` S3 key prefix;
reads scope via the `manifest_id` FK. `label` holds the optional discrepancy
descriptor (customer + type + carton tags). Uploaded via `POST /v1/manifests/{id}/evidence`.

### Migration 041 — `warehouse` table, release-note/receipt fields, credit-release tracking

Written off an audit against real paper documents (2x "Goods Release Note", a blank release note, a "Cash Receipt") from a Nigerian logistics company, checking the schema against every field the paper form captures that ShipX didn't yet.

```sql
CREATE TABLE warehouse (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id UUID NOT NULL REFERENCES tenant(id) ON DELETE RESTRICT,
    name VARCHAR(120) NOT NULL,
    address TEXT, city VARCHAR(100), state VARCHAR(100), phone VARCHAR(50),
    is_default BOOLEAN NOT NULL DEFAULT FALSE,
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    created_by UUID REFERENCES tenant_user(id),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (tenant_id, name)
);
CREATE UNIQUE INDEX idx_warehouse_one_default ON warehouse(tenant_id) WHERE is_default;
```

> **Superseded by migration 056:** the `UNIQUE (tenant_id, name)` above spanned
> *every* row, including soft-deactivated ones, so a removed warehouse reserved
> its name permanently. It is replaced by a partial index scoped to active rows:
> ```sql
> ALTER TABLE warehouse DROP CONSTRAINT warehouse_tenant_id_name_key;
> CREATE UNIQUE INDEX idx_warehouse_active_name
>     ON warehouse(tenant_id, name) WHERE is_active;
> ```
> See "Migration 056" below.
RLS on, standard tenant-isolation policy. Per-tenant branches (the paper letterhead lists ~9 for one company) — replaces the single `tenant_config.warehouse_address` JSON blob that gave every release note the same one address regardless of which branch actually issued it. Migration backfills exactly one default warehouse per tenant from that blob (or a bare "Main Warehouse" placeholder).

Also adds, all nullable/defaulted (purely additive — the existing suite and 58 non-test `carton_tags` call sites are unaffected):
- **`release_note`**: `warehouse_id`, `payment_record_id` (the form's "Receipt No" — NULL means "ON CREDIT"), `is_on_credit`, `credit_granted_by`/`credit_granted_by_name`, count-based release fields `packages_released`/`package_unit`/`packages_balance` (for manifest-imported shipments with no per-carton tags — `carton_tags` made nullable to support this), `physical_document_number` (pre-printed booklet serial), `packing_list_invoice_numbers TEXT[]`.
- **`pickup_record`**: `warehouse_id` + the three additional paper-form signatories — `customer_service_officer_id`, `accounting_officer_id`, `warehouse_attendant_id`.
- **`payment_record`**: `receipt_number` (unique per tenant when set), `payer_name`/`payer_address`, `bank_name`, `cheque_number`, `warehouse_id`, `physical_receipt_number`; `payment_method` allowlist gains `'cheque'`.
- **`carryover_ledger`**: `due_date` (the form's "Debt Payment Date"), `granted_by`, `release_note_id` (links a carryover back to the release note that created the debt).

**Ground-truth gaps in application code closed 2026-09-13** (the schema above already supported all of this — the bugs were in code silently dropping these columns): repository queries not joining `warehouse.phone`/`carryover_ledger.due_date`; `create_split_release_note` dropping every one of these columns on every split and reissue; no warehouse CRUD existing at all so a warehouse, once backfilled, could never be added to or promoted; tenants onboarded after this migration ran getting zero warehouse rows (the backfill only ever runs once). Full account in `13_api_payment_release.md` and `19_excel_import_export.md` (PDF export had the identical drop bug).

### Migration 056 — warehouse name uniqueness scoped to active rows

Reported from live use: *"I deleted a warehouse and tried to recreate it with the
same name. I was not able to until I changed the name."*

Migration 041's `UNIQUE (tenant_id, name)` covered all rows, but removal only set
`is_active = FALSE` — so a deleted warehouse kept its name reserved forever, and
the collision surfaced as a raw unique violation rather than an actionable
message.

```sql
ALTER TABLE warehouse DROP CONSTRAINT IF EXISTS warehouse_tenant_id_name_key;
CREATE UNIQUE INDEX IF NOT EXISTS idx_warehouse_active_name
    ON warehouse(tenant_id, name) WHERE is_active;
```

An active tenant still cannot hold two warehouses with the same name. No data
cleanup is needed first: the old global constraint already guaranteed at most one
row per `(tenant_id, name)`, so every existing row satisfies the narrower index.

**The FKs are deliberately left alone.** `release_note.warehouse_id`,
`pickup_record.warehouse_id` and `payment_record.warehouse_id` carry **no
`ON DELETE` action**, so Postgres refuses to delete a referenced warehouse — a
handover document must never lose the warehouse that released the goods.
`packing_list.arrival_warehouse_id` is `ON DELETE SET NULL` (migration 053) but is
counted as a reference too, since a list silently losing its destination is just
as wrong. `DELETE /v1/warehouses/{id}` is now a genuine delete and checks these
references first, returning 422 `WAREHOUSE_IN_USE` with the counts; the FK is the
database-level backstop, not the error an operator sees.

### Migration 057 — `country` on `warehouse`

The warehouse form asked for a **State** while the table had no country, so the
field had no anchor: a picker could not know whose subdivisions to offer, and the
value was necessarily free text.

```sql
ALTER TABLE warehouse ADD COLUMN country VARCHAR(100);
UPDATE warehouse w SET country = COALESCE(NULLIF(TRIM(t.destination_country), ''), 'Nigeria')
  FROM tenant t WHERE t.id = w.tenant_id AND w.country IS NULL;
ALTER TABLE warehouse ALTER COLUMN country SET DEFAULT 'Nigeria';
ALTER TABLE warehouse ALTER COLUMN country SET NOT NULL;
```

Added **nullable first** so the backfill decides each row's value rather than the
column default stamping `'Nigeria'` onto every existing warehouse. Existing rows
inherit their own tenant's `destination_country`, since warehouses are the
destination-side branches — a tenant already configured for another market is not
silently mislabelled. `NOT NULL DEFAULT 'Nigeria'` applies from then on.

With a country on the row, `state` became a real dropdown (Nigeria's 36 states +
FCT today; the frontend carries lists for the markets ShipX operates in and falls
back to free text elsewhere). See `frontend/03_component_library.md` →
`CountrySelect` / `StateSelect`.

### Migration 044 — `payment_claim` table

```sql
CREATE TABLE payment_claim (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id UUID NOT NULL REFERENCES tenant(id) ON DELETE RESTRICT,
    billing_id UUID NOT NULL REFERENCES billing(id) ON DELETE CASCADE,
    customer_id UUID NOT NULL REFERENCES customer(id) ON DELETE RESTRICT,
    amount_ngn NUMERIC(14, 2) NOT NULL CHECK (amount_ngn > 0),
    evidence_file_key TEXT NOT NULL,
    evidence_file_name VARCHAR(255) NOT NULL,
    customer_note TEXT,
    status VARCHAR(20) NOT NULL DEFAULT 'pending' CHECK (status IN (
        'pending', 'confirmed', 'rejected'
    )),
    rejection_reason TEXT,
    reviewed_by UUID REFERENCES tenant_user(id),
    reviewed_at TIMESTAMPTZ,
    payment_record_id UUID REFERENCES payment_record(id),
    submitted_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX idx_payment_claim_tenant_billing ON payment_claim(tenant_id, billing_id);
CREATE INDEX idx_payment_claim_tenant_status ON payment_claim(tenant_id, status);
CREATE UNIQUE INDEX idx_payment_claim_one_pending_per_billing
    ON payment_claim(billing_id) WHERE status = 'pending';
```
RLS on, standard tenant-isolation policy. The customer's "I've made this
payment" submission for a manual bank transfer — a real queue with mandatory
evidence, replacing what used to be nothing at all (a customer had no way to
tell the platform they'd paid). Full account, including why the partial
unique index needs `ON CONFLICT ... DO NOTHING` rather than a plain INSERT
(found live: the first version 500'd on a second submission instead of
returning a clean 422), in `13_api_payment_release.md`.

### Migration 046 — `staff_notification` + `staff_notification_read` tables

```sql
CREATE TABLE staff_notification (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id UUID NOT NULL REFERENCES tenant(id) ON DELETE CASCADE,
    target_role VARCHAR(30),
    target_user_id UUID REFERENCES tenant_user(id) ON DELETE CASCADE,
    event_type VARCHAR(50) NOT NULL,
    entity_type VARCHAR(30) NOT NULL,
    entity_id UUID,
    title VARCHAR(200) NOT NULL,
    body TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX idx_staff_notification_tenant_created ON staff_notification(tenant_id, created_at DESC);
CREATE INDEX idx_staff_notification_tenant_role ON staff_notification(tenant_id, target_role);
CREATE INDEX idx_staff_notification_tenant_user ON staff_notification(tenant_id, target_user_id);

CREATE TABLE staff_notification_read (
    tenant_id UUID NOT NULL REFERENCES tenant(id) ON DELETE CASCADE,
    notification_id UUID NOT NULL REFERENCES staff_notification(id) ON DELETE CASCADE,
    user_id UUID NOT NULL REFERENCES tenant_user(id) ON DELETE CASCADE,
    read_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (notification_id, user_id)
);
CREATE INDEX idx_staff_notification_read_user ON staff_notification_read(tenant_id, user_id);
```

RLS on both, standard tenant-isolation policy. Backs the TopBar bell — ground-truth gap found live, reported by the user: "a staff rejected a payment marked as paid, but no notification was showing when I logged into the staff account," followed by "let's go through the whole notification including the frontend notification to resolve all." The bell icon and unread badge were fully built in the frontend but never fed any data at all — no backing table, no API.

One row per event (broadcast to a role via `target_role`, targeted at one person via `target_user_id`, or everyone in the tenant when both are `NULL`); read state is tracked per-viewer in the separate `staff_notification_read` table so a role-broadcast notification can be independently marked read by each recipient without affecting what any other recipient sees. `entity_id` is a single-row UUID column — bulk actions (e.g. bulk packing-list submit) pass `None`, not a comma-joined id list, which would silently fail the UUID cast (the same latent bug `log_audit`'s own `BULK_APPROVE` call already has for its `entity_id`).

Full API and trigger-site account in `15_api_notifications.md`'s "Staff notification bell" section.

**Extended to customers (2026-09-12), no schema change needed:** the same two tables also back the customer portal's bell, via `target_user_id` (never `target_role`, since a customer notification is always 1:1) pointing at `customer.user_id` when the customer has a portal account. Full account in `15_api_notifications.md`'s "Customer notification bell + local-dev delivery plumbing" section.

### Migration 047 — `staff_notification_read.dismissed_at`

```sql
ALTER TABLE staff_notification_read ADD COLUMN dismissed_at TIMESTAMPTZ;
```

Backs per-viewer "clear notification" / "clear all" — direct user follow-up: "the notification should allow clearing." Lives on the existing per-viewer read-state row rather than the shared `staff_notification` row, so clearing a role-broadcast notification for one recipient never removes it from any other recipient's list. Clearing always sets both `dismissed_at` and `read_at` together; `list_staff_notifications` excludes `dismissed_at IS NOT NULL` rows from its query entirely (both audiences — staff and customer share this table). Full account in `15_api_notifications.md`'s "Clearing notifications + manual announcements" section, which also covers the new `POST /v1/notifications/announce` route (no schema change of its own — announcements are plain `staff_notification` rows with `event_type="announcement"`).

### Migration 048 — `announcement_request` table

```sql
CREATE TABLE announcement_request (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id UUID NOT NULL REFERENCES tenant(id) ON DELETE CASCADE,
    title VARCHAR(200) NOT NULL,
    body TEXT,
    audience VARCHAR(20) NOT NULL,
    status VARCHAR(20) NOT NULL DEFAULT 'pending',
    requested_by UUID NOT NULL REFERENCES tenant_user(id),
    reviewed_by UUID REFERENCES tenant_user(id),
    reviewed_at TIMESTAMPTZ,
    rejection_reason VARCHAR(500),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX idx_announcement_request_tenant_status ON announcement_request(tenant_id, status, created_at DESC);
```

RLS on, standard tenant-isolation policy. Direct user follow-up: "Tenant admin can send announcement to all staffs and all customers. But the staff can only send to customers, which should be approved by the tenant admins, this is to ensure that a compromised staff does not misinformation the customers." A `nigeria_office_staff` → `all_customers` announcement is held here as `pending` rather than written straight to `staff_notification` — approving it (tenant_admin only) is what actually creates the notification rows; rejecting it never does. `tenant_admin` sends (either audience) bypass this table entirely and go out immediately, as before. `status = 'pending'` doubles as the concurrency guard on approve/reject — see `repository.mark_announcement_request_reviewed()`. Full account in `15_api_notifications.md`'s "staff customer-announcements now require tenant_admin approval" section.

No further schema change was needed when this feature grew a dedicated Announcements page with full CRUD (edit/delete a request or a sent announcement, list a staff member's own submissions) — every new operation reads/writes columns that already existed here and on `staff_notification`, just through new repository functions layered on the same ownership (`requested_by`) and status (`'pending'`) guards. See `15_api_notifications.md`'s "Announcements page + full CRUD + Publish/Unpublish" section.

### Migration 049 — `staff_notification.announcement_group_id` + `banner_active`

```sql
ALTER TABLE staff_notification ADD COLUMN announcement_group_id UUID;
ALTER TABLE staff_notification ADD COLUMN banner_active BOOLEAN NOT NULL DEFAULT FALSE;
CREATE INDEX idx_staff_notification_banner_active ON staff_notification(tenant_id, target_role) WHERE banner_active = TRUE;
CREATE INDEX idx_staff_notification_announcement_group ON staff_notification(tenant_id, announcement_group_id);
```

Both columns are meaningful only for `entity_type = 'announcement'` rows. Direct user follow-up: "annoucement should be a banner on the target user's web page... It can be enabled or disabled, more can be created but only one can be visible per time." `announcement_group_id` ties an `all_staff` send's 4 fanned-out rows (one per staff role) back together so enabling/disabling/listing treats them as one announcement. `banner_active` is set true on insert (after first deactivating whatever was previously active for the same audience — staff and customer banners are independent, so this dedup never crosses between them) and can be flipped directly by a tenant_admin via `PATCH /v1/notifications/announcements/{group_id}/activate|deactivate`. Full account in `15_api_notifications.md`'s "announcement banner" section.

### Migration 050 — `billing.cbm_rate_currency` + `cbm_rate_mode` + `cbm_breakdown`

```sql
ALTER TABLE billing ADD COLUMN cbm_rate_currency VARCHAR(3) NOT NULL DEFAULT 'USD';
ALTER TABLE billing ADD COLUMN cbm_rate_mode VARCHAR(20) NOT NULL DEFAULT 'flat';
ALTER TABLE billing ADD COLUMN cbm_breakdown JSONB;
```

User: "For CMB rate, let's allow the tenant admin to have multiple options for the rate: 1. One Single rate with options of either Naira or Dollar. 2. Rates targeted to Bags, Cartons and Bales." The pre-existing `cbm_rate_usd` column stays as the single USD-equivalent rate other code (CBM dispute resolution, exports, staff/customer UI) already treats as ground truth (`total_cbm × cbm_rate_usd == subtotal_usd`); the three new columns record how it was actually derived: `cbm_rate_currency` ('USD'/'NGN', the tenant's configured currency at billing time — `cbm_rate_usd` is back-derived via the effective dollar rate when NGN), `cbm_rate_mode` ('flat'/'per_package_type', purely descriptive — billing computation never branches on it, since "flat" is just the case where the tenant's carton/bag/bale rates are all equal), and `cbm_breakdown` (JSONB, always populated, `{"carton": {"cbm", "rate", "subtotal"}, "bag": {...}, "bale": {...}}` in the tenant's configured currency — becomes historical record only, not reconciled, if a later CBM dispute adjusts `total_cbm`). No backfill needed for existing rows: `NOT NULL DEFAULT 'USD'`/`'flat'` exactly matches every pre-2026-09-20 invoice's actual (implicit) pricing basis, and `cbm_breakdown` stays `NULL` for them (never displayed — the frontend only renders it when `cbm_rate_mode = 'per_package_type'`). See `07_api_tenant_management.md`'s CBM Rate section and `11_api_billing.md`'s Billing Calculation section for the full design.

### Migration 038 — Widen `billing.status` to `VARCHAR(30)`

**Ground-truth gap:** `billing.status` was `VARCHAR(20)` since migration 002. Migration 006 added `'released_with_outstanding'` (26 chars) to the CHECK constraint without ever widening the column — so every write attempting that status, including the real `POST /v1/release-notes` "release with outstanding balance" code path (`payment_release/repository.py::mark_billing_released_with_outstanding()`), has always failed with `StringDataRightTruncation`. Discovered while running `scripts/seed_stress.py` (§14.1.1 of `LOCAL_TESTING.md`), which seeds every billing status to exercise the list views at volume.

```sql
ALTER TABLE billing ALTER COLUMN status TYPE VARCHAR(30);
```

No CHECK constraint change — all existing allowed values already fit within 30 chars.

### Migration 012 — GDPR Compliance Fields
```sql
-- customer table
ALTER TABLE customer ADD COLUMN anonymised_at TIMESTAMPTZ;
ALTER TABLE customer ADD COLUMN consent_given_at TIMESTAMPTZ;
ALTER TABLE customer ADD COLUMN notification_consent TEXT[] DEFAULT '{}';

-- tenant_user table
ALTER TABLE tenant_user ADD COLUMN consent_given_at TIMESTAMPTZ;
ALTER TABLE tenant_user ADD COLUMN marketing_consent BOOLEAN DEFAULT FALSE;
```

### Migration 013 — Field Encryption (Documentation)
No schema change. Records that the following columns are encrypted at rest using KMS + Fernet envelope encryption:
- `pickup_record.id_number` — passport / national ID at cargo collection
- `refund_request.account_number` — bank account for payout
- `refund_request.account_name`

Encryption scheme: KMS `GenerateDataKey` (AES-256) → Fernet encrypt → base64-encode(encrypted_key + ciphertext). No plaintext key material is stored in the database.

### Migration 014 — Drop `tenant_config.updated_by` FK
The `tenant_config.updated_by` column stores a Cognito sub UUID. Since Cognito subs are not stored in `tenant_user`, the FK constraint caused violations on every config update. The FK was dropped in migration 014 — the column is retained for auditing purposes.

### Migration 015 — `tenant.reactivated_at`

Added when re-onboarding support was implemented (`PATCH /v1/platform/tenants/{id}/reactivate`). Records the timestamp of re-activation. `deletion_scheduled_at` is cleared on reactivation.

```sql
ALTER TABLE tenant ADD COLUMN IF NOT EXISTS reactivated_at TIMESTAMPTZ;
```

GDPR note: `reactivated_at` provides an unambiguous audit boundary — data processed after this timestamp operates under the new subscription agreement.

### Migration 024 — `notification_template` Table

Tenant-customisable message copy per event type and channel. Falls back to hardcoded defaults in `services/notification/service.py` when no row exists.

```sql
CREATE TABLE notification_template (
    id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id     UUID NOT NULL REFERENCES tenant(id) ON DELETE CASCADE,
    event_type    VARCHAR(100) NOT NULL,
    channel       VARCHAR(20)  NOT NULL CHECK (channel IN ('sms', 'email', 'whatsapp')),
    template_body TEXT NOT NULL,
    subject       VARCHAR(500),   -- used for email channel only
    updated_by    VARCHAR(255),
    created_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (tenant_id, event_type, channel)
);
CREATE INDEX idx_notif_template_tenant ON notification_template(tenant_id);
```

RLS-enabled. Policy: `tenant_id::text = current_setting('app.tenant_id', TRUE)`.

For WhatsApp, `template_body` stores the pre-approved Meta template name. For SMS it is the message body text. For email, `template_body` is HTML and `subject` holds the email subject line.

### Migration 025 — `rate_history` Table

Append-only audit trail of dollar rate and CBM rate changes per tenant.

```sql
CREATE TABLE rate_history (
    id             UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id      UUID NOT NULL REFERENCES tenant(id) ON DELETE CASCADE,
    rate_type      VARCHAR(50)  NOT NULL,
    rate_value     JSONB        NOT NULL,
    previous_value JSONB,
    changed_by     VARCHAR(255),
    effective_from TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    created_at     TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX idx_rate_history_tenant_created ON rate_history(tenant_id, created_at DESC);
```

RLS-enabled. Policy: `tenant_id::text = current_setting('app.tenant_id', TRUE)`.

Records are inserted by `services/tenant_management/service.update_dollar_rate()` (best-effort — failures are logged but do not abort the rate update). Queried via `GET /v1/tenant/rate-history`.

**`rate_type='dollar_rate'` entries changed shape (2026-09-19):** since the base rate now comes from Bybit (not something an admin types in), what gets recorded is a **markup change**, not a raw rate — `rate_value`/`previous_value` are `{ "rate": <effective rate at the moment of the change>, "base_rate", "markup_type", "markup_value" }` (all plain `float`, never `Decimal` — `append_rate_history`'s `json.dumps()` has no `default=str` and raises on one, a real bug caught live the first time this feature's `PUT` was exercised end-to-end). `rate_value.rate` is still a single comparable number across every entry regardless of provenance, so `RateHistoryTable`/`RateTrendChart` on the frontend needed **no changes** — they've always just read `rate_value.rate` as a plain number.

### Migration 062 — `tenant_counter` and one live invoice per customer per container

```sql
CREATE TABLE tenant_counter (
    tenant_id  UUID NOT NULL REFERENCES tenant(id) ON DELETE CASCADE,
    name       VARCHAR(50) NOT NULL,          -- 'invoice' | 'receipt' | 'release_note'
    last_value BIGINT NOT NULL DEFAULT 0 CHECK (last_value >= 0),
    PRIMARY KEY (tenant_id, name)
);
CREATE UNIQUE INDEX idx_billing_one_live_per_customer_container
    ON billing (tenant_id, customer_id, container_id) WHERE status <> 'cancelled';
```

`tenant_counter` is RLS-enabled with the canonical predicate (migration 059) and `FORCE ROW LEVEL SECURITY`. It replaces
`SELECT COUNT(*) + 1` numbering, which handed the same number to two requests running at once. Seeded from the larger of
the row count and the highest trailing number already issued, so numbering continues unchanged.

The partial unique index makes a second live invoice for the same customer and container impossible, so invoice
generation is idempotent. Cancelled invoices are excluded: cancel-and-reissue stays possible. If duplicate live invoices
already exist the migration stops and lists them (see `docs/runbook.md`) — it never merges or cancels money records.

Invoice and receipt numbers now use the counter (receipts inside the atomic payment write). Release-note numbers still use
`COUNT(*) + 1`; the `release_note` counter is seeded for that follow-up (their unique index makes a collision loud, not silent).

### Migration 063 — storage-fee waivers and compensation refund types

```sql
ALTER TABLE storage_fee_log ADD COLUMN waived_at TIMESTAMPTZ, ADD COLUMN waive_reason TEXT;
CREATE INDEX idx_storage_fee_log_billing_unwaived ON storage_fee_log (billing_id) WHERE waived_at IS NULL;
ALTER TABLE refund_request DROP CONSTRAINT refund_request_refund_type_check;
ALTER TABLE refund_request ADD CONSTRAINT refund_request_refund_type_check
  CHECK (refund_type IN ('overpayment','cbm_correction','damage_or_loss','missing_item','seized_item'));
```

`waived_at` marks a fee as waived (the log row is kept as history); an invoice's storage fees are the un-waived rows.
`is_billed` stays as it was (default false, set by nothing). The widened CHECK is what lets seized/missing-item
compensation create its refund request. Downgrade fails if rows already use the two new types.

### Migration 016 — `cbm_dispute.status` — add `'rejected'`

The `reject_dispute()` service function sets `status = 'rejected'`, but migration 006's CHECK constraint omitted this value. Migration 016 drops and recreates the constraint with the full set of valid statuses.

```sql
ALTER TABLE cbm_dispute DROP CONSTRAINT cbm_dispute_status_check;
ALTER TABLE cbm_dispute ADD CONSTRAINT cbm_dispute_status_check
    CHECK (status IN (
        'submitted', 'acknowledged', 'investigating',
        'escalated_china', 'resolved_adjusted', 'resolved_no_change',
        'rejected', 'closed'
    ));
```

### Migration 051 — Container capacity presets

Adds a `container_capacity` table for tenant **custom** capacity presets (the ten well-known capacities are code constants in `services/tenant_management/service.py::DEFAULT_CONTAINER_CAPACITIES`, merged in on read — no per-tenant seed, no backfill), and snapshots the chosen capacity onto `container`. The display name stays in the existing `container.container_type` column (migration 030); `capacity_cbm`/`recommended_cbm` are denormalised so the utilization bar survives later edits/deletion of the preset. RLS on `container_capacity` matches the standard `current_setting('app.current_tenant_id')` policy.

```sql
CREATE TABLE container_capacity (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id       UUID NOT NULL REFERENCES tenant(id) ON DELETE CASCADE,
    name            VARCHAR(100) NOT NULL,
    capacity_cbm    NUMERIC(8,2) NOT NULL CHECK (capacity_cbm > 0),
    recommended_cbm NUMERIC(8,2) CHECK (recommended_cbm IS NULL OR recommended_cbm > 0),
    created_by      UUID,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (tenant_id, name)
);
ALTER TABLE container
    ADD COLUMN capacity_cbm    NUMERIC(8,2),
    ADD COLUMN recommended_cbm NUMERIC(8,2);
```

### Migration 052 — Packing-list loading/delivery dates

Shipment-level dates captured in the create/edit packing-list wizard (per packing list, not per item — every item in a list loads/delivers together). Both nullable/optional.

```sql
ALTER TABLE packing_list
    ADD COLUMN loading_date  DATE,
    ADD COLUMN delivery_date DATE;
```

> **Semantics clarified 2026-11-03 (no schema change).** This migration and the
> original UI described `delivery_date` as the *expected customer delivery* —
> a destination-side, future estimate. That was wrong for how the field is used:
> it is the date the **supplier delivered the goods to the China warehouse**,
> i.e. when the cargo was received. Both dates are origin-side events, in order:
>
> | Column | Event | Rule |
> |---|---|---|
> | `delivery_date` | goods received at the China warehouse | cannot be in the future |
> | `loading_date` | goods loaded into the container | `>= delivery_date` (same day allowed) |
>
> Enforced on `CreatePackingListRequest` **and** `UpdatePackingListRequest` via a
> shared validator, so a PATCH cannot write an ordering the create path refuses.
> `loading_date` is deliberately unbounded above — a packing list is written
> against a container still in `loading` status, so a planned load date is
> legitimate. Both columns stay nullable.
>
> Destination delivery estimation already lives on `container.estimated_delivery_date`
> (migration 002), so nothing is lost by this field not meaning that.

The item-entry enhancements (package type, bale sizing, minimum-CBM floor) reuse existing `packing_list_item` columns — `package_unit` and `bale_type` (migration 040) and `cbm` — so they need no migration. `bale_type` is now computed for bale items (`BIG BALE` ≥ 0.3 CBM, else `SMALL BALE`), and `cbm` is floored at the tenant's `min_cbm_per_item` (a `tenant_config` key, default 0.1 — no schema).

### Migration 053 — Packing-list arrival warehouse

Records the destination warehouse (from the migration-041 `warehouse` table) a packing list's goods are bound for. Nullable — existing lists keep NULL. `ON DELETE SET NULL` is belt-and-braces; warehouses are soft-deactivated (`is_active = FALSE`), never hard-deleted, so the FK target normally survives and the name still resolves.

```sql
ALTER TABLE packing_list
    ADD COLUMN arrival_warehouse_id UUID REFERENCES warehouse(id) ON DELETE SET NULL;
CREATE INDEX idx_packing_list_arrival_warehouse ON packing_list(arrival_warehouse_id);
```

Resolution is server-side (`services/packing_list/service.py::_resolve_arrival_warehouse`): an explicit id is tenant-validated; when omitted it defaults to the tenant's `is_default` warehouse. Warehouse CRUD lives on `/v1/warehouses` (payment_release) — see `13_api_payment_release.md`.

### Migration 054 — `tenant_onboarding_request` Table

Platform-scoped lead table (no tenant RLS, like `platform_settings`/`impersonation_session`) backing the shipping-company onboarding queue — see `07_api_tenant_management.md`. A row is a *lead*, not a tenant: it exists before any account, and is linked to the provisioned tenant (and flipped to `provisioned`) only when a platform admin creates the tenant with `onboarding_request_id`.

```sql
CREATE TABLE tenant_onboarding_request (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    company_name        VARCHAR(200) NOT NULL,
    contact_name        VARCHAR(200) NOT NULL,
    contact_email       VARCHAR(320) NOT NULL,
    contact_phone       VARCHAR(40),
    origin_country      VARCHAR(100) NOT NULL DEFAULT 'China',
    destination_country VARCHAR(100) NOT NULL DEFAULT 'Nigeria',
    monthly_volume      VARCHAR(100),
    notes               TEXT,
    status              VARCHAR(20) NOT NULL DEFAULT 'new'
                        CHECK (status IN ('new','contacted','approved','rejected','provisioned')),
    rejection_reason    TEXT,
    reviewed_by         UUID,
    reviewed_at         TIMESTAMPTZ,
    tenant_id           UUID REFERENCES tenant(id) ON DELETE SET NULL,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX idx_onboarding_request_status ON tenant_onboarding_request(status, created_at DESC);
CREATE INDEX idx_onboarding_request_email ON tenant_onboarding_request(lower(contact_email));
```

`reviewed_by` is a bare UUID (platform admins have no `tenant_user` row — same reasoning as migration 014/037, so no FK). `tenant_id` is `ON DELETE SET NULL` so offboarding a tenant doesn't delete its originating lead.

## Acceptance Criteria

- [x] All 14 tables created with correct schemas
- [x] TEXT[] array types used for carton_tags fields
- [x] CHECK constraints for all status/enum fields match the spec exactly
- [x] UNIQUE constraints: (tenant_id, reference_number) on release_note, (tenant_id, name) on charge_type
- [x] All foreign keys and indexes created
- [x] Migrations are sequentially numbered and run after 001/002
- [x] GDPR fields added to customer and tenant_user (migration 012)
- [x] platform_settings table created (migration 011)
- [x] Field encryption documented (migration 013)
- [x] tenant_config FK issue resolved (migration 014)
- [x] tenant.reactivated_at added for re-onboarding (migration 015)
- [x] tenant_onboarding_request table created (migration 054, platform-scoped, no RLS) — shipping-company onboarding leads; status new/contacted/approved/rejected/provisioned; nullable tenant_id FK (ON DELETE SET NULL); indexes on (status, created_at DESC) and lower(contact_email)
- [x] cbm_dispute.status CHECK includes 'rejected' (migration 016)
- [x] notification_template table created with RLS (migration 024) — per-tenant custom message copy for SMS, WhatsApp, and email
- [x] rate_history table created with RLS (migration 025) — append-only audit trail of rate changes
- [x] notification_log table created with RLS (migration 027) — persists every outbound notification; columns: id, tenant_id, event_type, channel (sms|email|whatsapp), recipient_masked, recipient_name, customer_id, status (queued|sent|delivered|read|failed|**suppressed** — added by migration 064), provider, provider_message_id, gateway_response JSONB, error_detail, retry_of (self-FK), template_data JSONB, created_at, updated_at; indexes on (tenant_id, created_at), status, channel, customer_id, provider_message_id
- [x] `notification_log.locale` VARCHAR(5) added (migration 043). `get_log_for_fallback` had always selected this column so a fallback SMS renders in the recipient's language, but it was never created — every WhatsApp→SMS fallback raised `UndefinedColumn` and no SMS was ever queued. Nullable: rows written before the migration have no recorded locale and `trigger_sms_fallback` coalesces to `en`.
- [x] impersonation_session table created (migration 028, platform-scoped, no RLS) — platform admin support sessions; columns: id, platform_admin_id, target_tenant_id FK, target_user_id, target_role, read_only, started_at, expires_at, ended_at, end_reason; indexes for active session lookup and by admin/tenant
- [x] customer.locale added (migration 029, `VARCHAR(10) NOT NULL DEFAULT 'en'`) — BCP-47 locale forwarded by scheduled jobs (storage_reminders, release_expiry) to `enqueue_notification` so notification Lambdas select the correct template language

- [x] Migration 064 (2026-11-15): `notification_log_status_check` now also allows `suppressed`, recording a message held back by the customer's notification preferences (`shared/notification_consent.py`), with the reason in `error_detail`. The downgrade refuses while any `suppressed` row exists rather than rewrite history. No other schema change in audit Phase 2: `customer.consent_given_at` already existed and now also means "preferences recorded".

## Migration 065 — release note pickup code (2026-11-16)

`release_note` gains `pickup_code_hash VARCHAR(64)` (HMAC-SHA256 hex of the code, keyed by `PICKUP_CODE_PEPPER` and bound to the note id; NULL means the note needs no code), `pickup_code_issued_at TIMESTAMPTZ`, and `pickup_code_failed_attempts INTEGER NOT NULL DEFAULT 0 CHECK (>= 0)`. The plaintext code is never stored. No RLS change (the table's policy covers the new columns). Downgrade drops the three columns. See ADR-008.

## Migration 066 — invoice total floor and partial credits (2026-11-17, audit BE-07)

- `refund_request.credit_applied_ngn DECIMAL(15,2) NOT NULL DEFAULT 0`, `CHECK (>= 0)`: how much of a credit (a refund approved as `credit_next_shipment`) invoices have used. The credit stays `applied_as_credit` until this reaches `COALESCE(amount_approved_ngn, amount_ngn)`, then `processed`. Backfill: credits already `processed` were spent whole under the old rule and are set to their full value.
- `billing.credits_applied_ngn DECIMAL(15,2) NOT NULL DEFAULT 0`, `CHECK (>= 0)`: the credit the invoice absorbed when issued. 0 for invoices issued before this migration (not recorded then).
- `billing` gets `ck_billing_total_not_negative CHECK (total_ngn >= 0)`. It is added `NOT VALID` (enforced at once for new and changed rows) and validated in the same migration **only if no existing invoice has a negative total**. If some do, the migration succeeds, logs how many, and leaves the constraint unvalidated: see `docs/runbook.md`, "Invoices with a negative total".
- The migration reads and backfills as `PLATFORM` (`app.current_tenant_id`), because both tables force row-level security, and restores the setting afterwards.
- No RLS change: no new table. Applied to the local dev database on 2026-11-17; the constraint validated (no negative invoices there).

## Migration 067 — `tenant_offboarding_export` (2026-11-17, audit BE-10)

One row per tenant data export. Columns: `id`, `tenant_id` (FK `tenant` ON DELETE CASCADE), `status` (`pending|running|completed|failed|cancelled`), `requested_by` (platform admin's id; VARCHAR, no FK: platform admins are not `tenant_user` rows), `requested_at`, `started_at`, `completed_at`, `attempts` (≥ 0), `object_key`, `size_bytes` (≥ 0), `sha256`, `row_counts` JSONB, `last_error` (exception type name only), `updated_at`. CHECK: a completed row has `object_key` and `completed_at`. Indexes: open work by `requested_at` (partial), `(tenant_id, requested_at DESC)`, and a partial UNIQUE on `tenant_id` WHERE status is pending or running (one export in flight per tenant; `queue_export` relies on it with `ON CONFLICT … DO NOTHING`). RLS: canonical predicate, ENABLE + FORCE (`05c`). Applied to the local dev database on 2026-11-17.

## Migration 068 — where an invoice's exchange rate came from (2026-11-17, audit BE-11)

- `billing.exchange_rate_source VARCHAR(20)`, `CHECK (IN ('live', 'last_known', 'hardcoded'))`: where `exchange_rate_ngn` came from (`shared.fx_rate.RATE_SOURCE_*`). Invoicing refuses `hardcoded`, so new rows carry `live` or `last_known`.
- `billing.exchange_rate_fetched_at TIMESTAMPTZ`: when that market rate was fetched.
- Both NULL for invoices issued before the migration (nothing recorded it). No backfill, no RLS change. Applied to the local dev database on 2026-11-17 (4 existing invoices, all NULL).

## Migration 069 — upload confirmation (2026-11-19)

- `confirmed_at TIMESTAMPTZ` on `claim_evidence`, `manifest_evidence` and `container_document`: when the client confirmed the upload and its stored size was checked. NULL means presigned but not confirmed; such a row is never listed or downloadable. Existing rows backfilled to `created_at`.
- `container_document.file_size_bytes INTEGER` (the other two already had it), set at confirmation.
- No RLS change: `container_document` keeps its tenant policy; the two evidence tables stay without RLS, scoped through their parent. Applied to the local dev database on 2026-11-19.
