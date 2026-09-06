# Task 12 — API Service: Damage Claims + Missing Items + Seized Items + Resolution

## Objective

Implement the Claims Lambda service: damage claim filing, inspection workflow, evidence upload (S3 presigned URLs), claim resolution (refund/discount/no_action), missing item and seized item logging.

## Depends On

- Task 06 (shared layer)

## Files: `services/claims/handler.py`, `service.py`, `repository.py`, `models.py`

## Routes

| Method | Path | Roles |
|---|---|---|
| POST | `/v1/claims` | customer, nigeria_office_staff |
| GET | `/v1/claims` | nigeria_office_staff, tenant_admin, customer (own) — sortable via `?sort=&direction=` |
| GET | `/v1/claims/{id}` | same |
| PATCH | `/v1/claims/{id}/inspect` | nigeria_office_staff |
| PATCH | `/v1/claims/{id}/resolve` | nigeria_office_staff, tenant_admin |
| POST | `/v1/uploads/presigned-url` | customer, nigeria_office_staff |
| POST | `/v1/claims/missing-items` | nigeria_office_staff |
| GET | `/v1/claims/missing-items` | nigeria_office_staff, tenant_admin |
| GET | `/v1/claims/missing-items/{id}` | nigeria_office_staff, tenant_admin |
| PATCH | `/v1/claims/missing-items/{id}` | nigeria_office_staff |
| POST | `/v1/claims/seized-items` | nigeria_office_staff |
| GET | `/v1/claims/seized-items` | nigeria_office_staff, tenant_admin |
| GET | `/v1/claims/seized-items/{id}` | nigeria_office_staff, tenant_admin |
| PATCH | `/v1/claims/seized-items/{id}` | nigeria_office_staff |

## Implementation notes / ground-truth gaps found (2026-09-06)

Found live via deep e2e interaction testing of the full customer-files →
staff-resolves → refund-created chain — not a code review:

**`POST /v1/claims` never resolved a container number, only a raw UUID.**
`FileDamageClaimRequest.container_id` was passed straight into a `uuid`
column with no lookup step, but the frontend's own field ("Container ID or
number … e.g. ACME-001 or paste the UUID") promised number support that
never existed server-side. A customer typing what they actually see — the
container number; they never see its internal UUID — crashed every attempt
to file a claim with `psycopg2.errors.InvalidTextRepresentation`. Fixed:
`repository.resolve_container_id()` accepts either form, scoped to tenant.
Also added `customer_has_cargo_in_container()` — without it, a customer
could file a claim against any container in the tenant by guessing or
enumerating numbers, not only their own cargo. Both covered by new cases in
`tests/unit/test_claims.py::TestClaimStateMachine`.

**`PATCH /v1/claims/{id}/resolve`'s staff-approval threshold was dead code.**
`resolve_claim()` checked `req.amount_usd`, but `ResolveClaimInput` (the real
frontend request body) only ever sends `amount_ngn` — no field named
`amount_usd` exists on it. `if resolution_type == "refund" and req.amount_usd:`
was therefore always falsy from the one call site that actually reaches
this code, so **`nigeria_office_staff` could resolve a refund of any size
with no `tenant_admin` escalation**, despite the UI showing a "may need
approval" warning banner that was purely cosmetic. Confirmed live: a
₦500,000 refund resolved cleanly as `nigeria_office_staff` with zero
rejection. Fixed by converting the NGN amount actually sent to USD via the
tenant's configured dollar rate (the same conversion this file already does
the other direction for the new-style settlement path). Covered by
`tests/unit/test_claims.py::TestRefundThresholdUsesRealFrontendContract`.

**`create_refund_request_for_claim()` never set `refund_type`.** Migration
007/009 added the column (and its `damage_or_loss` / `overpayment` /
`cbm_correction` CHECK constraint) with exactly this case in mind, but the
INSERT never populated it. Every claim-triggered refund had `refund_type`
`NULL` in the real database, and the frontend's `refundTypeLabel()` switch
had no fallback for that — `RefundDetail.tsx`'s page `<h1>` silently
rendered blank for every one of them (React renders `undefined` as
nothing). Fixed at both layers: the INSERT now sets `'damage_or_loss'`, and
`refundTypeLabel()` has a generic fallback so a future gap of this shape
can't blank the page again. See `14_api_refunds.md` for the refund-side
detail. Covered by `tests/unit/test_claims.py::
TestCreateRefundRequestForClaimSetsRefundType` and a new case in
`refundsRules.test.ts`.

## Damage Claim State Machine

```
filed → under_inspection → inspection_complete → pending_resolution → resolved → closed
                                                → resolved (no_action)
```

### File Claim (POST /claims)
1. Validate cartons_affected exist in tenant scope
2. Create `damage_claim` record (status = 'filed')
3. Generate presigned S3 upload URLs (scoped to `{tenant_id}/claims/{claim_id}/`)
4. Publish `DamageClaimFiled` event
5. Return claim + upload URLs

### Start Inspection (PATCH /inspect)
1. Set `inspection_method` — one of: `delegate_visit`, `customer_evidence` (added in migration 007)
2. Update status to `under_inspection`

### Resolve Claim (PATCH /resolve)
1. Validate approval authority (approval_level values from migration 007):
   - `resolution_type = 'no_action'`: any `nigeria_office_staff` (approval_level = `nigeria_staff`)
   - `refund ≤ $50`: `nigeria_office_staff` (approval_level = `nigeria_staff`)
   - `refund > $50`: `tenant_admin` (approval_level = `tenant_admin`)
   - `refund` linked to CBM/damage > $50 dispute: `head_of_finance` (approval_level = `head_of_finance`)
   - `discount`: `discount_percentage` stored on `claim_resolution`
2. Create `claim_resolution` record (with `refund_request_id` FK if refund raised)
3. If refund: create `refund_request` linked via `damage_claim_id`
4. If discount: store `discount_percentage` for next shipment
5. Update claim status to `resolved`
6. Publish `DamageClaimResolved` event

### Presigned URL Generation (POST /uploads/presigned-url)
1. Validate claim_id exists in tenant scope
2. Generate S3 presigned POST URL:
   - Key: `{tenant_id}/claims/{claim_id}/{filename}`
   - Expires in 1 hour
   - Max file size: 10MB
   - Allowed content types: image/jpeg, image/png, application/pdf
3. Insert `claim_evidence` record
4. Return upload URL + fields

### Missing Items (POST /claims/missing-items)
- Create `missing_item` record linked to manifest
- `carton_tags TEXT[]` — array of carton tag identifiers (added migration 007)
- Status: `reported → investigating → found_and_shipping / confirmed_lost → resolved`

### Seized Items (POST /claims/seized-items)
- Create `seized_item` record linked to container
- `carton_tags TEXT[]` — array of carton tag identifiers (added migration 007)
- Status: `seized → recovery_in_progress → recovered / permanently_lost`

## Schema Notes (Migration 007)

| Column | Change |
|---|---|
| `damage_claim.status` | New values: `filed/under_inspection/inspection_complete/pending_resolution/resolved/closed` |
| `damage_claim.inspection_method` | New: `VARCHAR(30)` — `delegate_visit` or `customer_evidence` |
| `claim_resolution.approval_level` | New values: `nigeria_staff/tenant_admin/head_of_finance` |
| `claim_resolution.refund_request_id` | New: UUID FK → `refund_request` |
| `claim_resolution.discount_percentage` | New: `DECIMAL(5,2)` |
| `missing_item.status` | New values: `reported/investigating/found_and_shipping/confirmed_lost/resolved` |
| `missing_item.carton_tags` | New: `TEXT[]` |
| `seized_item.status` | New values: `seized/recovery_in_progress/recovered/permanently_lost` |
| `seized_item.carton_tags` | New: `TEXT[]` |

## Acceptance Criteria

- [x] Damage claim lifecycle with 6 states (`filed → closed`)
- [x] Approval threshold enforcement ($50 USD boundary) with three approval levels
- [x] S3 presigned URLs scoped to tenant prefix (isolation)
- [x] Refund request auto-created on refund resolution (linked via `damage_claim_id`)
- [x] Missing item and seized item CRUD with `carton_tags` support
- [x] Events published: DamageClaimFiled, DamageClaimResolved
- [x] Customer can only file and view own claims
- [x] `GET /v1/claims?sort=&direction=` — `reference` or `created_at` (default), wired to ClaimList's 'Claim ID'/'Filed' `sortable: true` columns (previously dead UI — see `frontend/07_domain_modules.md`)

**Implementation note (2026-07-11):** `GET /v1/claims` accepts `customer_id` as a staff-side filter (admin Customer Profile Claims tab). For the customer role the service pins the filter to the caller's own record regardless of the param, so it cannot widen scope — covered by `TestListClaimsCustomerFilter`.

**Implementation note (row 7.37):** `sort` defaults to `created_at`, `direction` defaults to `desc`. `list_damage_claims()` prefixes `sort_field` with the `dc.` table alias before calling `shared/pagination.py::build_paginated_query()` — same pattern as `billing/repository.py::list_billing_all()`'s `b.` prefix. The 'Claim ID' column renders `damage_claim.reference` (migration 033's human-readable `DC-YYYYMMDD-NNN` number, added to `ALLOWED_SORT_FIELDS`), not the raw UUID.
