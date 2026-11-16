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
| GET | `/v1/claims` | nigeria_office_staff, tenant_admin, customer (own) — sortable via `?sort=&direction=` (`sort` must be one allowlisted identifier, else `422`; hardened 2026-09-23 — see `00_CROSS_CUTTING_STANDARDS.md` §2.2) |
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

**`POST /v1/claims` had no check on the container's arrival status — a
claim could be filed against cargo still `loading` or `in_transit`, before
it had even reached Nigeria.** Reported directly by the user. Damage or
loss can only be observed once the container is physically unpacked and
inspected here, so `file_claim()` now rejects (`422
BUSINESS_RULE_VIOLATION`, `CONTAINER_NOT_ARRIVED`) unless the resolved
container's status is one of `arrived`, `customs_clearance`, `cleared`,
`at_warehouse`, `fully_released` — the check applies to both the customer
and staff filing paths, since neither can meaningfully assess damage before
arrival either. New `repository.get_container_status()`; the pre-arrival
set (`_PRE_ARRIVAL_STATUSES`) mirrors `CustomerStepper.tsx`'s first three
tracking stages. Covered by
`tests/unit/test_claims.py::TestClaimStateMachine::test_cannot_file_claim_before_container_arrives`
(parametrized over all three pre-arrival statuses) and
`test_can_file_claim_once_container_has_arrived` (parametrized over all
five arrived-or-later statuses, confirming the fix doesn't over-block).
Also closed the matching frontend gap: `MyClaimsNew.tsx`'s free-text
"Container ID or number" field let a customer type (or guess) any
container regardless of status — replaced with a dropdown populated from
the customer's own shipments, filtered to arrived ones only, so a
non-arrived shipment is never offered in the first place rather than being
submitted and rejected. See `frontend/07_domain_modules.md`.

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

**Upload file names are sanitised (2026-09-23).** The client's `filename` is passed through `shared.validation.safe_filename()` before it is used in the S3 key or stored: directory components dropped, anything outside Unicode word characters / `. ( ) space -` replaced with `_`, no leading/trailing dots, ≤100 chars with the extension kept (Chinese names like `装箱单.xlsx` survive). A name that reduces to nothing is a `422`. The download `Content-Disposition` is sanitised again on read, since rows written earlier may hold an unsafe name. See `00_CROSS_CUTTING_STANDARDS.md` §2.2.
1. Validate claim_id exists in tenant scope
2. Generate a cloud-neutral presigned **PUT** URL (via `StorageProvider`, 2026-10-05 — was S3 presigned-POST; see the cloud-portability note in `09_api_manifest.md`):
   - Key: `{tenant_id}/claims/{claim_id}/{filename}`
   - Expires in 1 hour
   - Max file size: 10MB (enforced client-side; PUT cannot enforce at the edge)
   - Allowed content types: image/jpeg, image/png, application/pdf
3. Insert `claim_evidence` record
4. Return `{ upload_url, upload_method: "PUT", upload_headers, evidence_id, file_key }` — the browser PUTs the raw file to `upload_url` with `upload_headers`

### Missing Items (POST /claims/missing-items)
- Create `missing_item` record linked to manifest
- `carton_tags TEXT[]` — array of carton tag identifiers (added migration 007)
- Status: `reported → investigating → found_and_shipping / confirmed_lost → resolved`
- `PATCH /v1/claims/missing-items/{id}` `{ status, notes?, refund_amount_ngn? }` — `status` must be one of the five values above
  (anything else is `422`). **Compensation is owed when the item is `confirmed_lost`:** with `refund_amount_ngn` it opens a
  `refund_request` (`refund_type = missing_item`, `pending_review`) and links it via `missing_item.refund_request_id`; without an
  amount the loss is confirmed with no compensation. The amount is ignored for every other status.

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
- [x] Confirming a missing item lost with `refund_amount_ngn` opens one compensation refund, atomically and at most once per item
- [x] `refund_amount_ngn` that is non-numeric, non-finite or not greater than 0 is `422`, never a `500` from the refund CHECK
- [x] Events published: DamageClaimFiled, DamageClaimResolved
- [x] Customer can only file and view own claims
- [x] `GET /v1/claims?sort=&direction=` — `reference` or `created_at` (default), wired to ClaimList's 'Claim ID'/'Filed' `sortable: true` columns (previously dead UI — see `frontend/07_domain_modules.md`)

**Implementation note (2026-07-11):** `GET /v1/claims` accepts `customer_id` as a staff-side filter (admin Customer Profile Claims tab). For the customer role the service pins the filter to the caller's own record regardless of the param, so it cannot widen scope — covered by `TestListClaimsCustomerFilter`.

**Implementation note (row 7.37):** `sort` defaults to `created_at`, `direction` defaults to `desc`. `list_damage_claims()` prefixes `sort_field` with the `dc.` table alias before calling `shared/pagination.py::build_paginated_query()` — same pattern as `billing/repository.py::list_billing_all()`'s `b.` prefix. The 'Claim ID' column renders `damage_claim.reference` (migration 033's human-readable `DC-YYYYMMDD-NNN` number, added to `ALLOWED_SORT_FIELDS`), not the raw UUID.

**Ground-truth gap found live (2026-09-07):** the "Last 30 days" button on `ClaimList.tsx` was a static label with no `onClick` at all, and `GET /v1/claims` had no date-filter support to back it — found while checking every page with a "calendar" filter after the same dead-UI bug was fixed on `GET /v1/billing` (row 7.63). Added `created_after`/`created_before` (ISO date, inclusive) filtering on `damage_claim.created_at` — `list_damage_claims()` gains the same `dc.created_at >= / <=` conditions as `list_billing_all()`'s `billed_at` filter. Frontend now pairs a `DateRangeFilter` preset (7/30/90/all) with an exact custom From/To range via the shared `useDateRangeFilter` hook (extracted from `ActivityLog.tsx`'s original hand-rolled version) — a custom date always overrides and clears the preset. Verified live: `created_after=2099-01-01` correctly returns 0 of the tenant's 12 claims; `created_after=2020-01-01` returns all 12. Tests: `TestListClaimsDateRange` (2 cases) in `tests/unit/test_claims.py`; `ClaimList.test.tsx` gained 1 case.

**Ground-truth gap found while auditing log coverage (2026-09-07):** `log_missing_item`, `update_missing_item`, `log_seized_item`, and `update_seized_item` had no `log_audit()` call at all — a genuinely missing/seized item (goods) being reported or resolved, and the `refund_request` compensation/recovery can trigger, left zero trail in the tenant's audit log. All four now log (`entity_type="missing_item"`/`"seized_item"`, plus a separate `"refund_request"` entry when compensation fires). Full account, including the other gaps found in the same pass, in `07_api_tenant_management.md`'s "Tenant Activity Log" section.

**Ground-truth gap found live, reported by the user (2026-09-09) while investigating a separate missing notification on payment-claim rejection — asked to check every notification in the app:** `damage_claim_update` had full SMS/WhatsApp/email templates defined but no call site ever used it — a claim moving to `under_inspection` or `resolved` sent no notification to the customer at all. Wired into `start_inspection` and both `resolve_claim` paths (the old approval-threshold path and `_resolve_claim_new_style`), best-effort and never able to fail the status change itself. Full account in `15_api_notifications.md`. Tests: `TestClaimStatusChangeNotifications` in `tests/unit/test_claims.py`.

**Staff bell (2026-09-12):** a customer filing a claim (`file_claim`) now also writes a `staff_notification` row for `nigeria_office_staff`/`tenant_admin` — only when the filer is the customer, not when staff file on a customer's behalf. Full account in `15_api_notifications.md`.

**Customer bell (2026-09-12):** `start_inspection`/`resolve_claim`'s customer notification now also writes an in-app row when the customer has a portal account, reusing the same `staff_notification` table as the staff bell above. Full account in `15_api_notifications.md`.

## Atomic resolution and compensation (2026-11-14)

`resolve` (both request styles) moves the claim to `resolved` with a guarded update (only from `under_inspection`,
`inspection_complete`, `pending_resolution`), opens the refund request and records the resolution **in one transaction**.
Two staff resolving the same claim at once open one refund; the loser gets `409`. A failure part-way (for example the
resolution insert) rolls the refund back with it, where before a refund was left behind with no resolution.

`PATCH /v1/claims/seized-items/{id}` with `recovery_status` `recovered`/`forfeited` and `refund_amount_ngn` records the status
change, the refund request and the link in one transaction, and opens **no second refund** if the item already carries one.
This used to fail outright: it created `refund_type = 'seized_item'`, which the database rejected (migration 063 now allows
it), after the item's new status had already been saved.

**Missing-item compensation (decided 2026-11-14): it triggers on `confirmed_lost`.** The branch used to test
`status == 'compensated'`, a value `missing_item.status` (CHECK, model and UI) has never allowed, so it was unreachable through
the API. It now fires on `confirmed_lost` with `refund_amount_ngn`, in one transaction with the status change and the link, and
opens no second refund if the item already carries one. `PATCH` validates its input at the handler: an unknown `status` and a
`refund_amount_ngn` that is non-numeric, non-finite or `<= 0` are `422 VALIDATION_ERROR` (the same amount check applies to
`PATCH /v1/claims/seized-items/{id}`). The Update dialog on the Missing Items page shows an optional **Compensation (₦)** field
only when the new status is *Confirmed lost*. Tests: `TestMissingItemCompensation` and `TestItemUpdateValidation`
(`tests/unit/test_claims.py`), `TestClaims` (3 cases, `tests/db/test_atomic_writes.py`).

**Seized-item compensation (decided 2026-11-16): it triggers on `permanently_lost`.** It used to fire on
`recovery_status in ('recovered', 'forfeited')`: `forfeited` is not a value the CHECK allows (`seized`, `recovery_in_progress`,
`recovered`, `permanently_lost`), and paying compensation for *recovered* goods was backwards. `PATCH /v1/claims/seized-items/{id}`
now rejects an unknown `recovery_status` with `422` (as missing items do), and only `permanently_lost` with `refund_amount_ngn` opens
the refund (`refund_type = seized_item`, once per item, in one transaction). The Update dialog shows an optional **Compensation (₦)**
field for *Permanently lost*. Tests: `TestSeizedItemCompensation`, `TestItemUpdateValidation` (`tests/unit/test_claims.py`), `TestClaims`
(`tests/db/test_atomic_writes.py`).

**Storage-fee waiver (decided 2026-11-14):** a waiver covers the fees accrued so far; days that accrue afterwards are charged
again. This is the intended behaviour, not a gap.
