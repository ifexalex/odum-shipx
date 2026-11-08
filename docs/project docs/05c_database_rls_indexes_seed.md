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
- [x] Application role `logistics_app` created with appropriate grants — and **the application connects as it** since migration 060 (2026-11-08); see the switchover section below
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

### ~~What is left: the switchover~~ Done — migration 060, 2026-11-08

Both halves are in place:

1. **The credential** — migration `060_app_role_login.py` runs
   `ALTER ROLE logistics_app LOGIN PASSWORD …` from `APP_DB_PASSWORD`, and
   asserts `NOBYPASSRLS` while it is there. The password is bound as a
   parameter into a transaction-local `SET` and quoted inside the DO block with
   `format('%L', …)`, so it is never interpolated into SQL by Python.
   **Unset is not an error**: the migration logs a notice and leaves the role
   NOLOGIN, so an environment whose secret is not provisioned still migrates
   rather than blocking its own deploy.
2. **The cutover** — `DATABASE_USER` now points at `logistics_app` for the
   service Lambdas, with its own Secrets Manager secret
   (`aurora.db_app_secret_arn`) and a second `auth` block on the RDS Proxy.
   Without that second auth block the proxy rejects the user outright, and the
   failure looks like a bad password rather than a missing entry.

**Migrations keep running as the owner**, by design rather than omission: DDL
cannot be run by a role holding only DML. The migrate Lambda therefore stays on
`postgres` and additionally reads the app secret, because 060 is what sets the
app role's password. Locally and in CI the same split is expressed as
`DATABASE_ADMIN_USER` / `DATABASE_ADMIN_PASSWORD`, resolved by
`shared/db_credentials.py` with a fallback to `DATABASE_*` so an environment
that has not been cut over behaves exactly as before.

#### What this actually changed, stated precisely

Measured on the local stack before and after:

| connection | rows visible in `billing` | distinct tenants |
|---|---|---|
| `postgres`, scoped to tenant 1 | 4 | **2 — leaked** |
| `logistics_app`, scoped to tenant 1 | 3 | 1 |
| `logistics_app`, scoped to tenant 2 | 1 | 1 |
| `logistics_app`, no tenant set | 0 | — (fails closed) |
| `logistics_app`, `PLATFORM` | 4 | 2 (deliberate, still works) |

**The leak was local, not production.** `FORCE ROW LEVEL SECURITY` makes the
table *owner* subject to its policies; only `BYPASSRLS` defeats them. The local
Docker superuser has `BYPASSRLS`, so RLS was inert there and in CI. A managed
RDS master user does not get `BYPASSRLS`, so with 059's `FORCE` applied the
predicate should already have been engaging in AWS — that part is **documented
RDS behaviour, not verified against the live cluster**, so treat it as the
likely rather than the confirmed prior state.

What the switchover buys, then, is less "turning isolation on in production" and
more:

- **Local and CI now match production**, so layer 3 is finally exercisable at
  all — CI runs the isolation suite as the real app credential.
- **Least privilege that does not depend on a coincidence.** The app can no
  longer run DDL (asserted by a test), cannot read the master secret (IAM), and
  does not rely on "the master user happens not to have BYPASSRLS".

#### Not done: Azure — and Azure is the cloud that actually deploys

`infrastructure/azure` still points the container app at
`module.postgres.administrator_login`. Azure has its own `migrate` Container App
Job, so the same owner/app split applies cleanly.

**Read the scope of the AWS work above with this in mind.** `vars.DEPLOY_CLOUD`
is `azure`, and every AWS deploy job is gated on `DEPLOY_CLOUD != 'azure'` (AWS
also deploys only on a version tag). So the AWS switchover is **staged in `main`
but not applied**, and the environment that is actually running still connects as
its admin login. The AWS configuration is correct and will take effect if and
when that variable changes or a release tag is pushed — it is simply not live
today.

What this means in practice:

- **Local and CI** enforce RLS for real. That is the part of this work that is
  in effect, and it is the part that makes tenant-isolation bugs visible before
  they reach production.
- **Azure's live behaviour is unchanged.** Migration 060 runs there and
  correctly no-ops, because the Azure migrate job has no `APP_DB_SECRET_ARN`.
  That no-op path was built so an unprovisioned environment would not block its
  own deploy; it is doing exactly that.
- **Azure's outstanding gap is least privilege, not isolation.** An Azure
  Flexible Server admin login is not a superuser and so has no `BYPASSRLS`,
  which means 059's `FORCE` should already be enforcing tenant isolation there.
  Unverified against the live server — the same caveat as the AWS claim above.

Tracked as master plan 7.158.

Do **not** reorder any of this before 059 is applied: switching the role first
makes every platform-scoped read raise, which takes out public tracking,
activation and sign-in simultaneously.

**Verification already in place.** The RLS test suite is catalog-driven too: it
asserts every tenant-scoped table is `FORCE`d, that no policy casts to `::uuid`
or references `app.tenant_id`, that each carries a PLATFORM branch, and — as an
unprivileged probe role — that a tenant sees only its own rows, that PLATFORM
scope still crosses tenants, that an unscoped connection sees nothing, and that
`WITH CHECK` blocks a cross-tenant write. A future migration adding a table with
a non-canonical policy fails CI.
