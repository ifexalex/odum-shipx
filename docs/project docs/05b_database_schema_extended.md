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

2. **`platform_audit_log`** — Cross-tenant admin actions (NOT tenant-scoped)
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

Also: `carryover_ledger` gains `exempted` status, `exempted_by UUID`, `exempted_at TIMESTAMPTZ`. `misc_charge.charge_type` CHECK constraint dropped (allows free-form types). `misc_charge.amount_usd` added.

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
- [x] cbm_dispute.status CHECK includes 'rejected' (migration 016)
