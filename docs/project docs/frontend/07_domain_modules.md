# Task FE-07 — Domain Modules

## Objective

Per-domain implementation notes that go beyond the route↔API mapping in Task 06: state machines, multi-step flows, frontend-only validation rules, and UX states the design brief calls out explicitly. Build these domains independently and in any order (each is a vertical slice) — see the parallelizable Phase 3 breakdown in [00_frontend_master_plan.md](00_frontend_master_plan.md).

## Depends On

Tasks 05, 06.

---

## 7.1 Containers & Packing Lists (China Office)

Backend: `08_api_packing_list.md`, `10_api_tracking.md`.

**State machine (packing list):** `draft → pending_approval → approved`, with `pending_approval → rejected → draft` revision cycle. Render this as a visual stepper (`TrackingStepper`/status badge), not a raw status string — staff should see "2 of 3" progress at a glance. Illegal transitions (draft→approved, approved→anything) must be impossible to trigger from the UI, not just rejected server-side: gray out/hide action buttons that would attempt an illegal transition rather than letting the user click and eat a 409.

**Self-approval prevention:** the approve/reject buttons on a packing list must be hidden (not just disabled) when `session.userId === packingList.createdBy`. The backend enforces this (`SELF_APPROVAL_FORBIDDEN`), but surfacing it as a missing button rather than a 422 toast is better UX.

**Create wizard (3 steps — `PLStep1/2/3`):** Details → Items (editable rows with running CBM/USD totals, computed client-side as a live preview but always re-validated server-side on submit) → Review. Carton tags and tracking codes are server-generated (don't attempt to predict them client-side for display before save — show "assigned on save").

**Bulk approve/reject:** operates on up to 100 items; the response returns `{succeeded: [...], failed: [...]}` per item (self-approval still blocked per-row even in bulk). Render partial success clearly — don't show a single pass/fail toast for a bulk action; show a result table (`BulkResultState` in `gapfix-screens-a.jsx`).

**Container status updates:** sequential, jurisdiction-restricted — China-side stages render in `--color-info` (blue), Nigeria-side in `--color-primary` (green). A status not reachable by the current role's jurisdiction should be visually disabled with a tooltip ("not available in your role"), and the picker is forward-only — no "revert to previous stage" control exists in the UI at all.

## 7.2 Excel Import

Backend: `19_excel_import_export.md`. Full upload mechanics in [10_file_uploads_and_exports.md](10_file_uploads_and_exports.md). Frontend-specific: the 3-step wizard (`BulkImport`/`ImportStep1/2/3`) must show per-row validation results with amber (warning, skippable) vs red (error, blocking) badges, a running "Parsing file... validating N rows" progress state, and a "skip invalid rows" toggle that still imports the valid subset.

### 7.2 Implementation notes / ground-truth gaps found

**Blocker (resolved): no generic upload endpoint existed.** `POST /v1/packing-lists/import` (`services/excel/service.py`) was fully implemented and expected `{ container_id, file_key }` for a file already in S3, but nothing in the codebase could produce that `file_key` for this purpose:
- `POST /v1/uploads/presigned-url` (`services/claims/handler.py`) is hardcoded to claim evidence — restricted to `customer`/`nigeria_office_staff` (china_office_staff, who owns this feature, can't call it), keys under `{tenant_id}/claims/{claim_id}/...`, and inserts a `claim_evidence` row as a side effect.
- `POST /v1/containers/{id}/documents/presigned-url` (`services/tracking/service.py`) is china-staff-accessible and lands under the right tenant prefix, but is hardcoded to container documents (`document_type` allowlist, inserts a `container_document` row) — reusing it would silently create a spurious "document" record with the wrong audit trail.

**Fix:** added a new, narrowly-scoped endpoint rather than reusing either of the above or generalizing the claims one (smaller blast radius, no risk to existing claims/tracking behavior):
- `POST /v1/packing-lists/import/presigned-url` (`china_office_staff` only) — `services/excel/service.py`'s `generate_import_presigned_url()`, dispatched in `services/excel/handler.py`. Validates `content_type` is exactly the xlsx MIME type (`_IMPORT_ALLOWED_CONTENT_TYPES`), then returns an S3 POST-policy (`upload_url`/`fields`/`file_key`).
- Key format is `{tenant_id}/imports/{uuid}.xlsx` — no caller-supplied filename is embedded at all (unlike the claims/tracking equivalents), which sidesteps filename-injection entirely. No DB row is created; the file is transient, consumed once by `POST /v1/packing-lists/import`, and never listed or referenced again.
- Added to `infrastructure/aws/modules/api-gateway/main.tf`'s route map (API Gateway routes are explicit route-key → Lambda mappings here, not a catch-all proxy, so this was required for the route to actually exist once deployed) and to `tests/tenant_isolation/test_s3_isolation.py` (mirrors the existing per-service key-structure tests) and `tests/unit/test_excel.py` (content-type validation).
- Frontend: `src/api/excel.ts` gained `getImportPresignedUrl()`; `src/api/uploads.ts`'s `uploadImportFile()` now calls it, builds a `FormData` from the returned `fields` (file field appended last, per S3's POST policy contract), and POSTs directly to `upload_url` — no `apiRequest()` wrapper, since this goes straight to S3, not the API. Throws `UploadFailedError` on a non-2xx response from S3.

Every other part of the flow — container picker, drag/drop file picker, confirm step, and the results step's stat tiles + skipped-row table — was already complete; only the one stubbed seam changed.

**The 3-step structure was adjusted to match what the backend actually supports.** `import_packing_list()` (`services/excel/import_packing_list.py`) is a single combined parse-and-commit call — there is no separate dry-run/validate-only endpoint, so a true "preview rows before committing" step (as the mockup's `ImportStep2` shows, with an editable per-row table) isn't possible without re-implementing the backend's customer-name-matching and validation logic in the browser. The real backend also has no severity distinction (every invalid row is unconditionally skipped — there's no warning-vs-blocking split) and no "skip invalid rows" toggle (skipping is the only behavior, not optional). The wizard's 3 steps are therefore: **Upload file** (pick container + local file, no server call yet) → **Confirm import** (explains the real one-shot behavior, no preview) → **Results** (the actual `total_rows`/`imported`/`errors`/`packing_lists_created`/`error_details` response, rendered as stat tiles + a skipped-rows table — this part faithfully matches the real `ImportResult` shape).

An "Import from Excel" entry point was added to `PackingListList.tsx`'s page header (china_office_staff only) since routeTable.ts already declared `/packing-lists/import` but nothing linked to it.

## 7.3 Manifests (Nigeria Office)

Backend: `09_api_manifest.md`. Manifest verify/resolve-discrepancy flows are staff-only actions against an auto-generated manifest (created when a packing list is approved — there's no manifest "create" screen). Discrepancy resolution needs a clear diff view: expected (from packing list) vs actual (counted on arrival) cartons/weight, not just a free-text resolution field.

### 7.3 Implementation notes / ground-truth gaps found

Built `ManifestList`/`ManifestDetail` against `services/manifest/handler.py`'s real role gates: `_READ_ROLES` (china/nigeria/tenant_admin), `_VERIFY_ROLES` (china/nigeria), `_RESOLVE_ROLES` (nigeria/tenant_admin) — `routeTable.ts`'s `/manifests*` `allow` arrays and `navConfig.ts`'s china-staff nav were widened to match (china staff can read+verify, not resolve). State machine: `pending → verified` OR `pending → discrepancies_found → resolved` (migration 021 added `resolved`). `ResolveDiscrepancyRequest.final_counts` is accepted by the Pydantic model but never referenced by the resolve SQL `UPDATE` — deliberately not given UI, since the backend doesn't persist it.

`weight_discrepancies` is present on `GET`/`verify` responses (the handler spreads the raw repository dict, not the declared `ManifestResponse` model) but is the **one** Decimal-sourced field that arrives as real JSON numbers, not strings — `_compute_weight_discrepancies()` casts through Python `float()` before serializing, unlike every other numeric column in this codebase (see below).

**Carton diff view added to `ManifestDetail`.** When `verification_status` is `discrepancies_found` or `resolved`, a "Missing cartons — expected vs. reported" table appears above the weight discrepancies table. It shows, per customer: expected carton count, number missing, cartons accounted for, and the specific missing carton tags (sourced from `missing_item` records linked to the manifest). Backend: `get_manifest()` in `services/manifest/service.py` now calls `repo.get_missing_items_for_manifest()` (new function in `manifest/repository.py`), returning `missing_items[]` alongside the existing `customers[]` and `weight_discrepancies[]`. Frontend: `manifest.ts` adds `ManifestMissingItem` type and `Manifest.missing_items?: ManifestMissingItem[]`.

**§6.3 verification photo upload added (F-D3, 2026-07-13).** The claims `EvidenceUploader` was generalised — it now takes a `getPresignedUrl: (file) => Promise<PresignedResponse>` callback instead of a hard-coded `claimId` (claims call sites in `ClaimDetail`/`MyClaimsNew` updated to pass `(f) => presignedUploadApi.getUrl(...)`). In `VerifyManifestModal` each discrepancy card gets a **Photo evidence (optional)** uploader that calls `manifestApi.getEvidenceUploadUrl(manifestId, name, type, label)` — `label` is built from the customer + type + carton tags. `ManifestDetail` renders a **Verification evidence** gallery (`evidence[]` from `GET /v1/manifests/{id}`, each a link to a short-lived presigned `download_url`). Backend: new `manifest_evidence` table (migration 036) + `POST /v1/manifests/{id}/evidence` presigned contract (see `09_api_manifest.md`). Frontend types: `ManifestEvidence`, `ManifestEvidenceUploadResponse`, `Manifest.evidence?`.

**Bug found and fixed (pre-existing, not specific to 7.3): every Decimal column on the wire is a JSON string, not a number.** `shared/responses.py`'s `json.dumps(body, default=str)` has no Decimal encoder, so every Postgres `DECIMAL` column round-trips as a string. 7.1's `PackingList`/`PackingListItem` types had several of these fields typed as `number`, which crashed `.toFixed()` calls at runtime against real data. Fixed by retyping the affected fields as `string` and adding `src/api/decimal.ts`'s `formatCbm()` helper, used everywhere a Decimal-sourced field is rendered.

**Bug found and fixed (pre-existing, systemic, not specific to 7.3): every paginated list endpoint was broken against a real backend.** `apiRequest<T>()` in `src/api/client.ts` always did `return envelope.data`, i.e. it unwraps exactly one level. That's correct for single-resource endpoints, but paginated endpoints (`shared/responses.py`'s `paginated()` → `{"data": [...], "meta": {...}}`) have no outer envelope to unwrap — calling `apiRequest<ListResponse<T>>(...)` silently double-unwraps, so `result.data` downstream is `undefined`. This was never caught before because the local dev stack (see below) didn't actually run end-to-end until this round of work, so no paginated list page had ever been browser-tested against live data. Fixed by adding a dedicated `apiRequestList<T>()` that returns the parsed envelope as-is, and switching all 5 affected call sites: `manifest.ts`, `tracking.ts`, `tenantManagement.ts`, `packingList.ts` (`list` and `listByContainer`).

**Bug found and fixed (pre-existing, blocked all `/v1/containers` requests):** `services/tracking/service.py` imported `from metering.service import check_container_limit` — a module path that doesn't exist (the real package is `services.metering.service`). Every container list/create request 500'd with `ModuleNotFoundError`. This had no test coverage gap to explain it — `pytest`'s rootdir-based `sys.path` insertion silently makes the bare `metering` import resolve in the test runner, masking the bug; only `scripts/local_server.py`'s `PYTHONPATH=.`-only import path actually exposed it.

**Local dev stack was non-functional end-to-end before this round; fixed 4 issues blocking real browser testing:** migrations `026`–`029` used the wrong Alembic signature (`def upgrade(op: object)` instead of module-level `from alembic import op` + parameterless `upgrade()`), migration `028`'s partial index used `NOW()` in a `WHERE` predicate (not IMMUTABLE, Postgres rejects it), `scripts/seed.py`'s `create_tenant()` never supplied `tenant.slug` (NOT NULL since migration 023), and `scripts/local_server.py` had no CORS handling so the browser (localhost:5173) blocked every request to the API (localhost:3000) at the preflight stage, including the OPTIONS preflight triggered by `LocalAuthProvider`'s custom `X-Tenant-ID`/`X-Role`/`X-User-ID` headers. `make stack` now succeeds end-to-end and the frontend can talk to a real local backend.

## 7.4 Billing & CBM Disputes (Nigeria Office, Tenant Admin, Customer)

Backend: `11_api_billing.md`. **Billing status values are exactly:** `unpaid`, `partially_paid`, `paid`, `overpaid`, `waived`, `released_with_outstanding` — never render or accept `draft`/`sent` (CLAUDE.md hard constraint; if a mockup or future redesign shows those, it's wrong, not the frontend).

**Payment recording (`RecordPaymentModal`):** must warn before submit if the entered amount exceeds the outstanding balance ("Amount entered exceeds balance — overpayment will accrue as a carryover credit"), since `overpaid` is a valid terminal-ish state, not an error.

**Carryover ledger:** credits from overpayment can be applied to future billing (`apply-carryover`) or exempted from expiry by a tenant admin. Show expiry countdown per carryover line.

**Storage fees:** 14-day grace period from release-note issue, then a daily per-carton fee accrues. Render the grace-period countdown as a banner (`StorageFeeBanners` in `gapfix-screens-b.jsx`) on billing detail, release-note detail, and the customer's own shipment view — this is the same banner component reused in three places, not three different banners.

**CBM disputes:** customer-filed (`POST /v1/billing/{billing_id}/dispute`) vs staff-filed differ only in entry point, same detail/timeline view after creation (`DisputeDetailPanel`, `DispEvent` timeline). Disputes escalate automatically after a configurable SLA (`dispute_escalation` tenant config) — show a ticking SLA countdown on open disputes nearing the threshold (`DisputeSLA` in `gapfix-screens-b.jsx`), not just a static "open" badge.

### 7.4 Implementation notes / ground-truth gaps found

**`billing_status` has a 7th value (`cancelled`) not in CLAUDE.md's constraint list.** `services/billing/models.py`'s `PaymentStatus` StrEnum includes `cancelled` (added post-006 by service logic for `cancel_billing()`). Frontend types and badge map include it.

**~~No `GET /v1/billing/{billing-id}` endpoint exists.~~ Fixed 2026-11-07 — `GET /v1/billing/{billing-id}/detail`.** The bare route `GET /v1/billing/{resource-id}` still takes a *customer* id as `resource_id` (it calls `get_billing_for_customer()`), and both ids are UUIDs, so the single-record read got its own path with a `/detail` suffix rather than overloading that shape. `billingApi.get(id)` binds it; the response is byte-identical to the matching `GET /v1/billing` row.

Both `BillingDetail.tsx` and `MyBillingDetail.tsx` previously worked around the gap by fetching `GET /v1/billing` (no `limit` → server default **50**) and searching the page client-side, so any record past the first page opened as "Billing record not found." — and because that same `load()` is the refresh after recording a payment, confirming a claim, waiving storage fees or removing a charge, an off-page record that *displayed* fine from router state turned into "not found" the moment it was mutated. Both now call `billingApi.get(id)`. Router state from `BillingList` is kept, but only as a first-paint seed. See `11_api_billing.md`'s 2026-11-07 ground-truth note for the authorization model (customer role force-scoped to its own records, fails closed) and the live verification.

**Decimal wire-format exception: `misc_fees_ngn`/`carryover_ngn`/`storage_fees_ngn`.** These are computed with Python's `sum()` over a list. An empty list returns integer `0`, not `Decimal` — so these three fields arrive as JSON number `0` when zero, but as JSON string for non-zero values. All other monetary fields are always strings. `billing.ts` types them as `string | number`; display sites use `Number()` coercion.

**Payment recording endpoint is in `payment_release` handler, not `billing`.** `POST /v1/payments/{billing-id}/confirm` goes to `services/payment_release/handler.py`. `billing.ts`'s `billingApi.recordPayment()` correctly calls `/v1/payments/${id}/confirm`.

**7.150 complete — every page now reads through TanStack Query (2026-11-08).** The 23 remaining hand-rolled fetch effects were migrated across all five areas; `grep -rn 'migrate to TanStack Query' frontend/src` returns nothing.

What this changes for anyone adding a page:

- **Do not hand-roll a `load()` useCallback invoked from an effect.** Read through `useQuery` (or an existing domain hook) keyed with `src/api/keys.ts`. Several pages were duplicating a hook that already existed and read the very same cache slot — `Warehouses`/`useWarehouses`, `MyClaims`/`useClaimList`, `MyBilling`/`useBillingList`, `ContainerCapacities`/the slot `CreateContainer` reads.
- **Do not reload after a mutation.** `api/client.ts` invalidates the affected roots after every successful non-GET, so a page whose key sits under an invalidated root refreshes itself. The one exception is a write that bypasses the API client — currently only the container document upload (direct PUT to presigned storage), where `DocumentsTab` invalidates `containerKeys.documents(id)` explicitly because the presign POST fires before the bytes land.
- **A mutation response that carries the updated record** goes into the cache with `setQueryData`, not into local state, so the open page and every list showing that row move together.
- **Keep mutation errors in their own `actionError`.** Merging them into the load error made a failed write render as a failed load.
- **An editable field seeded from the server needs a draft**, not derivation — see `StaffUserDetail`'s `localeDraft`. Deriving it discards a half-made edit on refetch (the 7.149 `CompanySettings` bug class).
- **Tests need `withQuery()`** from `src/test/queryWrapper.tsx`. Without a provider the page throws `No QueryClient set` with a stack pointing at the component, which reads like a product bug.

`ActivityLog.tsx` still hand-rolls a loader and that is intentional: it was never one of the 25 and carries no suppression, because 7.149 resolved its render-purity problems differently.

**A real bug this surfaced:** `MyShipments` had been calling `billingApi.listForCustomer(session.userId)` — a *customer*-id endpoint handed a user id — which returned **403 on every call**, swallowed by `Promise.allSettled`. The outstanding-balance greeting therefore always read ₦0 and the per-shipment billing lookup was always empty. See `11_api_billing.md` and the 7.156 master-plan entry.

**Customer billing pages migrated to TanStack Query (2026-11-07, master plan 7.150 — customer billing slice).**

- `MyBilling.tsx` now uses the existing **`useBillingList`** hook — the same paginated hook the staff `BillingList` uses — instead of hand-rolling `billingApi.list()` in a `useEffect`. This fixed a real truncation as a side effect: the page fetched one page with **no `limit`** and rendered it with no "Load more", so a customer with more than 50 invoices simply could not reach the older ones. It now renders the shared `ListFooter` with `hasMore`/`loadMore`, matching the staff list.
- `MyBillingDetail.tsx` had **three** hand-rolled fetch effects (the billing record, the tenant bank-transfer config, and its own payment claims); only the first was lint-flagged, because the other two set state inside `.then()` callbacks rather than synchronously. All three are now queries. The record lives at `billingKeys.detail(id)` — **the same cache slot the staff `BillingDetail` uses**, so a mutation on either side is seen by both — with router state from `MyBilling` passed as `initialData` to keep the instant first paint.
- The bank config reads through a new **`useBankTransferConfig()`** hook in `hooks/useConfig.ts`, sharing `configKeys.tenantConfig()` with the existing `useBranding()`; both read the same `GET /v1/tenant/config` response, so the page reuses whatever the shell already fetched instead of issuing its own request.
- `showTransfer` was state that an effect pushed to `true` whenever claims existed. It is now **derived** (`transferOpened || claims.length > 0`), which is correct because the panel only ever opens, never closes.

Test-harness consequence worth noting: once a page uses queries it needs a `QueryClientProvider`, and without one it throws `No QueryClient set` at render. `MyBillingDetail.test.tsx` and `MyBillingDetailPaymentClaim.test.tsx` both gained one (with `retry: false`), plus stubs for the two newly-queried endpoints.

**Dispute actions on `BillingDetail` are inline, not on a separate detail page.** The `_active_disputes` array is already embedded in the billing response by `_enrich_billing()` — no extra fetch is needed. Acknowledge/resolve/reject modals/inputs are rendered directly within `DisputeCard` components inside `BillingDetail`.

**`china_office_staff` has a "Disputes" nav entry** — `_DISPUTE_LIST_ALL_ROLES` in `billing/handler.py` includes china, and they can also resolve disputes (via `_RESOLVE_ROLES`). Added a Billing & Disputes nav group for china staff containing only the Disputes link. `routeTable.ts`'s `/billing/disputes` `allow` array updated to include `china_office_staff`. `/billing/disputes/:id` route removed — no separate dispute detail page exists; disputes are managed inline on `BillingDetail` via `DisputeCard`.

**`carryoverApi.list()` must not filter by `customer_id: billing.container_id` (fixed bug).** Billing records are per-container, not per-customer — `Billing` has no `customer_id` field. `BillingDetail.tsx`'s `loadCarryovers()` previously passed `billing.container_id` as `customer_id`, returning empty or wrong results. Fixed to call `carryoverApi.list({ status: 'outstanding' })` — no customer filter.

**`StorageFeeBanner` added to `BillingDetail`.** Shows when `storage_fees_ngn > 0`. If `release_note_issued_at` is present in the billing response (optional field, not yet returned by the backend), the banner shows a precise grace-period countdown (14-day window). Without it, it shows a generic "fees are accruing" warning. `billing.ts`'s `Billing` interface has `release_note_issued_at?: string | null` ready for when the backend adds it.

**`DisputeSLA` countdown added.** `BillingDetail.tsx`'s `DisputeCard` shows a ticking "X until auto-escalation" countdown for open disputes approaching the 7-day SLA window (surfaces only within 2 days of deadline, turns red when overdue). `DisputeList.tsx` has a dedicated SLA column with the same logic.

**`disputeApi.file()` added** (`POST /v1/billing/{billing_id}/dispute`) — API binding ready; UI integration deferred to 7.8 (customer portal's `/my-billing/:id` page).

## 7.5 Claims, Missing & Seized Items (Nigeria Office, Customer)

Backend: `12_api_claims.md`. Damage claim flow: file (customer or staff) → inspect (staff) → resolve (staff, approve/deny with refund linkage). The customer-facing "file a claim" wizard (`CustomerFileClaim`, 3 steps: Details → Evidence → Review) uses the same S3 presigned-upload mechanism as staff evidence upload (Task 10) — build one evidence-uploader component, used by both `CustomerFileClaim` and `StartInspectionModal`.

Missing items and seized items are separate lists from damage claims (different backend tables/endpoints) but visually similar list+detail patterns — share the list/detail page shell, don't duplicate.

### 7.5 Implementation notes / ground-truth gaps found

**`_fmt_claim` now includes `container_id`, `customer_id`, `description` (fixed).** Previously returned only `id`, `status`, `cartons_affected[]`, `upload_urls`, `created_at`. All three context fields are now included so `ClaimDetail` can show a "Claim details" card. `claims.ts`'s `Claim` interface updated accordingly.

**Evidence upload wired.** `EvidenceUploader.tsx` component created (S3 POST-policy flow via `presignedUploadApi.getUrl()`). Used in `StartInspectionModal` when `inspection_method === 'customer_evidence'` — the submit button is disabled until at least one file is uploaded. Also rendered as a standalone "Attach evidence" section on `ClaimDetail` for any non-terminal claim. `presignedUploadApi`'s return type corrected from `{ upload_url, key }` to `{ upload_url, fields, evidence_id, file_key }` to match the actual backend shape.

**Approval threshold warning on `ResolveClaimModal`.** `nigeria_office_staff` resolving a `refund` or `compensation` above ~₦25,000 sees a warning banner: "This amount exceeds the staff approval limit — a tenant admin must resolve refunds above the configured threshold." The backend (`resolve_claim()`) enforces the actual threshold from tenant config — the frontend warning is advisory only. The threshold constant is intentionally hardcoded as a hint; exact value fetched server-side.

**Three separate status machines.** Damage claims: `filed` → `under_inspection` → `inspection_complete` → `pending_resolution` → `resolved` → `closed`. Missing items: `reported` → `investigating` → `found_and_shipping` → `confirmed_lost` → `resolved`. Seized items: `seized` → `recovery_in_progress` → `recovered` → `permanently_lost` (stored as `recovery_status` in DB, aliased to `status` in `_fmt_seized`).

**Missing/seized items are staff-only** — `_ITEM_READ_ROLES = (NIGERIA_OFFICE_STAFF, TENANT_ADMIN)`. Customer cannot read or update these. `canUpdateItem` is nigeria-only (PATCH gate is `_STAFF_ROLES`); tenant_admin can see but not update.

**Missing/seized item pages share CSS** (`ItemList.module.css`) — chip filters, paginated table, inline UpdateModal are the same across both. Separate `.tsx` files, one shared CSS module.

**Missing/Seized Items added to `BILLING_CLAIMS_GROUP` nav** — both appear as nav items for nigeria + tenant_admin.

## 7.6 Refunds (Nigeria Office, Tenant Admin, Customer)

Backend: `14_api_refunds.md`. Multi-stage approval: `pending_review` (accounts) → `pending_approval` (manager, only above a configurable threshold — `refund_threshold_usd` tenant config) → `approved`/`rejected`/`processed`/`applied_as_credit`. Render this as a horizontal stepper (`RefundStepper`) that visually skips the manager-approval step when the amount is within the staff auto-approval limit — make the threshold check visible ("$50 staff limit — this request requires manager approval") rather than a silent business rule.

Refund preference (bank account payout vs. apply-as-credit) is captured from the customer at request time — `account_number`/`account_name` are encrypted fields server-side (`shared/encryption.py`); never log these client-side, mask in any client-side debug output, same rule as backend CloudWatch (CLAUDE.md "no PII in logs").

### 7.6 Implementation notes / ground-truth gaps found

**Actual backend state machine skips `approved` and `accounts_reviewed` states.** The `approve_refund()` service transitions directly from `pending_approval` → `processed` or `applied_as_credit` (never via `approved`). The `accounts_review()` service transitions directly from `pending_review` → `pending_approval` or `rejected` (never via `accounts_reviewed`). Both status enum values exist in the DB but are dead in the current service path. Frontend stepper reflects the real transitions, not the spec diagram.

**`_fmt_refund` enriched with context fields.** Previously returned only id, status, refund_type, amount_requested_ngn, amount_approved_ngn, customer_choice, created_at. Now includes: `customer_id`, `billing_id`, `damage_claim_id`, `reason`, `rejection_reason`, `approval_level`, `debt_check_passed`, `debt_check_notes`. `RefundDetail` shows these in a "Request details" card and debt check banners.

**`RefundStepper` is a 3-step horizontal stepper:** Accounts Review → Manager/Head of Finance Approval → Processed/Credit. The approval step label adapts to `approval_level` (`manager` or `head_of_finance`). The step is not visually hidden for staff — instead `ApproveModal` disables the confirm button and shows an error banner if `approval_level === 'head_of_finance'` and the role is `nigeria_office_staff`. An advisory warning appears in `ApproveModal` when the entered amount likely exceeds the staff threshold (~₦77,500 / $50 at typical rates).

**Approval authority enforced at two layers.** `canApproveRefund()` in `refundsRules.ts` blocks `nigeria_office_staff` from even seeing the Approve button when `approval_level === 'head_of_finance'`. The backend also enforces it with a 422 `InsufficientPermissionsError`.

**`AccountsReviewModal` shows debt check pass/fail radio.** `nigeria_office_staff` selects whether the debt check passed (advances to `pending_approval`) or failed (rejects with debt offset). Notes field is required in both cases. When failed, the reject button is labelled "Reject — debt offset" to be explicit.

**Customer portal refund filing deferred to 7.8.** The customer-facing `POST /v1/refunds` path (from `/my-billing/:id/refund-request`) is not built yet. `refundsApi.create()` is the API binding ready for 7.8.

**`/refunds` nav link** is already present in `BILLING_CLAIMS_GROUP` for nigeria_office_staff and tenant_admin. Routes `/refunds` and `/refunds/:id` were pre-declared in routeTable.ts — wired to `RefundList`/`RefundDetail` in routes.tsx.

## 7.7 Release Notes & Warehouse Pickup

Backend: `13_api_payment_release.md`. A release note can be split (`SplitReleaseModal`) into multiple notes by carton subset before full pickup — carton-tag conflicts ("Cartons X are already on release note Y") must be checked and shown inline before the split is submitted, not just on server rejection. Warehouse Attendant's pickup recording (`RecordPickupModal`) is a single-purpose, high-frequency action — optimize this screen for speed (large touch targets per the mobile rules below, minimal required fields) since it's used dozens of times a day on a warehouse floor, possibly on a tablet.

### 7.7 Implementation notes / ground-truth gaps found

**Three UI surfaces for release notes:**
1. `ReleaseNoteList` (`/release-notes`) — filterable by status for nigeria/admin/warehouse. Shows carton count (note/customer total), type (partial/full), issued date.
2. `ReleaseNoteDetail` (`/release-notes/:id`) — shows carton tags, pickup/split actions. Warehouse sees "Record pickup" (large green CTA); staff see "Split note" (multi-select chip picker of tags to move to child note).
3. `WarehouseDashboard` (`/warehouse`) — warehouse-attendant-only queue of active release notes. Card layout (not table), bottom-sheet modal, min-height 48px buttons, font-size 16px inputs — all per mobile/tablet UX spec. After a successful pickup the card shows ✓ Done for 2 seconds then disappears from the queue.

**"Generate release note" added to `BillingDetail`** for nigeria/tenant_admin when billing is `paid`, `overpaid`, or `partially_paid`. Opens a modal with a textarea for carton tags (one per line or comma-separated). The backend validates tags against approved packing list items. Optionally toggles "release with outstanding balance" which requires approval notes — backend creates a `carryover_ledger` entry. On success, navigates to `/release-notes`.

**Carton tags are not auto-fetched in GenerateReleaseNoteModal.** The list endpoint does not return item-level carton tags (only `carton_count`). Getting tags would require a detail fetch per packing list (O(n) calls). Instead the modal uses a textarea for manual entry — staff reads tags from the physical packing list or the system's packing list detail view.

**Delegate pickup flow fully supported.** `RecordPickupModal` (both on `ReleaseNoteDetail` and `WarehouseDashboard`) shows delegate fields (name, phone, ID type dropdown, ID number) when the delegate toggle is on. The server-side encrypted `id_number` field is written to `pickup_record.delegate_id_number` via the `shared/encryption.py` path — the frontend sends it in plaintext (HTTPS in transit) and never logs it client-side.

**Pickup success feedback.** After a successful pickup, a banner shows remaining cartons on the note. If all customer cartons are collected (`shipment_status = 'picked_up'`), an additional "shipment tracking updated" message appears. In `WarehouseDashboard` the card self-removes after 2 seconds to clear the queue visually.

**`SplitModal` enforces subset selection.** The tag picker only shows tags from the parent note. Backend additionally validates: (a) all requested tags must exist in parent, (b) none already picked up (`TAGS_ALREADY_PICKED`). The frontend prevents submitting with zero tags selected.

## 7.8 Customer Portal

Card-based layouts, not tables, throughout (`CustomerBilling`, `CustomerClaims` use cards — this is a deliberate departure from the staff table-heavy UI, confirmed in the mockups, not an oversight). Payment options split into "pay online" (gateway redirect — Paystack/Flutterwave, lands back on `/my-billing/:id/payment-success` or `/payment-failed`) vs. "manual bank transfer" (staff later confirms via `POST /v1/payments/{billing_id}/confirm`). Public tracking (`/track/:code`) requires both tracking code and phone number — don't expose any shipment data without both matching.

### 7.8 Implementation notes / ground-truth gaps found

**All 12 customer portal routes are now wired:** `MyShipments`, `MyShipmentDetail`, `MyBilling`, `MyBillingDetail`, `PaymentSuccess`, `PaymentFailed`, `RefundRequest`, `MyClaims`, `MyClaimsNew`, `Account`, `PublicTrack` (`/track` + `/track/:code`). All customer routes use `CustomerLayout` (horizontal top-nav, no staff sidebar). Public tracking routes have `layout: 'none'` and `allow: 'public'` — no `RoleGuard`, no auth headers.

**`publicTrackingApi.lookup(code, phone)` in `customer.ts`** calls `GET /v1/track/{code}?phone={phone}`. The `apiRequest` wrapper sends auth headers if a token exists, but the server doesn't require them — it validates ownership via phone match. For authenticated customers (`MyShipmentDetail`), the phone isn't available in the JWT session, so the endpoint is called with an empty phone. If the server rejects this, a clear error is shown.

**"Pay online" button is disabled** — online payment gateway (Paystack/Flutterwave) integration requires env vars (`PAYSTACK_WEBHOOK_SECRET`, `FLUTTERWAVE_WEBHOOK_SECRET`) and a gateway redirect URL not yet configured. The button shows with a disabled state and a note. Bank transfer details are shown on demand via a toggle. `PaymentSuccess`/`PaymentFailed` pages are built and wired for when the gateway redirect is configured.

**Customer refund filing** (`RefundRequest`) uses `refundsApi.create()` with `refund_type: 'overpayment'` and `customer_choice` (immediate_refund / credit_next_shipment). `customer_id` is sent as an empty string — the backend derives it from the JWT `user_id` for the customer role (per `create_refund()` in `service.py`'s customer path). Account number / account name fields are omitted from the form — those are captured by the accounts team during review.

**Claim filing wizard** (`MyClaimsNew`) is 3 steps: Details (container ID + description + carton tags) → Evidence (EvidenceUploader, same component as staff `ClaimDetail`) → Review. The claim is created after step 1 so the `claim_id` is available for S3 presigned upload in step 2. The customer can skip evidence upload and add it later.

**`MyBillingDetail` shows release notes indirectly** — customer sees their payment history and outstanding balance but doesn't see a list of their release notes on this page. They see release notes (shipments) via `MyShipments` (`/my-shipments`).

**`Account` page is read-only** — customer name and email come from session (JWT claims). There is no `GET /v1/customers/me` endpoint; the customer's customer_id is not in the JWT. Staff can update customer profiles via `PATCH /v1/customers/{id}`.

**`routes.test.tsx` updated** — two test assertions changed from `getByText('/my-shipments')` (RouteStub path text) to `getAllByText('My Shipments')` (real page heading + nav link), since the page now renders the real `MyShipments` component.

## 7.9 Platform Admin & Tenant Admin (Config, Users, Customers)

Backend: `07_api_tenant_management.md`. **GDPR anonymise flow:** typing the literal word "ANONYMISE" to confirm `DELETE /v1/customers/{id}` — this is an explicit, deliberate friction point from the design brief, implement the confirmation input exactly (case-sensitive match), not a generic "are you sure?" modal. Show a persistent GDPR banner on the customer profile if `anonymised_at` is set, and gate the data-export action (`GET /v1/customers/{id}/export`) as available to both the tenant admin and the customer themselves (self-service, no admin required) — confirm this against [11_security_and_compliance.md](11_security_and_compliance.md).

Notification template editor (`NotificationTemplatesPage`) needs a per-channel SMS character counter: ≤160 chars = 1 segment (gray), 161–320 = amber warning, >320 = red warning — this is a cost/deliverability signal for the tenant admin, not validation that blocks save.

### 7.9 Implementation notes / ground-truth gaps found

**`tenantManagement.ts` fully expanded.** Previously only had `customersApi.list()`. Now includes: `customersApi` (list, get, create, update, anonymise, export), `usersApi` (list, get, create, update, deactivate, resendInvite, resetPassword), `configApi` (dollar rate, CBM rate, charge types, notification templates), `platformApi` (list/get/create/suspend/activate/offboard tenants).

**Pages built:**
- `Dashboard` (`/dashboard`) — tenant_admin + nigeria_office_staff. Shows container count, unpaid billing count, outstanding total. Quick-link cards to Operations, Billing/Claims, and Administration (admin-only).
- `StaffUserList` / `StaffUserDetail` — invite, role-change (multi-role checkbox + primary radio, migration 039 — see 2026-07-20 notes below), deactivate, resend invite, reset password.
- `AdminCustomerList` / `AdminCustomerDetail` — search customers; full GDPR anonymise + export flows.
- `ConfigOverview` — links to dollar-rate, CBM-rate, charge-types, notifications, webhooks sub-pages.
- `DollarRateConfig` / `CbmRateConfig` — view and update rates.
- `NotificationTemplates` — grouped by event type; per-template save; **SMS character counter** (≤160 gray, 161–320 amber, >320 red) per spec.
- `PlatformTenantList` — list + onboard new tenant modal.
- `PlatformTenantDetail` — suspend / lift suspension / offboard actions.

**GDPR anonymise: exact "ANONYMISE" text match required (case-sensitive).** `AdminCustomerDetail`'s `AnonymiseModal` calls `DELETE /v1/customers/{id}`. The confirm button only enables when `confirmText === 'ANONYMISE'` (strict equality, no `.toLowerCase()`). A persistent GDPR banner appears on any customer with `anonymised_at` set. Export downloads as a JSON file client-side (`customer-export-{id}.json`) with no console logging of PII.

~~**Platform admin routes not yet wired:** `/platform/dashboard`, `/platform/settings`, `/platform/audit-log` — still fall through to `RouteStub`.~~ *(Superseded: all wired; `RouteStub` was deleted 2026-11-17, audit FE-08.)* These are lower priority; the critical CRUD and suspend/activate flows are complete.

~~**Tenant-admin config sub-pages not yet wired:** `/admin/config/charge-types`, `/admin/config/webhooks`, `/admin/reports`, `/admin/notifications/log` — still fall through to `RouteStub`.~~ *(Superseded: all wired; `RouteStub` was deleted 2026-11-17, audit FE-08.)* The API bindings (`configApi.listChargeTypes`, etc.) are ready in `tenantManagement.ts`.

## 7.10 Reports & Notification Log ✅

Backend: `15_api_notifications.md`. Notification log (`NotificationLog`, `NotifDetailModal`) shows delivery status per channel with a retry action (`POST /v1/notifications/log/{id}/retry`, tenant_admin only) — surface provider error detail (`gateway_response`) on the detail modal for debugging delivery failures, but never the full raw payload if it could contain PII beyond what's already masked server-side.

### 7.10 Implementation notes / ground-truth gaps found
- `TenantReports` page: 4 stat cards, DonutChart (conic-gradient CSS), TopCustomersChart (CSS bars), ContainerPipelineChart (8-week stacked bars), CBM billing table with CBM-rate + FX columns, Claims summary cards using `<Icon>` (not emoji).
- `NotificationLog` page: status dropdown filter, `message_body` preview column (after migration 034 adds the column), chat-bubble message body in detail modal, `suspended: true` on failed rows, Resend + Close modal footer.
- Migration 034 adds `notification_log.message_body TEXT`; notification handler now formats message body before calling `log_queued` so it's stored at queue time.
- `NotificationLogEntry` frontend type extended with `message_body: string | null`.
- 4th stat card changed from "Collected" to "Avg CBM / container" (computed from billing data).

---

## Cross-Domain UX Conventions (apply everywhere, not just where called out above)

- **Empty states are positive, not apologetic:** "✓ No disputes escalated", "You're all caught up!", "All pickups cleared!" — port this tone, don't default to a generic "No data found."
- **Loading states:** table skeletons = 5 gray rows matching real column widths (built once into the `Table` component, Task 03); card skeletons = gray bars matching title/body/button shape.
- **Mobile (warehouse/customer-heavy usage):** minimum touch target 44×44px, input font-size ≥16px (prevents iOS auto-zoom), tables collapse to a 2-column label:value card list, modals go full-screen(-ish, bottom-sheet). **This was aspirational until 2026-09-20** — implemented on exactly one screen (`WarehouseDashboard`'s pickup sheet) before that date, and not even mirrored in its own near-duplicate (`ReleaseNoteDetail`'s `RecordPickupModal`, same feature). Now genuinely true app-wide — see the "App-wide responsive pass" note below and [03_component_library.md](03_component_library.md)'s matching addendum for the implementation.
- **Voice:** active, ownership-driven copy ("Confirm payment" not "Submit form"; "Lead every shipment" not "Track shipments") — this is a brand voice rule from the design brief, apply it in button labels and page titles, not just marketing copy.

## Acceptance Criteria

These bullets are cross-domain (apply once *every* 7.x slice exists), so they stay unchecked until the last domain lands. Status per bullet, scoped to what's actually built so far (7.1–7.3):

- [x] Every state machine above is enforced in the UI by hiding/disabling illegal-transition controls — **done (2026-07-10)** across all domains: `billingRules`/`claimsRules`/`refundsRules`/`releaseNotesRules` (all pure + unit-tested) drive control visibility in `BillingDetail`/`ClaimDetail`/`RefundDetail`/`ReleaseNoteDetail` (e.g. `canApproveRefund` gates on `status === 'pending_approval'` + role + approval_level), alongside the earlier container/packing-list/manifest rules.
- [x] Self-approval is hidden client-side wherever the backend enforces `SELF_APPROVAL_FORBIDDEN` — **done**: `PackingListDetail` (`isSelfApproval`/`canApproveOrReject`). Packing-list approval is the only flow with this backend rule, so coverage is complete.
- [x] Bulk operations render per-item success/failure, never a single pass/fail toast — **done**: `PackingListList`'s `BulkResultPanel`. Packing-list bulk approve/reject is the only bulk operation in the app, so coverage is complete.
- [x] Billing status badges only ever render the valid values — the `PaymentStatus` union (`api/billing.ts`) contains exactly `unpaid/partially_paid/paid/overpaid/waived/released_with_outstanding/cancelled`; rendering `draft`/`sent` is a **compile error** (not assignable to the union, and `STATUS_VARIANT: Record<PaymentStatus, …>` enforces exhaustiveness).
- [x] GDPR anonymise requires exact "ANONYMISE" text match before the delete button enables — **done**: `AdminCustomerDetail.tsx` (`confirmText === 'ANONYMISE'`); the customer-portal Privacy tab uses the same typed-`DELETE` gate.
- [x] SMS character counter matches the 160/320 thresholds exactly — **done**: `NotificationTemplates.tsx` `SmsCounter` (≤160 = 1 segment, 161–320 = 2, >320 = 3+).
- [x] Empty/loading states across all list pages use the shared `Table`/`Card` skeleton + positive-tone empty copy — **done (2026-07-10)**: every list page renders the shared `Table` with `loading` + `emptyState` props; consistent after the query-hook migration.

### 7.1 Implementation notes / ground-truth gaps found

- **Container form fields trimmed to the real schema.** The China mockup's `CreateContainer` shows vessel name, voyage number, shipping line, container type, and seal number — none of those have a column on the `container` table (`05a_database_schema_core.md`) or are accepted by `create_container()` in `services/tracking/service.py`. `CreateContainer.tsx` only collects `container_number` (required), `parcel_number`, `origin`/`destination` (default China/Nigeria), `estimated_arrival_date`, and `notes` — what the backend actually persists. This is a real mockup-vs-backend gap, not an oversight; flagging here since `19_excel_import_export.md`/future backend work may want to close it by adding those columns.
- ~~`GET /v1/packing-lists` (list) doesn't return `customer_name`~~ **Fixed.** The list query now LEFT JOINs the `customer` table (`cu.name AS customer_name`) inside the subquery wrapper, alongside the existing `container` and `packing_list_item` JOINs. `PackingListList.tsx` shows Customer as the first column; the packing-lists tab on `ContainerDetail` also shows it (useful since a single container can have packing lists for multiple customers). The `customer_name?: string | null` field was already typed on the `PackingList` interface — it was just never populated by the list endpoint before.
- **`PATCH /v1/packing-lists/{id}/submit` is implemented in `services/packing_list/handler.py` but missing from `08_api_packing_list.md`'s routes table** — confirmed by reading the handler directly. The frontend wires to the real endpoint (`packingListApi.submit`); the backend doc itself hasn't been corrected since that's outside this task's scope.
- **Container status advance UI** (`ContainerDetail`'s `AdvanceStatusModal`) surfaces the `sealed`/`in_transit` pre-transition guards (`NO_APPROVED_PACKING_LISTS`/`NO_MANIFEST`/`MISSING_SHIP_DATE` in `update_container_status()`) as advisory copy (`containerAdvanceRequirementHint`) rather than re-validating client-side — the backend remains the source of truth and still fails closed on a real violation; this is UX-only.
- ~~**No container-list aggregate-count endpoint exists**, so `ContainerList.tsx` doesn't show the mockup's 5-stat row or per-chip counts.~~ **Revised (prototype-compliance pass).** There's still no dedicated aggregate endpoint, but `ContainerList.tsx` now renders the prototype's 5-`StatCard` row and per-chip counts by computing them client-side from a single up-front `containersApi.list({ limit: 200 })` batch (`allContainers`), separate from the paginated table view. Counts are grouped by status: Active (`loading`+`sealed`), In transit, Arrived NG (`arrived`+`customs_clearance`), Cleared (`cleared`+`at_warehouse`+`fully_released`), Total. This is real data (not fabricated) but bounded to the first 200 containers — a true aggregate endpoint would remove that ceiling. Filter chips map to the same status groups and toggle the table's single-status filter (multi-status server filtering would need a backend change).
- **Four small UI atoms were promoted from mockup-local duplicates to shared components**: `Kvp`, `UserCell`, `ViewLink`, `KebabBtn` (`src/design/components/`). They were never in `shared/components.jsx` (Task 03's actual source) — each domain mockup file (`platform-screens.jsx`, `reports-screens.jsx`, `china-screens.jsx`) redefined its own copy. Promoted to shared components here since 7.1 needed them and every other 7.x domain will too; see `03_component_library.md`'s note.
- **`customersApi` (`src/api/tenantManagement.ts`) was pulled forward from Task 7.9** — the packing-list create wizard needs a customer picker (`GET /v1/customers`). Only `list()` exists; full customer CRUD/profile/GDPR lands with 7.9.
- **Carton tags/tracking codes render as "Assigned on save"** in the create wizard's item rows (`PLStep2`-equivalent in `CreatePackingList.tsx`) rather than predicted client-side, per this doc's own instruction.
- Not yet built for 7.1: CSV import (`/packing-lists/import`, this is 7.2's Excel Import slice), and the **Manifest** / **Documents** tabs on `ContainerDetail` (Manifest = 7.3; Documents = Task 10 file uploads). The **Tracking** tab **is now built** (prototype-compliance pass): it renders `ContainerStepper` plus an event-log `Table` sourced from `containersApi.events(id)` (`GET /v1/containers/{id}/events`), so `ContainerDetail` now has 3 of the prototype's 5 tabs (Overview / Packing lists / Tracking).
- **Bug fixed during 7.3 ground-truth work: DECIMAL fields were mistyped as `number`.** `weight_dispatch_kg`/`weight_actual_kg`/`cbm`/`length_cm`/`width_cm`/`height_cm`/`declared_value_usd` (item-level) and `total_cbm`/`total_weight_kg` (list-level) are all DECIMAL columns; `shared/responses.py`'s `json.dumps(body, default=str)` has no native Decimal encoder, so they serialize as strings on the wire. `packingList.ts` had typed them `number`, and `PackingListDetail.tsx`/`PackingListList.tsx`/`ContainerDetail.tsx` called `.toFixed(3)` directly on `total_cbm`/`item.cbm` — a real `TypeError` crash on any packing list with cartons (the normal case; only masked in earlier testing because `sum()` over an empty items list returns a plain `int 0`, not `Decimal`). Fixed: all affected fields retyped `string | null`/`string`; display call-sites use a new `formatCbm()` helper (`packingListRules.ts`) instead of calling `.toFixed()` directly; `totalDeclaredValueUsd()` now coerces with `Number(...)` before summing (previously would have silently string-concatenated instead of adding).
- **Bug found and fixed (infra, surfaced by browser-testing `ContainerDetail`'s Packing Lists tab): `GET /v1/containers/{id}/packing-lists` was unroutable end to end.** `services/packing_list/handler.py` implements this path as a deliberate sub-resource alias (`_container_packing_lists()`), but `infrastructure/aws/modules/api-gateway/main.tf`'s route map never had an entry for it — Terraform would have shipped a route that 404s in production — and `scripts/local_server.py`'s prefix-based dispatch table sent the whole `/v1/containers/*` prefix to the `tracking` Lambda, which also 404'd. Fixed both: added `"GET /v1/containers/{id}/packing-lists" = "packing_list"` to the Terraform route map (`04c_terraform_api_gateway.md`), and added an explicit path check in `local_server.py` ahead of the generic prefix loop.
- **Bug found and fixed (local dev only): create container / approve / reject all 500'd with `invalid input syntax for type uuid`.** `created_by`/`approved_by`/`rejected_by` are `UUID REFERENCES tenant_user(id)` columns (migrations 001-003), but `LocalAuthProvider.tsx`'s `ROLE_USER_IDS` sends fake slugs (`"local-china-staff"`, etc.) as `X-User-ID`, which aren't valid UUID literals — every write that stamped an actor id failed. Real Cognito subs are always UUIDs, so this never affects production. Fixed in `scripts/local_server.py`: `_resolve_user_id()` now looks up a real `tenant_user.id` for the request's tenant+role (cached) whenever `X-User-ID` isn't a valid UUID, falling back to a fixed nil UUID for `platform_admin` (no `tenant_user` row exists for that role).
- **Bug found and fixed: bulk approve/reject 500'd with `operator does not exist: uuid = text`.** `services/packing_list/repository.py`'s `get_packing_lists_by_ids()` and `bulk_set_status()` both did `id = ANY(%s)` with a Python list of id strings — psycopg2 adapts that to `text[]`, which doesn't compare against a `uuid` column without an explicit cast. This is a real bug independent of local dev (would 500 in production too). Fixed by casting: `id = ANY(%s::uuid[])`.
- **Bug found and fixed: `bulk_set_status()`'s UPDATE used `execute_with_tenant` (the read-only helper, which never commits) instead of a write helper.** The bulk approve/reject UPDATE...RETURNING would appear to succeed within the request (rows returned from the still-open transaction) but was never durably committed — a silent-failure risk masked by connection reuse across requests. No existing `shared/db.py` helper supported a multi-row write-with-commit, so added `execute_write_with_tenant_many()` (mirrors `execute_write_with_tenant` but returns every row, not just the first) and switched `bulk_set_status()` to it.
- **Bug found and fixed (frontend): a failed reject left its error invisible.** `PackingListDetail.tsx`'s `RejectModal` and `PackingListList.tsx`'s `BulkRejectModal` only called `setShowRejectModal(false)` on the success path — on failure the modal stayed open with no indication anything happened, since the page-level error banner rendered underneath the still-open modal overlay. Approve had no such bug (no modal in its path). Fixed by threading the `error` state into both modals as a prop, rendered inside the modal (same pattern `ManifestDetail.tsx`'s `VerifyManifestModal` already used in 7.3); also clears stale errors when a modal opens. Covered by new tests in both `PackingListDetail.test.tsx` and `PackingListList.test.tsx`.
- **`wrong_status:draft` on bulk approve/reject (fixed, two-layer fix).** If a user selected a draft packing list and tried to bulk approve/reject it, the backend returned `failed: [{reason: "wrong_status:draft"}]`. Fixed at two layers: (1) `Table.tsx` now supports a per-row `selectable?: boolean` field — `PackingListList.tsx` sets `selectable: pl.status === 'pending_approval'` so checkboxes only appear on rows that can legally be bulk-actioned. (2) `PackingListDetail.tsx` adds a "Submit for approval" button (visible when `status === 'draft' && items.length > 0 && canEditPackingList(pl)`) so the user can advance a saved draft to `pending_approval` status from the detail view — previously impossible without going back through the create wizard.
  - **Correction (2026-09-06):** (1) above overcorrected — excluding `draft` from `selectable` entirely meant the list's own **bulk** "Submit for approval" button (`bulk_submit_packing_lists`, added the same day, draft-only) could never be clicked with a selection it would accept; draft rows had no checkbox at all. `selectable` is now `pl.status === 'pending_approval' || pl.status === 'draft'`, and a new `submittableCount` (same pattern as `approvableCount`) disables the button and shows the real submittable count rather than the raw selection size. Found by an e2e test attempting to select a draft row.
- **Edit & resubmit expanded to all item fields + add/remove items.** The edit mode in `PackingListDetail.tsx` previously rendered one `<input>` per row (description only). It now uses the shared `Table` component with inline inputs for all editable fields: description, weight actual (kg), L×W×H cm (with live CBM computation), declared value (USD). The "Add item" button appends a new blank row; each row has a ✕ button to remove it (disabled on the last remaining row). The backend's `PUT /v1/packing-lists/{id}` deletes all existing items and re-inserts from the submitted list — item `id` values are ignored server-side and carton tags are reassigned fresh — so add/remove work without any new API contract.
- **`GET /v1/packing-lists` list now includes `container_number`, `carton_count`, and `total_cbm`.** These were absent from the list response (only computed by `_assemble_response` for single-record endpoints). The repo query now joins `container` for the number and aggregates `packing_list_item` for counts/totals in a single subquery. `PackingList.container_number` added to the frontend type; list cell now shows `pl.container_number ?? pl.container_id`.
- **`PATCH /v1/manifests/{id}/revoke-verification` added.** Transitions `verified → pending`, clearing `verified_by`/`verified_at`. Available to china, nigeria, and tenant_admin. `ManifestDetail.tsx` shows a "Revoke verification" outlined danger button when `canRevokeVerification` is true, which opens a confirmation dialog before calling the API. `manifestRules.ts`'s `canRevokeVerification()` covers all role/status guard logic; 3 new unit tests in `manifestRules.test.ts`.
- **Revoke-verification is blocked once the container is sealed.** `canRevokeVerification()` additionally checks `manifest.container_status === 'loading'` — the button is hidden for any container that has advanced past `loading` (sealed, in_transit, etc.). Both `GET /v1/manifests` and `GET /v1/manifests/{id}` now include `container_status` in the response (joined from `container`). The backend also enforces this with a 422 `CONTAINER_ALREADY_ADVANCED` guard in `service.py`. Tests in `manifestRules.test.ts` cover the sealed/in_transit block and the loading allow case.
- **Bug: "Advance to Sealed" sent `{ status: "sealed" }` but backend expects `{ new_status: "sealed" }`.** The tracking handler reads `body.get("new_status", "")` — with the wrong key, `new_status` was an empty string, producing "Cannot transition container from 'loading' to ''". Fixed by renaming `UpdateContainerStatusInput.status → new_status` in `tracking.ts` and updating the `ContainerDetail.tsx` modal submit accordingly.

#### Prototype-compliance pass (China screens, Section 5 of `Shipx_frontend_design/`)

A dedicated pass aligning the China Office screens to the design prototype (`screens/china/china-screens.jsx` + `shared/app-shell.jsx`). Changes:

- **Shell header + nav now match the prototype.** `StaffLayout.tsx` derives the TopBar breadcrumb (`Operations / Containers`) and title from the current route via `navConfig` + `routeTable`, and enables the global search box (~~a page-driven slot, removed 2026-11-16; now `GlobalSearch`~~) — previously the TopBar rendered empty (`search={false}`, no title/breadcrumb). Title is **suppressed on form routes** (`…/new`, `…/import`) and on detail routes (dynamic `:id`, which never match a static path) so the body `PageHeader`/hero stays the single heading — matching the prototype, which blanks the topbar title on those screens. `ContainerList.tsx` and `PackingListList.tsx` dropped their in-body `PageHeader` title (now carried by the TopBar) and keep only a right-aligned actions row. Covered by 2 new `StaffLayout.test.tsx` cases.
- **China sidebar regrouped** to the prototype's three labeled groups: **Operations** (Containers, Create container), **Packing lists** (All packing lists, Create packing list), **Coordination** (Manifests, CBM disputes). Was a flat ungrouped list. `navConfig.ts` + `AppSidebar.test.tsx` updated.
- **`ContainerList` stat row + chips** — see the revised aggregate-count note above.
- **`ContainerList` status column** uses the shared `Badge` (was a bespoke dot+text `statusCell`); route cell shows color-coded origin→destination mono codes.
- **`ContainerDetail` tracking stepper is two-tone** — China-side stages (`loading`, `sealed`) render `--color-info` blue, Nigeria-side green, per the prototype's `TrackingStepper`. Added a **Tracking tab** (stepper + `containersApi.events()` log table).
- **`ContainerDetail` Overview built out to the prototype (5.3).** Hero now shows a `container_type` badge (neutral, no dot) beside the status badge and vessel · voyage in the meta, plus an "Add packing list" action for china staff (alongside Advance). The Overview's second card was upgraded from a two-row "Total lists / Approved" summary to a full **Cargo summary**: 2×2 `SummaryTile`s (distinct Customers · Packing lists approved/total · Total cartons · Total CBM — all derived from the container's packing lists) plus a **utilization bar** (`totalCbm / capacity`, where capacity is inferred from `container_type` via `containerCapacityCbm()` — 20'≈33, 40'≈67, HC≈76, 45'≈86 m³; hidden when the type is blank/unrecognised rather than faking a %). A second grid adds a **Recent events** card (last 5 `containersApi.events()`, "View all →" jumps to the Tracking tab) and a **Customers on this container** dense table (packing lists grouped by customer → cartons + CBM + approved/pending, sorted by CBM). Covered by a new `ContainerDetail.test.tsx` case.
- **`PackingListDetail`**: hero shows the **customer name** (display font) as the title with container number + submitted date in the meta (was a mono "Packing list" placeholder + raw container UUID); added the green-tint **totals footer** (cartons · weight · CBM) and, on the rejected state, a **per-item Flag column** cross-referencing `approval_comments[].item_rejections` ("Re-check" badge / "OK").
- **`PackingListList`**: bulk-action bar restyled to the prototype's **Forest-green (`#0B2F0D`) bar** with white text (was a plain `Card`); added a **Submitted** column.
- **`CreatePackingList` wizard steps** match the prototype: each step shows a "STEP N" eyebrow, label, and sub-label, with a green-tint active background and a ring on the current step's circle; the Step 2 items table highlights the auto-computed **CBM (auto)** column header in green.
- **Deliberately not replicated** (no backing schema/endpoint): the Manifest/Documents tabs on `ContainerDetail` (5.3).

#### Full Section 5 compliance pass (second round)

A second compliance pass against `screens/china/china-screens.jsx` addressed all remaining structural gaps. Backend changes were made where the prototype required data that wasn't in the API.

**Backend (tracking/repository.py):**
- `list_containers` + `get_container_by_id` now return two new derived aggregates: `approved_packing_list_count` (approved PLs only) and `total_cbm_packed` (sum of `total_cbm` across all PLs). The search `q` parameter now also matches `vessel_name` and `voyage_number` in addition to `container_number`.
- `api/tracking.ts` types updated: `Container` gains `approved_packing_list_count?`, `total_cbm_packed?`.

**Backend (packing_list/repository.py):**
- `get_packing_list_by_id` now LEFT JOINs `tenant_user` three times (`tu_a`/`tu_r`/`tu_c`) to resolve `approved_by_name`, `rejected_by_name`, `created_by_name`.
- `list_packing_lists` now supports free-text `q` search: matches `cu.name ILIKE` or `c.container_number ILIKE` on the joined columns. `PackingListListParams.q?` added to the frontend API type.
- `api/packingList.ts` types updated: `PackingList` gains `approved_by_name?`, `rejected_by_name?`, `created_by_name?`.

**5.1 ContainerList:**
- Added "Vessel · voyage" column (two-line: vessel name + Voy XXX in mono).
- Added "Packing lists" column (approved/total, green when all approved).
- Added "CBM" column (total CBM packed).
- ETA cell now color-codes: today=warning, cleared=success.
- **Filter bar bug fixes (search/date-range were non-functional):** four bugs found root-causing a user report that the header search box, table search box, and the "Last 30 days"/"Filters" buttons all did nothing.
  - **Header search was a no-op app-wide, not just here.** *(Superseded 2026-11-16: the `onSearch` slot described here was removed; the header box is now the global search, `GlobalSearch`, and `ContainerList` keeps only its table search.)* `TopBar.tsx` had an `onSearch` prop wired to its input's `onChange`, but no caller anywhere in the app ever passed it — the search box (placeholder "Search tenants, users, containers…") never did anything on any page. `TopBarContext`/`useTopBarSlot` gained a third slot (`onSearch`, same set-on-mount/clear-on-unmount shape as `actions`), threaded through `StaffLayout.tsx` → `TopBar`. `ContainerList` passes `useTopBarSlot({ onSearch: setSearch })`, so the header box drives the exact same `search` state as the table's own search input (single source of truth, not two independent search implementations) — the table input also reflects text typed into the header box.
  - **Table search had no debounce** — every keystroke fired a new `GET /v1/containers?q=` request. Added a 300ms debounce (`useEffect`+`setTimeout`, the same pattern already used in `AdminCustomerList.tsx`): `search` (raw, drives both input boxes) → `debouncedSearch` (drives the actual query).
  - **The `q` search filter 500'd server-side** — a real backend SQL bug, not just missing debounce (see `10_api_tracking.md` for the root cause: `list_containers()`'s free-text OR-clause was double-prefixed with the `c.` table alias, producing invalid SQL). Every non-empty table/header search would have errored before this fix.
  - **"Last 30 days" and "Filters" buttons were fully decorative** (no `onClick`, no state). Added a new reusable `DateRangeFilter` design component (`frontend/src/design/components/DateRangeFilter.tsx` — button + preset popover, presets: 7/30/90 days + All time) wired to a new `created_after`/`created_before` pair on `GET /v1/containers` (see `10_api_tracking.md`). Defaults to **All time** — deliberately not defaulted to a 30-day scope, since the dev tenant alone has 200+ containers (`seed_stress.py`) and a silent default filter would hide most of them from a china_office_staff user. "Filters" opens a small popover panel with the same date-range presets plus a "Clear all filters" action (resets status chip, search, and date range together) — the only additional filter dimension the container list API supports today beyond status (chips) and free text (search box).
  - **"Cleared (30d)" stat card was mislabeled** — `stats.cleared` counted every cleared/at_warehouse/fully_released container ever, not just the last 30 days. Now scoped to `created_at` within the last 30 days client-side, over the already-fetched `allContainers` stats batch, matching its label.
  - Not fixed (flagged only): `BillingList.tsx`, `ClaimList.tsx`, `NotificationLog.tsx`, `TenantReports.tsx` have the identical dead calendar/filter button pattern — out of scope for this pass, tracked for a follow-up.
  - Tests: `ContainerList.test.tsx` (+4 cases — debounce, header/table search sync, date-range filter, Filters panel clear-all); `ContainerDetail.test.tsx`'s local `TopBarContext.Provider` test fixture updated for the new `onSearch`/`setOnSearch` fields (`TopBar.test.tsx`/`StaffLayout.test.tsx` needed no changes at the time — they don't construct a raw context value).

**5.1 ContainerList — Table sorting wired up + Filters panel rework (row 7.37):**
- **Table sort UI was fully dead app-wide.** The shared `Table` component (`design/components/Table.tsx`) already renders clickable sortable headers with chevron icons reflecting `sort`/`onSort` props, and the backend's `shared/pagination.py::build_paginated_query()` already accepted `sort_field`/`sort_direction` — but zero pages ever passed `onSort` to `Table`, and zero handlers read a `sort` query param; every `sortable: true` column (declared on 4 tables total) was decorative. Added a small shared `useTableSort` hook (`frontend/src/hooks/useTableSort.ts`) that drives the click-to-toggle-asc/desc state and derives the `sort`/`direction` query params, used identically by `ContainerList`, `BillingList`, and `ClaimList`. Sort changes flow into the page's React Query cache key (same mechanism as the existing `search`/`status` filters), so pagination resets to page 1 automatically.
- 'Container' (`container_number`) defaults ascending; 'ETA' (`estimated_arrival_date`) also defaults ascending (soonest-arriving first) — a forward-looking scheduling date, not a "when was this recorded" timestamp, so it does not follow the created/billed/filed-desc convention `BillingList`/`ClaimList` use for their date columns.
- Backend: `shared/pagination.py::ALLOWED_SORT_FIELDS` was missing `estimated_arrival_date` (the container table's real ETA column) and instead had `arrival_date`/`departure_date`/`total_amount_ngn` — none of which match any real column on any table in the schema, confirmed by grep against every migration. Removed the three dead entries, added `estimated_arrival_date`/`invoice_number`/`billed_at`/`reference`. See `10_api_tracking.md`.
- **Filters panel reworked** — the previous pass (row 7.36) put a duplicate date-range control in both the standalone calendar button and the "Filters" popover; removed the duplicate from the panel (the standalone button is now the only place date-created filtering lives).
  - Added a granular **status multi-select** across all 9 real statuses (`loading`…`cancelled`, via `CONTAINER_STATUS_LABELS`) — a second, independent entry point from the grouped quick-access chips above the table. Both write to the same `activeStatuses` state, so there is exactly one active status filter concept: picking in the panel visually clears whichever chip group was previously highlighted rather than silently ANDing with it.
  - **Backend bug found and fixed while wiring this up:** `GET /v1/containers?status=` only ever accepted a single value, but the frontend's grouped chips (e.g. "Cleared" = `cleared` + `at_warehouse` + `fully_released`) were already sending a 3-status array — `ContainerList.tsx` silently truncated it to `activeStatuses[0]` before it reached the API, so clicking "Cleared" only ever fetched `status=cleared` and dropped the other two statuses from the result set. Fixed on both ends: `status` now accepts a comma-separated list, matched via a parameterized `status = ANY(%(statuses)s)` (never string-interpolated) in `services/tracking/repository.py::list_containers`.
  - Added an **"Arriving" (ETA range) filter** as the second real filter dimension, backed by new `eta_after`/`eta_before` query params (same shape as the existing `created_after`/`created_before`). **Judgment call:** the task's suggested candidate, container `origin`, was checked via `psql` against the seeded dev tenant (`scripts/seed_stress.py`'s 200+ container Acme dataset) and found to have **zero variance** — all 208 containers are `origin = 'China'` (the stress-seed script never varies it; only `seed.py`'s 2 curated containers would). `vessel_name`/`shipping_line`/`container_type` were checked too and are NULL/near-constant for the same reason. `estimated_arrival_date` was the one column with genuine variance (62 distinct dates spanning ~4 months), so "Arriving in 7/30/90 days" + "Overdue" presets became the second filter dimension instead of origin.
  - "Clear all filters" resets the status multi-select, ETA preset, and search — but deliberately does **not** touch the standalone date-created button's state anymore, since that control now lives entirely outside the panel.
  - Tests: `ContainerList.test.tsx` (+6 cases — Container/ETA header sort toggle, Filters panel content, status multi-select override, Clear-all-filters scope).

**BillingList / ClaimList — Table sort wired up (row 7.37):**
- `BillingList.tsx`'s 'Reference'/'Billed' columns and `ClaimList.tsx`'s 'Claim ID'/'Filed' columns declared `sortable: true` but had no `onSort` handler — same dead-UI pattern fixed on `ContainerList` (see above), reusing the same `useTableSort` hook. 'Reference' (`invoice_number`) and 'Claim ID' (`reference`, the damage claim's human-readable `DC-YYYYMMDD-NNN` number) default ascending; 'Billed' (`billed_at`) and 'Filed' (`created_at`) default descending (newest first) — both are "when was this recorded" timestamps, unlike `ContainerList`'s forward-looking ETA. Only the sort wiring changed on these two pages in this pass — their calendar/Filters buttons were fixed in a later pass, below. Tests: `BillingList.test.tsx` (+2 cases), `ClaimList.test.tsx` (+2 cases).

**Every "calendar" filter, tenant-wide — made real (2026-09-07):** the user first asked to double-check `BillingList.tsx`'s date-range/Filters buttons (see `11_api_billing.md`'s multi-status + `created_after`/`created_before` fix and its Filters panel — same granular multi-select pattern as `ContainerList`'s), then asked directly: "I want all the filters that use calendar to allow date range. Check all pages where we are using calendar filter. Include date filter to them." Audited every page rendering a `calendar`-icon button:

- `ClaimList.tsx` and `NotificationLog.tsx` had a **static label with no `onClick` at all** ("Last 30 days") — pure dead UI, and neither backend (`services/claims/repository.py::list_damage_claims`, `services/notification/repository.py::list_logs`) supported a date filter to back one. Added `created_after`/`created_before` to both (see `12_api_claims.md`, `15_api_notifications.md`), then wired a real `DateRangeFilter` + custom range on each page.
- `TenantReports.tsx`'s "Last 3 months" button was the same dead pattern, and worse: the whole report always fetched **unscoped** `billing`/`containers`/`claims` data regardless of what the label implied — "Total revenue" and "Containers processed" never actually meant "this period." Wired the date range into all three underlying list calls (all now support `created_after`/`created_before`); `customerCount` (a registered-customers total) is intentionally left unscoped, since "how many customers exist right now" isn't a per-period metric. The date controls live in the shared TopBar action slot (`useTopBarSlot`), same as the page's existing Export button.
- `ContainerList.tsx` and `BillingList.tsx` already had a working preset (`DateRangeFilter`, 7/30/90 days/all time) but no way to pick an *exact* day or range — "everything billed on this one specific day" wasn't answerable by a preset alone, the same gap `ActivityLog.tsx` had already solved with its own hand-rolled custom From/To inputs. Added the same custom range to both.

**New shared hook: `frontend/src/hooks/useDateRangeFilter.ts`.** The preset+custom-date pairing logic (a custom date always overrides and clears the preset, and vice versa) had been hand-rolled once, in `ActivityLog.tsx`; duplicating it a fourth and fifth time crossed into real duplication, so it's now one hook returning `{ daysBack, dateFrom, dateTo, createdAfter, createdBefore, handlePreset, handleCustomFrom, handleCustomTo, isActive, clear }`, used by `ContainerList`, `BillingList`, `ClaimList`, `NotificationLog`, and `TenantReports`. Each page still renders its own `<DateRangeFilter>` + "From"/"To" `<input type="date">` pair using its own CSS module (`customDateWrap`/`customDateLabel`/`customDateInput`, identical class shape across all five modules), since each page's surrounding filter-bar markup differs; `ActivityLog.tsx` itself was left as-is (its category/action/search filters are more involved than a plain list page, and its custom-date inputs are already correct) rather than churned for a cosmetic refactor.

Verified live against the real local stack for every backend change: `GET /v1/claims?created_after=2099-01-01` → 0 of 12; `GET /v1/notifications/log?created_after=2099-01-01` → 0 of 8; both return the full count with `created_after=2020-01-01`. Tests: `TestListClaimsDateRange` (`test_claims.py`), `TestListLogsDateRangeRepository` + `TestNotificationLogHandlerDateRangeQueryParams` (`test_notifications.py`); `ClaimList.test.tsx` (+1), new `NotificationLog.test.tsx` (2 cases), new `TenantReports.test.tsx` (2 cases), `ContainerList.test.tsx` (+1), `BillingList.test.tsx` (+1). 690 backend + 674 frontend tests pass.

**5.3 ContainerDetail — Packing lists tab:**
- Added "Weight" and "Submitted" columns.
- **'Ref #' column sort wired up (row 7.37) — pure client-side.** Unlike `ContainerList`/`BillingList`/`ClaimList`, the packing-lists sub-table here is an already-fully-loaded in-memory array (`packingListApi.listByContainer(id)` for one container, not a paginated list endpoint), so clicking the header sorts the local array via `Array.prototype.sort` on `pl.reference` — no query param, no backend change. The `useMemo` computing the sorted array is declared before the component's loading/error/not-found early returns (hooks must run unconditionally every render — an earlier draft placed it after those returns and broke the rules of hooks under React's dev-mode double-render).

**5.5 PackingListDetail:**
- "Export PDF" and "Print" (window.print()) buttons added to the hero.
- Approved/rejected banners now show the approver/rejector name and full datetime (`Approved by Amara Okafor on 2026-04-16 at 11:30`) using the new `approved_by_name`/`rejected_by_name` fields.
- Rejected banner body describes the specific items to fix (matching the prototype's wording).

**5.6 PackingListList:**
- Added search field to the filter bar (searches customer name + container number via the new `q` backend param).
- Submitted column now shows date + time (e.g. "28 Jul, 14:22") instead of date only.

**5.4 CreatePackingList Step 3:**
- Added the "Document preview" card: a print-accurate in-page rendering of the packing list (tenant logo placeholder, PACKING LIST header, customer/container grid, item rows with dimensions/CBM/USD, and totals). All data drawn from component state — no new API needed.

#### Step 2 (Carton items + live pricing) full build

The 5.4 Step 2 screen was brought to prototype parity:

- **Context bar** now shows the customer avatar + name + phone and the container icon + number + vessel/ETA, plus a "Draft — assigned on save" badge (was just `name · number`).
- **`Wt dispatch (kg)` column added** alongside `Wt actual (kg)` — both are backed by `packing_list_item.weight_dispatch_kg` / `weight_actual_kg`; the totals footer sums each. `weight_dispatch_kg` was already on `PackingListItemInput`; the wizard just wasn't capturing it.
- **CBM cell** is now the prototype's green chip (`--color-primary-soft` bg); **Import CSV** button (→ `/packing-lists/import`) added to the header and an **Add another carton** ghost button to the card footer.
- **Live pricing card** (4 tiles: Total CBM · CBM rate · Shipping USD · Shipping NGN highlighted) — computed as `ΣCBM × cbm_rate_usd × fx_rate`. Rates come from `configApi.getCbmRate()` + `getDollarRate()`, fetched on wizard mount and swallowed on failure so pricing degrades to "—" without breaking the create flow. **This required a backend auth change**: `GET /v1/tenant/{dollar-rate,cbm-rate}` was widened from tenant_admin-only to also allow china/nigeria office staff (see `07_api_tenant_management.md`) — writes stay admin-only. Covered by a new `CreatePackingList.test.tsx` case (CBM $48/m³ × FX ₦1,650 → $1.44 / ₦2,376 for a 0.030 m³ carton).

#### Backend work to unblock the wizard's rich pickers (migration 030 + derived counts)

The prototype's Step 1 customer/container picker cards and 5.2 create form need data the schema didn't have. Rather than fake it, the backing was added:

- **Migration 030** adds `vessel_name`, `voyage_number`, `shipping_line`, `seal_number`, `container_type` (all nullable) to the `container` table. `services/tracking/{repository,service}.py` `create_container()` persists them; `CreateContainer.tsx` (5.2) now captures them in "Container details" + a new "Vessel & voyage" section; `ContainerDetail.tsx` shows them in the hero meta (vessel · voyage) and the Container-info Kvp block. `Container`/`CreateContainerInput` types updated in `tracking.ts`.
- **Derived `packing_list_count`** on `GET /v1/containers` + `/{id}` (correlated `COUNT(*)`), for the container picker card's "N PLs".
- **Derived `shipment_count`** on `GET /v1/customers` (correlated `COUNT(*)` over `packing_list`), for the customer picker card's "N shipments lifetime". `Customer.shipment_count?` added in `tenantManagement.ts`.
- Docs updated: `05a_database_schema_core.md` (container DDL + derived field), `10_api_tracking.md` (create body table + `packing_list_count`), `07_api_tenant_management.md` (`shipment_count`), and the Postman "Create Container" body (which also had stale `origin_port`/`destination_port`/`expected_arrival_date` keys — corrected to the real `origin`/`destination`/`estimated_arrival_date` contract).
- **Still to build (the "come back" work):** the actual Step 1 picker **cards** (avatar + phone + shipment/PL counts, replacing the plain `<select>`s) and the Step 3 **review + document preview** now that all the data they display is available.

---

## Implementation notes — vital-gap pass (2026-07-09)

Cross-checked against the prototype's section/subsection map (Section N HTML titles). Landed in one pass, all backend-ready unless noted:

- **1.2/1.3/1.4 Auth trio** — `RegisterScreen`, `ForgotPasswordScreen`, `ResetPasswordScreen` (new, on a shared `AuthShell` extracted from LoginScreen). `CognitoClient` gains `forgotPassword`, `confirmForgotPassword`, `completeNewPassword` + a `NewPasswordRequiredError` signIn challenge path; LoginScreen's dead "Forgot password?"/"Register here" links wired. **Ground-truth divergences (deliberate):** registration has *no password fields* — the backend provisions Cognito and emails a temporary password (first sign-in then routes through `/reset-password?first=1`); forgot-password emails a *code*, not a link.
- **10.7 Customer Account** — full 3-tab rewrite (`Account.tsx`): Profile (phone/whatsapp self-service; name/email locked), Notifications (channel-consent toggles → `notification_consent`), Privacy (JSON export download, consent summary, typed-DELETE erasure that logs out on success). Backend widened for self-service (see `07_api_tenant_management.md` note — includes the customer-list PII-scoping security fix).
- **7.2 BillingDetail misc-charges** — `AddChargeModal` (presets from charge types w/ default-amount pre-fill + total-impact banner), id'd charge rows with tenant_admin remove (unpaid only). New `billingApi.listMiscCharges/addMiscCharge/deleteMiscCharge`. **B8 (2026-07-13):** when a configured charge type is picked, the modal now sends `charge_type_id` so the charge is attributed to that type for §4.4 usage counts (free-form "other" stays unattributed).
- **5.3 Container Documents tab** — `DocumentsTab` in `ContainerDetail` (list, presigned-S3-POST upload modal, short-lived download links). New `containerDocumentsApi` + `uploadToPresignedPost` in `api/tracking.ts`.
- **7.4 Carryover Ledger** — new `/billing/carryovers` page: status chips, outstanding totals, tenant_admin exempt modal.
- **4.4 Charge Types** — new `/admin/config/charge-types` CRUD page (create/edit modal, deactivate). **B8 (2026-07-13):** added a "Times used" column fed by `usage_count` (misc charges attributed via `charge_type_id`, migration 035). **Also fixed a wire-contract bug** the page shipped with: the frontend sent/read `amount_ngn` while the backend repo wrote/read the `default_amount_ngn` column with no mapping, so charge-type amounts were silently dropped on save and shown as blank/NaN — the service now maps `amount_ngn` ↔ `default_amount_ngn` at the boundary.
- **2.1 Platform Dashboard** — new `/platform/dashboard`: cross-tenant stats, tier mix, tenant-health table. Activity feed deferred (no backend endpoint).
- **14.7 Platform Audit Log** — new `/platform/audit-log`: tenant filter, action badges, expandable JSON details, cursor pagination. New `platformApi.dashboard/auditLog` bindings.
- **10.4 Customer CBM dispute** — `CbmDisputeModal` on `MyBillingDetail` + open-dispute banner (one active dispute per billing enforced server-side).
- **10.4 Download invoice (2026-07-19)** — `MyBillingDetail.tsx`'s Invoice breakdown section gained a "Download invoice" button (`billingApi.export(id, 'pdf')`, opens in a new tab). Previously there was no way for a customer to actually download an invoice at all — `PaymentSuccess.tsx`'s "View invoice" button only navigated to the on-screen billing detail, and `GET /v1/billing/{id}/export` was staff-only. See `19_excel_import_export.md`'s ground-truth fix note for the backend ownership-check details.
- **4.6 Payments config — multi-tenant Paystack (2026-07-19)** — new `/admin/config/payments` (`PaymentGatewayConfig.tsx`, added to `ConfigLayout`'s sub-nav), modelled on `WebhookConfig.tsx`. Each tenant connects/replaces/disconnects their own Paystack secret key (masked status card — last4 + test/live badge, never the real value round-tripped), plus a "Test connection" button that makes a real live Paystack API call (not just a shape check). New `configApi.updatePaystackConfig/deletePaystackConfig/testPaystackConnection` bindings and a `PaystackConfig` type on `TenantConfig`. This replaces the old single platform-wide `PAYSTACK_SECRET_KEY` — see `07_api_tenant_management.md`'s "Multi-Tenant Paystack" design note for the full backend rationale (encryption choice, webhook-verification reordering, no fallback). Customer-side `MyBillingDetail.tsx` needed no changes — its existing generic `ApiError` → `payError` banner already surfaces the new `PAYMENT_GATEWAY_NOT_CONFIGURED` message when a tenant hasn't connected a key yet.


## Implementation notes — platform admin functionality repair (2026-07-18)

- **Impersonation ("Impersonate" on §2.4 tenant detail) never worked end-to-end** — four stacked bugs, each masking the next: backend `_get_tenant_admin()` selected non-existent `tenant_user` columns (500 on start); `platformApi.impersonate` typed the response as `id_token` where the wire field is `token` (undefined token stored); `buildSession()` threw on the raw impersonation-claim shape (bare `tenant_id`/`role` vs Cognito's `custom:tenant_id`/`cognito:groups` — now accepted as a fallback); and `LocalAuthProvider.startImpersonation` was a hard `throw`. The dev shim now supports the full loop (Bearer token + `X-Token-Type: impersonation`, auto-exit at the 30-min expiry), `local_server.py` maps impersonation claims like the production authorizer, and the read-only guard was verified live (mutations 422). Regression test: `jwt.test.ts` "parses a raw ShipX impersonation token".
- **Platform audit log (§14.7) was permanently empty** — `platform_audit_log.actor_id`'s FK to `tenant_user(id)` rejected every insert (platform admins have no `tenant_user` row by design); the error was swallowed with a warning. Migration 037 drops the FK; suspend/activate/create/offboard now appear in the feed.

## Implementation notes — audit pass 2 closure (2026-07-16)

- **B3 layout completion (§3.1 + §6.1, 2026-07-16)** — the admin dashboard's bottom half never matched the prototype: it had three generic nav-button stacks instead of §3.1's QuickActionCards, and Recent containers sat full-width instead of the two-column main. Now: two-column main (Recent containers w/ vessel subline + Activity feed), bottom row PlanUsagePanel + QuickActionCards (**Add customer** / **Invite staff** — accent / **Update dollar rate**; "Create container" swapped out because `POST /v1/containers` is china-staff-only). Quick actions deep-link with router state (`openAdd` / `openInvite`) and the target lists auto-open their modals. `QuickActionCard` extracted to `design/components/` and the platform dashboard's inline copy refactored onto it. Nigeria §6.1 bottom row completed too: Recent payments + Incoming containers (sealed/in_transit, soonest ETA first) in a responsive two-column grid (`.dashGrid2`, collapses ≤1080px). China staff have no dashboard by design — §5.1's landing screen is the Container List, which is what `/containers` already is.

- **P2-1 customer notification language** — `customer.locale` (migration 029) was read by `tracking/service.py` to pick the EN/ZH template set but had **no write path anywhere**. Backend: added to `_CUSTOMER_UPDATE_FIELDS` + the customer self-service PATCH allowlist, validated against `_SUPPORTED_LOCALES`. UI: EN/中文 radio picker on the customer Account Notifications tab (saved with consent) and an inline select on `AdminCustomerDetail`'s Consent & GDPR card.
- **P2-2 warehouse dashboard (§9.3)** — scan-or-type reference lookup block (text input covers handheld scanners with no camera code; active match opens the pickup sheet, other statuses navigate to the detail; backend gained a `?reference=` exact-match list filter), real "Completed today" (counts `picked_up_at` = today; the old stat was session-local 0/1), "Expired · not collected" stat, urgency chips + age labels + oldest-first sort (urgent >24h from `authorized_at`). **Shipped-bug fix:** the release-note LIST endpoint returned raw DB rows (`total_cartons`/`is_partial`/`created_at`) while the frontend read the detail shape (`carton_count`/`is_partial_release`/`authorized_at`) — ReleaseNoteList crashed against real data; the list now maps rows through `_fmt_release_note` (billing joined for `payment_status`). Also: `GET /v1/release-notes`, `/split`, `/reissue` were missing from the Terraform route map (prod 404s).
- **P2-3/P2-4 list stats rows** — new aggregate endpoints `GET /v1/release-notes/stats` and `GET /v1/manifests/stats` (single `FILTER`ed queries) feed 4-card stats rows on both lists; manifest stats include the B11 `overdue` count (predicate now shared via `manifestRules.isManifestOverdue`). Rows hide when the endpoint fails.
- **P2-5 Nigeria dashboard queues (§6.1)** — "Containers awaiting manifest verification" (B11 predicate), "CBM disputes need response" (submitted, 24h SLA), "Recent payments" (new staff-only `GET /v1/billing/payments`), "Ready for pickup" stat. Queues render only when non-empty.
- **P2-6 responsive grids** — final four fixed `fr` grids (`TenantReports`, `CreatePackingList` + `.previewMeta`, `CreateContainer`, `ContainerDetail` + `.summaryGrid`) collapse to one column ≤860px via `@container sxapp`.

## Implementation notes — remainder pass (2026-07-09, pass 2)

Everything left in the compliance review after the vital-gap pass (the review doc was retired 2026-07-15 once fully closed — see `AUDIT_GAPS.md`; history in git), plus the three backend endpoints:

- **Backend B-1/B-2/B-3** — provider gateway configs (`{sms,whatsapp,email}-gateway` PUT + test, secrets masked with `****` round-trip), plans CRUD, per-tenant quota-override. All persisted in `platform_settings`; `shared/tier_limits.get_effective_limits()` merges tier defaults → plan overrides → tenant override and now backs both metering limit checks and `GET /v1/tenants/me/quota`. Two new platform read routes for the TenantDetail tabs (`…/users`, `…/config`); local dev routes `…/usage` to the metering handler.
- **2.5 Platform Settings** (`PlatformSettings.tsx`) — General / Notification providers / Plans & limits sub-pages on one component across three routes.
- **2.4 TenantDetail tabs** — Overview / Users / Usage & quota (quota bars + override form) / Config (read-only) / Audit.
- **2.3 Create-tenant wizard** (`CreateTenantPage.tsx`) — plan radio cards + success screen at `/platform/tenants/new`. **Bug fixed:** the old modal's flat body never matched `CreateTenantRequest` (nested `initial_admin`) — creates always 422'd. `CreateTenantInput` corrected.
- **4.2/4.3 Rate history** — shared `RateHistoryTable` (delta, changed-by, Current badge) on Dollar + CBM pages; sourced from `/v1/tenant/rate-history` (migration 025).
- **6.1 NgOps kanban** — `PipelineKanban` (8 stage columns, hover-lift cards) + submitted-PL approval queue on the Dashboard for nigeria_office_staff.
- **7.2 breakdown** — dispute-adjustment (when non-zero) + Total-paid + Outstanding rows.
- **8.2 resolve modal** — 2×2 `ResolutionPick` radio cards + auto-refund banner. Deliberate: ₦ input kept (backend contract); USD+auto-FX and internal-notes need backend fields first.
- **3.4 permissions matrix** — static per-role ✓/✕ capability list on StaffUserDetail, mirroring handler role gates.
- **4.5 WhatsApp preview** — live bubble preview in the template editor.
- **1.1 login** — dedicated deactivated-account banner (Cognito "User is disabled"); tenant-suspension intentionally still surfaces post-login (login never touches our backend).
- **14.12 print layouts** — `/packing-lists/:id/print` + `/release-notes/:id/print`, shell-less guarded routes (`layout: 'none'` branch added to `elementForRoute`), A4 `@page` CSS, print-hidden toolbar; release note includes carton checklist, signature lines, and an EXPIRED stamp.
- **Deferred:** manifest-verify photo upload (F-D3) — needs a manifest-scoped presigned-upload contract.

## Implementation notes — marketing landing page (2026-07-10)

Prior to this, `/` unconditionally redirected signed-out visitors to `/login` — there was no public marketing surface, unlike every other design-prototype file, which lived under `screens/` and had already been implemented. The landing prototypes sit outside `screens/` and were never assigned to a numbered task, which is why they were missed in the earlier gap-closure passes. Implemented against **`Shipx Landing Page v2.html`** (same content as v1, plus the motion/polish layer); verified pixel-equal to the prototype at 1280px (identical 5958px full-page height, diff mask shows only text anti-aliasing).

- `pages/marketing/LandingPage.tsx` + `LandingPage.module.css` — full single-page port (nav, hero, route strip, problem/solution, features, roles, how-it-works, pricing, CTA band, footer). Colours mapped 1:1 from the prototype's hardcoded hex onto existing design tokens (`--color-primary`, `--color-accent`, `--color-forest-dark`, etc.) rather than duplicating raw hex — passes the CI "no token-duplicating hex" guard. (The only literal hexes are the v2 gradient stops with no token equivalent: `#b13e15`/`#a83a0e` accent-button and `#229329`/`#24a02c` primary-button gradients.)
- **v2 motion layer** — gradient buttons with inset-highlight shadows + hover bloom, glassy nav (`blur(18px) saturate(1.4)`), animated hero glow orb (`heroGlow` 9s) + masked dot-grid overlay, pulsing eyebrow dot, staggered hero entrance (`heroIn`, delays .08–.34s), marching-ants route line (`flow`) with ▸ arrowhead, hover lifts + icon `scale(1.08) rotate(-3deg)` on feature cards, featured price card white→tint gradient, CTA band dot-grid.
- **Scroll reveal** — `useScrollReveal` hook in `LandingPage.tsx` mirrors the prototype's inline script: 29 `data-reveal` targets get `.reveal`/`.revealIn` via `IntersectionObserver` (`rootMargin '0px 0px -8%'`, threshold .08) with a sibling-index stagger. The hidden state is styled only under `@media (prefers-reduced-motion: no-preference)` and classes are added by JS, so reduced-motion users and non-JS paths always see fully visible content (verified with `emulateMedia({ reducedMotion: 'reduce' })`).
- `shell/routes.tsx` — `RootRedirect` now renders `<LandingPage />` for signed-out visitors instead of `<Navigate to="/login" />`; signed-in visitors still redirect to their role home unchanged. See [06_routing_rbac_and_navigation.md](06_routing_rbac_and_navigation.md).
- CTAs use plain `<Link>`/styled `<a>` elements (a local `CtaLink`/`CtaAnchor` pair), not the design system's `Button` — `Button` renders a `<button>`, and these are navigational (route change / same-page scroll / `mailto:`), so wrapping them in `Button` would nest an anchor inside a button (invalid HTML, breaks keyboard/AT focus).
- `e2e/smoke.spec.ts` and `App.test.tsx`/`shell/routes.test.tsx` updated: the apex path now asserts the landing hero heading instead of the login screen; a second smoke test clicks the landing page's "Sign in" link through to confirm `/login` is still reachable.
- **Ground-truth bug found & fixed while verifying pixel parity**: `design/tokens.css`'s "semantic aliases" block (`--color-text` etc.) sat outside any selector; CSS error-recovery consumed everything up to the next block — which was the global `* { box-sizing: border-box }` rule. The whole app was silently running content-box, and the alias tokens never existed (11 page stylesheets referenced them). Wrapped the aliases in their own `:root {}`; this also silenced the long-standing esbuild css-syntax-error warning on every build. See [02_design_tokens_and_theming.md](02_design_tokens_and_theming.md).

## Implementation notes — audit gap A1: Company Settings (2026-07-11)

§4.1 was the audit's headline gap: `/admin/config` was only a navigation hub — tenant admins had no way to set their company identity anywhere in the app, despite `PUT /v1/tenant/config {branding}` and `ThemeProvider` both existing unwired.

- `pages/tenant-admin/CompanySettings.tsx` (+ module CSS) now owns `/admin/config`: three form cards (Company identity / Warehouse & contact / Document footer), a brand-colour field with hex validation, and the prototype's sticky **live document preview** (Packing list / Release note toggle) rendered from live form state. `ConfigOverview.tsx` was deleted; its hub navigation lives on as the prototype's `ConfigSubNav` rail (exported from `CompanySettings.tsx`, links to dollar/CBM/charges/notifications/webhooks).
- Branding shape: `BrandingConfig` in `api/tenantManagement.ts` (display_name, tagline, primary_color, warehouse_address, pickup_hours, pickup_phone, support_email, support_whatsapp, document_footer) → stored as-is in `tenant.branding_config` JSONB. `useBranding()` / `useSaveBranding()` in `hooks/useConfig.ts`; the save mutation writes the PUT response straight into the query cache (no refetch race).
- **Consumers wired the same pass** (the preview is honest, not aspirational): `PrintPackingList` / `PrintReleaseNote` render the tenant's identity via `print/PrintBrand.tsx` (initials tile + name + tagline in the header, `document_footer` boilerplate above the ShipX attribution line, pickup address block on release notes; ShipX lockup remains the fallback when no branding is set) — and `StaffLayout` mounts `ThemeProvider` with `branding_config.primary_color`, so the staff shell takes the tenant's brand colour. Platform admins keep the canonical palette; while impersonating, the shell correctly shows the impersonated tenant's brand.
- Backend: `GET /v1/tenant/config` read-widened to all staff roles (see [07_api_tenant_management.md](../07_api_tenant_management.md)) so documents render for whoever prints them.
- Divergences (tracked in AUDIT_GAPS.md): logo is an initials tile + brand colour, not an uploaded image — no tenant-scoped upload endpoint exists yet (the only presigned route is claim-scoped). Customer-portal theming deferred: the config response includes the webhook endpoint URL, so customers need a branding-only read model first.
- Tests: `CompanySettings.test.tsx` (hydrate/save/dirty-guard/hex-validation/sub-nav/preview), `PrintBrand.test.tsx` (tenant header, ShipX fallback, footer lines), backend guard matrix in `TestTenantConfigReadAccess`.
- **UX decision — routed sections in a shared layout (2026-07-11):** the prototype renders every config screen with the same left rail, which reads as "one page with tabs." Implemented as `ConfigLayout.tsx`: all six `/admin/config/*` routes render inside it (wired in `routes.tsx`), so the rail persists and only content swaps — tab-like feel without giving up per-section URLs, deep links (billing screens link straight to `/admin/config/dollar-rate`), browser back/forward, or refresh-restores-position. Local tab state on a single page was considered and rejected for exactly those losses.

## Implementation notes — audit gap B5a: Add customer (2026-07-11)

`AdminCustomerList` now has the prototype 3.5 "Add customer" action — previously staff had no way to create a customer from the UI at all despite `POST /v1/customers` existing (customers could only enter via self-registration). `AddCustomerModal`: full name (required), phone / email / WhatsApp (optional), and NDPR/GDPR notification-consent checkboxes (SMS pre-ticked, with copy telling staff to only tick channels the customer actually agreed to — this writes the customer's `notification_consent` consent record). On success the list cache is invalidated and the admin lands on the new customer's profile. `customersApi.create`'s body type gained `whatsapp` + `notification_consent` (backend `create_customer` already persisted both).

## Implementation notes — audit gap A4: tenant offboarded/suspended gate (2026-07-11)

Prototype 16.12's "Account closed" page is now real, and it covers the 403 `TENANT_SUSPENDED` sibling too. Mechanism: `shared/auth.py` fails **every** request identically once a tenant is suspended/offboarded (fail-closed), so per-page error banners were the wrong shape — the user saw raw errors on every screen. Now `api/client.ts`'s error parser reports the code to `auth/tenantGate.ts` (module-level store, same pattern as tokenStore/sessionBridge, consumed via `useSyncExternalStore`), and `TenantBlockedGate` — mounted in both StaffLayout and CustomerLayout — replaces all routed content with the full-page state: variant copy for closed vs suspended, Contact-support mailto, Sign out (so a user with another account can leave), and the `HTTP 410 · TENANT_OFFBOARDED` / `HTTP 403 · TENANT_SUSPENDED` footnote. The gate resets on every session transition alongside `queryClient.clear()`. Note: an impersonating platform admin who hits an offboarded tenant sees the same gate — Sign out is their exit; acceptable for now since impersonating a non-active tenant is an edge case the backend mostly rejects earlier.

## Implementation notes — audit gap A2: Customer Profile tabs (2026-07-11)

`AdminCustomerDetail` rebuilt to prototype 3.6's structure: hero (Avatar, name, Active/Anonymised badge, phone · email · "Customer since") + tab strip — Profile / Shipments / Billing / Claims / Data & privacy. Profile carries the contact Kvps, an NDPR/GDPR consent card (consent date, channel badges, anonymised-at), and lifetime stat cards computed from the customer-scoped queries. Shipments/Billing/Claims are per-customer tables deep-linking to the respective detail pages. The GDPR export + ANONYMISE-erasure flows moved from header buttons into the Data & privacy tab, friction unchanged. Backend addition (authorized backend work): `GET /v1/claims` now accepts a `customer_id` filter for staff — the repo already supported it; the handler param is harmless for the customer role because `list_claims` always overwrites the filter with the caller's own record (regression-tested). `Customer.created_at` and `ClaimListParams.customer_id` added to the API types. Skipped: prototype's "Recent activity" table (needs a tenant-scoped audit endpoint — tracked under B3/B6).

## Implementation notes — audit gap A3: Customer Shipment Detail (2026-07-12)

`MyShipmentDetail` rebuilt to prototype 10.2's zones (hero / tracking stepper + status hint / my-cartons / billing summary with Pay CTA / file-a-claim prompt; Documents zone deferred per AUDIT_GAPS). The rebuild surfaced that the page had **never worked**: it fetched `/v1/track/{code}` — no such route exists in API Gateway, the backend handlers, or `local_server.py` (the real public route is `GET /v1/shipments/{code}?phone=`) — so every load 404'd into the error banner; the same dead path broke the public `/track` page (`publicTrackingApi.lookup` corrected). Data flow now: `/my-shipments/:code` carries the packing-list id (MyShipments navigates with `pl.id`, not `pl.reference`), the page loads `GET /v1/packing-lists/{id}` (customer-own enforced in `get_packing_list`) for cartons + container status, and matches the customer's own `billingApi.list()` by `container_id` for the billing card. Pay CTA routes to the existing `/my-billing/{id}` pay panel. `CustShell` now declares the `sxapp` container-query context (the customer shell previously had none, so customer-page container queries silently never applied).

## Implementation notes — audit gap A5: advance-status confirmation (2026-07-12)

`AdvanceStatusModal` (ContainerDetail) is now the prototype 6.4 two-step flow. Step 2 spells out the customer-facing side effects **before** anything fires, keyed to what `services/tracking/service.py` actually does: advancing to `at_warehouse` enqueues a container-arrived notification to every customer on the container, and `cleared` publishes PaymentDue per customer (billing + payment-due notifications downstream) — those two stages get a warning banner with the distinct-customer count and channels, and the confirm button becomes "Confirm & notify"; all other stages get an explicit "no customer notifications are sent at this stage" note. Divergence: the prototype's rendered SMS/WhatsApp/Email message previews are skipped — rendering templates client-side would duplicate backend template logic; the count + channel warning addresses the actual risk (accidentally notifying a whole container of customers).

## Implementation notes — MyShipments only showed one active shipment (2026-09-06)

`MyShipments` computed `activeShipments` (any container status in `ACTIVE_STATUSES`) correctly, but then only ever rendered `activeShipments[0]` as a single "Active shipment" feature card — every other active shipment a customer had was silently dropped from the page entirely (not even listed in a table; the "Past shipments" table only covers `fully_released`/`cancelled`). Found live testing a real customer account with 3 simultaneously active shipments (one `sealed`, two `loading`) — only the first ever appeared. Fixed by rendering the same rich card (stepper, ETA, cartons/CBM/cost stats, "View details" CTA) once per active shipment in a vertical stack (`.activeList`, new in `MyShipments.module.css`) instead of picking a single "primary" one; the greeting and `SectionHead` copy now reflect the actual count (`Active shipments (3)` vs the singular `Active shipment`). No backend change — the API already returned all of them; the bug was purely in how the page indexed into the array.

## Implementation notes — claims could be filed before a shipment arrived (2026-09-06)

Reported directly by the user: a customer could file a damage claim against a
container that hadn't even left China yet. `MyClaimsNew.tsx`'s step 1 was a
free-text "Container ID or number" field with no status awareness at all, and
`services/claims/service.py::file_claim` had no server-side check either — see
`12_api_claims.md`'s matching ground-truth-gap entry for the backend fix
(`CONTAINER_NOT_ARRIVED`, 422). Redesigned step 1 as a dropdown of the
customer's own shipments (from `packingListApi.list()`), filtered to
`ARRIVED_STATUS_LABEL`'s five arrived-or-later statuses (mirrors the
backend's `_PRE_ARRIVAL_STATUSES` complement) — a non-arrived shipment is
never offered, rather than being submitted and rejected after the fact. A
customer with nothing eligible sees an explanatory banner ("Nothing to claim
against yet … check back once your shipment shows as arrived") and no way to
submit, instead of a dead-end error. Verified live: a customer with 3
pre-arrival shipments sees zero options and can't proceed; a customer with a
mix sees only the arrived ones in the dropdown and can file successfully.
Covered by `MyClaimsNew.test.tsx` (new).

## Implementation notes — Activity Log UX + information-boundary fixes (2026-09-07)

Third same-day round of direct feedback on the Activity Log. (1) The filter bar's search box looked misaligned next to the dropdowns — root cause was using the `Field` design component (which carries its own label spacing and a `fieldRoot` bottom margin) alongside plain `<select>` elements with a different label/box convention; replaced with a plain input sharing one `selectStyle`/`filterLabelStyle` pair (explicit `height: 36` matching `Button`'s default size, since the "When" date-range control in the same row renders one) so every control in the row now shares an identical box height and bottom edge. (2) "Details" opened a block appended after the entire table — clicking it on any row but the last meant scrolling well past the list, and the diff's position moved with whichever row was clicked; replaced with a `Modal` that always opens in the same place. (3) The Record-type dropdown offered "Impersonation" as a filterable option — reported as irrelevant, and (see `07_api_tenant_management.md`) it's now excluded entirely, both from the dropdown and from what the backend will return even if asked for by name. (4) The single day-preset date filter wasn't "fully functional" custom-range filtering — added explicit From/To date inputs alongside the presets, with an explicit-date selection always overriding and clearing the preset.

## Implementation notes — tenant-admin Activity Log (2026-09-07)

User feedback, in the same session as the payment-claim work above: "we need to ensure that we have log trail for everything, since it has to do with people's goods and money, so that the tenant admin can see every activity going on." The only thing that existed was `shell/ActivityFeed.tsx`, an 8-row dashboard widget with no filtering and no way to see *what* changed — platform admins already had a full `platform/PlatformAuditLog.tsx` page for platform-level actions, but tenant admins had no equivalent for their own tenant's activity.

New `tenant-admin/ActivityLog.tsx` (route `/admin/activity-log`, nav entry under Admin), modelled directly on `PlatformAuditLog.tsx`: a "Record type" filter over every real `entity_type` the backend writes (`payment_claim`, `damage_claim`, `refund_request`, `billing`, `packing_list`, …), cursor pagination, and an expandable before/after diff per row so a tenant admin can actually verify what a confirmed payment or resolved claim changed, not just that something did. Backend `GET /v1/tenant/activity` gained a matching `?entity_type=` filter and now returns `before_state`/`after_state` (previously excluded as a "lean projection" for the small widget this was originally built for).

Auditing actual backend log *coverage* while building this turned up several real gaps — money/goods-affecting writes with no audit trail at all, and one case (webhook-confirmed payments) where the code was calling the audit function but it was silently failing on every single call. Full account in `07_api_tenant_management.md`'s "Tenant Activity Log" section and `02_shared_utilities.md`'s `log_audit` write-up.

**Follow-up the same day, reported directly by the user:** a single "Record type" dropdown "lacks fully functional filtering, sorting and search" and needed "proper categorization for easy filtering." Rebuilt the filter bar: every `entity_type` is grouped into six categories (Money, Goods & shipments, Customers, Staff & access, Settings, System) — picking a category sends every type in it as one request (real "show me everything money-related", not just a label) and narrows the Record-type dropdown to that category's types, clearing any selection that no longer applies when the category changes. Added an Action filter, a debounced search box (matches the actor's name or a pasted record id — the practical "find everything that happened to invoice X" query an audit trail needs), the shared `DateRangeFilter` component for a date range, and a sort-order toggle (uses `shared/pagination.py::build_paginated_query`'s existing `sort_direction` support — no new backend pagination logic needed, since it already flips the cursor comparison operator correctly for ascending order). All filters combine as one request. "Clear filters" resets everything at once.

## Implementation notes — payment-claim staff review + double-payment prevention (2026-09-07)

Follow-up the same day, prompted by the user actually using the "I've made this payment" feature and asking how staff confirm it: the staff-side half hadn't been built at all — the backend confirm/reject endpoints existed, but no page could reach them. Added a "Payment claims" table to `nigeria/BillingDetail.tsx` (any `nigeria_office_staff`/`tenant_admin`): amount, submission date, a "View evidence" button (new `GET /v1/payments/claims/{id}/evidence-url` presigned S3 GET — staff need to see the actual receipt, not just its filename), status, and Confirm/Reject for pending ones (reject requires typing a reason first).

Then, checking the customer side while explaining this, the user caught a real gap themselves: after submitting a claim, "Pay online" stayed fully clickable and the page showed no sign a payment was already in flight — a real double-payment risk. Fixed in `MyBillingDetail.tsx`: a pending claim now replaces the *entire* "Pay now" section (Pay online and bank transfer both) with a single "Payment submitted — awaiting confirmation" banner; a rejected claim (with nothing currently pending) surfaces the rejection reason above the restored payment options instead of leaving it buried inside the bank-transfer accordion. `MyShipmentDetail.tsx`'s compact billing-summary CTA got the matching fix. Full account, including a real duplicate-rendered-banner bug this refactor caught (found by a component test, not by eye), in `13_api_payment_release.md`.

## Implementation notes — billing money-clarity pass: "misc fees" and beyond (2026-09-06)

User feedback: "misc fees" in the billing breakdown doesn't say what the fee is actually for, and — since it's money — asked for a broader check of the same surface for anything else unclear or ambiguous. That check turned up several real gaps beyond the label itself, not just wording:

- **`MyBillingDetail.tsx`'s "Invoice breakdown" card silently omitted misc fees, storage fees, carryover, and CBM-dispute adjustments from the customer's own bill entirely** — only CBM/Rate/Exchange rate/(Storage fees if >0)/Total due were shown, so a customer with any of the first three components in their bill saw a `total_due_ngn` that didn't reconcile with anything visibly on the page. Fixed: the card now itemizes every real `billing.misc_fees[]` entry by its actual `description` (never a lump "Misc fees" line), and conditionally shows storage fees / carryover / adjustments / total paid / outstanding — full parity with the staff-side `nigeria/BillingDetail.tsx` breakdown, which already did this correctly.
- **`MyShipmentDetail.tsx`'s compact billing summary** had the same ambiguous lump "Misc fees" Kvp (shown even at ₦0). Same fix: itemized by description, storage fees shown conditionally.
- **`nigeria/BillingDetail.tsx`'s staff-facing summary** had a "Misc fees" lump line too — not wrong (a fuller itemized "Miscellaneous charges" table already exists further down the page), but a staff member had to scroll to decode it. Made the inline summary itemized as well, for consistency and one less step.
- **The customer's downloadable invoice (PDF/CSV) had no breakdown at all** — see `19_excel_import_export.md`'s matching ground-truth-gap entry. Far more serious than a wording issue: the actual document a customer downloads as their invoice said "total ₦X, balance ₦Y" with nothing explaining either figure.
- **The "Manual bank transfer" bank account was hardcoded and wrong for most tenants** — see `07_api_tenant_management.md`'s "Manual Bank Transfer Configuration" and `13_api_payment_release.md`'s "Payment Claims" sections. Not ambiguous so much as actively incorrect: every tenant's customers were shown the same one tenant's bank account.
- **There was no customer-side confirmation step for a manual bank transfer at all** — reported directly by the user mid-session ("should have a button to allow the user to indicate that the payment is done, and also they must upload the evidence of payment before they can submit it for staff verification"). New `PaymentClaimPanel` in `MyBillingDetail.tsx`: an "I've made this payment" button opens a form requiring both an amount and a mandatory evidence upload (reusing `EvidenceUploader` from the damage-claims flow) before "Submit for review" enables. A pending claim shows a status banner in place of the form; a rejected one shows the reason and lets the customer resubmit. Full backend account in `13_api_payment_release.md`.

Verified live end-to-end against the local stack: submitted a real payment claim through the browser (amount + uploaded file), confirmed the "Payment claim pending review" banner rendered with the correct amount/date/filename; separately confirmed the claim via the API and verified the underlying `payment_record`/`billing.status` updated correctly.

## Implementation notes — audit gap B9: plan-usage panel (2026-07-12)

Prototype 15.4A's "full plan-usage panel with per-dimension bars" now renders on the tenant-admin dashboard (`shell/PlanUsagePanel.tsx`, mounted in `Dashboard.tsx` for admins only). Bars for the three limited dimensions from `GET /v1/tenants/me/quota` with the prototype's colour thresholds (<80% green, ≥80% amber badge, 100% red "At limit" badge); the counters that have no configured maximum (API calls, SMS/WhatsApp/email sent) are shown as a plain this-period meta line instead of bars — the prototype drew limits for those, but the quota response has none, and fabricating them would be dishonest. The prototype's "Upgrade plan" CTA is omitted: there is no self-service plan-change endpoint (tier changes are a platform-admin action).

## Implementation notes — audit gaps B1–B5b: list/dashboard enrichment sweep (2026-07-13)

Brought five list/dashboard pages up to the prototype's density. **B2 Platform Tenant List**: status filter chips (counts), client-side search, initials-avatar tenant cell, mono ID, users x/limit — the one backend change in the sweep is `list_tenants` returning `user_count` (active-user LATERAL count, matching quota semantics) + effective `users_limit` per tenant, so the list renders "x/limit" without an N+1 usage fetch. **B1 Platform Dashboard**: recent-activity feed from the audit-log endpoint, 3 quick-action tiles, users-x/limit in the tenant-health table. **B3 Tenant Dashboard**: time-of-day greeting hero + container summary line, admin-only Active-customers (list total_count) + Open-claims stats, recent-containers table. **B4 Staff List**: role chips + search + Created column. **B5b Customer List**: stat cards, All/Active/Anonymised chips, consent pills (SMS/WA/EM), shipments column. Consistent honesty calls throughout: per-tenant container usage (needs a batch endpoint), trends/MRR/API-call limits (no historical source), and last-login (no field) are omitted rather than fabricated — each noted in AUDIT_GAPS.md. Filtering/search that acts on a single fetched page is framed "on this page" where pagination applies.

## Implementation notes — multi-role staff support (2026-07-20, migration 039)

A `tenant_user` can now hold more than one role at once (e.g. `nigeria_office_staff` +
`warehouse_attendant`). Backend: new `tenant_user_role` join table, `tenant_user.role`
kept as "primary role", `TenantContext.roles` set-intersection in `assert_role`
(`shared/tenant_context.py`), and a real bug fix — `CognitoClient.sync_user_groups()` —
for role changes never having actually updated Cognito group membership before now
(`07_api_tenant_management.md` has the full writeup).

Frontend surface, all in `pages/tenant-admin/`:
- **`StaffUserList`'s invite modal** and **`StaffUserDetail`'s role-edit flow** replace
  the single-role `<select>` with `RoleCheckboxList.tsx` (new, shared by both) — a
  checkbox per assignable role plus a radio marking which checked role is primary.
  Checking the first role auto-primaries it; unchecking the primary role reassigns
  primary to whatever's left. `StaffUserDetail`'s "Roles" Kvp now shows a badge per
  assigned role (` · primary` suffix on the primary one) instead of a single role badge.
  `ROLE_PERMISSIONS[user.role]` (the informational per-role capability list) stays keyed
  off the primary role only — deliberately not merged across roles, matching the
  existing "purely informational" code comment.
- **Breaking change**, matching the backend: `CreateUserInput`/`UpdateUserInput`
  (`api/tenantManagement.ts`) — `role` → `roles: TenantUserRole[]` +
  `primary_role?: TenantUserRole`. `TenantUser` keeps `role` (primary) and adds
  `roles: TenantUserRole[]`.
- **Session/auth surface** (detailed in `06_routing_rbac_and_navigation.md`):
  `Session.roles`, `RoleGuard`'s set-intersection check, the `setActiveRole`
  client-side-only role-switch toggle in `TopBar`'s user menu, and the local-dev
  `nigeria_warehouse` identity + `X-Roles` header.
- Tests: `StaffUserDetail.test.tsx` (new — role checkbox pre-selection, save with
  roles/primary_role, primary-via-radio, disabled-when-empty, cancel-discards),
  `StaffUserList.test.tsx` extended (default single-role invite, multi-role invite,
  disabled submit when unchecked), `RoleGuard.test.tsx` extended (multi-role
  allow/deny), `jwt.test.ts`/`SessionProvider.test.tsx`/`LocalAuthProvider.test.tsx`
  extended for `roles` parsing and `setActiveRole`.


## 7.2b — Import from Excel (two modes)

`frontend/src/pages/china/ImportPackingLists.tsx` · route `/packing-lists/import` · `china_office_staff`

The wizard now covers **two genuinely different import shapes** behind one page, chosen by a
radio-card selector at step 1:

| Mode | Endpoint | Container | Customers |
|---|---|---|---|
| **Forwarder manifest** *(default)* | `POST /v1/manifests/import` | Read from the file's `PARTIAL NO` heading — **no picker shown** | Created on the fly, matched on phone |
| **ShipX packing-list template** | `POST /v1/packing-lists/import` | Chosen by the user | Must already exist |

Manifest mode is the default because it is the file staff actually receive from their agent; the
template is the fallback for lists typed up in-house.

**Results panel** is mode-aware. Manifest imports report two groups of tiles — what happened to the
rows (`Rows read` / `Items added` / `Already imported` / `Skipped (errors)`) and, under a separate
"Created for you" heading, what ShipX added on the user's behalf (`Containers` / `Customers` /
`Packing lists`). A fully-duplicate re-import (`items_created === 0` with duplicates > 0) shows an
explicit *"Nothing new to add"* banner, so an idempotent re-upload doesn't read as a failure. The
skipped-rows table gains a **Sheet** column for manifest imports, since real exports span several
worksheets and a row number alone is ambiguous.

### Implementation notes / ground-truth gaps found

- **The import wizard was effectively unreachable.** It had a route but no nav entry — the only way
  in was a small "upload" button buried inside *Create packing list*
  (`CreatePackingList.tsx:277`). Added `Import from Excel` to `china_office_staff`'s "Packing lists"
  nav group in `shell/navConfig.ts`.
- **JSX does not interpret `\uXXXX` escapes in text nodes.** Curly quotes and em dashes written that
  way rendered literally as `\u2019` / `\u2014` on screen — caught only by looking at a real
  browser screenshot, not by typecheck, lint, or the 614-test suite. Typographic characters are now
  written directly.
- The `.xls` file the forwarder's platform also offers is **not an Excel file** — it is tab-separated
  text with an `.xls` extension, and `openpyxl` cannot open it. The file input accepts `.xlsx` only
  and the dropzone says so; TSV support is a separate pass (see `00_MASTER_PLAN.md` 7.43).
- Local-dev note: the wizard needs `VITE_ENVIRONMENT=local` for the role switcher, and the floating
  switcher panel overlays bottom-right page actions (it intercepted the "Confirm & import" click
  during browser verification) — dev-only, does not affect staging/production builds.


## Customer contact in operational tables (2026-08-30)

`customer_phone` now renders as a **Contact** column in the three places customers appear as rows:

| Table | File |
|---|---|
| Container → Overview → customers on this container | `pages/china/ContainerDetail.tsx` |
| Container → Packing lists | `pages/china/ContainerDetail.tsx` |
| Manifest → customers | `pages/nigeria/ManifestDetail.tsx` |

The container customer table previously repeated the carton count in `UserCell`'s secondary slot
(already its own column); that slot is now blank rather than duplicating the new Contact column.

### Ground-truth gap found: cargo totals only counted the first page

`ContainerDetail` called `packingListApi.listByContainer(id)` with no paging and aggregated
`result.data` as if it were the whole container — but the endpoint returns 50 by default. Any
container with more than 50 packing lists silently **under-reported its own cargo summary**: the
STL409 manifest import (68 packing lists, 81 cartons, 72.55 CBM) displayed **50 customers, 55
cartons, 35.77 CBM**, and the packing-lists tab showed "50 list(s)". Real forwarder manifests
routinely exceed 50 customers, so this was not an edge case.

Fixed with `fetchAllPackingLists()`, which follows `next_cursor` to the end (100 per page, guarded at
`_MAX_PAGES = 100`). Verified live: the same container now reads 68 / 81 / 72.55, matching the source
document's own declared totals. Regression test asserts two pages are fetched and that totals reflect
both.


## Bulk submit on the packing-list list (2026-08-30)

`pages/china/PackingListList.tsx`'s bulk action bar gains **"Submit for approval · N"**
(`packingListApi.bulkSubmit` -> `POST /v1/packing-lists/bulk-submit`), beside the existing bulk
approve/reject. Needed because bulk approve only accepts `pending_approval`, and the only
`draft -> pending_approval` path was the single-item submit — unusable after an import that creates
68 lists at once. Imported lists now arrive already in `pending_approval`, so this button is for
hand-created drafts.


## Bulk-action failures: prevent, then explain (2026-09-01)

Reported live: bulk-approving 50 imported lists as the person who imported them produced 50 table
rows of `<uuid>  self_approval_forbidden`. Two problems — the message was a machine code, and one
cause was repeated once per record.

**Prevent.** `canApproveOrReject`/`isSelfApproval` already existed in `api/packingListRules.ts` but
nothing consulted them before firing the request. The bulk bar now counts how much of the selection
this user can actually approve: the button reads **"Bulk approve · N"** using that count, is disabled
at zero, and the bar says why inline ("you created all of these, so someone else must approve them").

**Explain.** `explainBulkFailure()` maps every API reason code to a title plus a next step
(`self_approval_forbidden` → "You created these, so you cannot approve them" / "Ask a colleague or
your admin"); `groupBulkFailures()` collapses failures sharing a reason. `BulkResultPanel` renders
one block per cause with a count and the affected lists as **reference · customer** chips, not UUIDs
(resolved from the already-loaded page data). Unknown codes fall back to showing the raw value —
a visible code is bad, a silently swallowed failure is worse.

### Ground-truth gap: the dev shim hid this class of bug

`LocalAuthProvider`'s `ROLE_USER_IDS` used placeholder slugs (`local-china-staff`). In production
`session.userId` is the Cognito sub, which equals `tenant_user.id` for seeded users — so any UI rule
comparing the session user to a record's `created_by` **silently never matched** under the shim, and
the self-approval prevention appeared to do nothing when first tested in the browser. The shim now
uses the real fixed seed UUIDs (`scripts/seed.py` pins them precisely so they are stable across
`make stack`), making local dev behave like production for ownership checks.


## Showing bale vs carton (2026-09-01)

Staff could not tell what a line actually was: every count was labelled
"Cartons", so an 18-bale list read "18 cartons" — and after migration 040 the
number itself was a row count, not a package count.

`api/packingListRules.ts` gains `formatPackageMix()` ("16 bags · 2 bales",
largest group first), `formatPackageUnit()` (pluralised per unit) and
`dominantPackageUnit()`. Surfaced as:

- **Packages** column (replacing "Cartons") on `PackingListList` and both
  `ContainerDetail` tables, rendering the mix rather than a bare number.
- **Packages** column on `PackingListDetail`'s item table via `PackageCell` —
  "16 bags", or "1 × BIG BALE · No. 2" for bale rows, keeping the verbatim
  `bale_type` and `bale_no`. Compound source cells ("3bags2ctns1pallet") show
  their `quantity_raw` alongside the normalised mixed count.
- **Total packages** tile on the container overview, summing `package_count`
  with the mix as its sub-label. Previously "Total cartons" summing rows:
  STL409 read 81 where the container physically holds 437 packages
  (342 cartons · 76 bags · 18 bales · 1 pallet) — which reconciles with the
  source manifest's own declared `CTNS/PKGS: 419` plus 18 bales.
- Hardcoded "cartons" copy on the detail page ("Carton items", "1 cartons")
  replaced with the derived mix.


## Result counts on the packing-list list (2026-09-01)

`PackingListList` states how much of the result it is showing —
"Showing 50 of 68 packing lists" — and the Load more button names what is left
("Load more · 18 remaining"). When a page holds everything, no total is claimed
("Showing 1 packing list") and no button renders.

A page of 50 with no total previously read as the entire result set, so a
container with 68 packing lists appeared to have 50 until a status filter
revealed the rest.


## Customer account-creation invites + self-signup fix (2026-09-01)

Manifest import creates customers with only `name` + `phone` — no way to log in, and 68 of them
appeared from a single STL409 import with no path to a portal account. This adds an expiring,
single-use invite link (delivered by SMS/WhatsApp) and repairs tenant-scoped self-signup, which turned
out to be genuinely broken.

**New public pages:**
- `pages/auth/InviteClaimScreen.tsx` (route `/invite/:token`) — fetches `GET /v1/invites/:token` on
  mount for the claim-page preview (company name, customer name, expiry only); on failure (unknown,
  expired, or already-consumed token) shows a "This link is no longer valid — contact your shipping
  company" state rather than a raw error, since the public endpoint's 404 deliberately doesn't say
  which case it is. On success, collects email + password (same 4-requirement checklist and
  `PasswordStrength` component as `ResetPasswordScreen`) and calls `POST /v1/invites/:token/accept`.
- `pages/auth/RegisterScreen.tsx` — now reads `slug` from the route (`/register/:slug`) via
  `useParams` and sends it explicitly to `POST /v1/register/{slug}`; the old Host-header-guessing
  backend behaviour is no longer what the frontend relies on. A bare `/register` (no slug) shows a
  "this link doesn't identify a shipping company" warning banner and disables submit, rather than
  silently failing against the backend's fallback resolution.

**Staff UI** (`pages/tenant-admin/`):
- `AdminCustomerDetail.tsx`'s hero gains a "Send account invite" / "Resend account invite" button
  (`Action`, respects read-only impersonation) calling `customersApi.invite(id)`, and a second badge
  next to Active/Anonymised showing account state — *Has portal login* / *Invited · expires …* / *No
  login*.
- `AdminCustomerList.tsx`'s Status column becomes `AccountStatusBadge`, the same three states, driven
  by a new `pending_invite_expires_at` field on `Customer` (backend correlated subquery — no separate
  round trip).

**API bindings:** `api/customer.ts` gains `inviteApi.get`/`inviteApi.accept` (public, no JWT) and
`registerApi.selfRegister` now takes `slug` as its first argument; `api/tenantManagement.ts`'s
`customersApi` gains `.invite(id)` and `Customer.pending_invite_expires_at`.

**Ground-truth bug found and fixed (backend, not frontend-visible until now):**
`self_register_customer` wrote the Cognito sub straight into `customer.user_id`, a column with
`FOREIGN KEY REFERENCES tenant_user(id)` — that write could never succeed against the real schema, so
self-registration had never actually worked in this codebase's history. Fixed alongside this feature
(`services/tenant_management/service.py`) by also creating the `tenant_user` row and linking its id.
See `07_api_tenant_management.md` for the full backend writeup.

**Verified live:** re-imported STL409 through the running local stack, confirmed invites issued and
visible in `notification_log`; claimed one invite through the real `/invite/:token` page and logged in
as that customer to confirm shipment tracking renders; reused the same link (rejected), expired a
second link by moving `expires_at` back (rejected with the friendly page), and resent a third (old
token dead, new one worked). See `00_MASTER_PLAN.md` row 7.52 for the full verification log.

## Dev role-switcher panel gains a stable id (2026-09-06)

`RoleSwitcher.tsx`'s outer `<div>` now has `id="dev-role-switcher-panel"`
alongside its CSS-module class. It's `position: fixed; bottom; right;
z-index: 2000` — deliberately on top of everything so a role can be flipped
from any screen — which means it can sit directly over a real button near
that corner. A click there is delivered by the browser to whatever's topmost
at those coordinates, silently the switcher rather than the button
underneath, no error. `frontend/e2e/support/roleSwitch.ts`'s
`switchRole()` now suppresses its pointer-events via this id once a role is
set, since most tests never touch the switcher again afterward. Purely a
test hook; no visual or behavioral change for real dev use.

## Two real bugs found by deep e2e interaction testing (2026-09-06)

**`Dashboard.tsx` crashed the whole page for any tenant with an unmethoded
payment.** `RecentPayment.payment_method` was typed `string` (non-nullable),
but the DB column is deliberately nullable (migration 008 dropped `NOT NULL`
specifically to support `RecordPaymentInput.payment_method` being optional).
`Dashboard.tsx` called `.replace(/_/g, ' ')` on it directly — `tsc` never
caught it because the *type*, not the real value, said non-nullable. Any
payment recorded without picking a method (a real, common case — the field
is optional in the Record Payment form) blanked the entire nigeria-staff/
tenant-admin dashboard with "Cannot read properties of null". Fixed: the
type is now `string | null`, and the cell falls back to `'—'`. Covered by a
new case in `Dashboard.test.tsx` — the only existing recent-payments test
stubbed a payment *with* a method, so this was untested.

**`ReleaseNoteDetail.tsx`'s pickup form never collected a required field.**
See `13_api_payment_release.md`'s "Ground-truth fix (2026-09-06)" for the
full story — a backend validator requires `collected_by_name` for any
non-delegate pickup, but the form only ever asked for delegate details.
Fixed by adding a "Collected by" field (defaulting to the note's own
customer) shown when the delegate toggle is off. Covered by two new cases
in `ReleaseNoteDetail.test.tsx`.

Both were found running the real billing → payment → release-note → pickup
chain against the live local stack, not through code review — confirmed
each fix by watching the record actually reach `picked_up` in the database.

## refundTypeLabel() gains a fallback (2026-09-06)

See `12_api_claims.md`'s and `14_api_refunds.md`'s matching entries for the
full story — `create_refund_request_for_claim()` never set `refund_type`,
and `refundTypeLabel()`'s switch had no default, so an unmapped value
returned `undefined` and React rendered nothing: `RefundDetail.tsx`'s page
`<h1>` was silently blank for every claim-triggered refund. Fixed at the
source and defensively here (`'Refund request'` fallback), covered by a new
case in `refundsRules.test.ts` — there was no existing test for this
function at all before.

## Staff notification bell (2026-09-12)

Ground-truth gap found live, reported by the user: "a staff rejected a payment marked as paid, but no notification was showing when I logged into the staff account." The TopBar bell icon and unread badge were already fully built (`TopBar.tsx`'s own doc-comment even said "wired to GET /v1/notifications/log in Task 07") but `StaffLayout.tsx` never passed it any data at all — direct follow-up from the user: "let's go through the whole notification including the frontend notification to resolve all," choosing the full read/unread feed over a cheaper live-count alternative.

**New files:**
- `frontend/src/api/staffNotifications.ts` — `StaffNotification` type + `staffNotificationsApi` (list, unreadCount, markRead, markAllRead), hitting the new `GET/PATCH /v1/notifications/staff*` routes (`15_api_notifications.md`).
- `frontend/src/hooks/useStaffNotifications.ts` — `useStaffNotifUnreadCount` (polls every 30s, pauses when the tab is backgrounded, `enabled` param so a bare platform admin never fires it), `useStaffNotifList` (the dropdown's fixed recent page, `enabled` tied to the panel's own open state so a closed-but-mounted bell doesn't fetch in the background), `useMarkStaffNotifRead`/`useMarkAllStaffNotifRead` mutations invalidating the whole `staffNotifKeys.all` cache slot on success.
- `frontend/src/shell/StaffNotificationPanel.tsx` (+ `.module.css`) — the dropdown itself: header with a "Mark all read" button (only rendered when something is unread), a scrollable list of rows (title, body truncated to 2 lines, relative time, an unread dot), click-a-row-to-mark-it-read, an empty state, and an overlay that closes the panel on outside click — same overlay+absolute-panel idiom as `DateRangeFilter.tsx`'s popover.

**Changed files:**
- `TopBar.tsx` gained a `notificationsPanel?: ReactNode` prop, rendered inside a new `.bellWrap` (`position: relative`) alongside the existing bell `<button>` — so a dropdown passed in that slot anchors under the bell (`position: absolute; top: 100%; right: 0`) regardless of what else sits in the TopBar's right side, without StaffLayout needing to know the bell's on-screen position. The bell button and badge markup are otherwise unchanged.
- `StaffLayout.tsx` — the only place that mounts `TopBar` for staff/admin roles — now calls `useStaffNotifUnreadCount`, holds `notifPanelOpen` state toggled by `onNotificationsClick`, and passes `<StaffNotificationPanel open={...} onClose={...} />` as `notificationsPanel`. Gated with the exact same `!isPlatformShell` check `useBranding` already uses on the line above it — a bare platform admin has no tenant context and the backend 403s that role for these routes anyway (`_STAFF_NOTIF_ROLES` in `services/notification/handler.py` excludes `platform_admin`). The bell icon itself still always renders (TopBar's own unconditional markup); what's suppressed for a platform admin is the badge count, the click handler, and the panel.

Verified live against the real local stack: submitted a payment claim as a real customer, confirmed the unread count and dropdown row appeared for `nigeria_office_staff`, marking it read there left a separate `tenant_admin` session's count untouched (independent per-viewer read state), and "Mark all read" cleared it. Tests: `TopBar.test.tsx` (+1 — panel renders inside the bell's wrapper), `StaffLayout.test.tsx` (+4 — unread count shown, panel opens on click, platform_admin gets neither the count nor a working click), new `StaffNotificationPanel.test.tsx` (7 cases — empty state, row rendering, mark-one-read, conditional "Mark all read", overlay dismiss). 737 backend + 686 frontend tests pass.

## Customer notification bell (2026-09-12)

Ground-truth gap found live, reported by the user right after the staff bell shipped: "i rejected ifexalex2@gmail[.com]'s submitted payment with a comment that we did not receive the payment, and i did not see the notification when i logged in as ifexalex2@gmail.com." `CustomerTopNav.tsx` already had a bell icon and unread badge, but nothing fed it data — the same gap the staff bell had before its own fix. Full backend/ground-truth account in `15_api_notifications.md`'s "Customer notification bell + local-dev delivery plumbing" section.

**New files:**
- `frontend/src/api/customerNotifications.ts` — mirrors `staffNotifications.ts` exactly (`CustomerNotification` is a re-export of `StaffNotification`, same row shape), hitting `GET/PATCH /v1/notifications/customer*`.
- `frontend/src/hooks/useCustomerNotifications.ts` — mirrors `useStaffNotifications.ts` exactly.
- `frontend/src/shell/CustomerNotificationPanel.tsx` — reuses `StaffNotificationPanel.module.css` rather than a shared component with a role switch, since the staff and customer shells never share a render tree (three similar lines beat a premature abstraction here).

**Changed files:** `CustomerTopNav.tsx` gained the same `notificationsPanel`/`onNotificationsClick` props and `.bellWrap` wrapper `TopBar.tsx` has; `CustomerLayout.tsx` wires `useCustomerNotifUnreadCount` + `CustomerNotificationPanel` the same way `StaffLayout.tsx` wires the staff bell.

Verified live, reproducing the user's exact report: rejected a real payment claim for `ifexalex2@gmail.com`, confirmed `GET /v1/notifications/customer/unread-count` went 0→1 with the correct rejection-reason body. Tests: `CustomerTopNav.test.tsx` (+1), `CustomerLayout.test.tsx` (+2, plus 2 pre-existing tests fixed to wrap in `QueryClientProvider`), new `CustomerNotificationPanel.test.tsx` (7 cases). 755 backend + 696 frontend tests pass.

## Clearing notifications + manual announcements (2026-09-12)

Direct follow-up to both bells above: "The notification should allow clearing. Secondly tenant admin and nigeria staff should be able to send a announcements, for example during celebration sessions, or import announcements." The user chose one broad audience per announcement (every staff member, or every customer) over a role/person picker. Full backend account in `15_api_notifications.md`'s "Clearing notifications + manual announcements" section.

**New files:**
- `frontend/src/api/announcements.ts` — `announcementsApi.send({title, body?, audience})`, hitting `POST /v1/notifications/announce`.
- `frontend/src/shell/ComposeAnnouncementModal.tsx` — `Modal` + `Field` (title required, message optional/multiline) + two `Chip`s for audience + `Banner` error display. Invalidates both `staffNotifKeys.all` and `customerNotifKeys.all` on success so an `all_staff` send updates the sender's own bell immediately.

**Changed files:**
- `staffNotifications.ts`/`customerNotifications.ts` gained `dismiss(id)`/`clearAll()`, hitting the new `DELETE /v1/notifications/{staff,customer}/{id}` and `.../clear-all` routes; `useStaffNotifications.ts`/`useCustomerNotifications.ts` gained matching `useDismiss*`/`useClearAll*` mutations.
- `StaffNotificationPanel.tsx` / `CustomerNotificationPanel.tsx`: `NotificationRow` changed from one clickable `<button>` to a wrapper `<div>` containing a `rowMain` button (click-to-mark-read) and a separate `clearBtn` `×` button (`e.stopPropagation()` so clearing never also marks read via the row click). Header gained a `.headerActions` row holding both "Mark all read" (unread-conditional, as before) and "Clear all" (shown whenever the list is non-empty). `StaffNotificationPanel.tsx` additionally calls `useSession()` for the first time, gating a "New announcement" trigger (`ANNOUNCE_ROLES = {tenant_admin, nigeria_office_staff}`, mirroring the backend's `_ANNOUNCE_ROLES`) that opens `ComposeAnnouncementModal`. `CustomerNotificationPanel.tsx` got the row/clear restructuring only — no announcement trigger, since customers never send them.
- `StaffNotificationPanel.module.css` — new `.headerActions`, `.rowMain`, `.clearBtn`, `.announceBtn` classes; `.row` is now a plain flex container rather than the clickable element itself.

**Test-file impact:** `StaffNotificationPanel.test.tsx`'s `renderPanel()` helper now wraps in `SessionContext.Provider` (`makeSession`/`makeContextValue`, same pattern as `StaffLayout.test.tsx`) — required once the component started calling `useSession()`, since the bare `QueryClientProvider`-only wrapper it had before this task threw `"useSession must be used within a SessionProvider"` on every test.

Verified live against the real local stack: `all_staff` announcement → 4 rows (one per staff role), visible to all four staff roles, invisible to a customer session; `all_customers` announcement → 1 row, visible to two different customer sessions (role-broadcast, not per-user), invisible to staff; `china_office_staff` 403s on the announce route itself. Dismissed one notification as one recipient of a broadcast row — a different recipient's copy was unaffected; `clear-all` returned the correct count and left other recipients' lists untouched; repeated on the customer route. Tests: `StaffNotificationPanel.test.tsx` 7→13 cases, `CustomerNotificationPanel.test.tsx` 7→11 cases, new `ComposeAnnouncementModal.test.tsx` (8 cases). 766 backend + 714 frontend tests pass.

## Staff announcement approval + announcement banner (2026-09-12)

Two direct follow-ups sent in quick succession while reviewing the announcement feature above. First: "Tenant admin can send announcement to all staffs and all customers. But the staff can only send to customers, which should be approved by the tenant admins, this is to ensure that a compromised staff does not misinformation the customers." Second, sent mid-review of the first: "annoucement should be a banner on the target user's web page, with this they won't miss it. It can be enabled or disabled, more can be created but only one can be visible per time... we can add amination to it, so that it is obvious to the target user." Full backend account in `15_api_notifications.md`'s two matching "Follow-up" subsections.

**Changed:**
- `ComposeAnnouncementModal.tsx` now calls `useSession()`. A `nigeria_office_staff` session never renders the "All staff" `Chip` at all (not just disabled — the backend 403s that audience outright for that role), audience state initialises locked to `all_customers`, the submit button reads "Submit for approval" instead of "Send announcement", and a note explains the review step. `tenant_admin` sessions are unaffected.
- `StaffNotificationPanel.tsx` gained a second footer trigger, "Manage announcements", visible only when `session.role === 'tenant_admin'`, opening the new `ManageAnnouncementsModal`.

**New files:**
- `frontend/src/api/announcements.ts` — extended with `AnnouncementRequest`/`AnnouncementHistoryEntry` types and `listPending`/`approve`/`reject`/`listHistory`/`activate`/`deactivate`, alongside the existing `send`. `SendAnnouncementResult` is now a discriminated union (`{status: 'sent', ...}` | `{status: 'pending', request_id, ...}`).
- `frontend/src/hooks/useAnnouncements.ts` — `useAnnouncementPending`, `useApproveAnnouncement`, `useRejectAnnouncement`, `useAnnouncementHistory`, `useActivateAnnouncement`, `useDeactivateAnnouncement` — all mutations invalidate the announcement, staff-notif, and customer-notif query-key namespaces together, since an approve/activate can change what any of the three show.
- `frontend/src/shell/ManageAnnouncementsModal.tsx` — tenant_admin only. Two stacked sections: a pending-approval queue (each row: title/body/audience `Badge`, Approve button, Reject button that reveals an inline reason `Field` before confirming) and a banner-management history list (each row: title/audience `Badge`, a `ToggleSwitch` wired to activate/deactivate).
- `frontend/src/shell/AnnouncementBanner.tsx` (+ `.module.css`) — presentational: takes `{id, title, body} | null | undefined` and an internal dismiss state keyed by the banner's own id (so a genuinely different banner, e.g. a new send or a re-activated older one, always shows regardless of a prior dismissal). Built on the existing `Banner` design component (`variant="info"`, `dismissible`) wrapped in a container with a CSS slide-down-then-pulse animation (`prefers-reduced-motion: reduce` turns it off). Mounted once each in `StaffLayout.tsx` and `CustomerLayout.tsx`, in the same header slot as `ImpersonationBanner`/`QuotaWarningBanner`.
- `useStaffBanner`/`useCustomerBanner` added to the existing `useStaffNotifications.ts`/`useCustomerNotifications.ts` hook files — 60s poll, paused when the tab is hidden (same pattern as the unread-count hooks), `enabled` gated identically (off for a bare `platform_admin` in `StaffLayout`).

Dismissing the banner is deliberately **not** persisted anywhere — it's component state for the current tab only, so a reload or a different device still shows it until a `tenant_admin` actually deactivates it. This was a deliberate choice, not an oversight: the whole point of a banner "so they won't miss it" is defeated by a dismiss that sticks across sessions.

**Verified live**: two sequential `all_customers` sends — customer banner showed only the second; deactivating it manually returned it to `null`; re-activating the first send brought it back and simultaneously retired the second. An `all_staff` send's banner had no effect on the customer banner endpoint and vice versa.

Tests: `AnnouncementBanner.test.tsx` (new, 6 cases), `ManageAnnouncementsModal.test.tsx` (new, 5 cases — this modal was deleted in the very next follow-up below), `StaffLayout.test.tsx`/`CustomerLayout.test.tsx` each +3 (shows banner, no banner, platform_admin/no-fetch), `StaffNotificationPanel.test.tsx` +2 ("Manage announcements" tenant_admin-only), `ComposeAnnouncementModal.test.tsx` gained a `nigeria_office_staff` describe block (+3: no "All staff" chip, "Submit for approval" label, audience locked). 787 backend + 735 frontend tests pass.

## Announcements moved to a dedicated page, gained full CRUD, and Publish/Unpublish (2026-09-13)

Direct follow-up rejecting the popup-based approach above: "no, i wan the annoucement management to be on it's own page, not on the notification popup. when the page is opened, staff or tenant admin can create annoucements. Annoucement is managed in that page (CRUD), and they can enable only one announcement to be visible per time." Then, reviewing the first pass at that page: "Instead of toggle to enable an announcement, let it be "publish". For the admin. For staff, it will be submit announcement (it will show the state) once it is approved, it will show approved on the staff's end." Full backend account (including the route restructuring this forced) in `15_api_notifications.md`'s "Announcements page + full CRUD + Publish/Unpublish" section.

**Deleted:** `ManageAnnouncementsModal.tsx` / `.module.css` / `.test.tsx` — its two sections became the new page below instead of a bell-triggered popup.

**Changed:**
- `StaffNotificationPanel.tsx` reverted to notification-only: no `useSession()` call, no compose/manage triggers, no modal imports. Its test file dropped the `SessionContext.Provider` wrapper it no longer needs.
- `ComposeAnnouncementModal.tsx`'s staff-facing submit button now reads "Submit announcement" (was "Submit for approval"); still opened from the new page rather than the bell.
- `frontend/src/api/announcements.ts` — `approve`/`reject` now call `/v1/notifications/announcements/requests/{id}/approve|reject` (moved, see backend section); added `listMine`, `updateRequest`, `deleteRequest`, `update`, `remove`.
- `frontend/src/hooks/useAnnouncements.ts` — added `useMyAnnouncementRequests`, `useUpdateAnnouncementRequest`, `useDeleteAnnouncementRequest`, `useUpdateAnnouncement`, `useDeleteAnnouncement`, all invalidating the same announcement/staff-notif/customer-notif key namespaces as the existing mutations.
- `routeTable.ts` (`/announcements`, `allow: ['tenant_admin', 'nigeria_office_staff']`), `navConfig.ts` (a nav item added to both roles' arrays), and `routes.tsx`'s `STAFF_SCREENS` map all gained the new route — the three places every routed page in this app is wired (06_routing_rbac_and_navigation.md).

**New:** `pages/staff/AnnouncementsPage.tsx` (+ `.module.css`), a single component that branches its entire body by role rather than showing/hiding a couple of controls:
- `tenant_admin` sees two `Card` sections: "Pending approval" (unchanged Approve / Reject-with-reason rows) and "All announcements" — every sent announcement, each row now showing a **Publish** or **Unpublish** `Button` (never a `ToggleSwitch` — the user explicitly asked for a named action instead of a toggle) alongside a `Badge` reading "Draft" or "Published" so the state reads at a glance without inferring it from a switch position. Each row also has inline **Edit** (an `EditForm` swapping the row for a title/message form) and **Delete** (click-to-arm, then a **Confirm delete** step — no native `confirm()`, consistent with the rest of this codebase's destructive-action pattern).
- `nigeria_office_staff` sees one `Card` section, "My announcements" — every submission they've ever made, each with a status `Badge` ("Pending approval" / **"Approved"** / "Rejected", using a `STATUS_LABEL` map rather than the raw backend string) so a staff member sees their submission flip to **Approved** directly on this page without needing to check a bell notification; a rejected one shows its `rejection_reason` inline. Edit/Withdraw actions appear only while `status === 'pending'` and disappear the moment a tenant_admin reviews it, mirroring the backend's ownership+status guard.

Both roles share the same "New announcement" trigger in the page's `PageHeader`, opening the existing `ComposeAnnouncementModal` — audience restrictions (staff never sees "All staff") are unchanged from the prior iteration.

**Verified live**: staff submits, sees it in "My announcements" as "Pending approval", edits its title, then a genuinely different user (a fabricated UUID, not just a different `X-User-ID` header string — local dev's non-UUID header resolves to the tenant's one seeded user per role, so two arbitrary strings for the same role can collide) 404s trying to edit it. tenant_admin approves via the new route path — staff's own row flips to "Approved". tenant_admin sends a fresh `all_staff` announcement, sees "Draft" become "Published" after clicking Publish, edits its title (visible immediately on a staff bell), then deletes it and confirms it's gone from that bell entirely (not just unpublished) with a repeat delete correctly 404ing.

Tests: `AnnouncementsPage.test.tsx` (new, 15 cases covering both role views, publish/unpublish, edit, delete-with-confirm, approve/reject, my-announcements state display, edit/withdraw gating by status), `StaffNotificationPanel.test.tsx` simplified back down (announcement tests replaced with one confirming those controls never render), `ComposeAnnouncementModal.test.tsx` updated for the new button label. 805 backend + 741 frontend tests pass.

## `nigeria/BillingDetail.tsx` never invalidated the billing query cache (2026-09-13)

Ground-truth gap found live, reported by the user: "i approved a payment, but it did not record the payment as paid, until i refreshed the page." The backend was correct (`confirm_payment_claim` → `confirm_payment()` writes `billing.status`/`amount_paid_ngn` synchronously, verified by reading the full write path) — this was a pure frontend stale-cache bug, and it was **systemic across the entire file**, not just the payment-claim confirm button that triggered the report.

**Root cause:** every single billing-mutating action on this page — confirm/reject a payment claim, record a payment, waive storage fees, remove a misc charge, apply a carryover, cancel the billing, acknowledge/resolve/reject a CBM dispute, generate a release note — refreshes only this component's own local `billing`/`carryovers` React state (via a hand-rolled `load()` that re-scans `GET /v1/billing` client-side, or a direct `setBilling(updated)`). None of them ever called `queryClient.invalidateQueries`. `BillingList.tsx`'s own list query (`billingKeys.list(...)`, 5-minute `staleTime`) kept serving the pre-mutation row on every other screen for up to 5 minutes — exactly matching "did not record... until I refreshed the page," since a hard refresh is what discards the entire in-memory `QueryClient` and forces every query to refetch from scratch. Every comparable mutation *elsewhere* in this codebase (`useRecordPayment`, `useFileDispute`, `useResolveDispute` in `hooks/useBilling.ts`) already invalidates `billingKeys` correctly on success — this page's confirm/reject/record-payment/etc. handlers were hand-rolled instead of using those hooks, and the invalidation step was simply never added when they were written.

**Fix:** added a single `invalidateBillingCaches()` helper (`useQueryClient()` + `invalidateQueries({ queryKey: billingKeys.all })`, called once per mutation's success path) and wired it into all nine call sites: `handleConfirmClaim`, `handleRejectClaim`, `handleWaiveStorageFees`, `handleRemoveCharge`, `handleDisputeUpdated` (the callback every `DisputeCard` acknowledge/resolve/reject action already funnels through), and the `onSuccess` handlers of `AddChargeModal`, `RecordPaymentModal`, `CancelBillingModal`, and `ApplyCarryoverModal` (the release-note modal's `onSuccess` also invalidates before navigating away, since the underlying billing record's status changes too). Invalidating `billingKeys.all` (the `['billing']` prefix) covers `billingKeys.list(...)`/`billingKeys.detail(...)`/`billingKeys.forCustomer(...)` in one call — no need to enumerate each shape separately.

Left as hand-rolled rather than converted to real `useMutation` hooks (a further improvement the investigation surfaced but out of scope for this fix): `RecordPaymentModal` calls `billingApi.recordPayment` directly instead of the already-correct `useRecordPayment` hook in `useBilling.ts` — two implementations of the same mutation now both invalidate correctly, but consolidating them is a separate refactor.

## Release note expanded to match a real paper form; multi-tenant warehouses (2026-09-13)

User supplied 4 photos of a real "Goods Release Note" / "Cash Receipt" pair from a Nigerian logistics company: "we can expan on the release note that we already have... ensure that we sure make that it is a multitanat app... it is [NOT] hardcorded... something that will be emcompassing for all other tanants." Full backend account (migration-041 field completeness, split/reissue carry-forward fix, warehouse CRUD, tenant-onboarding gap) in `13_api_payment_release.md`'s "Ground-truth gaps closed (2026-09-13)" section.

**New files:**
- `frontend/src/api/warehouses.ts` — `Warehouse`/`CreateWarehouseInput` types, `warehousesApi` (`list`, `create`, `setDefault`).
- `frontend/src/hooks/useWarehouses.ts` — `useWarehouses(enabled = true)`, `useCreateWarehouse()`, `useSetDefaultWarehouse()`; since 2026-11-17 also `useUpdateWarehouse()`, `useRemoveWarehouse()`, `useDeactivateWarehouse()` (every warehouse write refreshes the list — see "Warehouse confirmations (audit UX-11)").

**Changed:**
- `api/releaseNotes.ts` — `ReleaseNote` gained `packages_released`/`package_unit`/`packages_balance`, `warehouse_name`/`warehouse_phone`, `is_on_credit`/`credit_granted_by_name`, `receipt_number`, `physical_document_number`, `packing_list_invoice_numbers`, `amount_paid_ngn`/`balance_ngn`/`total_ngn`, `debt_due_date` — all non-optional (the backend's `_fmt_release_note` always returns them, null/`[]`/`"0.00"` when absent, never omitted). `PickupResult` gained `customer_service_officer_name`/`accounting_officer_name`/`collected_by_name?`/`delegate_phone?`. `CreateReleaseNoteInput`/`RecordPickupInput` gained the matching optional request fields (`warehouse_id`, `physical_document_number`, `credit_granted_by_name`, `due_date`, `packing_list_invoice_numbers`, `customer_service_officer_id`, `accounting_officer_id`, `warehouse_attendant_id`).
- `nigeria/BillingDetail.tsx`'s `GenerateReleaseNoteModal` gained: a warehouse `<select>` (rendered only when `useWarehouses()` returns at least one row — most existing tenants still have exactly the migration-041-backfilled default, so this degrades to "no picker" gracefully rather than showing an empty dropdown), "Physical document number" and "Packing list invoice numbers" (comma/newline-parsed into an array) text fields, and — shown only when the "release with outstanding balance" checkbox is on — "Credit granted by" and "Debt payment date" fields. Also dropped an already-unused `PaymentClaim` type import found while in this file (pre-existing `noUnusedLocals` violation, unrelated to this task, fixed opportunistically).
- `nigeria/ReleaseNoteDetail.tsx`'s `RecordPickupModal` gained three optional native `<select>` pickers — Warehouse/branch, Customer Service Officer, Accounting Officer — each rendered only when its backing list (`useWarehouses()` / `useStaffList()`) is non-empty, matching the existing inline-styled `<select>` pattern already used for `delegateIdType` in this same file. The page's "Release details" Kvp list gained: physical document number, carton count that now reads "N of M {unit}" for count-based releases (vs. the original tag-count format), a balance-remaining row (only when > 0), packing list invoice numbers, warehouse name + address, on-credit status with the granting officer's name, receipt number, a combined "₦X paid of ₦Y — ₦Z outstanding" payment row, and the debt due date — every one of them conditional, so an older note with none of these fields renders exactly as it did before.
- `print/PrintReleaseNote.tsx` — the core bug found live: the warehouse address block always read the one tenant-wide `branding.warehouse_address` singleton, so a multi-branch tenant printed the same address on every release note regardless of which office actually issued it. Now reads `note.warehouse_address ?? branding?.warehouse_address` (per-note first, tenant singleton only as fallback for older notes with no linked warehouse). Added physical document number, packing list invoice numbers, and cartons-balance rows; a new conditional payment block (amount paid, balance owed, receipt number or "ON CREDIT" + granted-by, debt due date — rendered only when there's actually a payment, balance, or credit to show); and the signature block expanded from 2 generic lines to the paper form's 4 named ones (Customer's Rep, Customer Service Officer, Accounting Officer, Warehouse Attendant), plus the paper form's liability disclaimer as a new bold footer paragraph.

**Verified live:** fetched the one pre-existing real release note via `GET /v1/release-notes/{id}` and confirmed it now returns real, previously-invisible `amount_paid_ngn`/`balance_ngn`/`total_ngn`/`is_on_credit`/`packages_balance` while correctly showing `null`/`[]` (not fabricated data) for fields that genuinely don't exist on that older note (warehouse, document number, invoice numbers, due date).

**Tests:** `print/PrintReleaseNote.test.tsx` (new, 9 cases — per-note warehouse over tenant fallback, fallback when no warehouse linked, document/invoice numbers shown, payment-block field visibility in every combination, receipt number replacing "ON CREDIT" once linked, balance-of-cartons on a partial release, all 4 signature lines + footer disclaimer, payment block omitted entirely when nothing paid/owed/credited). Existing fixtures updated for the extended `ReleaseNote`/`PickupResult` interfaces: `api/releaseNotesRules.test.ts`, `warehouse/WarehouseDashboard.test.tsx`, `nigeria/ReleaseNoteDetail.test.tsx` (also gained a `QueryClientProvider` wrapper — `RecordPickupModal` now calls `useWarehouses()`/`useStaffList()`, which need one), `readonly-impersonation.test.tsx`. 849 backend + 744 frontend tests pass.

**Process note:** the bare `npx tsc --noEmit` (no `-p` flag) was discovered mid-task to silently pass even with real type errors present — only `npx tsc -p tsconfig.app.json --noEmit` (the project's actual config, which `tsconfig.json` merely references) catches them. Several of the fixture fixes above were only found this way. Any prior "clean tsc" claim in this session that used the bare command should be treated as unverified.

Tests: `BillingDetail.test.tsx` gained a `paymentClaimApi` mock (previously absent from this file entirely) and 3 new cases spying on `queryClient.invalidateQueries` — confirming a claim, rejecting a claim, and recording a payment each call it with `{ queryKey: ['billing'] }`. 744 frontend tests pass. No backend change — verified the write path is correct by reading `confirm_payment_claim`/`confirm_payment()` rather than modifying them.

## CBM rate: currency choice + per-package-type rates (2026-09-20)

User: "For CMB rate, let's allow the tenant admin to have multiple options for the rate: 1. One Single rate with options of either Naira or Dollar. 2. Rates targeted to Bags, Cartons and Bales (for e.g carton and bags can have the same rate while bale can have a different rate)." Full backend account (new `shared/cbm_rate.py`, `billing`'s per-package-type grouping, new `billing` columns) in `07_api_tenant_management.md`'s CBM Rate section and `11_api_billing.md`'s Billing Calculation section.

**`api/tenantManagement.ts`** — `CbmRateConfig` gained `currency`/`rate_mode`/`bag_rate`/`bale_rate` (was just `{rate_usd}`); new `UpdateCbmRateInput`/`CbmRateCurrency`/`CbmRateMode` types; `configApi.rateHistory`'s CBM member fixed from `'cbm_rate_per_unit'` to `'cbm_rate'` (see ground-truth fix below). `hooks/useConfig.ts`'s `useUpdateCbmRate` updated to match.

**`pages/tenant-admin/CbmRateConfig.tsx`** rewritten: a Currency (Dollar/Naira) toggle and a Rate-by (Single rate/By package type) toggle, both styled like `DollarRateConfig.tsx`'s existing percentage/flat toggle. Flat mode shows one numeric input; per-package-type mode shows three (Cartons/Bags/Bales) with a note that any other package type bills at the carton rate. `RateHistoryTable` now gets `rateType="cbm_rate"` (was the wrong value, see below), `valueKey="carton_rate"` (always present and meaningful regardless of mode, since flat mode keeps all three equal), and a currency-aware `prefix` (₦/$) instead of a hardcoded `$`.

**`pages/china/CreatePackingList.tsx`**'s live pricing card: this wizard doesn't collect a per-item package type, so it can only ever estimate with one representative rate (`carton_rate`, the same rate any unrecognized type bills at) — switched from the old `cbm.rate_usd`. Made the USD/NGN tile pair currency-aware: when the tenant prices in NGN, the NGN tile is computed directly and the USD tile is derived via the FX rate, mirroring the backend's own approach, instead of always computing USD-first.

**`pages/nigeria/BillingDetail.tsx`** (staff) and **`pages/customer/MyBillingDetail.tsx`** (customer) both gained a conditional per-package-type breakdown (carton/bag/bale CBM, rate, subtotal), shown only when `billing.cbm_rate_mode === 'per_package_type'` — a flat-rate invoice's existing single rate line is unchanged, avoiding new noise for the common case. Without this, a customer on a per-package-type or NGN-priced invoice would see only a back-derived blended USD number that corresponds to nothing they were actually billed against — a real trust/audit gap on a money screen, flagged during design review and closed in the same pass rather than deferred. `api/billing.ts`'s `Billing` interface gained the matching optional `cbm_rate_currency`/`cbm_rate_mode`/`cbm_breakdown` fields.

**Ground-truth bug found live: `rate_history`'s `rate_type` mismatch.** The backend has always written `rate_type="cbm_rate"` for CBM changes, but the frontend queried `"cbm_rate_per_unit"` (the `tenant_config` *key*, not the `rate_history` *rate_type*) — so the CBM Rate History table/chart silently never matched any row, with no error (just an empty table). Fixed frontend-side only.

**Ground-truth bug found live: a real browser crash, invisible to mocked unit tests.** `get_cbm_rate`'s response returned raw `Decimal` values, which the backend's `success()` response helper serializes via `json.dumps(..., default=str)` — silently turning every rate into a JSON *string* over the wire, while `update_cbm_rate`'s response (already `float`-cast) returned a JSON *number* for the same field. `CbmRateConfig.tsx` calls `.toFixed(2)` on these values (a JS operation that doesn't exist on strings) — loading the page threw `config.carton_rate.toFixed is not a function`. Every Vitest unit test mocks `configApi.getCbmRate` to return a plain JS number literal directly, so this class of bug is invisible to that suite entirely — only caught by actually loading the real page against the real backend (`e2e/flows/cbm-rate-config.spec.ts`, new). Fixed backend-side: `get_cbm_rate` now casts to `float` before returning, matching `update_cbm_rate`. Note: `get_dollar_rate` has the identical latent issue, currently benign only because `DollarRateConfig.tsx` happens to use `.toLocaleString()` everywhere (a no-op-through on a string, not a crash) rather than `.toFixed()` — left unfixed as out of scope for this task, flagged for whoever next touches that endpoint.

**Ground-truth bug found live: a stale return-value bug from the pre-2026-09-20 code this replaced.** `update_cbm_rate`'s return statement was a leftover `{**new_value, "previous_rate_usd": current.get("rate_usd")}` from the old single-rate shape — `current` (from the new `get_cbm_rate`) no longer has a `"rate_usd"` key, so this field was always `None` and the frontend never even reads it. Fixed by returning `new_value` directly, matching `get_cbm_rate`'s shape.

**Verified live against the real running stack:** all four currency/mode combinations (flat/USD, flat/NGN, per-type/USD, per-type/NGN) via direct `PUT` calls; a genuine mixed carton+bale billing record generated via `handle_payment_due` against real seeded packing-list data (carton: 1.85 CBM × $45 = $83.25; bale: 3.2 CBM × $60 = $192.00; blended `cbm_rate_usd` = 275.25/5.05 = $54.5050 exactly) — confirmed correct via both a direct DB read and the real `GET /v1/billing/{customer-id}` HTTP response; a CBM dispute filed and resolved against that same per-type invoice, confirming `resolve_dispute` needed zero code changes and its existing math (`corrected_cbm × billing.cbm_rate_usd`) stayed exactly correct; the `rate_history` round-trip (4 consecutive rate changes, all correctly stored and queryable under `rate_type="cbm_rate"`, including the tenant's real pre-existing pre-2026-09-20-shape history row still rendering correctly). Test billing/dispute records created for this verification were deleted afterward; the tenant's CBM rate config was reset to its original flat/USD/$45 state.

**Tests:** new `tests/unit/test_cbm_rate.py` (13 cases — `normalize_package_unit`, all three `get_cbm_rate_config` shape cases, `compute_cbm_charge` including the bucket-then-sum rounding rule); `test_tenant_management.py` gained `TestUpdateCbmRateRequestValidator` (4), `TestGetCbmRate` (2, including the float-cast regression test), `TestUpdateCbmRate` (3) — 12 new; `test_billing.py` gained `TestHandlePaymentDueCbmPricing` (5 cases: flat stays exact, genuine per-type mix uses the blended average and records the breakdown, NGN currency back-derives `subtotal_usd`, the skip-guard fires only when all three rates are zero, one zero rate among others still bills normally) and updated `TestHandlePaymentDueNotification`'s mocks for the new `service.get_cbm_rate_config` name (mirroring the existing `get_effective_dollar_rate` patch idiom). 922 backend tests pass. Frontend: new `CbmRateConfig.test.tsx` (9 cases), `CreatePackingList.test.tsx` gained an NGN-currency case (6 total), plus the new e2e file above. 786 frontend unit tests pass; only the 3 pre-existing unrelated `tsc -p tsconfig.app.json` errors remain (unchanged from before this task, all in files untouched by it).

## Release flow audit: count-based release unreachable from the UI, duplicate-release guard, stale release-note list (2026-09-20)

User: "double check release flow, we need to make sure that everything is alinged and wokring well and E2e is tested from front end." Backend account (the duplicate/over-release guard) in `13_api_payment_release.md`'s "Duplicate / over-release guard" section.

**Ground-truth gap found live: count-based release (`packages_released`/`package_unit`) was a real, working backend feature with zero UI path to it.** `CreateReleaseNoteInput` has declared these fields since the 2026-09-13 pass, and the backend's `generate_release_note` has always supported them as an alternative to `carton_tags` — but `nigeria/BillingDetail.tsx`'s `GenerateReleaseNoteModal` never rendered a form field for either one, and its `canSubmit` hard-required `cartonTags.length > 0`, making the mode unreachable through the browser regardless. The only release notes using it were ones created by direct API calls during backend testing. Fixed by adding a "Release by: Carton tags / Count" toggle (mirrors `DollarRateConfig.tsx`'s existing percentage/flat toggle pattern) that swaps the carton-tags textarea for "Packages released" (number) + "Package unit" (text, defaults to "cartons") fields; `handleSubmit` sends `carton_tags: []` and the count fields in count mode, the reverse in tags mode — matching the backend's own `is_count_based = not carton_tags and packages_released is not None` branch exactly.

**Accessibility/testability gap:** four `<select>` elements (`GenerateReleaseNoteModal`'s warehouse picker; `RecordPickupModal`'s warehouse, Customer Service Officer, Accounting Officer, and delegate ID-type pickers) had a visible `<label>` with no `htmlFor`/`id` association — invisible to screen readers and to `getByLabel` in tests. Added an `aria-label` matching each one's visible text; no visual change.

**Release-notes list served up to 3 minutes of stale data after any mutation.** `lib/queryClient.ts`'s own doc comment states the intended pattern: "Mutations call invalidateQueries immediately, so the [3-minute default staleTime] timer is just a safety net." `ReleaseNoteDetail.tsx` never imported `useQueryClient` at all — none of its three mutations (pickup, split, reissue) invalidated `releaseNoteKeys`, and `BillingDetail.tsx`'s generate-success handler invalidated `billingKeys` but not `releaseNoteKeys` before navigating straight to `/release-notes`. Reproduced live: split a note, land back on `/release-notes` (freshly navigated to, not reloaded), and the new child note was missing from the list because `useReleaseNoteList`'s cached query hadn't been told anything changed. Fixed by adding `qc.invalidateQueries({ queryKey: releaseNoteKeys.all })` to all four success handlers (generate, pickup, split, reissue).

**New E2E coverage** (previously zero for any of this, per an explicit audit of `frontend/e2e/flows/`):
- `e2e/flows/release-note-migration-fields.spec.ts` — generates a count-based release note through the real UI (warehouse selection, physical document number, packing list invoice numbers), views the resulting detail page, records a pickup through `RecordPickupModal`'s warehouse/CSO/accounting-officer pickers, opens the print view, and exercises the PDF export button. Uses a different real seeded billing (Ngozi Adeyemi, ACME001001, `INV-A-001`) than the pre-existing `billing-payment-and-release.spec.ts` (Ibrahim Musa, ACME001001) specifically so the two don't collide over the same record.
- `e2e/flows/release-note-split.spec.ts` — generates a two-carton-tag release note (Ngozi Adeyemi, ACME001002, `INV-A-003`) and splits one tag into a child note through `SplitModal`, confirming the child appears as a second, "Partial release" row on the list.
- Both files follow the established `test.skip()` idempotency-guard convention (real seeded data exhausts itself after one genuine run — see `billing-payment-and-release.spec.ts`'s own header comment) and share a fix applied to all three release-note e2e files: the release-notes list's own data fetch starts a tick after the nav click settles, so a one-shot `.count()` on the row locator immediately after `goToViaNav` can race the `Table` component's loading skeleton (5 blank rows) and wrongly report "not found." Replaced with an `expect(...).toHaveCount(1, { timeout: 10_000 })` (auto-retrying) pattern everywhere this list is checked right after navigating to it.
- Split/reissue's own cross-note duplicate exposure (splitting the same tag into two separate children isn't blocked, mirroring the top-level gap fixed in `generate_release_note`) was noted but not fixed in this pass — `split_release_note` validates only against its own parent note's `carton_tags`/pickup records, not sibling release notes for the same billing. Flagged here as a known follow-up, not yet reproduced live.

**Verified live against the real running stack:** the duplicate-release probe that motivated the backend fix (re-POSTing the exact carton tags already on a `picked_up` release note) was reproduced against a real seeded record before the fix (silently created a duplicate `active` note — since deleted as test debris) and confirmed rejected with a clean `422` after it. `make bootstrap` had to be re-run mid-task after a Docker container restart wiped Moto's in-memory EventBridge bus (`event bus logistics-events does not exist` — `make up` does not restore this, only `make bootstrap` does, per `LOCAL_TESTING.md`); this is environmental, not a code regression, but cost real debugging time before the actual duplicate-release symptom (a raw 500 from the event-publish failure, masking the fact that the DB write beneath it had already, incorrectly, succeeded) was correctly separated from it.

**Tests:** 4 new backend cases (`tests/unit/test_payment_release.py::TestGenerateReleaseNoteDuplicateGuard`) plus 4 existing `TestGenerateReleaseNote` cases updated to mock the new repo call — 894 backend tests pass. 776 frontend unit tests pass (no frontend unit test changes needed; the fixes are UI/query-cache only, exercised by the new e2e coverage instead).

## Logout didn't actually log out in local dev (2026-09-13)

User report: "i logged in as ifesinachi (customer), when i logout and refresh the page it still logged in." Full technical account — the two compounding `LocalAuthProvider` bugs (hardcoded `status: 'authenticated'`, and `session` falling back to the always-on dev-identity shim the instant a real Cognito session cleared, with no way to represent "logged out" at all, including across a reload since that requires state a plain React variable can't hold) and the fix (`src/auth/LocalAuthProvider.tsx`'s new `loggedOut` flag, `src/lib/localDevSession.ts` for its reload-surviving persistence, `RoleSwitcher.tsx`'s new logged-out placeholder option) — is in [04_auth_and_session.md](04_auth_and_session.md)'s matching "Explicit logout must not resurrect the dev-shim session" entry, since this is auth-provider plumbing rather than a page or component.

**Verified live, two ways:** 12 new unit cases in `LocalAuthProvider.test.tsx` (immediate post-logout state, simulated reload via unmount+remount, a stale-cookie-wins edge case, re-entering via `RoleSwitcher`, logging back in afterward), plus a new Playwright e2e spec (`e2e/flows/auth-logout.spec.ts`) driving a real Cognito-via-Moto login/logout/reload cycle against the actual running local stack — all 4 cases pass run serially. 758 frontend unit tests pass; only the 3 pre-existing, unrelated `tsc -p tsconfig.app.json` errors from earlier in this session remain (`MyBillingDetail.tsx` unused exports, two test-fixture type mismatches), all in files untouched by this fix.

**Same-day follow-up — this fix broke the dev role switcher:** reported immediately after shipping ("The Dev selection bar for roles is no longer working"). The sticky `loggedOut` flag was being set unconditionally inside `logout()`, but `api/client.ts`'s 401-recovery path calls that same `logout()` on any unrecovered 401 — routine in local dev, unrelated to any real session. Fixed by making `logout()` a complete no-op whenever there's no real `cognitoSession` to end (see 04_auth_and_session.md's matching entry for the full account and the new regression test). Re-verified `auth-logout.spec.ts` (real login/logout) and `auth.spec.ts` (all 6 dev roles via the switcher) pass together in the same serial run — 759 frontend unit tests pass.

## Dollar rate: markup on a Bybit-sourced base, not a typed-in number (2026-09-19)

User: "for the dollar rate i want to use the black market price, using the bybit p2p naira rate, then on the frontend we can add a markup for the tenant admins... markup can be in percentage... or in dollars." Full backend account (the Bybit P2P fetch, Redis caching, `platform_settings` fallback chain, and the migration from four independent `tenant_config['dollar_rate']` readers to one shared `shared/fx_rate.get_effective_dollar_rate()`) is in `07_api_tenant_management.md`'s Dollar Rate section and `02_shared_utilities.md`'s `shared/fx_rate.py` entry.

**`pages/tenant-admin/DollarRateConfig.tsx` rewritten.** It used to show one editable number ("Rate: ₦1550 per $1 USD") with a bare numeric input to overwrite it. Now: three `Kvp` rows — "Base rate (Bybit P2P)" (with a relative "updated Xm ago" from the new `fetched_at` field), "Your markup" (formatted per type — `"12%"` or `"₦10 per $1"`), and "Effective rate charged to customers" (the number that actually feeds billing, in the primary brand colour). The update form became a type toggle (Percentage / Flat ₦) plus one numeric input whose label and placeholder switch with the selected type, replacing the old bare "New rate" field. `RateHistoryTable`/`RateTrendChart` (shared with `CbmRateConfig.tsx`) needed **no changes** — the backend still writes a plain numeric `rate` into each `rate_history` row (now the *effective* rate at the moment the markup changed, not a typed-in value), so the existing `valueKey="rate"` charting keeps working unmodified.

- `api/tenantManagement.ts` — `DollarRateConfig` interface gained `base_rate`, `markup_type`, `markup_value`, `source`, `fetched_at`; new `UpdateDollarRateMarkupInput` type; `configApi.updateDollarRate` body changed from `{rate, effective_from?}` to `{markup_type, markup_value}` (a deliberate breaking change to that one endpoint's contract — single frontend in this repo, confirmed acceptable with the user).
- `hooks/useConfig.ts` — `useDollarRate()`/`useUpdateDollarRate()` types updated to match (the page itself still doesn't use these hooks — a pre-existing inconsistency noted but not fixed here); dropped `useDollarRate`'s `staleTime: STALE_FOREVER` since the effective rate now tracks a live market feed (~10 min server-side cache) rather than a value an admin sets once and rarely touches.

**Verified live** against the real running stack: `GET /v1/tenant/dollar-rate` returned a genuine live Bybit P2P rate (₦1368.80/$ at test time); a second call within the 10-minute window returned the identical `fetched_at`, confirming the Redis cache; `PUT` with both a flat and a percentage markup produced exactly the expected arithmetic (`1368.80 + 15 = 1383.80`; `1368.80 × 1.05 = 1437.24`); a fresh billing record generated via `handle_payment_due` froze `exchange_rate_ngn` at the then-current effective rate, confirming the new source flows all the way through to real invoices. Caught one real bug this way: `rate_history` silently stopped recording any dollar-rate change at all, because the new code passed raw `Decimal` values into a `json.dumps()` call with no `default=str` (unlike `shared/audit.py`'s, which has one) — fixed by casting to `float` before the call; see `00_MASTER_PLAN.md` for the full account.

**Tests:** `DollarRateConfig.test.tsx` (new, 8 cases — base/markup/effective display, percentage-vs-flat formatting, form pre-fill, switching markup type, successful update, disabled-when-empty, and error banners for both the initial load and the update failing). 767 frontend unit tests pass.

## Refreshing any dev-shim page reset the active role to platform_admin (2026-09-19)

User: "when i am on tab e.g customer or any other tab and i refresh, it goes to the dashboard. this is experienced in the tenant admin page. i believe this issue will be persistent on other pages as well, check all the pages and ensure that we handle it properly." Full technical account (the `LocalAuthProvider` `identity`-state-had-no-persistence root cause, why it reproduces on every page rather than one, and the theoretically-similar-but-unreproducible real-Cognito-login race that was investigated and deliberately left unfixed) is in [04_auth_and_session.md](04_auth_and_session.md)'s matching ground-truth entry, since this is auth-provider plumbing rather than a page or component.

**Verified live**, reproducing the exact bug first: Playwright confirmed a reload on `/admin/customers` while acting as `tenant_admin` landed on `/platform/dashboard` every time — and, per the user's prediction, the same reproduced identically on a `ConfigLayout` sub-nav page, a China-office page, and a customer-portal page, since the bug is in the shared identity-restoration step, not any individual page. After the fix (`src/lib/localDevSession.ts` gained a sessionStorage-backed persisted identity, restored on `LocalAuthProvider` mount instead of always defaulting to `platform_admin`), all 4 stayed on their original URL after a reload — now permanent e2e coverage in `e2e/flows/auth.spec.ts`'s `describe('dev role survives a reload')` block. 3 new unit cases in `LocalAuthProvider.test.tsx`; 769 frontend unit tests pass.

**Same-day follow-up — a second, pre-existing switcher bug surfaced testing the fix above:** user report — "the dev role switcher is not working" — persisted after a dev-server restart and hard browser refresh, ruling out stale HMR state. A lingering real Cognito session (e.g. left over from earlier real-login testing in the same browser tab) unconditionally outranks the dev shim, so picking a role updated the dropdown but had zero visible effect on the actual session — indistinguishable from "does nothing." Fixed by having `setIdentity()` end any active real session before switching, the same way `logout()` already did (see 04_auth_and_session.md's matching entry). Reproduced live (real customer login → pick `tenant_admin` → app stayed on the customer's page) before the fix, confirmed switching correctly after it, including surviving a subsequent reload. New unit case in `LocalAuthProvider.test.tsx`; 770 frontend unit tests pass.

## `PaymentSuccess.tsx` claimed success unconditionally, trusting a webhook that could never fire (2026-09-19)

User: "when i pay a bill as a customer through paystack, it showed successful, view invoice and when i clicked view invoice, it took be back to the same billing page and on that page the payment is not made. if i click pay it attempts making the payment again." Full backend account (why the webhook alone is structurally unreliable — Paystack can never reach a local dev URL at all, and can be delayed/lost even in production — and the new `POST /v1/payments/{billing-id}/verify` reconciliation path that fixes it) is in `13_api_payment_release.md`'s matching ground-truth section.

**`pages/customer/PaymentSuccess.tsx` rewritten.** It used to render one static, unconditionally-cheerful message ("being confirmed automatically") with no actual verification — the page had no idea whether the payment had really succeeded. It now reads `reference`/`trxref` from the URL (Paystack appends one of these to the `callback_url` regardless of outcome) and calls `billingApi.verifyPayment()` on mount, rendering one of four real states: a brief "Confirming your payment…" loading state, a success state (unchanged copy/CTAs), a new "not yet confirmed" pending state (Paystack itself hasn't reported success — e.g. an abandoned/failed attempt), and a new non-scary error state if the verify call itself fails (network/gateway issue) rather than ever silently claiming success.

- `api/billing.ts` — new `billingApi.verifyPayment(billingId, reference)`, `POST /v1/payments/{id}/verify`. Safe to call more than once (e.g. the customer refreshing the success page) — the backend shares the exact same idempotent confirmation path the webhook uses.

**Verified live against the real Paystack test API**, not mocked: initialized a real transaction for the exact billing record from the bug report, confirmed it correctly read as "not yet paid"; completed it for real via Paystack's server-to-server test Charge API (avoiding needing to automate Paystack's own hosted checkout UI in a browser) to get a genuinely successful reference; called the new verify path and confirmed the exact stuck billing record flipped to paid — checked via the real `GET /v1/billing/{customer_id}` HTTP endpoint the frontend itself calls, not just a direct DB read. Calling verify a second time with the same reference correctly reported success again with no duplicate payment record.

## App-wide responsive pass (2026-09-20)

User: "Responsiveness of the website is not working properly. Make sure that it is responsive 100% across all pages" — scoped through follow-up questions to a comprehensive, all-domain pass (not just one area), prioritizing genuine UX quality over speed ("we are still in development phase, it is not live, so nothing to rush"), and explicitly choosing the real documented `Table` card-list fallback over extending the existing horizontal-scroll pattern when offered both options.

A full audit found responsive coverage very uneven: 22 nigeria-domain page stylesheets had **zero** responsive CSS; the customer-portal shell had no mobile nav at all (no hamburger, no drawer, unlike the staff shell); the `Cross-Domain UX Conventions` "tables collapse to a card list" rule above was never actually built (`Table` just scrolled horizontally); the 44×44px/16px-input/full-screen-modal mobile rules were implemented on exactly one screen (`WarehouseDashboard`) and not mirrored in its own near-duplicate (`ReleaseNoteDetail`'s `RecordPickupModal`); and ~18 hand-rolled modals plus ~15 fixed-column stat grids overflowed or clipped below ~480–860px, several of them (`PaymentGatewayConfig`, `WebhookConfig`, `PackingListList`/`PackingListDetail`/`ContainerDetail`'s modals) with a literal fixed `width: 480px` — genuinely wider than any phone, not just unoptimized.

Full implementation detail (the `Table` `ResizeObserver`-based card view and why it's a different mechanism than the rest of the app's CSS-only responsive rules, the `ShellDrawer` extraction shared by both shells, the canonical bottom-sheet modal pattern and every file it was applied to, the `Field` iOS-zoom fix, the grid-reflow pattern, and the hero/toolbar `flex-wrap` fixes) is documented in [03_component_library.md](03_component_library.md)'s matching 2026-09-20 addendum, since almost all of it lives in shared components rather than domain-specific page code. The 860px breakpoint convention itself is written down in [02_design_tokens_and_theming.md](02_design_tokens_and_theming.md) for the first time (previously informal).

Domain-specific fixes not covered by the shared-component addendum:
- `customer/Account.tsx` — three inline `style={{ gridTemplateColumns: '1fr 1fr' }}` grids (profile fields, GDPR data-export/consent cards) moved into a new shared `.twoCol` class in `customer.module.css` (`repeat(auto-fit, minmax(220px, 1fr))`) — inline styles can't be targeted by a CSS-module `@container` rule at all, so these stayed rigid 2-column no matter how narrow the shell got.
- `customer/MyBillingDetail.tsx`'s CBM-dispute modal, `nigeria/CarryoverLedger.tsx`'s exempt-carryover modal, `tenant-admin/ChargeTypes.tsx`'s add/edit modal — all hand-rolled inline-styled `position: fixed` modals with no CSS module (same shape as `design/components/LimitReachedModal.tsx`, fixed the same way): added `maxHeight: '90vh'`/`overflowY: 'auto'` for tall-content safety and `size="lg"` (44px) on their action buttons.
- `nigeria/BillingDetail.module.css` `.hero` and `nigeria/ClaimDetail.module.css` `.hero` — title + up to 4 action buttons (Record payment / Add charge / Apply carryover / etc.) with no `flex-wrap`, genuine overflow risk once more than 2 buttons are shown.
- `china/PackingListList.module.css` `.bulkBar`/`.bulkActions` — the bulk-selection toolbar (a label that can grow long — "N were created by you and need another approver" — alongside up to 3 buttons) had no `flex-wrap` at all.
- `china/CreatePackingList.module.css`/`ImportPackingLists.module.css` `.actionsRow`/`.actionsRowFull` — multi-step form footers (Back / Save draft / Next, 3 buttons) gained `flex-wrap`.
- `tenant-admin/ActivityLog.tsx`, `platform/CreateTenantPage.tsx` — inline `gridTemplateColumns: '1fr 1fr'` (an audit-log before/after JSON diff, and two admin-creation form rows) switched to inline `repeat(auto-fit, minmax(...px, 1fr))` directly, since `auto-fit` needs no container query to be responsive on its own.

**Verified live** against the real running stack (Playwright, 375×800 viewport — jsdom, the unit-test environment, has no layout engine and never evaluates `@container`/`@media` at all, so this was the only way to actually catch these): confirmed `BillingList` renders the `Table` card view with zero `<table>` elements and no horizontal overflow; confirmed `BillingDetail`'s hero actions, the `PackingListList` bulk bar (triggered via a real row selection), and the customer `Account` page (all three tabs) have no horizontal overflow; confirmed the customer-portal hamburger opens the drawer, navigates to a different page via a drawer link, and the hamburger is present again on the new page. This live coverage is now permanent in `e2e/flows/responsive_smoke.spec.ts` — see [17_testing.md](../17_testing.md) for the full test list. 799 frontend unit tests pass (up from 767 before this pass — new `Table.test.tsx` card-view cases and `CustomerTopNav.test.tsx` drawer cases), zero regressions.

**Tests:** `PaymentSuccess.test.tsx` (new, 6 cases — confirming-then-success, falling back to `trxref` when `reference` is absent, a pending state, a verify-call-failure error state, a no-reference-at-all error state with zero API calls, and "View invoice" navigating correctly). 776 frontend unit tests pass; 890 backend unit tests pass (+11: `TestVerifyTransaction` for the raw Paystack HTTP call, `TestConfirmOnlinePayment` for the new service function's ownership/reference-matching/dedup/not-yet-successful logic).

## Frontend debugging pass — broken production build, a stale-response race, dead code (2026-09-23)

Part of the whole-project debugging pass (backend/infrastructure findings are in `docs/runbook.md`'s findings log).

- **`npm run build` was failing.** The script is `tsc -b && vite build`, and four type errors made the production build
  fail while `vitest` (which doesn't type-check) stayed green: two dead `CLAIM_STATUS_LABEL` / `CLAIM_STATUS_VARIANT`
  maps in `customer/MyBillingDetail.tsx` (pending and rejected claims are surfaced by explicit banners, confirmed ones
  by the billing status changing — the maps were leftovers, removed), a `disputeApi.list` mock returning `[]` instead of
  a `ListResponse` in `BillingDetailPaymentClaims.test.tsx` (and `BillingDetail` never calls `disputeApi.list`, so the
  line was a no-op and is removed), and a `TenantActivityEntry` test helper missing the required nullable
  `before_state`/`after_state`. `tsc -b --noEmit` is now clean and `npm run build` succeeds.
- **`TenantReports` stale-response race.** The report effect fired four parallel requests keyed on the date range with
  no cancellation, so changing the range while a slower earlier request was in flight let the *older* response
  overwrite the newer one (and clear `loading` early). Now guarded with a `cancelled` flag in the effect cleanup.
- **`MyBillingDetail` effect dependency** keyed on `billing?.id` with `billing` read inside — now reads a `billingId`
  const, so the dependency list is honest.
- **`useMemo` churn** in `BillingList`, `ClaimList`, `ContainerList`, `NotificationLog`: `const all = data?.data ?? []`
  built a fresh array every render while loading, defeating every downstream `useMemo`. Wrapped in `useMemo` keyed on
  the query data.
- ESLint: 0 errors; 4 dev-only `react-refresh/only-export-components` warnings remain (`ShellDrawer`, `AuthShell`,
  `DateRangeFilter`) — HMR ergonomics only.
- Not changed: the single 937 kB JS bundle (no route-level code splitting) — recorded as an open item in
  `docs/runbook.md`.

799 frontend unit tests pass; `npm run build` succeeds.

## Production-readiness pass: header consistency, bounded lists, server-side stat cards (2026-10-01)

Comprehensive pass to make every list/detail page consistent and correct at scale (data grows to tens of
thousands of rows). Three structural changes, applied app-wide:

- **Header consistency.** List pages carry their title in the shared `TopBar` (via `useTopBarSlot`), with an
  optional `subtitle` (new `TopBar`/`StaffLayout`/`TopBarContext` plumbing). 14 list pages migrated their inline
  page-title block into the TopBar slot; 7 detail-page heroes unified onto one `.hero`/`.heroTitle`/`.heroActions`
  spec (26px, `--color-ink`, `flex-start`, `flex-wrap`, mono for codes / display for names).
- **Bounded load-more lists.** New shared `ListFooter` (`design/components`) renders "Showing X of N {noun}" + a
  "Load more (N remaining)" button, and past a 500-row cap nudges the user to refine their search instead of
  accumulating unbounded DOM. Adopted by all migrated list pages. Tables already paginate (DOM bounded); this makes
  the accumulation explicit and capped.
- **Server-side stat cards.** Stat figures no longer aggregate a capped client sample — they come from SQL
  `COUNT(*) FILTER (...)` aggregate endpoints, so they stay correct regardless of page size. Endpoints + frontend
  wiring: `billingApi.stats()`/`report()`, `claimsApi.stats()`, `containersApi.stats()`, and (this increment)
  **`customersApi.stats()`** → `GET /v1/customers/stats` (`CustomerStats` = total/active/anonymised/with_whatsapp/
  shipments; `customerKeys.stats()`). Pages rewired: `BillingList`, `ClaimList`, `ContainerList`, `TenantReports`,
  **`AdminCustomerList`**, **`Dashboard`**.

**`AdminCustomerList`**: the loaded-page `useMemo` stats block (which framed figures "on this page") is replaced by a
`useQuery(customerKeys.stats())`. Stat cards + All/Active/Anonymised chip counts now read tenant-wide totals; the
"on this page" suffix is gone because the numbers are no longer sample-scoped.

**`Dashboard`** (tenant_admin + nigeria_office_staff): every numeric figure now comes from a stats endpoint, fixing
several capped-sample bugs:
- `customerCount` previously read `r.meta.pagination.total_count ?? r.data.length` — list endpoints don't return
  `total_count`, so it silently showed the loaded-row count. Now `customerStats.active`.
- Container count, the greeting summary line (in-transit / awaiting-customs / ready), and the pipeline Kanban
  per-stage count badges now come from `containerStats` (Kanban cards remain a bounded visual sample; the header
  badge + "+N more" use the true count).
- Unpaid-billing count + outstanding ₦ from `billingStats`; open claims from `claimStats.open`.
- "Incoming containers" is now a dedicated server query (`status=sealed,in_transit`, `sort=estimated_arrival_date
  asc`, `limit=5`) instead of filtering a capped client list, so it's correct even with thousands of containers.
  `claimStats`/`customerStats` queries are `enabled: isAdmin` (admin-only cards).

Gates: backend `TestCustomerStats` (service delegation + repository two-query mapping + empty-tenant) added to
`tests/unit/test_tenant_management.py`; `GET /v1/customers/stats` verified live against direct SQL (70 total / 372
shipments). Terraform route added; Postman "Customer Stats" request added. 799 frontend unit tests pass, `tsc` +
eslint clean.

### Follow-up: dashboard visual consistency with the list pages (2026-10-01)

Live-browser review (tenant_admin, 1440px) against the now-canonical list pages (Customers / Activity Log / Users — all audited consistent: TopBar title+subtitle, stat row, filter card, dense table) surfaced two Dashboard-specific inconsistencies:

- **Large ₦ figure clipped.** The "Outstanding" stat card rendered the raw `₦28,658,693.94` at the 30px display size, overflowing the ~210px card, while `BillingList` showed the *same* metric compactly as `₦28.66M`. Added `src/lib/format.ts::formatNgnCompact` (millions → `₦X.XXM`, large thousands → `₦XXXk`, else full; sign-preserving; `₦0` for null/zero/non-finite) and used it on both the Dashboard and `BillingList` stat cards — one source of truth, no drift. `BillingList`'s two inline `/1_000_000).toFixed()` computations were replaced by it.
- **Embedded "Recent containers" table rendered as giant mobile cards on desktop.** The `Table` card view switches at its own measured wrapper width ≤860px; the dashboard's left column (`.dashCols` = `minmax(0,1fr) 340px`) is ~776px on a wide screen, so the table collapsed to one big card per row — three containers filling the viewport, nothing like the dense tables everywhere else. Added an optional `Table` prop `cardBreakpoint` (default 860) so compact dashboard tables pass `cardBreakpoint={600}`: tabular at the ~776px desktop column, still collapsing to cards at real phone width (verified live: 0 `<table>` elements at 390px, dense table at 1440px). Applied to all five embedded dashboard tables (recent containers, pending packing lists, pending manifests, CBM disputes, recent payments).

Verified live in-browser at 1440px (dashboard now matches the list pages) and 390px (stat cards reflow, Outstanding fits, tables collapse to cards). Tests: `src/lib/format.test.ts` (new) + two `Table.test.tsx` `cardBreakpoint` cases. 806 frontend unit tests pass, tsc + eslint clean.

### Follow-up: filter-bar consistency across Customers / Users / Activity Log (2026-10-01)

Live review flagged the tenant-admin list pages' filters as inconsistent with each other and with `nigeria/BillingList` (the established pattern: chips + a 36px search + 36px controls, all inside one `Card`):

- **Shared filter-bar CSS** added to `tenant-admin/admin.module.css` (`.filterRow`, `.searchWrap`, `.searchInput`, `.filterControls`, `.controlGroup`, `.controlLabel`, `.control`) — mirrors BillingList's module so the three pages render identically. Every control sits at 36px so bottom edges line up.
- **Customers & Users search alignment.** Both used the full `Field` component (~44px tall) for their search box, which floated taller than the short filter chips next to it — the "not aligned/centralized" report. Replaced with the 36px `.searchWrap` icon+input (same as Billing), so the search now lines up with the chips. (The role/status **chip** filters were already functional — verified live, 5→1 rows on a China filter; the complaint was purely the visual misalignment.)
- **Activity Log restructure (the "scattered" report).** It was the only list page whose filters were *not* in a Card and used a flat row of eight stacked-label native `<select>`/`<input>` controls. Rebuilt onto the shared pattern: a `Card` containing (row 1) **Category as chips** (All / Money / Goods & shipments / Customers / Staff & access / Settings / System) + the `.searchWrap` search, and (row 2) the secondary controls (Record type, Action, When, From, To, Sort) on one aligned 36px baseline. Behaviour unchanged — category still narrows Record-type options, custom dates still override the preset, all filters still `AND`. Search/date inputs keep their test-facing accessible names via `aria-label`.

Note (dev-only): a hard browser reload of `/admin/activity-log` can briefly show a "Couldn't load — Insufficient permissions" banner — the local dev auth shim resets to its default role on reload, 403ing the first fetch before the tenant_admin role re-applies. Confirmed not reproducible via normal in-app navigation (0 fetch errors) and not a production concern (real JWT carries the role).

Verified live at 1440px: all three pages share one filter look; Activity Log reads as a tidy two-row card, not a scattered control strip. Tests: `ActivityLog.test.tsx` updated for Category-as-chips (4 cases) + the impersonation-not-offered check; `StaffUserList`/`AdminCustomerList` search assertions unaffected (placeholder/role-chip based). Full frontend suite green, tsc + eslint clean.

### Follow-up: BillingList horizontal scroll eliminated (2026-10-01)

Reported: the billing table scrolled left/right. It had 10 columns whose min-content (~1280px) exceeded the content area on anything but an ultra-wide monitor, so the `Table` wrapper's `overflow-x: auto` kicked in (and the action column was clipped at the right edge). Fixes:

- **Trimmed the list to triage columns.** Dropped `CBM` and `Paid (₦)` from the list (both remain on the billing **detail** page). The list now shows Reference, Customer, Container, Total, Outstanding, Status, Billed, action — Outstanding + Status already convey payment progress, and CBM is a cargo metric, not a billing-triage field. (`SORT_COLUMNS` billed_at index updated 8 → 6 to match.)
- **Shortened the `released_with_outstanding` badge** from "Released (outstanding)" to "Released" — one long nowrap badge was forcing the Status column to 236px; the red Outstanding amount already conveys the "with outstanding" part.
- **Tightened shared table cell padding** 16px → 12px horizontal (`Table.module.css` `.th`/`.td`/`.tdDense`) — a small global density improvement that helps every wide table.
- **Set `cardBreakpoint={960}`** on the billing table so that below ~1280px viewport it collapses to the card list (the app's documented responsive pattern) instead of scrolling. Verified live: table with 0 overflow at 1440/1366/1280, cards at 1180/1024/phone, and `document` has no horizontal page overflow at any width. Claims/Containers/Manifests were checked and already fit (0 overflow) — billing was the only offender.

Tests: `BillingList.test.tsx` green (sort-by-Billed index updated); full frontend suite green; tsc + eslint clean.

## Light / dark theme (2026-10-01)

Implemented app-wide light/dark theming. New: `src/design/colorScheme.tsx` (`ColorSchemeProvider` + `useColorScheme` — preference light/dark/system, persisted, system-aware, with a standalone no-provider fallback), `src/design/components/ThemeToggle.tsx` (single button cycling System → Light → Dark, placed in `TopBar` and `CustomerTopNav`), and a `:root[data-theme="dark"]` block in `tokens.css` plus a pre-paint anti-FOUC script in `index.html`. `Icon` gained `sun`/`moon`/`monitor`.

Key refactors that made the surface flip safe: introduced `--color-on-brand` (always white) and replaced all 23 `color: var(--color-surface)` on-colored-text usages across shell/components/pages with it; introduced `--color-primary-on-soft` (dark→bright green) for stat-card icon chips and consent pills. Fixed a handful of hardcoded light colors dark mode would have exposed (`TopBar` hover `#e8ebe8`, `MyShipments` card gradient `#fff`). Verified live in dark mode: staff dashboard/billing/customers, customer portal, and the login screen all render correctly with legible badges, amounts and controls. Full detail of the token model is in [02_design_tokens_and_theming.md](02_design_tokens_and_theming.md) and the `ThemeToggle` component in [03_component_library.md](03_component_library.md).

### Follow-up: dark-mode contrast audit (2026-10-01)

Ran a WCAG contrast pass over the dark palette and fixed the hard-to-read combinations, **dark-only** (new tokens' light values match the old ones). Biggest: `<Mono>` defaulted to the static `colors.ink` (#1c1b1c) from `theme.ts`, so container numbers/totals/CBM were near-invisible dark-on-dark across every table — now defaults to `var(--color-ink)` (verified live: those cells render light in dark, unchanged in light). Also lightened the accent badge/monogram text, accent eyebrow labels, and the platform/purple badge via new `--color-accent-on-soft` / `--color-accent-text` / `--color-role-platform-text` tokens. Detail + the WCAG numbers in [02_design_tokens_and_theming.md](02_design_tokens_and_theming.md) §Dark-mode contrast fixes. 813 frontend unit tests pass; tsc + eslint clean.

## Container capacity presets + searchable pickers (2026-10-01)

New feature: containers are created against a **capacity preset**, which drives the utilization bar's colour.

- **Backend:** migration 051 + `GET/POST/DELETE /v1/tenant/container-capacities` (see `07_api_tenant_management.md`). Ten built-in defaults (code constants) merge with tenant custom presets. Container create snapshots `container_type` (name) + `capacity_cbm` + `recommended_cbm` (`10_api_tracking.md`).
- **Searchable `Combobox`** (new shared component, `design/components/Combobox.tsx`): a button that opens a filter box + keyboard-navigable list. Used for the capacity picker on `CreateContainer` and — per the UX request — the **container picker on `CreatePackingList`** (replacing the native `<select>`; searching by container number is far better once a tenant has many open containers).
- **`CreateContainer`:** the old free-text "Container type" field is now a capacity Combobox (loads `containerCapacitiesApi.list()` via react-query); selecting a preset sends its name + CBM + recommended.
- **Admin page `ContainerCapacities`** (`/admin/config/container-capacities`, tenant_admin, in the config nav): lists defaults (read-only) + custom presets with a source badge, add-custom modal (validates recommended ≤ capacity), remove on custom only.
- **Utilization bar (`ContainerDetail`):** uses the stored `capacity_cbm` (fallback to the type-name estimate for pre-051 containers), and colours the fill by **absolute packed CBM — ≥70 green, 65–69 yellow, <65 red** (`utilizationColorClass`, status tokens so both themes stay legible). The track is now neutral (`--color-line-soft`) and the recommended load is shown on the sub-line.

Tests: `Combobox.test.tsx` (filter/select/keyboard/disabled/empty), `ContainerCapacities.test.tsx` (list/badges/create/validation), updated `CreateContainer`/`CreatePackingList` tests for the Combobox + react-query. 822 frontend unit tests pass; tsc + eslint clean. Backend: `TestContainerCapacities` (8) + `TestCreateContainer` capacity cases; 1093 backend tests pass.

### Follow-up: edit recommended CBM for presets (2026-10-01)

Admins can now **edit** a preset's recommended load (not just create/delete). New `PATCH /v1/tenant/container-capacities/{id}` + `containerCapacitiesApi.update`. The `ContainerCapacities` page has an **Edit** action on every row (defaults + custom); the modal is shared with create. For a **default** preset the name + capacity fields are locked (physical constants) and only recommended is editable — persisted as a per-tenant override in `tenant_config` (`container_capacity_overrides`), merged into the defaults on read; clearing the field reverts to the built-in value. For a **custom** preset all three fields are editable. Validation (recommended ≤ capacity) enforced client- and server-side. Verified live: default override (72) reflected in the list and reverted on clear, custom edit, `>capacity` 422, china-staff PATCH 403. Tests: `ContainerCapacities.test.tsx` (+2), `TestUpdateContainerCapacity` (8 backend).

### Follow-up: ContainerDetail overview — "Top shippers by CBM" (2026-10-01)

The overview's uncapped per-customer **table** (which would scroll endlessly for a 60–100+ customer container — STL409 has 68) was replaced with a compact **Top shippers by CBM** ranked list: the top 5 customers by CBM, each a single row (avatar + name, CBM, and an inline share-bar + % of the container's total packed CBM), with a `View all →` link to the Packing lists tab when there are more. The full per-customer breakdown (incl. contact) stays on the Packing lists tab; the overview keeps the Cargo summary tiles + utilization bar. Scales identically at 5 or 100 customers. Test: `ContainerDetail.test.tsx` — top-5 list + View-all navigation.

### Follow-up: searchable customer picker on CreatePackingList (2026-10-02)

Extended the searchable `Combobox` from the container picker to the **customer** picker on the packing-list wizard (step 1), replacing the native `<select>`. It filters on name **and** phone/email, and each option shows `phone · email` as meta — a tenant can have dozens/hundreds of customers, so type-to-find is the right UX (verified live: 50 customers, typing "chuk" narrows to 3). Test: `CreatePackingList.test.tsx` — the shared `selectFromCombobox` helper now drives both the Customer and Container pickers.

## Packing-list item entry: validation, package type, bale sizing, min-CBM, dates, draft edit (2026-10-02)

`CreatePackingList.tsx` (now also the draft-edit page via `/packing-lists/:id/edit`):

- **Input hardening** — the quantity cells (Wt dispatch/actual kg, L × W × H cm, Declared USD) are `type="number" min={0}` with an `onKeyDown` guard blocking `e/E/+/-` and a `sanitizeNumber` that rejects negatives/non-numeric. (The backend already enforced `ge=0`/`gt=0`; this stops bad entry at the source.)
- **Package type** — a per-row select (Carton / Bag / Pallet / Bale / Sack, default Carton), `PACKAGE_UNITS` / `PackageUnit` in `api/packingList.ts`.
- **Bale sizing** — a live `BIG BALE`/`SM BALE` badge on bale rows (`baleSizeAbbr`, threshold 0.3 CBM), mirroring the backend `bale_type`.
- **Minimum CBM** — the CBM cell shows the floored value (`applyMinCbm`, tenant `min_cbm_per_item`) with a `min` tag when a sub-minimum parcel is bumped up; totals + the live pricing estimate use the floored CBM. The admin sets the floor on the CBM-rate page (`CbmRateConfig.tsx`).
- **Shipment dates** — Loading date + Delivery date fields in step 1 (optional).
- **Draft editing** — a draft's detail page has an **Edit** button → the wizard loads it (`packingListApi.get`), with customer/container fixed and items/dates editable, saving via `packingListApi.update`. Submitting from there moves it to pending approval.
- **Searchable container + customer pickers** (from the prior pass) carry over.

Layout: the step-2 table was realigned with the new Type column and a compact CBM cell (value + min tag + bale badge); headers abbreviated (Wt disp./act., Decl.) to keep it on one row at desktop width. Verified live.

## Arrival warehouse on packing lists + Warehouses admin config page (2026-10-03)

A shipping company runs multiple destination warehouses (the migration-041 `warehouse` table, already used by release notes/pickups). Two additions let an admin manage them and tag each packing list with where its goods are bound.

- **Admin config page `Warehouses`** (`/admin/config/warehouses`, tenant_admin, in the config nav under Container capacities): lists the tenant's warehouses, **Add**/**Edit** modal (name required; city/state/address/phone optional), **Set default** (one default per tenant, shown with a `Default` badge), and **Remove** (soft-deactivate). The default row hides Set-default/Remove — the backend refuses to deactivate the default or the last active warehouse (422). ~~Remove = soft-deactivate~~ **superseded 2026-11-02: Remove is now "Delete" and is a real delete, falling back to an offered retire when records reference the warehouse — see the 2026-11-02 section below.** Mirrors `ContainerCapacities` structurally; uses the extended `warehousesApi` (`update`, `deactivate` added alongside the existing `list`/`create`/`setDefault`).
- **Backend:** the `/v1/warehouses` surface (payment_release) gained `PATCH /{id}` (edit) and `DELETE /{id}` (deactivate). A **duplicate** `/v1/tenant/warehouses` CRUD surface in the tenant-management service — never wired to the frontend, Terraform, or Postman — was **removed** (see `13_api_payment_release.md`). `arrival_warehouse_id` added to packing-list create/update (migration 053).
- **`CreatePackingList` step 1:** a searchable arrival-warehouse `Combobox` (pre-selects the tenant's default; filters on name/city). Sent as `arrival_warehouse_id`; omitting it defaults server-side to the tenant default. Prefilled on draft edit.
- **`PackingListDetail`:** the hero meta line shows `· To {arrival_warehouse_name}` when set (resolved via a LEFT JOIN in the list/detail queries).

Tests: `Warehouses.test.tsx` (list/badges/create/edit/set-default/deactivate — 6), `CreatePackingList.test.tsx` (+1: default warehouse pre-selected and sent), backend `TestWarehouseUpdateAndDeactivate` (5) + `TestResolveArrivalWarehouse` (4). Verified live against the local stack: first-warehouse-auto-default, set-default swap, edit, deactivate guards (default / last-active → 422), packing-list default resolution + explicit + invalid-404 + detail join; the removed `/v1/tenant/warehouses` route 404s while `/v1/warehouses` stays 200. 835 frontend + 1122 backend tests pass; tsc/eslint/ruff clean; terraform valid.

## Warehouse fixes: empty picker, real delete, visible set-default (2026-11-02)

Three defects reported from live use, each with a distinct root cause. The
2026-10-03 section above is amended by this one where they conflict.

**1. The arrival-warehouse picker was always empty on `CreatePackingList`.**
`GET /v1/warehouses` was gated to Nigeria-side roles, omitting
`china_office_staff` — who are exactly the role that creates packing lists. It
403'd, and `CreatePackingList.tsx` caught it with `.catch(() => [])`, so the form
rendered **"No warehouses configured"**: a permission error displayed as a
configuration state, which is why it survived unnoticed. The saved data was never
wrong (the backend applies the tenant default server-side), only the picker.

The role was added backend-side, and the page now tracks a separate
`warehouseError` so the two cases read differently — the placeholder becomes
"Warehouses unavailable" and the helper text says the list could not be loaded
*and* that the default is still applied on save. The rest of the form keeps
loading: one optional field must not take the whole form down.

**2. Delete is now a real delete.** "Remove" (soft-deactivate) became **Delete**,
with a confirmation, calling `warehousesApi.remove` → `DELETE /v1/warehouses/{id}`.
When the backend refuses with `rule_id: WAREHOUSE_IN_USE` (a release note, pickup,
payment record or packing list references it) the page does not dead-end: it
offers to **retire** it instead via the new `PATCH /{id}/deactivate`. Since
migration 056 scoped name uniqueness to active rows, a retired warehouse's name is
reusable either way — the original complaint was that a deleted name stayed
blocked forever.

**3. "Set default" looked like it did nothing.** The route and its transaction
were correct. The page's only feedback was an error banner rendered at the **top
of the page, above the table**, so a failure on a row further down was invisible.
Fixed structurally rather than cosmetically: a `bannerRef` + `scrollIntoView`
brings any failure into view, and success is now confirmed explicitly
("X is now the default warehouse") instead of relying on a badge quietly changing.
A `Make this the default warehouse` checkbox was also added to the **create**
modal (`is_default` on `CreateWarehouseInput`) — promoting a warehouse previously
required finding a separate row action afterwards. The checkbox is create-only;
promoting an existing warehouse stays the dedicated Set-default action, which
moves the flag atomically.

**`ApiError.ruleId`** is new on the API client: `shared/responses.error_response`
never serialized `BusinessRuleViolationError.rule_id`, so clients could only
branch on a specific rule by matching its English message. The retire-instead
prompt above is the first consumer.

Tests: `Warehouses.test.tsx` (+6 — real delete, declined confirmation, retire-on-
`WAREHOUSE_IN_USE`, success confirmation, surfaced failure, create-as-default),
`CreatePackingList.test.tsx` (+2 — "unavailable" messaging never reads as "none
configured"; the rest of the form still loads). Backend `TestWarehouses` +11.
1380 backend + 877 frontend tests pass (7 frontend failures in
`colorScheme.test.tsx`/`storage.test.ts` are pre-existing on `main` and unrelated).

**Correction (same day):** an earlier draft of this note claimed
`frontend/src/hooks/useWarehouses.ts` was dead code. **That was wrong** — the
grep behind it excluded every line containing `hooks/useWarehouses`, which is
exactly what an import statement contains, so it hid the real callers.
`useWarehouses()` is used by `nigeria/BillingDetail.tsx` and
`nigeria/ReleaseNoteDetail.tsx`. Only the two *mutation* hooks in that file,
`useCreateWarehouse()` and `useSetDefaultWarehouse()`, are genuinely unused —
`Warehouses.tsx` calls `warehousesApi` directly instead.

## Goods dates reordered and constrained on the packing-list wizard (2026-11-03)

User: *"During packing list creation, the dates for loading date and arrival date,
I want it to be flipped… the arrival date will be first and the loading date will
be second. With a clear description stating what they are for."* On a follow-up they
clarified that by "arrival date" they meant the **existing `delivery_date`** field,
not a new one.

**The semantics were wrong before this, not just the order.** Migration 052 and
the section copy described `delivery_date` as the *expected customer delivery* — a
destination-side future estimate. It is actually the date the **supplier delivered
the goods to the China warehouse**. Both dates are origin-side events, which is why
one must precede the other.

| Field | Shown | Means | Rule |
|---|---|---|---|
| `delivery_date` | 1st | Received in the China warehouse | not a future date |
| `loading_date` | 2nd | Loaded into the container | same day as delivery or later |

Section head is now **"Goods dates"** with the sub *"Delivery comes first — cargo
has to reach the warehouse before it can be loaded."*, and each field carries its
own one-line helper rather than leaving the meaning to a shared subtitle.

**Guarded three ways, deliberately:**
1. `max={today}` on the delivery input and `min={deliveryDate}` on the loading
   input, so the commonest mistakes are **unreachable in the native picker**
   rather than merely rejected after the fact.
2. Inline errors replace the helper text and **disable "Next"**, so an invalid pair
   cannot even reach step 2.
3. The same rules on the Pydantic models (see
   [08_api_packing_list.md](../08_api_packing_list.md)) — the client guard is a
   convenience, not the enforcement.

**Timezone trap avoided.** "Today" is computed from the user's **local** date,
built field by field rather than via `toISOString()`, which would convert to UTC.
The China office is UTC+8, so for several hours each evening `toISOString()` would
have flagged the date on their own wall calendar as a future date. The backend
allows one day past UTC for the same reason. ISO `YYYY-MM-DD` strings are compared
as plain strings, so no `Date` parsing — and no further timezone shifting — happens
in the comparison.

`loading_date` has **no upper bound**: a packing list is written against a
container still in `loading` status, so a planned load date is legitimate.
Both fields remain optional, as they were.

Tests: `CreatePackingList.test.tsx` (+8) and `TestShipmentDateOrdering` (+8).
Note the four frontend tests that assert "Next" is disabled now **select a
customer and container first** — without that precondition the button is disabled
anyway and the assertion proves nothing.

## Searchable country/state pickers and a real phone field (2026-11-02)

User instruction: *"Anywhere in the application where a country/state is required,
use a drop down with search instead of typing"*, and *"phone number fields are
typed manually, it should be a phone field with country code defaulted to
Nigeria."* Component design is documented in
[03_component_library.md](03_component_library.md); this is the rollout.

**Phone — 11 sites**, all now `PhoneField` emitting E.164: warehouse phone
(`Warehouses`), pickup contact + support WhatsApp (`CompanySettings`), customer
self-registration (`RegisterScreen`), onboarding request
(`RequestOnboardingScreen`), admin customer create (`AdminCustomerList`), tenant
create (`CreateTenantPage`), delegate phone (`ReleaseNoteDetail` **and**
`WarehouseDashboard` — the same modal duplicated in two places), customer account
(`Account`), and the public tracking lookup (`PublicTrack`).

**Country — 2 sites:** origin and destination on `RequestOnboardingScreen`.

**State — 1 site:** `Warehouses`, which also gained a **Country** picker, since
migration 057 added the column. Changing the country **clears** the state: a
state belongs to one country's list, so keeping it would submit a mismatched pair
the picker cannot even display.

**City stays free text.** The instruction was country/state, and warehouse cities
("Onitsha", "Trade Fair") are not a closed list worth maintaining.

**`PublicTrack` is the one that was actually broken.** Its lookup compared the
typed number against stored E.164 as one exact string, so a customer entering
`08012345678` never matched their own `+2348012345678`. The new field fixes the
browser, and the server-side normalisation (see
[10_api_tracking.md](../10_api_tracking.md)) fixes the public API too — necessary
because saved links and direct callers bypass the UI entirely.

**`CompanySettings` needed a second setter.** Its `set(key)` helper returns a DOM
*event* handler; `PhoneField` emits a value. Added `setValue(key)` beside it
rather than making the component fake an event.

Tests: `PhoneField.test.tsx` (8), `StateSelect.test.tsx` (11, covering
`CountrySelect` too), `phone.test.ts` (18), `countries.test.ts` (12). Existing
page tests updated where they typed a full E.164 into what is now the *national*
box — `AdminCustomerList` and `Warehouses`, the latter of which is what surfaced
the dial-code-doubling bug. 1385 backend + 927 frontend tests pass.

## Nigeria-ops dashboard overhaul — container pipeline redesign (2026-10-03)

User: the Nigeria office staff dashboard's "Container pipeline — every container by stage, click a card to open it" wasn't user-friendly and **hid a lot of containers**. The old `PipelineKanban` was 8 horizontally-scrolling columns, each capped at **6 cards** with a dead "+N more" label — so most containers in any busy stage were simply unreachable, and the whole thing needed horizontal scrolling.

**Redesign (`DashboardPipeline.tsx` + `.module.css`, new `ContainerPipeline` component):**
- **Stage rail** — a responsive `repeat(auto-fit, minmax(132px,1fr))` grid of stage tiles (never horizontal scroll; wraps to 2 columns on mobile). An "All active" lead tile plus all 8 pipeline stages, each showing the live tenant-wide count (from `containersApi.stats`, not a sample), a colour dot + label, and a thin proportional **meter** (count ÷ max-stage) for at-a-glance magnitude. Stage accent colours reuse the app's status semantics (same hues as the status badges: cool at sea → amber needs-attention → green done), so nothing is colour-alone (every tile is labelled).
- **Drill-down table** — selecting a stage (or "All active") drives the **complete, paginated** container list below via `useContainerList({ status })` + `ListFooter` load-more. Columns: Container (+ vessel), Route, Status badge, ETA/Arrival (actual once arrived, else estimated), Packing lists, View. **No container is hidden** — the full set is reachable by stage + load-more, and it scales to tens of thousands.
- **Stat row trimmed** — the per-stage operational counts (in transit / arrived / customs / at warehouse) now live in the rail, so the redundant stat tiles were removed; the Nigeria stat row is the headline + financials: Containers, Ready for pickup, Unpaid billing, Outstanding. `StatCard`'s label now wraps to 2 lines instead of truncating to "AWAITING…"/"READY F…" on a dense row.

Everything else on the Nigeria dashboard (manifest-verification queue, CBM-dispute queue, packing-list approval queue, recent payments, incoming containers) is retained. **Verified live** (Playwright, nigeria_office_staff, 1280px + 390px): the rail shows all stages with counts + meters, selecting "At Warehouse" refetches the at-warehouse list, the table collapses to cards on mobile, and there's no horizontal overflow at phone width. Tests: new `DashboardPipeline.test.tsx` (4 — all stages render, default active list, stage-select refetch, row shape); `Dashboard.test.tsx` updated. 841 frontend tests pass; tsc/eslint clean; build OK.

### Follow-ups: relevant bottom cards + pipeline search/filters (2026-10-03)

Two refinements after the overhaul, both from the user reviewing it live:

- **Bottom two-column cards made actionable.** "Incoming containers (next 5 ETAs)" and "Recent payments (latest confirmed)" were flagged as not relevant — both passive, and "Incoming" duplicated the pipeline rail's In-Transit/Sealed tiles. Replaced with what Nigeria ops actually chases: **Outstanding invoices** (`billingApi.list({status:'unpaid,partially_paid', sort:'billed_at', direction:'asc'})` — oldest unpaid first, amount in `--color-error`, click → billing detail to record payment) and **Awaiting pickup** (active release notes — released, not yet collected — with an "On credit" badge, click → release-note detail). The `.dashGrid2` grid became `repeat(auto-fit, minmax(440px,1fr))` so a lone card (e.g. nothing awaiting pickup) spans full width instead of being stranded at half, and the two bottom tables use `cardBreakpoint={420}` so they stay real tables at the grid-cell width and only collapse to cards on small screens.
- **Search + filters on the pipeline.** Per the user ("there should be filters and search for the container pipeline not just cards"), the pipeline gained a toolbar above the table: a **debounced search box** (`?q=` — container number / vessel, 300ms) and an **"Arriving" ETA quick-filter** (Any / ≤7 days / ≤30 days / Overdue → `eta_after`/`eta_before`, same backend contract as the full `ContainerList` filter panel). Stage (rail), search, and ETA are independent AND filters; the table heading shows "· filtered" when any is active, and the empty state distinguishes "no match" from "none in this stage". Verified live: typing `ACME9057` narrows to that one container. Tests: `DashboardPipeline.test.tsx` (+2 — search → `?q=`, ETA chip → eta range incl. the overdue upper-bound-only case). 843 frontend tests pass; tsc/eslint clean; build OK.

## Manifest table — package-type breakdown + weight (2026-10-03)

User: "the manifest table should show the cartons, bales, bags, sacks, pallet counts in each container." The list showed a single "Cartons" number (`total_cartons`), which under-reports mixed cargo — a container with 5 cartons + 4 bales stored `total_cartons = 5`, hiding the bales entirely (and the stored value can be stale between `recalculate_manifest_totals` runs).

- **Backend:** `GET /v1/manifests` + `GET /v1/manifests/{id}` now return `package_mix` (JSONB unit→qty), computed live from the manifest's **approved** packing-list items (`manifest/repository.py::_PACKAGE_MIX_LATERAL`, summing each item's `quantity` per `package_unit`; blanks → `unspecified`). See `09_api_manifest.md`.
- **`ManifestList`:** the "Cartons" column became a **"Packages"** breakdown cell — `5 ctn · 4 bale` (abbreviations: ctn/bale/bag/sack/plt, unspecified→pkg; via `orderedPackageMix()`), falling back to the carton count when no mix exists. Added a **Weight** column (`total_weight_kg`, already on the wire but never shown — vital for a container manifest). Columns: Container · Customers · Packages · CBM · Weight · Status.
- **`ManifestDetail`:** the "Total cartons" stat card became **"Packages"** (total quantity + a `5 ctn · 4 bale` sub-label); the hero line shows `N packages (mix) · CBM` instead of a bare carton count.

Verified live (nigeria_office_staff): STL420 shows `5 CTN · 4 BALE` in the list and `9 · 5 ctn · 4 bale` on the detail; weights render per row. Tests: `ManifestList.test.tsx` (+2: mix render + carton fallback), backend `TestManifestPackageMixQuery` (2: list + detail SQL carry the aggregation). 845 frontend + 1126 backend tests pass; tsc/eslint/ruff clean; build OK.

## Container utilization on the China container list (2026-10-03)

User asked (after declining it on the manifest table — not actionable there, capacity mostly NULL) to surface container **utilization** where it *is* actionable: the China-side `ContainerList`, the loading/ops-planning view.

- The plain **"CBM"** column became a **"Utilization"** cell: the packed CBM (`total_cbm_packed`) + a capacity **fill bar** + the **% full**. Bar width = packed / capacity (visual fullness); bar colour = the **absolute-CBM business rule** (≥70 green / 65–69 yellow / <65 red, from 7.84) — a green bar means an *economically-loaded* container, not merely a full one — kept identical to the `ContainerDetail` bar for consistency.
- Capacity resolves to the container's exact `capacity_cbm` (snapshot from a capacity preset, migration 051) or, for older containers, a free-text container-type estimate; when neither is known the cell shows just the packed CBM with no bar/% (never a fabricated figure).
- **De-duplication:** the capacity estimate + colour-level logic moved to `api/containerRules.ts` (`containerCapacityCbm`, `utilizationLevel`), and `ContainerDetail` now imports them instead of its own copies.

Why the list, not the manifest table: by the time a container reaches manifest verification it's sealed/arrived — the load is fixed and not a Nigeria-ops decision; utilization is a loading-time (China) signal, and `capacity_cbm` is populated only for containers created with a preset. Tests: `ContainerList.test.tsx` (+3 — exact-capacity %, type-estimate fallback %, capacity-unknown CBM-only). 848 frontend tests pass; tsc/eslint clean; build OK.

## Shipping-company onboarding — public lead + platform queue (2026-10-11)

User: "there is no way to onboard a shipping company … customers shouldn't be onboarded, customers should be invited … tenants are the ones to be onboarded," with a follow-up to make company onboarding *unmistakable* from customer sign-up. Backend already had platform-admin tenant creation; the gap was a public entry point for companies and clean separation of the two audiences. Model chosen (admin/sales-led): public lead → platform admin provisions. See `06_routing_rbac_and_navigation.md` for the route/guard table and the full separation rationale, and `07_api_tenant_management.md` for the API.

- **`pages/auth/RequestOnboardingScreen.tsx`** (`/get-started`, public) — company + contact form on the shared `AuthShell`/`FormHead`. No password, no account; `POST /v1/onboarding-requests` via `companyOnboardingApi.requestOnboarding`. Success copy explicitly says "No account has been created yet." Carries an "Are you a customer?" off-ramp.
- **`pages/auth/RegisterScreen.tsx`** — relabelled "Create your customer account"; bare `/register` now renders a which-are-you chooser instead of a dead-end warning.
- **`pages/auth/LoginScreen.tsx`** — two labelled footer CTAs (customer `/register` vs company `/get-started`).
- **`pages/platform/OnboardingRequests.tsx`** (`/platform/onboarding-requests`, platform_admin) — status-filtered lead queue (`useOnboardingRequests`); per-row **Mark contacted** / **Reject** (reason modal → `useUpdateOnboardingRequest`) / **Provision**. Provision navigates to `CreateTenantPage` with the lead in router state.
- **`pages/platform/CreateTenantPage.tsx`** — reads `useLocation().state.lead`; pre-fills company/contact/countries and sends `onboarding_request_id` so a successful create links + closes the lead. Shows a "Provisioning from an onboarding request" banner when launched from a lead.
- **Nav:** `navConfig.ts` gains an "Onboarding Requests" platform entry; `AppSidebar.tsx` overlays a live pending-lead count via `useOnboardingPendingCount` (gated to platform admins — no fetch for other roles). New hooks in `hooks/useOnboardingRequests.ts`; query keys in `api/keys.ts` (`onboardingRequestKeys`).

Tests: `RequestOnboardingScreen.test.tsx`, `RegisterScreen.test.tsx`, `OnboardingRequests.test.tsx`, plus a platform-nav assertion in `AppSidebar.test.tsx` (harness wrapped in a `QueryClientProvider` for the new hook). 861 frontend tests pass; tsc clean; eslint 0 errors.

---

## Implementation notes / ground-truth gaps found — two component defects surfaced by the e2e suite (2026-11-03)

Both were found while getting the full `e2e-local-stack` Playwright suite green,
and both are real product defects rather than test-only concerns. Full testing
account in `17_testing.md`.

**`design/components/Table.tsx` — loading skeletons were indistinguishable from
data.** The `loading` branch renders `SKELETON_ROWS = 5` placeholder `<tr>`s with
a full set of `<td>`s, structurally identical to real rows and carrying no marker
of any kind. Anything counting rows mid-load therefore saw **five rows that do not
exist**. Beyond breaking tests, the placeholders were also announced to assistive
technology as if they were table content, and nothing told a screen reader the
table was busy.

Fixed: placeholder rows are now `aria-hidden="true"` (they convey nothing) and
carry `data-skeleton-row`, and the `<table>` sets `aria-busy={loading}`. The
`aria-busy` attribute is also the DOM signal the e2e helpers now wait on, in place
of a fixed 300ms sleep.

**`pages/customer/MyClaimsNew.tsx` — the shipment `<select>` had no accessible
name.** Step 1's "Which shipment?" label was a **sibling** `<label>` with no
`htmlFor`, and the `<select>` had no `id`, so the two were never associated. A
screen reader announced an unlabelled combobox, and `getByLabel(/which shipment/i)`
found nothing. Fixed by wiring `htmlFor="claim-shipment"` / `id="claim-shipment"`.

Worth noting for anyone reading the spec history: `claims-and-refunds.spec.ts` had
been filling a free-text "container id or number" field that this page **stopped
having on 2026-09-06**, when step 1 became a dropdown of the customer's *arrived*
shipments (mirroring `_PRE_ARRIVAL_STATUSES` server-side). The spec was never
updated and had been timing out on a field that no longer existed.

## Packing list — bulk quantity entry (2026-11-12)

`CreatePackingList.tsx` gains a **Qty** column with a three-part safeguard. The
risk being designed against is not a typo — a typo looks wrong — but an
*oversight*: 100 cartons recorded at one carton's weight because they were
nearly identical.

1. **The quantity input is disabled** until an "identical" checkbox on the same
   cell is ticked, so the number cannot be reached without passing the
   assertion. Unticking resets the quantity to 1, so a stale 100 cannot be saved
   by clearing the box and missing the input.
2. **The line states what it will create** on a row beneath it — count, total
   CBM, total weight. "500" in a narrow input looks much like "50"; the CBM it
   implies does not.
3. **Saving asks** when any line is ≥ `BULK_CONFIRM_THRESHOLD` (25), restating
   the package count, CBM and weight. Only above the threshold: prompting on
   every "2" would train people to dismiss it, which is worse than not asking.

The server enforces the same rule, so the form is a prompt rather than the
protection.

**The totals multiply by quantity** — package count, weights, CBM, declared
value, and therefore the live shipping price. They are the real safeguard, and
had they been left per-row they would have quietly understated every bulk line.

**Editing.** The API returns a bulk line already expanded — one row per package
— so the form shows them individually with `quantity` at 1; re-expanding would
duplicate the cargo. `batch_ref` is carried through the load so the grouping
survives a save, and the row's remove button removes **the whole batch** when
the row belongs to one, with the count in its label and tooltip.

### A bug the tests caught

`clampQuantity` first coerced an emptied field to 1, so clearing the box left a
"1" behind and typing "40" produced **140**. It now allows a transiently empty
value (`undefined`, which reads as one package everywhere). Worth recording
because it would have been a daily irritation for the people this feature is
meant to help.

### Alignment and the draft round trip (2026-11-12, follow-up)

Three defects found by **screenshotting the table** rather than reasoning about
the CSS. Two were pre-existing.

**1. Every right/centre header was left-aligned** (pre-existing). `.itemsTable
th` is specificity (0,1,1) and `.right` / `.center` are (0,1,0), so the header
alignment classes lost to the `text-align: left` in the element rule — Wt disp.,
Wt act., L × W × H, CBM and Decl. all had a left-aligned heading over
right-aligned numbers. Restated as `.itemsTable th.right` / `th.center`.

**2. The totals footer was one cell short** (mine). Adding the Qty column to the
header and body without adding a `<td />` to `<tfoot>` pushed every figure after
CBM one column left, so the declared-value total rendered under **Qty**. Only
visible in a screenshot; no test asserts footer cell positions.

**3. A saved draft did not give back what was typed** — reported from the
warehouse as *"the quantity is not being retained"*. The API stores a bulk line
expanded, so reopening returned 100 rows and the number entered appeared
nowhere. `collapseBatches()` folds a group sharing one `batch_ref` back into a
single line carrying `quantity`, which is lossless because the server re-expands
from the same ref on save. A group is only folded when every row still matches —
if one package was edited directly, the rows stay expanded, since folding would
silently discard that edit.

**Also fixed in the same pass:** the edit load dropped `received_date`
(pre-existing). The server falls back to `received_date or date.today()`, so
editing any draft silently re-dated every item to today — and the tracking code
is derived from customer + received date, so the grouping moved with it. Worst
on imported lists, where that date is real rather than the day of entry.

The Qty cell itself is a centred flex stack with a fixed `min-height`, so a
bulk row is exactly as tall as a plain one; without it the table jolted taller
the moment a checkbox appeared, which is what made the column look misaligned.
The quantity input is narrower than the measurement inputs and centre-aligned —
it is a count, not a dimension.

### Review step and printed document now carry the full item detail (2026-11-12)

Reported as *"a lot of information is missing when I preview the packing list …
quantity, the package type, carton or bag … I want the preview to contain every
single information"*. Both views were showing a subset.

**Review step (document preview)** gained **Type**, **Qty**, **Wt disp.** and
**Wt act.** (it showed only one weight), and the money/CBM figures are now line
totals — `value × quantity` — matching what will actually be created and billed.

**Printed document** (`PrintPackingList.tsx`) gained **Type**, **Qty**,
**Wt act.** and **Received**, alongside the dispatch weight it already had.

**A counting bug fixed with them.** The printed total was `pl.items.length` —
a *row* count. A row has meant "N packages" since migration 040, so an imported
manifest line of 50 cartons printed as **"Total cartons: 1"**. It is now
`totalPackages()` (summing `quantity`), labelled "Total packages", with a
**Package mix** line beside it: *"3 cartons · 1 sack"*.

**"carton(s)" was hardcoded** in the review banner and both totals lines, so a
list of bales or sacks described itself as cartons on the very screen meant for
checking it. All three now use `formatPackageMix(buildPackageMix(items))`.

New shared helpers in `api/packingListRules.ts` — `packagesInRow`,
`totalPackages`, `buildPackageMix` — so the form, the review preview and the
printed document cannot drift apart. `buildPackageMix` deliberately mirrors the
server's `_PACKAGE_MIX_LATERAL`, which groups by `package_unit` and sums
`COALESCE(quantity, 1)`.

Layout: the preview document's header and row are **separate CSS grids**, so
adding columns to one and not the other would shear every value away from its
heading; both now declare the same nine tracks, and a comment says so. Mono
cells in the printed table are `nowrap` — carton tags and ISO dates were
breaking mid-token into two ragged lines per row.

### Loading date, delivery date and arrival warehouse on both documents (2026-11-12)

All three are captured on step 1 of the wizard and appeared on **neither** the
review preview nor the printed document — so the screen used to verify a list
before submitting, and the document handed to a customer, could not answer when
the cargo loads, when it lands, or where it is going. Added to both, rendering
`—` when unset.

They sit in the existing two-column meta grids, which wrap, so no layout change
was needed; verified by screenshot rather than assumed.

### Saving a draft twice created two packing lists (2026-11-12)

Reported as *"when I save item to draft, it keeps saving a new copy of that
same item to the draft … I was expecting it to be a unique item saved as draft,
that can be edited or removed, and not resaving them as more drafts."*

`CreatePackingList` decided create-vs-update from the **route param alone**:

```ts
const { id: editId } = useParams()
const isEdit = Boolean(editId)
```

On `/packing-lists/new` there is no param, so *every* save took the create
branch. The first produced a list; the second produced **another list holding
the same cargo**, and so on.

It normally navigates away after saving, which hides this — but not always:

- a save that **errors after the create succeeded** (e.g. `submit` fails on the
  review step) leaves the user on the page with a created list and a visible
  error, and pressing save again duplicates it
- any return to the form without a route param does the same

The page now remembers what it created:

```ts
const [createdId, setCreatedId] = useState<string | null>(null)
const targetListId = editId ?? createdId
```

so the second save **updates** the list the first one made. The update path
already deletes and re-inserts items, so repeated saves converge rather than
accumulate.

`regenerate()` is no longer called after a successful create. It was discarding
the idempotency key that guarded that create, immediately after it had been
used — leaving nothing to protect a double submit. The page creates at most one
list and then edits it, so the key never needs replacing.

**Harmonised:** step 2's button said "Save draft" and step 3's "Save as draft"
for the identical action. Both are now **"Save draft"** — the imperative form
matching the surrounding buttons ("Submit for approval", "Create packing
list"), and still unambiguous on step 3 where it sits beside Submit. The test
matcher was tightened back to the exact string once there was only one.


## Implementation notes — invoice outcome on clearing (audit Phase 1, 2026-11-14)

**Wire change.** `PATCH /v1/containers/{id}/status` now returns a `billing_summary` array when the new status is `cleared`
(absent for every other transition): one row per customer on the container,
`{ customer_id, customer_name, status: created | existing | skipped | failed, billing_id, invoice_number, reason, detail }`.
`containersApi.updateStatus` is typed `ContainerStatusUpdate = Container & { billing_summary?: InvoiceResult[] }`, and
`ContainerDetail` strips the extra key before writing the container into the query cache so it never leaks into other readers.

**Why.** Clearing used to invoice every customer inside the request, swallow any per-customer error and still report
success, so a customer who could not be invoiced (rates not set, no CBM, a transient failure) was simply never billed and
nobody knew. `InvoiceOutcomeBanner` (on the container page, above the tabs) now says who was invoiced and, for anyone who
was not, names them with a plain-language reason. Nigeria staff and tenant admins get **Generate missing invoices**, which
calls `POST /v1/billing { container_id }` (idempotent, so repeating it is safe); other roles see "ask your Nigeria office
or admin". The banner is session-local by design: it answers "what just happened"; after a reload the container shows as it
now stands. The dashboard queue of customers on cleared containers with no invoice (BE-06's second half) is built; see the next section.

~~**Found while doing this:** the **Generate billing** button on `nigeria/BillingList.tsx` has no `onClick` — it renders but
does nothing.~~ **Fixed 2026-11-14** — see "Generate billing picker and missing-item compensation" below.

## Implementation notes — unbilled queue, refund types, billing cache (audit Phase 1 / BE-04, 2026-11-14)

- **`shell/UnbilledQueue.tsx`** (dashboard, tenant admin and Nigeria staff): "Customers not invoiced" — customers on cleared
  containers with CBM to bill and no invoice, grouped by container, from `GET /v1/billing/unbilled`
  (`billingApi.unbilled`, `billingKeys.unbilled`). Renders nothing when empty. **Generate invoices** calls
  `POST /v1/billing { container_id }` (idempotent); **Open container** links to the container page.
- **Cache:** `PATCH /v1/containers/{id}/status` now invalidates `billingKeys.all` too — moving a container to `cleared` creates
  invoices, so billing lists and the unbilled queue must refresh with it (`api/cacheInvalidation.ts`).
- **Refund types:** `RefundType` gained `missing_item` and `seized_item`; `refundTypeLabel` shows "Missing item compensation" /
  "Seized item compensation".
- **Behaviour changes worth knowing when testing the UI:** an invoice that was `paid` becomes `partially_paid` the moment a
  misc charge, carryover or storage fee is added; storage fees now actually appear on the invoice (`storage_fees_ngn` is read
  from the fee log — it was always 0 before, so the storage banner and the Waive action never showed); waiving works and a
  second waive returns `422 NO_STORAGE_FEES`.

## Implementation notes — Generate billing picker and missing-item compensation (2026-11-14)

- **Generate billing (`nigeria/BillingList.tsx` + `GenerateBillingModal.tsx`).** The top-bar button was dead; it now opens a
  dialog for **tenant admins and Nigeria staff** (`canGenerateInvoices` in `api/billingRules.ts`, the same check
  `ContainerDetail` now uses; **Export** stays admin-only ~~and is still unwired~~ (wired 2026-11-16, see the list-export notes below)). The dialog lists only containers that still have
  a customer to invoice, from the same `GET /v1/billing/unbilled` query as the dashboard queue (`billingKeys.unbilled`), grouped
  by `groupUnbilledByContainer`, which `UnbilledQueue` now shares. One candidate is pre-selected; with several, **Generate
  invoices** stays disabled until one is chosen. The chosen container's customers and CBM are listed. The result is the
  existing `InvoiceOutcomeBanner` (who was invoiced; who was skipped and why, with **Generate missing invoices**), then
  **Done**. When nothing is unbilled it says so instead of showing an empty picker. The picker is a native `<select>`, **not**
  `Combobox`: the shared `Modal` body is `overflow-y: auto`, which clips the Combobox dropdown, so the options were unreachable
  (seen in a browser screenshot, not in the jsdom tests).
- **Missing Items → Update dialog.** Choosing *Confirmed lost* reveals an optional **Compensation (₦)** field and sends it as
  `refund_amount_ngn`; blank confirms the loss with no compensation, an amount that is not greater than 0 blocks Save, and an
  amount typed before switching to another status is not sent. Backend rule and validation: `12_api_claims.md`.

## Implementation notes — registration confirmation and notification preferences (audit SEC-04 / SEC-01, 2026-11-15)

- **`pages/auth/RegisterScreen.tsx`:** `POST /v1/register/{slug}` now answers `202 {status: "received"}` whether or not the email already had an account, so the "An account with this email already exists" branch is gone (it was the enumeration leak). The confirmation reads "Check your email." and covers both outcomes ("If this is your first time, it has a temporary password... If you already have an account, it tells you so, with a link to sign in"); it no longer says "Account created". `SelfRegisterResult` is `{status: 'received'}` (it was `{id, name, email}`, which nothing read).
- **Notification preferences copy is now truthful.** The registration form's "Notify me via" is "Send me optional messages via" with a line saying shipment, invoice, claim and account messages are always sent; the Account page's Notifications tab says the same and each channel describes optional messages (the SMS toggle used to promise "payment due, status changes, claims"). The three `ToggleSwitch`es now carry their label as an accessible name (they had none).
- **`pages/customer/Account.tsx` sends only what changed.** It used to send `notification_consent` with every save, so a customer who only switched language was recorded as having *chosen* their channel list (an imported customer's empty default would have become an opt-out of everything). Saving the channel list is what records a choice (`consent_given_at`; ADR-006).

- **Seized Items → Update dialog (2026-11-16):** *Permanently lost* reveals the same optional **Compensation (₦)** field as Missing Items (blank records the loss with no compensation; an amount not above 0 blocks Save). It used to be impossible to compensate from the UI at all.

## Implementation notes — code splitting (2026-11-16, master plan 7.190)

- `shell/routes.tsx` loads pages through `lazyNamed` and the area modules in `shell/areas/`; the route tests are async (`findBy*`), because a page now renders after its chunk loads. Details and measurements: `06_routing_rbac_and_navigation.md`. `SessionLoading` gained an `inline` mode for the page-sized wait inside an on-screen layout.

## Implementation notes — global search (2026-11-16, master plan 7.188)

- **`shell/GlobalSearch.tsx`** (+ `GlobalSearch.module.css`), `hooks/useGlobalSearch.ts` (250 ms debounce, nothing sent under 2 characters, previous results kept while the next term loads), `api/search.ts`, `searchKeys` in `api/keys.ts`, `shell/searchRoutes.ts` (result → route, placeholder per role). Behaviour and routes are in `06_routing_rbac_and_navigation.md` (UX-05).
- **Removed:** `TopBar`'s `onSearch`/`searchPlaceholder` props, the `onSearch`/`searchPlaceholder` fields of `TopBarContext`, and `useTopBarSlot({ onSearch })`. Test fixtures that built a raw `TopBarContext` value (`TopBarTestWrapper`, `ContainerList`/`ContainerDetail`/`TenantReports` tests) lost the two fields.
- **Looked at in a real browser** (Playwright against the Vite dev server with the API stubbed): staff dropdown, customer dropdown on the brand-coloured bar, phone collapsed and open (no horizontal overflow), platform admin shows none.
- **Not verified:** the SQL behind it has not been run against a real database (Docker unavailable); see `21_missing_endpoints.md` Part 12.

## Implementation notes — audit Phase 3 (2026-11-16)

- **CBM dispute screen for China staff (UX-01)** `pages/china/DisputeDetail.tsx`: status, customer and container, billed CBM against what the customer measured, their reason, the packing-list lines the CBM was summed from (with dimensions) and the resolve action (no change, or adjust with a corrected CBM; notes required). Read-only once resolved. Shows no money anywhere. Backend: `11_api_billing.md`.
- **Customer release note (UX-02)** `pages/customer/MyReleaseNote.tsx`: reference, status, cartons ("4 of 10"), container, validity, warehouse name, address and phone, carton tags, a credit warning when released on credit, an expired notice, and **Download PDF**. Another customer's id is a 404 ("Release note not found."). `ReleaseNoteCard` lists the notes for an invoice's or shipment's container and renders nothing until one exists, or if the lookup fails. It uses `releaseNoteKeys.lookup`, because `releaseNoteKeys.list` belongs to the infinite-query hook (a repo test enforces that).
- **Search box, menu, return path, error boundaries (UX-05, UX-03, UX-04, FE-01)** are described in `06_routing_rbac_and_navigation.md`.
- **Found on the way:** the ContainerList "Export" button, like the invoice list's, has no handler (~~still open~~ wired 2026-11-16). `App.test.tsx` made a real network call to the developer's API port (the silent session refresh) and failed whenever that server was slow or down; it now stubs `fetch`.

## Implementation notes — list exports (2026-11-16, master plan 7.189)

- **Invoice list Export (`BillingList`)** is wired for the tenant admin, who was the only role the dead button was shown to. ~~The API also allows Nigeria office staff; offering them the button is an owner call.~~ **Decided 2026-11-17: admin only.** The API now refuses every other role (403), so the button and the server agree. **Container list Export (`ContainerList`)** is shown to every role that can open the list (China, Nigeria, admin); *Create container* stays China-only.
- Both pages hand one `listParams` object to the list query and to `exportList`. `useListExport` keeps the TopBar-captured button pointed at the current filters and turns a refusal into a banner (`Couldn't export invoices` / `Couldn't export containers`). See `10_file_uploads_and_exports.md`.
- Looked at in a real browser: with the *In transit* chip and the search text `MSC` applied after the page opened, the CSV request was `/v1/containers/export?status=in_transit&q=MSC&format=csv`.

## Implementation notes — display formatting (2026-11-16, master plan 7.192)

- 124 `toLocale*String` calls and 56 `.slice(0, 10)` dates across 42 files now go through `lib/format.ts` (see `00_CROSS_CUTTING_STANDARDS.md`, "Display formatting and time zone"). Dates read `10 Nov 2026` instead of `2026-11-10`; times are Lagos time and say WAT; money is `₦174,375` / `₦174,375.50`; USD always has cents. Seven `.slice(0, 10)` calls were not display but data (query presets, the ETA-is-today comparison, the warehouse "today" check, the data-export filename): they use `isoDateOffset` / `todayIso`, which are Lagos dates.
- **Behaviour changes to know about:** money that has kobo now shows them (the old local helpers `fmtNgn` / `ngn` in `BillingList`, `MyShipments` and the payment dialog rounded to whole naira, so ₦174,375.50 read as ₦174,376); `formatNgn` of a missing amount is "—" (it was "₦NaN"); USD `112.5` reads `$112.50`; `ActivityLog`/`NotificationLog` timestamps now carry "WAT".
- Found on the way: `api/decimal.ts` already had a `formatCbm`; the implementation moved to `lib/format.ts` and `api/decimal.ts` re-exports it. `MyReleaseNote` had a local `formatDate` that would have recursed after the rewrite and was removed. Checked in a real browser: the same invoice rendered by Shanghai/zh-CN, New York/de-DE and Lagos/en-GB reads identically.

## Implementation notes — dispute list and claim references (2026-11-16, audit UX-06)

- `DisputeList` now shows **Customer, Invoice and Container** instead of "Billing ID" with eight characters of a UUID; a dispute whose record is gone shows a dash. Dates use the FE-03 helper (`15 Jun 2026`). Backend and wire fields: `11_api_billing.md`.
- `MyClaims` shows the claim's reference (`c.reference`) instead of `id.slice(0, 8)…`. The other `id.slice(0, 8)` sites already prefer a human reference and fall back to the id only when the API sends none (checked: packing lists, invoices, claims, shipments); the tenant list's ID column is an ID column on purpose.

## Implementation notes — customer claim page (2026-11-16, master plan 7.194, audit UX-07)

- **Refund request (OPS-03, 2026-11-17).** `RefundRequest` now has tests, and its "Credit on next shipment" option says that anything left over after the next invoice stays as credit (BE-07 spends a credit only as far as the invoice needs). **Ground-truth gap found, not changed:** the "Bank account refund" option never asks for the bank details (`account_number`, `account_name`), though the file's header comment and the backend's encrypted columns expect them; the accounts team has to get them from the customer another way. Collecting them here is a product change for the owner.
- **Platform tenant page: data export card (BE-10, 2026-11-17).** `PlatformTenantDetail` (`/platform/tenants/:id`) shows a **Data export** card on the Overview tab when the tenant is offboarded: status badge (Not queued / Queued / Being written / Ready / Failed / Cancelled), when it was prepared, size, record count, SHA-256, the date the data is deleted, **Download archive** (asks for a fresh five-minute link each time, `platformApi.offboardingExportLink`, then `window.location.assign`; the server marks it an attachment so the page stays) and **Queue export** when `can_queue`. While queued, running or retrying it re-checks every minute (`useOffboardingExport`, `refetchInterval`). The offboard dialog now says an export is prepared and must be handed over within 90 days. Wire types: `OffboardingExport`, `OffboardingExportLink` (`api/tenantManagement.ts`); keys `platformTenantKeys.offboardingExport/users/config`, `platformAuditKeys.forTenant`.
- **Ground-truth gap in FE-05 (closed 2026-11-17).** The 7.197 claim that no page fetched in a `useEffect` was wrong for this page: its Users, Configuration and Audit tabs did, through `import { platformApi as platformExtras }`, which the drift guard's `\w+Api.` pattern did not match. They now read through `usePlatformTenantUsers`, `usePlatformTenantConfig`, `usePlatformTenantAudit`, and `shell/noFetchInEffect.test.ts` also matches aliased API imports (checked: it fails on the old page with exactly those three calls).
- **Payment in another currency (BE-08, 2026-11-17).** `POST /v1/payments/{id}/verify` can now answer 422 `BR-PAY-VERIFY-002` when Paystack reports a successful charge that is not a positive naira amount. `PaymentSuccess.tsx` needs no change: it already shows an `ApiError`'s message in its error state.
- **Credits on invoices and refunds (BE-07, 2026-11-17).** `adjustments_ngn` on an invoice is now the negative of the credit it absorbed (it was always 0), so the existing "Adjustments" row on `BillingDetail` and `MyBillingDetail` appears for those invoices with no page change. `RefundDetail` shows a "Credit used: ₦X of ₦Y" stat for a refund taken as credit (`Refund.credit_applied_ngn?: string`), since a credit can now be part used. An invoice fully covered by credit arrives as `paid` with total 0.
- **`pages/customer/MyClaimDetail.tsx`** (`/my-claims/:id`): the reference and status with a progress strip (`aria-current="step"`), the outcome (decision, amount, decided-on date and the refund's status and amount) or a "No decision yet" note saying what is being waited for, what the customer filed (container, cartons, description, how it was checked) and the evidence with links that open in a new tab with `rel="noopener noreferrer"` (a file with no link says "Unavailable"). A claim that is not theirs, or does not exist, reads "Claim not found."; any other failure says it could not load. Wording lives in `api/claimsRules.ts` (`CUSTOMER_CLAIM_STATUS_LABELS`, `customerInspectionLabel`, `customerResolutionLabel`, `customerRefundLabel`, which collapses the refund pipeline to "Being reviewed / Approved: the payout is being arranged / Paid / Applied as credit / Not approved"), shared with `MyClaims`. **Reason (owner decision, 2026-11-17):** the Outcome card shows a **Why** row when `resolution.reason` is present, which the server sends to a customer only for a decision against them (`no_action`, "Closed without a payout"); a refund, compensation or discount arrives with `reason: null` and shows no row. Staff's `ResolveClaimModal` (`pages/nigeria/ClaimDetail.tsx`) labels the reason field by the picked outcome: "Reason (the customer will see this)" with a helper line for *No action*, "Reason (internal, not shown to the customer)" otherwise. Wire format: `ClaimResolution.reason?: string | null` (`api/claims.ts`).
- **`MyClaims`** lists the claim reference (it printed `id.slice(0, 8)…`) and each card opens the claim. Backend: `12_api_claims.md`. Checked in a real browser, desktop and phone (no horizontal overflow).

## Implementation notes — China office and missing items (2026-11-16, master plan 7.195, audit UX-08)

- `MissingItemList` is role-aware. For China staff the Update dialog offers only **Investigating** and **Found & shipping**, has no Compensation field whatever the status, says that deciding a loss and compensation are the Nigeria office's, and sends only `{status, notes}`; an item already confirmed lost or resolved has no Update button. Nigeria staff are unchanged (every status; compensation on confirmed lost). The rules are in `api/claimsRules.ts` (`missingItemStatusesFor`, `canUpdateMissingItem`, `canCompensateMissingItem`, `CHINA_MISSING_ITEM_STATUSES`), mirroring the server, which is the authority. Backend and the 403/422 rules: `12_api_claims.md`. Checked in a real browser as China staff.

## Implementation notes — pickup code (2026-11-16, master plan 7.196, audit UX-09)

- **Warehouse** (`WarehouseDashboard` pickup sheet and the `ReleaseNoteDetail` pickup dialog): when the note has `pickup_code_required`, a **Pickup code** field appears first (the dialog opens with focus on it), Confirm is disabled until something is typed, and a wrong code shows the server's message with the tries left while the sheet stays open. A locked note shows "Pickup code locked" and cannot be confirmed. A note without a code looks as before.
- **Fixed on the way:** the dashboard sheet now has a **Collected by** field (defaulted to the customer) and sends `collected_by_name`; without it every in-person pickup recorded from the dashboard was refused by the backend.
- **Office staff** (`ReleaseNoteDetail`): **Send new pickup code** (tenant admin, Nigeria staff; active notes) opens a confirmation that says the current code will stop working; afterwards a banner says which channels it went out on. A locked note shows a banner. Rules: `canSendPickupCode`, `sentViaLabel` in `api/releaseNotesRules.ts`; API: `releaseNotesApi.sendPickupCode`.
- **Customer** (`MyReleaseNote`): a notice that a pickup code was sent and must be given by whoever collects, or that the note is locked. The code is never shown in the app.

## Implementation notes — React Query migration finished (2026-11-16, master plan 7.197, audit FE-05)

See `09_state_management_and_data_fetching.md`, "No page loads server data in a `useEffect`". Behaviour changes worth knowing: the tenant dashboard's queues and the rate history table now refresh after a relevant write; the payment-gateway settings page makes one config request instead of two; the packing-list form's pricing estimate shows the CBM rate even if the dollar rate cannot be read (the two were loaded together and failed together).

## Warehouse confirmations in the app's own dialog (audit UX-11, 2026-11-17)

`Warehouses.tsx`'s Delete asked through `window.confirm` twice ("Permanently delete?", then "Retire instead?" when the server answered `WAREHOUSE_IN_USE`) — the only native dialogs in the app. Both are now one design-system `Modal` (480 px, `danger` button) that changes stage in place: **Delete this warehouse?** → on `WAREHOUSE_IN_USE`, **Retire this warehouse instead?** showing the server's reason and what retiring does. Cancel, Escape and the close button leave the warehouse untouched; focus opens on Cancel. On a phone it is the Modal's full-screen sheet.

**Ground-truth gap found and fixed:** add, edit, delete and retire called `warehousesApi` directly and never invalidated `warehouseKeys.all`, which is cached for five minutes, so the list kept showing a deleted warehouse (or lacked a new one) until something else reloaded it. Only Set default refreshed. Every warehouse write now goes through a mutation hook in `useWarehouses.ts` that invalidates the list.

Guard: `shell/dialogs.test.ts` fails on any `window.confirm` / `alert` / `prompt` (or a bare `confirm(`) under `src/`, mutation-checked. Tests: `Warehouses.test.tsx` (16; the `window.confirm` stub is gone — cases drive the dialog, including Escape, cancel at each stage, and the list refreshing after a delete). Checked in Chromium against the local app with the warehouse endpoints stubbed (desktop and 375 px).

## Route screens in one checked map (audit FE-08, 2026-11-17)

The screen maps moved out of `shell/routes.tsx` into `shell/screens.tsx`: `PUBLIC_SCREENS` (no guard) and `GUARDED_SCREENS` (renamed from `STAFF_SCREENS`, which also held the customer portal), plus `screenForRoute(route)`. `routes.tsx` keeps the route tree, the layouts and the apex redirect, so neither file mixes components and plain exports (fast refresh). `RouteStub` ("the real page lands in Task 07") is deleted; a missing screen renders `NotFoundPage`. Stale comments removed: the `routeTable.ts` note that `/billing/disputes` must precede `/billing/:id` (React Router v6+ ranks by specificity), the "stays a stub until Task 07" headers, and the same in `CustomerTopNav.tsx`.

Guard: `routes.test.tsx` "every route has a real screen" — one case per route, plus no screen without a route or under the wrong guard (a guarded page in `PUBLIC_SCREENS` would skip `RoleGuard`) and no duplicate path. The FE-02 code-splitting check now reads `routes.tsx` and `screens.tsx` together. Both mutation-checked; the production build still emits the entry chunk at 168 kB.

## Container document upload refuses an untyped file (audit BE-12, 2026-11-17)

`ContainerDetail`'s Documents tab sent `file.type || 'application/octet-stream'`; the server no longer accepts the unknown type, so the dialog now refuses a file whose browser type is not PDF, JPEG, PNG or WebP ("Choose a PDF, JPEG, PNG or WebP file.") without calling the API. **Ground-truth gap fixed:** upload errors were set on the tab's page banner, which sits behind the dialog's overlay, so a failed upload looked like nothing happened; they now render inside the dialog (`uploadError`), cleared when a new file is picked or the dialog reopens. Tests: `ContainerDetail.test.tsx` (+3).

## Exchange-rate source on invoices and the Dollar rate page (audit BE-11, 2026-11-17)

`Billing` gains optional `exchange_rate_source` / `exchange_rate_fetched_at` (staff detail read only). `BillingDetail` shows a warning-tinted note (`.rateNotice`, `role="note"`) under the exchange-rate line when the invoice used the last known rate, with the fetch time in Lagos time. `DollarRateConfig` (the type) gains `rate_source` and `fetched_at: string | null`; the page says "last known rate, fetched …" or "built-in default, never fetched" instead of "updated just now", with a warning banner when the rate is not live. `InvoiceOutcomeBanner` explains `RATE_UNAVAILABLE`. Tests: `BillingDetail.test.tsx` (+4), `DollarRateConfig.test.tsx` (+3).

## China office work queue (audit UX-10, 2026-11-17)

`/work-queue` → `ChinaWorkQueue`: four queues from existing list endpoints (no new API) — rejected packing lists (`status=rejected`), drafts not submitted (`status=draft`), manifests awaiting verification (`verification_status=pending`), CBM disputes escalated to China (`status=escalated_china`). Each shows its count, its first five rows (each opens the record) and a "View all →" to the filtered list; a queue that fails says so and the others still show. Hooks: `usePackingListQueue`, `useChinaManifestQueue`, `useEscalatedDisputes` in `hooks/useDashboard.ts` (lookup keys, so writes refresh them). China staff now land here (`roleHome.ts`), and it is their first menu item.

`lib/useStatusParam.ts` keeps a list's status filter in `?status=`; `PackingListList`, `ManifestList` and `DisputeList` use it, so links can open them filtered and the filter survives reload. The tenant dashboard's "Review all", "Verify" and "Respond" now open their lists filtered too.

**Ground-truth gaps found:** (1) the tenant dashboard's "Packing lists awaiting approval" queue (Nigeria staff) asked for `status=submitted`, a status no packing list has (`draft | pending_approval | approved | rejected`), so it was always empty — now `pending_approval`; checked against the API (0 vs 3 rows on the dev data). ~~(2) `GET /v1/manifests` and `GET /v1/billing/disputes` return `has_more` but no `total_count`, although `PaginationMeta.total_count` is typed as always present; the work queue counts the rows it has (with "+" when there are more) where the total is missing.~~ **Closed 2026-11-17:** both endpoints now return `total_count`; the work queue's row-counting fallback remains only for safety.

Tests: `ChinaWorkQueue.test.tsx` (9), `DisputeList.test.tsx` (+2, opened from a link), `roleHome.test.ts` / `RoleGuard.test.tsx` (China home). Checked in Chromium against the dev API as China staff (desktop and 375 px).

## The three largest pages split into folders of parts (audit FE-07, 2026-11-17)

No behaviour change; every page test passes unchanged. Each page keeps its path (routes and tests import it as before) and its parts live in a folder named after it; no file exceeds 400 lines.

| Page (lines before → after) | Parts |
|---|---|
| `nigeria/BillingDetail.tsx` (1,800 → 387) | `billingDetail/`: `status.ts` (status labels and variants), `StorageFees.tsx`, `DisputeCard.tsx` (with the SLA countdown and resolve dialog), `RecordPaymentModal.tsx`, `ChargeModals.tsx` (add charge, cancel, apply carryover), `GenerateReleaseNoteModal.tsx`, `Breakdown.tsx` (breakdown card, payments table), `PaymentClaims.tsx` (owns its query, confirm/reject state), `MiscCharges.tsx` (owns its query and remove) |
| `china/ContainerDetail.tsx` (1,187 → 295) | `containerDetail/`: `labels.ts`, `Timeline.tsx` (stepper, summary tile, event row), `AdvanceStatusModal.tsx`, `DocumentsTab.tsx`, `OverviewTab.tsx` (owns the cargo aggregates), `Tabs.tsx` (packing lists, with its sort; tracking), `packingLists.ts` |
| `china/CreatePackingList.tsx` (1,258 → 111) | `createPackingList/`: `useCreatePackingListForm.ts` (all wizard state and the save), `usePackingListPricing.ts` (rates, totals, live estimate), `Step1.tsx`, `Step2.tsx` + `ItemsTable.tsx` + `Step2Parts.tsx`, `Step3.tsx`, `WizardSteps.tsx`, `items.ts` |

Declarations moved byte for byte (a TypeScript-compiler-based mover); new files are Prettier-formatted with the frontend's `.prettierrc` (run with `--no-editorconfig`: the repo-root `.editorconfig` says 4-space indent, the frontend is 2-space). The `untestedPages` ratchet counts a part in a page's folder as covered by that page's test. Found along the way: ContainerDetail's packing-list `useMemo` depended on a value rebuilt every render (lint warning) — gone now the memo takes a prop; the tracking tab's "Export" button has no handler (unchanged here, noted in the master plan). Checked in Chromium against the dev API: all three pages and every ContainerDetail tab render with no console errors.

**Tooling note:** `npx tsc --noEmit -p .` in `frontend/` checks nothing — `tsconfig.json` has `"files": []` and only references the app and node configs. Use `npm run typecheck` (`tsc -b --noEmit`).

## Styling rule: no static inline styles (audit FE-06, 2026-11-17)

**Rule.** A `style={{...}}` prop is for values computed at runtime only (a width from a percentage, a colour from a status, a border on all but the last row). Anything fixed belongs in the page's CSS module, written with the design tokens in `src/design/tokens.css` (`var(--color-*)`, `var(--font-*)`, `var(--radius-*)`, `var(--scrim-modal)`). Inline values bypass theming (dark mode cannot reach them) and drift from the tokens.

Applied to the five largest pages: `ReleaseNoteDetail` (12 → 0), `ManifestDetail` (2 → 0), `AdminCustomerDetail` (21 → 0), `MyBillingDetail` (24 → 1, a runtime border), `LandingPage` (already 0). Classes were added to each page's module (`ReleaseNoteDetail.module.css`, `ManifestDetail.module.css`, the shared `admin.module.css` and `customer.module.css`), one per distinct style, with names for what the element is (`fieldLabel`, `prefRow`, `dialogOverlay`, `paymentsTh`). Pixel-compared before and after in Chromium against the dev data: two pages identical, two differing only in anti-aliasing (≤ 39 scattered pixels on card corners).

**Found and fixed:** `AdminCustomerDetail`'s locale select used `var(--color-ink-1)`, a token that does not exist (the scale is `--color-ink`, `--color-ink-2`, …), so its colour fell back to inherited — now `var(--color-ink)`; `MyBillingDetail`'s hand-rolled dialog overlay hard-coded the light-mode scrim `rgba(11,47,13,0.55)` — now `var(--scrim-modal)`, which darkens correctly in dark mode. About 650 inline styles remain elsewhere in `src/`; convert them page by page under this rule.

## Breadcrumbs on every page (FD-45/FD-46, 2026-11-17)

See `06_routing_rbac_and_navigation.md` "Breadcrumbs". Pages changed: every record page now calls `useBreadcrumbLabel` (PackingListDetail, ManifestDetail, BillingDetail, DisputeDetail, ClaimDetail, RefundDetail, ReleaseNoteDetail, StaffUserDetail, AdminCustomerDetail, PlatformTenantDetail, MyShipmentDetail, MyBillingDetail, MyReleaseNote, MyClaimDetail; the packing-list edit form names its list; RefundRequest and PaymentSuccess name their invoice). `TopBar`'s `breadcrumb` prop is now `Crumb[]` (`{label, to?}`), not `string[]`; `StaffLayout`'s `buildBreadcrumb` (sidebar-derived) is gone. Tests `PaymentSuccess.test.tsx` and `RefundRequest.test.tsx` now render inside `withQuery` and mock `billingApi.get` (the invoice crumb reads it). Also fixed: `routes.test.tsx`'s chunk-loading test waited 1 s for a cold chunk and failed intermittently under full-suite load (now 5 s). Seen, not changed: on a phone, the staff invoice page's action buttons run off the right edge.

## 5 MB upload limit in every upload screen (2026-11-17)

`lib/uploadLimits.ts` (`MAX_UPLOAD_BYTES`, `uploadSizeProblem`) is the one limit: `useFileUpload` (claim evidence, manifest evidence, payment-claim evidence through `EvidenceUploader`), `DocumentsTab` (container documents) and `uploadImportFile` (both spreadsheet imports, `FileTooLargeError`) refuse an empty or over-5 MB file with "This file is 6.0 MB. The limit is 5 MB." before any request, and every presign call sends `size_bytes` (`presignedUploadApi.getUrl`, `manifestApi.getEvidenceUploadUrl`, `paymentClaimApi.getUploadUrl`, `containerDocumentsApi.presignUpload`, `excelApi.getImportPresignedUrl` gained a size argument). Hints now say "max 5 MB" (were 10 MB, which nothing enforced).

## Redundant back links removed (FD-47, 2026-11-17)

Removed: AdminCustomerDetail, StaffUserDetail, PlatformTenantDetail, ManifestDetail, RefundDetail, ReleaseNoteDetail, ClaimDetail, BillingDetail, PackingListDetail, DisputeDetail (top and error state), MyClaimDetail, MyShipmentDetail, MyReleaseNote, MyBillingDetail, and on settings Warehouses, ContainerCapacities, ChargeTypes, DollarRateConfig and CbmRateConfig. Their now-dead `.backLink` CSS went too. Guard: `pages/noBackLinks.test.ts`. `MyClaimDetail.test.tsx`'s "goes back to the list" became "has no hand-written back link".

## Every page fits a phone (2026-11-17)

Owner request: all pages responsive on mobile phones. Measured, not eyeballed: `frontend/scripts/mobile-audit.mjs` opens all 78 routes at 375, 360 and 320 px as an allowed role with real records and fails on any page that scrolls sideways or has an element sticking out (clipped or scrolling the content column). Before: 15 pages failed at 375 px, more at 360 and 320. After: all 78 routes pass at 375, 360 and 320 px.

Fixed at the source, so the fix covers every page using the piece:
- **Top bar** (`shell/TopBar`): below 600 px, row one is the menu button, title and the bar's icons; the page's own actions (`useTopBarSlot` `actions`, now wrapped in `.pageActions`) get a full-width row below. Before, actions mixed in with the icons over three or four rows. The title steps down to 18 px and the account button drops its arrow so the title fits.
- **Cards** (`Card`): `min-width: 0`, so no card forces its grid column wider than its share. **Stat cards**: below 600 px the icon gives its room to the label (whole words wrap, no "OUTSTANDI/NG"), and the number scales (`clamp`) and may wrap.
- **Tabs** (`shell/Tabs`): scroll sideways inside their own strip (no visible scrollbar); tabs never shrink or wrap.
- **Long pipelines**: new `shell/ScrollStrip` (container stepper, customer shipment stepper; the refund stepper was already one). A strip scrolls inside itself and is marked `data-scroll-strip`.
- **Wizard steps** (create packing list, Excel import): below 600 px every step keeps its number, only the current one keeps its words.
- **Action rows** on invoice, container and release-note pages: capped at the page width so buttons wrap (they had `flex-shrink: 0` and ran off the edge, e.g. "Apply carryover" on the invoice). Webhook secret row wraps.
- **Key-value rows** (`Kvp`) and table phone cards: long values wrap. **Badges** wrap below 600 px instead of overflowing a card.
- **Key-value rows** also wrap the value under a long label when both do not fit ("Effective rate charged to customers" at 320 px). The platform tenant page's Suspend/Offboard row wraps (`.tenantActions`).
- **List filters**: the custom From/To date inputs wrap (billing, claims, containers, notification log). **Reports**: two-column grid and the donut legend stack on a phone; the dashboard two-column grid uses `minmax(min(440px, 100%), 1fr)`.

Dialogs: all ~40 already become full-width bottom sheets below 861 px (checked by a static scan for uncapped fixed widths; none found outside desktop-only rules).

Test harness: `src/test/setup.ts` sets Testing Library's `asyncUtilTimeout` to 3 s. A page's first render compiles its lazy chunk and under the full suite's parallel load sometimes took just over the default 1 s, failing `routes.test.tsx` and `ActivityLog.test.tsx` at random.

## Uploads are confirmed after they land (2026-11-19)

`useFileUpload` takes an optional `confirmUpload(presigned)` (not `confirm`: `shell/dialogs.test.ts` flags any bare `confirm(` call as a native dialog), called after a successful PUT; the upload is `done` only once it resolves, and its error message (e.g. the API's "The file is larger than 5 MB.") is what the uploader shows. `EvidenceUploader` takes `confirmUpload(evidenceId)`; claim evidence (`ClaimDetail` both uploaders, `MyClaimsNew`) passes `presignedUploadApi.confirm`, manifest evidence (`ManifestDetail`) `manifestApi.confirmEvidence`. Payment-claim evidence has no confirm: its size is checked when the claim is submitted. `DocumentsTab` calls `containerDocumentsApi.confirmUpload` after `uploadToPresignedUrl`; its manual list invalidation is gone, because the confirm POST invalidates the container keys through `api/client.ts`. Before, a file whose upload failed or was abandoned was still listed, with a link that did not open.

## Container tracking tab export (2026-11-19)

The event log's Export button (`containerDetail/Tabs.tsx` `TrackingTab`) was a plain button with no handler. It is now an `ExportButton` (xlsx, csv) calling `containersApi.exportEvents(id, format)` → `GET /v1/containers/{id}/events/export`, through `useListExport`, so a failure shows as a dismissible error banner above the table. Tests: `ContainerDetail.test.tsx` "ContainerDetail tracking export".

## Cancelling an invoice says what it gives back (2026-11-19)

`CancelBillingModal` takes `creditsNgn` (BillingDetail passes `-adjustments_ngn`) and `carryoverNgn`; when either is above zero an info banner reads "₦X of credit goes back to the customer. ₦Y carried over from earlier invoices is owed again, on their next invoice." The cancel API now does both (see `11_api_billing.md`). Refusal `CREDIT_NOT_TRACEABLE` (an older invoice) shows in the modal's existing error banner. Test: `billingDetail/CancelBillingModal.test.tsx`.

## Refund form collects the bank account (2026-11-19)

`RefundRequest.tsx`: with "Bank account refund" chosen (the default) the form shows Bank, Account number (digits only, 10, `inputMode="numeric"`) and Account name; `bankDetailsProblem` (`api/refundsRules.ts`) blocks submit with a message until all are valid, and the three fields are sent only for a bank refund. `RefundDetail.tsx` (staff) shows Bank / Account number / Account name under "Customer preference" when `bank_details` is present. Types: `BankDetails`, `Refund.bank_details`, `CreateRefundInput.bank_name/account_number/account_name`. Tests: `RefundRequest.test.tsx` (+4), `refundsRules.test.ts` (+4), `RefundDetail.test.tsx` (+2).
