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
- Added to `infrastructure/modules/api-gateway/main.tf`'s route map (API Gateway routes are explicit route-key → Lambda mappings here, not a catch-all proxy, so this was required for the route to actually exist once deployed) and to `tests/tenant_isolation/test_s3_isolation.py` (mirrors the existing per-service key-structure tests) and `tests/unit/test_excel.py` (content-type validation).
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

**No `GET /v1/billing/{billing-id}` endpoint exists.** The route `GET /v1/billing/{resource-id}` takes a *customer* id as `resource_id`, not a billing id — it calls `get_billing_for_customer()`. There is no single-record-by-billing-id HTTP endpoint (only an internal repo helper `get_billing_by_id()`). `BillingDetail.tsx` uses React Router navigation state (billing object passed from `BillingList` on click) as the primary data source, with a fallback list-scan (`GET /v1/billing` + find by ID) for direct URL access.

**Decimal wire-format exception: `misc_fees_ngn`/`carryover_ngn`/`storage_fees_ngn`.** These are computed with Python's `sum()` over a list. An empty list returns integer `0`, not `Decimal` — so these three fields arrive as JSON number `0` when zero, but as JSON string for non-zero values. All other monetary fields are always strings. `billing.ts` types them as `string | number`; display sites use `Number()` coercion.

**Payment recording endpoint is in `payment_release` handler, not `billing`.** `POST /v1/payments/{billing-id}/confirm` goes to `services/payment_release/handler.py`. `billing.ts`'s `billingApi.recordPayment()` correctly calls `/v1/payments/${id}/confirm`.

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

**Platform admin routes not yet wired:** `/platform/dashboard`, `/platform/settings`, `/platform/audit-log` — still fall through to `RouteStub`. These are lower priority; the critical CRUD and suspend/activate flows are complete.

**Tenant-admin config sub-pages not yet wired:** `/admin/config/charge-types`, `/admin/config/webhooks`, `/admin/reports`, `/admin/notifications/log` — still fall through to `RouteStub`. The API bindings (`configApi.listChargeTypes`, etc.) are ready in `tenantManagement.ts`.

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
- **Mobile (warehouse/customer-heavy usage):** minimum touch target 44×44px, input font-size ≥16px (prevents iOS auto-zoom), tables collapse to a 2-column label:value card list, modals go full-screen.
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
- **Bug found and fixed (infra, surfaced by browser-testing `ContainerDetail`'s Packing Lists tab): `GET /v1/containers/{id}/packing-lists` was unroutable end to end.** `services/packing_list/handler.py` implements this path as a deliberate sub-resource alias (`_container_packing_lists()`), but `infrastructure/modules/api-gateway/main.tf`'s route map never had an entry for it — Terraform would have shipped a route that 404s in production — and `scripts/local_server.py`'s prefix-based dispatch table sent the whole `/v1/containers/*` prefix to the `tracking` Lambda, which also 404'd. Fixed both: added `"GET /v1/containers/{id}/packing-lists" = "packing_list"` to the Terraform route map (`04c_terraform_api_gateway.md`), and added an explicit path check in `local_server.py` ahead of the generic prefix loop.
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

- **Shell header + nav now match the prototype.** `StaffLayout.tsx` derives the TopBar breadcrumb (`Operations / Containers`) and title from the current route via `navConfig` + `routeTable`, and enables the global search box — previously the TopBar rendered empty (`search={false}`, no title/breadcrumb). Title is **suppressed on form routes** (`…/new`, `…/import`) and on detail routes (dynamic `:id`, which never match a static path) so the body `PageHeader`/hero stays the single heading — matching the prototype, which blanks the topbar title on those screens. `ContainerList.tsx` and `PackingListList.tsx` dropped their in-body `PageHeader` title (now carried by the TopBar) and keep only a right-aligned actions row. Covered by 2 new `StaffLayout.test.tsx` cases.
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
  - **Header search was a no-op app-wide, not just here.** `TopBar.tsx` had an `onSearch` prop wired to its input's `onChange`, but no caller anywhere in the app ever passed it — the search box (placeholder "Search tenants, users, containers…") never did anything on any page. `TopBarContext`/`useTopBarSlot` gained a third slot (`onSearch`, same set-on-mount/clear-on-unmount shape as `actions`), threaded through `StaffLayout.tsx` → `TopBar`. `ContainerList` passes `useTopBarSlot({ onSearch: setSearch })`, so the header box drives the exact same `search` state as the table's own search input (single source of truth, not two independent search implementations) — the table input also reflects text typed into the header box.
  - **Table search had no debounce** — every keystroke fired a new `GET /v1/containers?q=` request. Added a 300ms debounce (`useEffect`+`setTimeout`, the same pattern already used in `AdminCustomerList.tsx`): `search` (raw, drives both input boxes) → `debouncedSearch` (drives the actual query).
  - **The `q` search filter 500'd server-side** — a real backend SQL bug, not just missing debounce (see `10_api_tracking.md` for the root cause: `list_containers()`'s free-text OR-clause was double-prefixed with the `c.` table alias, producing invalid SQL). Every non-empty table/header search would have errored before this fix.
  - **"Last 30 days" and "Filters" buttons were fully decorative** (no `onClick`, no state). Added a new reusable `DateRangeFilter` design component (`frontend/src/design/components/DateRangeFilter.tsx` — button + preset popover, presets: 7/30/90 days + All time) wired to a new `created_after`/`created_before` pair on `GET /v1/containers` (see `10_api_tracking.md`). Defaults to **All time** — deliberately not defaulted to a 30-day scope, since the dev tenant alone has 200+ containers (`seed_stress.py`) and a silent default filter would hide most of them from a china_office_staff user. "Filters" opens a small popover panel with the same date-range presets plus a "Clear all filters" action (resets status chip, search, and date range together) — the only additional filter dimension the container list API supports today beyond status (chips) and free text (search box).
  - **"Cleared (30d)" stat card was mislabeled** — `stats.cleared` counted every cleared/at_warehouse/fully_released container ever, not just the last 30 days. Now scoped to `created_at` within the last 30 days client-side, over the already-fetched `allContainers` stats batch, matching its label.
  - Not fixed (flagged only): `BillingList.tsx`, `ClaimList.tsx`, `NotificationLog.tsx`, `TenantReports.tsx` have the identical dead calendar/filter button pattern — out of scope for this pass, tracked for a follow-up.
  - Tests: `ContainerList.test.tsx` (+4 cases — debounce, header/table search sync, date-range filter, Filters panel clear-all); `ContainerDetail.test.tsx`'s local `TopBarContext.Provider` test fixture updated for the new `onSearch`/`setOnSearch` fields (`TopBar.test.tsx`/`StaffLayout.test.tsx` needed no changes — they don't construct a raw context value).

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
- `BillingList.tsx`'s 'Reference'/'Billed' columns and `ClaimList.tsx`'s 'Claim ID'/'Filed' columns declared `sortable: true` but had no `onSort` handler — same dead-UI pattern fixed on `ContainerList` (see above), reusing the same `useTableSort` hook. 'Reference' (`invoice_number`) and 'Claim ID' (`reference`, the damage claim's human-readable `DC-YYYYMMDD-NNN` number) default ascending; 'Billed' (`billed_at`) and 'Filed' (`created_at`) default descending (newest first) — both are "when was this recorded" timestamps, unlike `ContainerList`'s forward-looking ETA. Only the sort wiring changed on these two pages — their calendar/Filters buttons remain the pre-existing dead pattern noted above (out of scope for this pass, same as `NotificationLog.tsx`/`TenantReports.tsx`). Tests: `BillingList.test.tsx` (+2 cases), `ClaimList.test.tsx` (+2 cases).

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
