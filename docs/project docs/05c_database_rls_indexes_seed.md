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

- [x] RLS enabled on all tenant-scoped tables (25 as of migration 041: +container_document migration 022, +notification_template migration 024, +rate_history migration 025, +warehouse migration 041)
- [x] Both SELECT and INSERT policies created
- [x] `FORCE ROW LEVEL SECURITY` applied so RLS works for table owner too — **true only of migration 005's 21 core tables until migration 058**; the four later tables were `ENABLE`-only, see the audit below
- [x] Application role `logistics_app` created with appropriate grants — **created, but nothing connects as it**; the application connects as the database owner, see the audit below
- [x] Seed data creates 2 tenants with realistic data
- [x] Seed data uses correct billing status values (`unpaid`, `partially_paid`, `paid` — not `draft`/`sent`)
- [x] Seed data includes data in various states (draft packing lists, approved ones, paid/unpaid billing)
- [x] Cross-tenant query test: connecting as a non-owner role with Tenant A's ID returns zero Tenant B rows — **added 2026-11-03** (`tests/tenant_isolation/test_rls_enforcement.py`); this box was previously ticked with no such test in the repo
- [x] `onboard_tenant.py` creates all required records


---

## RLS audit, 2026-11-03 — what was actually enforced

Prompted by noticing that four policies referenced a session variable nothing
sets. The audit found **three** separate defects, two of which were hiding each
other.

### 1. Four policies could never match a row

`container_document` (022), `notification_template` (024), `rate_history` (025)
and `warehouse` (041) were each written as:

```sql
USING (tenant_id::text = current_setting('app.tenant_id', TRUE))
```

`shared/db.py::_set_tenant` sets **`app.current_tenant_id`**. So
`current_setting('app.tenant_id', TRUE)` returns NULL, `tenant_id::text = NULL`
evaluates to NULL, and NULL is not TRUE — the policy denies every row.

### 2. …and none of the four was `FORCE`d, which hid defect 1

Migration 005 runs `FORCE ROW LEVEL SECURITY` on its 21 tables. The four later
migrations ran only `ENABLE`. Postgres exempts a table's **owner** from
non-forced RLS, and the application connects as the owner — so the broken
policies were simply never evaluated.

**The two defects masked each other**, which is why this survived four
migrations and a ticked acceptance criterion. Correcting only the setting name
would have changed nothing observable; adding only `FORCE` would have taken
those four tables offline (zero rows). Migration **058** fixes both together.

### 3. The `PLATFORM` sentinel is incompatible with the core policies

`_set_tenant` sets the literal string `'PLATFORM'`
(`shared/tenant_context.PLATFORM_TENANT_ID`) for deliberate cross-tenant reads —
public shipment tracking, `find_user_across_tenants`, activation lookups,
`resolve_identity_from_db`. Migration 005's policies read:

```sql
USING (tenant_id = current_setting('app.current_tenant_id')::uuid)
```

`'PLATFORM'::uuid` **raises** (`invalid input syntax for type uuid`) rather than
returning false. So those policies cannot coexist with the PLATFORM access
pattern as written.

Migration 058's replacements compare `tenant_id::text` against the raw setting
with an explicit PLATFORM branch, and `current_setting(..., TRUE)` so an
unscoped connection is denied rather than erroring.

### What this means for the four-layer model

> **Layer 3 is not currently providing isolation in the deployed environments,
> and migration 058 does not by itself change that.**

The evidence is defect 3 above: `resolve_identity_from_db` reads `tenant_user` —
one of migration 005's **FORCE'd** tables — under PLATFORM scope, and succeeds
in dev. Under enforced RLS that query would have raised on `'PLATFORM'::uuid`.
It does not, so the connecting role is bypassing RLS: on Azure Flexible Server
the provisioned administrator both owns the tables and carries elevated
attributes.

Tenant isolation today therefore rests on **layer 2** — every repository
function passing `tenant_id` — which is real but is a single layer, not the
documented defence in depth.

### Migration 059 — every prerequisite except the credential

Auditing beyond the four tables showed the problem was not confined to them.
**No table in the schema had a policy compatible with how the application
connects.** Three incompatible styles had accumulated:

| Migrations | Predicate | Under enforced RLS |
|---|---|---|
| 005 (21 core), 027, 039 | `tenant_id = current_setting(...)::uuid` | **raises** — `'PLATFORM'::uuid` is invalid |
| 022, 024, 025, 041 | `current_setting('app.tenant_id', TRUE)` | denies every row (fixed in 058) |
| 042, 044, 046, 048, 051, 055 | correct name, no PLATFORM branch | denies every platform-scoped read |

Migration **059** normalises all of them onto one canonical predicate and sets
`FORCE` on each:

```sql
current_setting('app.current_tenant_id', TRUE) = 'PLATFORM'
OR tenant_id::text = current_setting('app.current_tenant_id', TRUE)
```

It is **catalog-driven** — every `public` table with RLS enabled *and* a
`tenant_id` column — rather than a hardcoded list, because a hardcoded list is
precisely how four tables drifted onto a broken predicate. Tables with no
`tenant_id` (`tenant`, `platform_settings`, `platform_audit_log`,
`tenant_onboarding_request`) are platform-scoped by design and left alone. The
migration raises if it matches zero tables, so it cannot report success after
silently doing nothing.

059 also closes two things that would have broken the switchover:

- **Stale grants.** 005's `GRANT ... ON ALL TABLES IN SCHEMA public` applied only
  to tables existing at that moment. Every table from 022 onward had **no grant**,
  so switching the app onto `logistics_app` would have failed with "permission
  denied" on whichever newer table it touched first. 059 re-grants and adds
  `ALTER DEFAULT PRIVILEGES`, so tables created by future migrations are covered
  without anyone remembering.
- **A login role with a committed password.** 005 created `logistics_app` with the
  literal `'CHANGE_ME_IN_SECRETS_MANAGER'` and nothing ever connected as it. 059
  strips `LOGIN`. Granting it back with a real credential belongs to the
  switchover, not to version control.

None of this changes observable behaviour while the application still connects on
a role that bypasses RLS. It makes enforcement *possible*.

### What is left: the switchover

One step remains, and it is a credentials/rollout change rather than a schema one:

1. Provision a real password for `logistics_app` (Key Vault / Secrets Manager),
   `ALTER ROLE logistics_app LOGIN`, and point `DATABASE_USER` at it via
   Terraform. **Migrations keep running as the owner** — they create tables and
   must not be subject to RLS.
2. Confirm the role has neither `SUPERUSER` nor `BYPASSRLS`.
   `tests/tenant_isolation/test_rls_enforcement.py` asserts exactly that of its
   own probe role, so the pattern is established.

Do **not** reorder these before 059 is applied: switching the role first makes
every platform-scoped read raise, which takes out public tracking, activation and
sign-in simultaneously.

**Verification already in place.** The RLS test suite is catalog-driven too: it
asserts every tenant-scoped table is `FORCE`d, that no policy casts to `::uuid`
or references `app.tenant_id`, that each carries a PLATFORM branch, and — as an
unprivileged probe role — that a tenant sees only its own rows, that PLATFORM
scope still crosses tenants, that an unscoped connection sees nothing, and that
`WITH CHECK` blocks a cross-tenant write. A future migration adding a table with
a non-canonical policy fails CI.
