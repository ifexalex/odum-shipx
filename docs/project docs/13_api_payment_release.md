# Task 13 — API Service: Payment Confirmation + Release Notes + Pickup Records

## Objective

Implement the Payment & Release Lambda service: payment confirmation, release note generation (full/partial), warehouse pickup recording with delegate support, and carryover handling.

## Depends On

- Task 06 (shared layer), Task 11 (billing records exist)

## Files: `services/payment_release/handler.py`, `service.py`, `repository.py`, `models.py`

## Routes

| Method | Path | Roles |
|---|---|---|
| POST | `/v1/payments/{billing-id}/confirm` | tenant_admin, nigeria_office_staff |
| POST | `/v1/payments/{billing-id}/initialize` | customer (own billing) — Paystack hosted checkout |
| POST | `/v1/payments/{billing-id}/verify` | customer (own billing) — reconcile a Paystack payment directly |
| POST | `/v1/payments/claims/presigned-url` | customer (own billing) |
| POST | `/v1/payments/{billing-id}/claims` | customer (own billing) |
| GET | `/v1/payments/{billing-id}/claims` | tenant_admin, nigeria_office_staff, customer (own) |
| PATCH | `/v1/payments/claims/{id}/confirm` | tenant_admin, nigeria_office_staff |
| PATCH | `/v1/payments/claims/{id}/reject` | tenant_admin, nigeria_office_staff |
| GET | `/v1/payments/claims/{id}/evidence-url` | tenant_admin, nigeria_office_staff, customer (own) |
| GET | `/v1/release-notes` | tenant_admin, nigeria_office_staff, warehouse_attendant, customer (own only) |
| GET | `/v1/release-notes/stats` | tenant_admin, nigeria_office_staff, warehouse_attendant |
| POST | `/v1/release-notes` | tenant_admin, nigeria_office_staff |
| GET | `/v1/release-notes/{id}` | tenant_admin, nigeria_office_staff, warehouse_attendant, customer (own; **404, not 403, for another customer's note** since 2026-11-16, so it cannot confirm the id exists) |
| PATCH | `/v1/release-notes/{id}/release` | warehouse_attendant |
| POST | `/v1/release-notes/{id}/split` | tenant_admin, nigeria_office_staff |
| POST | `/v1/release-notes/{id}/reissue` | tenant_admin, nigeria_office_staff |
| GET | `/v1/warehouses` | tenant_admin, **china_office_staff**, nigeria_office_staff, warehouse_attendant |
| POST | `/v1/warehouses` | tenant_admin |
| PATCH | `/v1/warehouses/{id}` | tenant_admin — edit letterhead fields (name/address/city/state/phone) |
| PATCH | `/v1/warehouses/{id}/set-default` | tenant_admin |
| PATCH | `/v1/warehouses/{id}/deactivate` | tenant_admin — retire (`is_active = false`) |
| DELETE | `/v1/warehouses/{id}` | tenant_admin — **permanent delete** (refused when referenced) |
| POST | `/v1/webhooks/payment` | No JWT — HMAC signature (Paystack / Flutterwave) |

**Warehouse management (admin config page `Warehouses.tsx`).** `/v1/warehouses`
is the single warehouse surface (a duplicate `/v1/tenant/warehouses` in the
tenant-management service was removed — it was never wired to the frontend,
Terraform, or Postman). Behaviour:
- **`country`** (migration 057) — the branch's destination country, defaulting to
  `'Nigeria'`. Accepted on create and PATCH, returned on reads. It anchors the
  state/province picker; without it `state` could only be free text.
- **POST** — a tenant's *first* warehouse is auto-promoted to default (otherwise
  `get_default_warehouse()` stays null and release-note generation resolves no
  warehouse). Later creates are non-default **unless `is_default: true` is sent**,
  which promotes the new warehouse in the same action. Rejects (409
  `DUPLICATE_RESOURCE`) a name an **active** warehouse already holds; a retired
  warehouse does not reserve its name.
- **PATCH `/{id}`** — `UpdateWarehouseRequest`, all fields optional; only fields
  sent are patched (`exclude_unset`), so an omitted field is untouched, not
  nulled. `is_default` is NOT editable here — use the set-default route.
  `is_active: false` is **refused** (`WAREHOUSE_DEACTIVATE_VIA_DELETE`): it would
  bypass the default/last-active guards. `is_active: true` (reactivate) is allowed.
  A rename onto another active warehouse's name is a 409.
- **PATCH `/{id}/set-default`** — atomically moves the one-default-per-tenant
  flag (`idx_warehouse_one_default` partial unique index).
- **PATCH `/{id}/deactivate`** — retire without deleting (`is_active = false`).
  The path for a warehouse handover documents reference. It leaves pickers, those
  records keep their history, and (migration 056) its name becomes reusable.
- **DELETE `/{id}`** — a **real delete**. Refused (422) with `rule_id` naming the
  reason: `WAREHOUSE_IN_USE` (a `release_note` / `pickup_record` /
  `payment_record` / `packing_list` references it — the message names the counts,
  and the caller should offer deactivate instead), `WAREHOUSE_DEFAULT_IMMUTABLE`
  (reassign the default first), or `WAREHOUSE_LAST_ACTIVE`. Audited with
  `action="DELETE"` and a `before_state` carrying enough to recreate the row —
  the trail is the only remaining record it existed.

### Implementation notes / ground-truth gaps found (2026-11-02)

Three defects reported from live use, all confirmed by reading the code before
anything was changed:

1. **The arrival-warehouse picker was always empty when creating a packing list.**
   `_WAREHOUSE_READ_ROLES` omitted `china_office_staff` — who are precisely the
   role that creates packing lists (`packing_list/handler.py::_WORKFLOW_ROLES`),
   and a packing list records its arrival warehouse (migration 053). `GET
   /v1/warehouses` therefore 403'd. Worse, `CreatePackingList.tsx` caught the
   failure with `.catch(() => [])`, so the form rendered **"No warehouses
   configured"** — a permission error displayed as a configuration state, which
   is why it went unnoticed. The backend still applied the tenant's default
   warehouse server-side (`_resolve_arrival_warehouse`), so the saved data was
   correct; only the picker was broken. Fixed on both sides: the role was added,
   and the frontend now distinguishes "could not load" from "none exist".
2. **A deleted warehouse's name stayed reserved forever.** Migration 041 declared
   `UNIQUE (tenant_id, name)` over *every* row while deletion only set
   `is_active = FALSE`, so recreating a removed warehouse failed until it was
   renamed. Migration 056 replaces the constraint with a partial unique index
   over `WHERE is_active`, and the service pre-checks the name so the caller gets
   a 409 instead of a raw unique violation surfacing as a 500.
3. **"Set default" appeared to do nothing.** The route, its transaction and its
   role gate were all correct and unit-tested. The page rendered its only
   feedback — an error banner — at the **top of the page, above the table**, so a
   failure on a row further down had no visible effect. The page now scrolls the
   banner into view and confirms success explicitly. Separately, there was no way
   to mark a warehouse default *while creating it*, which is the discoverable
   action an operator looks for; `CreateWarehouseRequest` gained `is_default`.

**Also fixed, generally:** `BusinessRuleViolationError.rule_id` was set by dozens
of business rules across every service and **never serialized** into the RFC 7807
error body, so no client could branch on which rule refused a request without
matching the prose message. `shared/responses.error_response` now emits it and
`ApiError` exposes it as `ruleId`.

## Payment Confirmation (POST /payments/{billing-id}/confirm)

**Idempotency:** Supply `Idempotency-Key: <uuid>` header to make retries safe. Duplicate keys within 24 hours return the original cached response without double-counting payments. Key max length: 100 characters.

1. Validate billing exists in tenant scope
2. In **one transaction** (`repo.record_payment`, 2026-11-14):
   - allocate the receipt number from the `tenant_counter` (`receipt`) — manual payments only
   - create `payment_record` (`payment_method` is nullable — migration 008)
   - update billing in a single `UPDATE`, which locks the row and computes the status from the stored total (not from a value read earlier):
     - `amount_paid_ngn += amount_ngn`
     - If outstanding == 0 (±0.01 tolerance) → `paid`
     - If outstanding < 0 → `overpaid`
     - If outstanding > 0 → `partially_paid`
   - if overpaid, create a `refund_request` for **this payment's** excess only (an invoice that was already overpaid is not refunded twice)
3. Publish `PaymentConfirmed` event
4. Return: payment_id, new status, outstanding, release_note_available flag

Any failure in step 2 rolls the whole thing back — there is never a payment record without the matching invoice update.
Two payments that arrive together are applied one after the other, so two halves of an invoice end `paid`, not `partially_paid`.
The gateway webhook (`process_webhook_payment`) uses the same function; a repeat of the same `gateway_transaction_id` returns
`None` and changes nothing. Real-database tests: `tests/db/test_money_integrity.py`.

## Payment Claims — customer "I've made this payment" (2026-09-06)

**Ground-truth gap reported directly by the user:** the "Manual bank transfer" payment option only ever showed static bank details — there was no way for a customer to tell the platform they'd actually sent the money, and no required proof. Staff had no queue to review and no paper trail; a transfer only ever got recorded if a staff member happened to notice it land in the bank account and manually keyed it in via the confirm-payment flow above, with nothing connecting that record back to what the customer actually sent.

**`payment_claim`** (migration 044) is the customer's submission — one row per attempt, evidence mandatory at the model level (`SubmitPaymentClaimRequest` rejects a request without `evidence_file_key`/`evidence_file_name`), reviewed by staff:

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
    status VARCHAR(20) NOT NULL DEFAULT 'pending' CHECK (status IN ('pending', 'confirmed', 'rejected')),
    rejection_reason TEXT,
    reviewed_by UUID REFERENCES tenant_user(id),
    reviewed_at TIMESTAMPTZ,
    payment_record_id UUID REFERENCES payment_record(id),
    submitted_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
```

RLS on, standard tenant-isolation policy. `idx_payment_claim_one_pending_per_billing` (a partial unique index on `billing_id WHERE status = 'pending'`) keeps at most one pending claim per billing at a time — `create_payment_claim()`'s INSERT uses `ON CONFLICT (billing_id) WHERE status = 'pending' DO NOTHING RETURNING *`, and the service layer turns a `None` result into a clean `422 PAYMENT_CLAIM_ALREADY_PENDING` rather than letting a raw `IntegrityError` 500 (found live: the first version of this INSERT had no `ON CONFLICT` clause at all).

**The claim is a queue/audit trail, never a second ledger.** Confirming one (`PATCH /v1/payments/claims/{id}/confirm`) calls the *existing* `confirm_payment()` function above — the real source of truth for `billing.amount_paid_ngn`/`status` — with `payment_method="bank_transfer"` and `payment_reference="payment_claim:{claim_id}"`, then links the resulting `payment_record.id` back onto the claim. Rejecting one (`PATCH /v1/payments/claims/{id}/reject`, body `{"reason": "..."}`) never touches billing at all — the customer can submit a new claim afterward.

**Who confirms it, and where (2026-09-07):** any `nigeria_office_staff` or `tenant_admin` for that tenant — the same roles that can record any other manual payment. `nigeria/BillingDetail.tsx` gained a "Payment claims" table (visible whenever the billing has at least one claim, regardless of the billing's current status — so a stale pending claim from before the billing was settled some other way is still reachable to close out): each row shows the amount, submission date, a "View evidence" button (opens the receipt via `GET /v1/payments/claims/{id}/evidence-url`, a presigned S3 GET — new, since staff need to actually see the receipt before confirming, not just trust a filename), status, and — for pending claims — Confirm/Reject actions. Rejecting requires typing a reason inline before the action enables.

**Ground-truth gap found live, reported directly by the user right after using the feature: nothing on the customer side reflected that a payment claim was in flight.** `outstanding_ngn` (correctly) stays unchanged until staff actually confirm, but "Pay online" stayed fully clickable and the page gave no indication a payment had already been submitted — a customer could pay a second time while their bank-transfer claim was still pending. Fixed: `MyBillingDetail.tsx`'s "Pay now" section checks for a pending claim on this billing and, if one exists, replaces *all* payment options (Pay online and Manual bank transfer both) with a single "Payment submitted — awaiting confirmation" banner — no path to a duplicate payment while a claim is in flight. If the most recent claim was rejected (and nothing is currently pending), the rejection reason surfaces above the restored payment options instead. `MyShipmentDetail.tsx`'s compact billing summary got the matching fix for its "Pay outstanding" CTA. A second bug this surfaced during review: the rejection banner was being rendered *twice* (once at this new top level, once inside the claim-submission panel itself, which auto-expands whenever the customer has any claim history) — caught by a component test asserting a single instance, not by manual inspection.

**Ground-truth gap found live, reported directly by the user (2026-09-09): confirming/rejecting a claim never told the customer either way.** Both `confirm_payment_claim`/`reject_payment_claim` only published an EventBridge event (`PaymentConfirmed`/`PaymentClaimRejected`) that was never wired into any routing rule — nobody was ever notified. Fixed by calling `enqueue_notifications` directly (new `payment_claim_confirmed`/`payment_claim_rejected` event types, full account in `15_api_notifications.md`), best-effort and never able to fail the confirm/reject request itself. Verified live: rejected a real pending claim, confirmed both a WhatsApp and email notification were enqueued and landed in `notification_log` with the correct amount and rejection reason.

**Staff bell (2026-09-12):** submitting a claim (`submit_payment_claim`) now also writes a `staff_notification` row for `nigeria_office_staff`/`tenant_admin`, so a pending claim shows up in the TopBar bell immediately, not just on the "Payment claims" table above. Full account in `15_api_notifications.md`'s "Staff notification bell" section.

**Ground-truth gap found live, reported directly by the user (2026-09-13): the staff bell notification for a new payment claim didn't say who paid.** The notification above shipped with `title="New payment claim submitted"` / `body=f"A payment claim for NGN {amount} is awaiting review."` — no customer name, invoice, container, or phone, so a staff member had to open the claim just to know whose payment they were looking at, "any other metadata that will help the staff quickly identify the payment source." Fixed in `submit_payment_claim`: the customer's name now goes in the (unclamped) notification title — `"New payment claim — {customer_name}"` — and the body carries amount, invoice number, container number (when the billing has one), and phone, e.g. `"NGN 367237.50 · Invoice ACM-INV-20260906-0004 · Container E2E-TEST-001 · +2348169760253"`. All four fields were already available for free from `repo.get_billing_by_id()`'s existing customer/container join — only `customer_phone` needed adding to that query's `SELECT` (a second query was deliberately avoided). Body text is kept to name-free identifiers only (not `"{name} claims NGN..."`) since the notification panel's body is CSS-clamped to 2 lines — repeating the name already in the title would waste that budget. Missing fields (no container on the billing, no phone on file) are simply omitted, never rendered as a literal "None"; a missing customer name (an anonymised/deleted customer) falls back to "A customer" in the title. Verified live against the real local stack — confirmed the exact title/body text `get_billing_by_id` produces for a real billing/customer record with a full identity profile.

Tests: `test_notification_identifies_the_customer_and_payment_source`, `test_notification_omits_missing_container_and_phone`, `test_notification_falls_back_when_customer_name_is_missing` added to `test_payment_release.py`'s `TestSubmitPaymentClaim`.

**Evidence upload** mirrors `services/claims`'s presigned-URL pattern exactly (same bucket, same `_ALLOWED_CONTENT_TYPES`/`_MAX_FILE_SIZE`/`_URL_EXPIRY`): `POST /v1/payments/claims/presigned-url` returns `{file_key, upload_url, upload_method, upload_headers}` for a direct **PUT** to object storage (2026-10-05; was an S3 presigned-POST `{file_key, upload_url, fields}` — see the cloud-portability note in `09_api_manifest.md`), scoped to `{tenant_id}/payment-claims/{billing_id}/{filename}` and ownership-checked before issuing. The frontend uploads the file first, then includes the returned `file_key` in the claim submission — there is no separate "evidence" table for payment claims (unlike `claim_evidence` for damage claims), since a payment claim only ever needs the one file.

**Frontend:** `MyBillingDetail.tsx`'s "I've made this payment" button (new) opens a form requiring an amount and the mandatory evidence upload (`EvidenceUploader`, reused from the damage-claims flow) before the "Submit for review" button enables. A pending claim shows a status banner instead of the form; a rejected claim shows the reason and lets the customer try again.

**Also fixed in the same pass — the bank details themselves were wrong, not just ambiguous:** `BankTransferDetails` in `MyBillingDetail.tsx` used to hardcode a single tenant's bank account ("First Bank of Nigeria" / "Acme Shipping Ltd") and show it to every tenant's customers regardless of who they were actually paying — a real money-misdirection risk. Fixed with a new `bank_transfer_config` tenant-config key (`services/tenant_management`'s existing flexible config store, alongside `paystack_config`/`webhook_config`), set via the existing `PUT /v1/tenant/config` and a new "Manual bank transfer" section on `PaymentGatewayConfig.tsx`. `GET /v1/tenant/config`'s role check was widened to include `CUSTOMER` (previously staff-only) — safe, since the response already masks `webhook_config.secret` and strips `paystack_config`'s secret key entirely, and every *write* plus the webhook sub-routes stay behind the `tenant_admin` assert.

## Release Note Generation (POST /release-notes)

### Business Rules (BR-BL-002, BR-BL-003, BR-BL-004)

**Payment required before release** unless `release_with_outstanding = true`:
1. Check `billing.status` (migration 006 values):
   - `paid` or `overpaid` → allow full release
   - `partially_paid` → allow partial release if proportional payment covers requested cartons
   - `unpaid` → block unless `release_with_outstanding`
2. If `release_with_outstanding = true`:
   - Require tenant_admin or nigeria_office_staff role
   - Require approval_notes
   - Set `billing.released_with_outstanding = true`
   - Create `carryover_ledger` entry (amount = outstanding_ngn, status = 'outstanding')

### Partial Release (BR-BL-003)
- Calculate CBM for each requested carton (from packing_list_item)
- Required payment = (CBM of selected cartons / total CBM) × total_due_ngn
- If `total_paid_ngn >= required amount` → allow

### Create Release Note
1. Generate reference_number: `{tenant_short}-RN-{YYYYMMDD}-{sequence}`
2. Determine is_partial_release (requested cartons < total customer cartons)
3. Insert `release_note` record (status = 'active', `valid_until = today + 14 days`)
4. Publish `ReleaseNoteGenerated` event (triggers SMS/WhatsApp/Email)

### Duplicate / over-release guard (BR-RN-DUPLICATE-001, BR-RN-OVERRELEASE-001)

**Ground-truth gap found live (2026-09-20):** `repository.create_release_note` is a bare `INSERT`
with no uniqueness constraint on `carton_tags`, and nothing checked a new request against release
notes *already issued* for the same billing. Reproduced live against a real seeded billing whose
only carton tags were already `picked_up`: re-submitting the identical `carton_tags` succeeded and
created a second, fully valid `active` release note authorising the same cartons for pickup a
second time — a genuine double-release / potential double-pickup-fraud path. The same gap applied
to count-based release: `packages_balance` was computed only against `billing.total_cartons`, never
against packages already claimed by an earlier release note on the same billing, so repeated
count-based submissions could each claim the full count again.

Fixed in `generate_release_note` — checked immediately after `carton_tags`/`packages_released` are
resolved, before the payment-status branch:

- **carton_tags mode:** `repo.get_active_release_note_carton_tags(tenant_id, billing_id)` returns
  every tag already on a release note with status `active` or `picked_up` for this billing (union
  across all such notes via `unnest`). Any overlap with the requested tags raises
  `BusinessRuleViolationError` (`rule_id="BR-RN-DUPLICATE-001"`), naming the offending tags.
- **count-based mode:** `repo.get_active_release_note_packages_released(tenant_id, billing_id)`
  sums `packages_released` across the same active/picked_up scope. If `already_released +
  packages_released > total_cartons_for_customer`, raises `BusinessRuleViolationError`
  (`rule_id="BR-RN-OVERRELEASE-001"`), reporting how many remain.

Scope is deliberately `status IN ('active', 'picked_up')` only — an `expired` or `cancelled` note's
tags are NOT counted as already claimed, since `reissue_release_note` is the sanctioned path back to
active for an expired note's own tags, and a cancelled note's tags were never actually released.
`split_release_note`/`reissue_release_note` are unaffected by this guard — they call
`repo.create_split_release_note` directly, a separate code path with its own validation against the
specific parent note being split/reissued (not this billing-wide check).

Covered by `tests/unit/test_payment_release.py::TestGenerateReleaseNoteDuplicateGuard` (4 cases:
reject/allow for each mode). Verified live against the real running stack: a repeat POST with tags
already on a `picked_up` note now returns a clean `422 BUSINESS_RULE_VIOLATION` instead of silently
creating a duplicate; a fresh, non-overlapping request still succeeds.

## Record Pickup (PATCH /release-notes/{id}/release)

1. Validate release note exists, status = 'active'
2. Validate warehouse_attendant role
3. Create `pickup_record`:
   - Record attendant details
   - If delegate: validate delegate_name, delegate_phone, delegate_id_type, delegate_id_number
4. Check if all cartons for this customer are now released:
   - Sum cartons_released across all pickup_records for this customer's release notes
   - If total released == total customer cartons → update `shipment_tracking` to 'picked_up'
5. Check if ALL customers' cartons in container are released:
   - If yes → update `container.status` to 'fully_released'
6. Update release note status to 'picked_up' (if all cartons in THIS release note collected)

**Ground-truth fix (2026-07-19):** `repository.get_release_note_by_id()` — called by both `GET /v1/release-notes/{id}` and this endpoint (it fetches the note first) — selected `b.storage_fees_ngn` directly from the `billing` table. That column has never existed; storage fees are aggregated from `storage_fee_log` (same pattern as `excel/repository.py::get_billing_for_export`). Every call raised `UndefinedColumn`, so **warehouse staff could never confirm a pickup** — clicking "Record pickup" → "Confirm pickup" always 500'd. Fixed by aggregating storage fees the same way the export path does (`COALESCE((SELECT SUM(...) FROM storage_fee_log WHERE billing_id = b.id), 0)`). Verified live against the real DB: `GET /v1/release-notes/{id}` and `PATCH .../release` both succeed end-to-end (carton release recorded, note flips to `picked_up`, shipment tracking updated). **Testing gap note:** this class of bug (query references a non-existent column) is invisible to the existing unit suite, which mocks `execute_with_tenant` entirely rather than running against a real schema — worth keeping in mind for other raw-SQL repository functions.

**Ground-truth fix (migration 038, 2026-07-19):** `repository.mark_billing_released_with_outstanding()` (the write path behind step 2 above) sets `billing.status = 'released_with_outstanding'` — 26 characters. `billing.status` had been `VARCHAR(20)` since migration 002; migration 006 added this value to the CHECK constraint without ever widening the column, so this write has always failed with `StringDataRightTruncation`. **Releasing a container with an outstanding balance has never worked.** Discovered while seeding `scripts/seed_stress.py` (a volume-testing dataset that exercises every billing status — see `LOCAL_TESTING.md` §14.1.1). Fixed by widening the column to `VARCHAR(30)` (migration 038); no CHECK constraint change needed. Same testing-gap caveat as above — a schema-level truncation bug like this is invisible to a unit suite that never runs against real Postgres.

**Ground-truth fix (2026-09-06): non-delegate pickup could never succeed.** `RecordPickupRequest`'s
`_require_collector_name_for_non_delegate` model validator requires `collected_by_name` whenever
`is_delegate` is false — but neither the frontend's `RecordPickupInput` type nor `ReleaseNoteDetail.tsx`'s
pickup form ever collected or sent that field. Every pickup where the customer collects in person
(the common case — a delegate is the exception) hit this validator and failed. Compounding it: the
error never reached the user as a real message. Nine independently-copied `_parse_validated()` functions
across `services/*/handler.py` all built `field_errors` with `str(e["loc"][-1])`, which crashes with
`IndexError` on a model-level validator's error (an empty `loc` tuple, since it isn't about one field) —
turning what should have been a clean 422 into a raw 500 ("Internal server error", no detail). Fixed at
both layers: the frontend form now collects "Collected by" (defaulting to the note's own customer) and
sends `collected_by_name` when not a delegate; the nine duplicate `_parse_validated()` copies (plus a
tenth, differently-shaped instance in `services/auth/handler.py`) are consolidated into
`shared/validation.py::parse_validated()`, which keys a model-level error `"__root__"` instead of
indexing an empty tuple. Found via e2e testing the full billing → payment → release note → pickup chain
live, not a validation-focused review — confirmed genuinely `picked_up` in the database afterward.
Covered by `tests/unit/test_shared_validation.py` and new cases in `ReleaseNoteDetail.test.tsx`.

## Payment Gateway Webhook (POST /webhooks/payment)

No JWT auth — the route is authenticated by HMAC signature verification.

**Paystack (multi-tenant, 2026-07-19):** `X-Paystack-Signature` = HMAC-SHA512(secret, raw_body), where `secret` is the **specific tenant's own** Paystack key — resolved from the billing reference *before* verification, not a global env var. Event type: `charge.success`. Order of operations in `_webhook_routes` (`handler.py`):
1. Extract `billing_id` from `data.reference` (harmless read, no trust yet).
2. `get_billing_tenant(billing_id)` — `PLATFORM_TENANT_ID`-scoped lookup of which tenant owns this billing.
3. `repository.get_tenant_paystack_secret(tenant_id)` — decrypt that tenant's own key.
4. Only now: `verify_paystack_signature(raw_body, signature, secret)`.

This ordering is a security requirement, not a stylistic choice — see `07_api_tenant_management.md`'s "Multi-Tenant Paystack" design note for the full reasoning (a leaked key from one tenant can never be used to forge a payment against another tenant's billing, since the signature is checked against the exact tenant the reference claims).

**Flutterwave:** `verif-hash` = plain secret configured on the Flutterwave dashboard. Stored in `FLUTTERWAVE_WEBHOOK_SECRET` env var. Event type: `charge.completed`. Unused (no frontend integration) — stayed on its original single env-var secret, out of scope for the Paystack migration.

For both gateways, the payment reference (`tx_ref` / `reference`) must equal the billing UUID. The handler looks up the billing tenant using PLATFORM scope, then confirms payment via `process_webhook_payment()`.

Duplicate webhook deliveries are idempotent: `payment_record.gateway_transaction_id` has a partial UNIQUE index (migration 018). A duplicate delivery returns HTTP 200 without creating a second payment record.

Always returns HTTP 200 to the gateway on every rejection path (bad signature, unknown billing_id, tenant has no gateway configured) — to prevent timing/response differences that would let an outside caller distinguish *why* a webhook was rejected.

Environment variables required:
| Variable | Purpose |
|---|---|
| `FLUTTERWAVE_WEBHOOK_SECRET` | Flutterwave verif-hash secret |

`PAYSTACK_WEBHOOK_SECRET` / `PAYSTACK_SECRET_KEY` env vars **no longer exist** — removed 2026-07-19. Each tenant's key lives encrypted in `tenant_config.paystack_config`, set via `PUT /v1/tenant/config/paystack`.

## Schema Notes (Migration 008)

| Column | Change |
|---|---|
| `release_note.status` | Values: `active/picked_up/expired/cancelled` (default: `active`) |
| `shipment_tracking.status` | Added `picked_up` to existing statuses |
| `payment_record.payment_method` | Made nullable (method may be recorded separately) |
| `pickup_record.collected_by_name` | Made nullable (delegate flow may populate differently) |

## Schema Notes (Migration 018)

| Column | Change |
|---|---|
| `payment_record.gateway_transaction_id` | VARCHAR(255) nullable; partial UNIQUE index per (tenant_id, gateway_transaction_id) |
| `payment_record.payment_method CHECK` | Expanded to include `paystack`, `flutterwave` |

## GET /v1/release-notes/stats

Per-status aggregates for the §9.1 stats row (P2-3): `{active, partial_active, picked_up_today, picked_up, expired}` — one `FILTER`ed aggregate query. Roles: tenant_admin, nigeria_office_staff, warehouse_attendant (not customer — tenant-wide counts). `picked_up_today` counts notes whose status flipped to `picked_up` today (`updated_at::date = CURRENT_DATE`); also feeds the warehouse "Completed today" card.

## GET /v1/release-notes (list)

Query params: `customer_id`, `container_id`, `status`, `reference` (exact `reference_number` match — the warehouse scan-or-type lookup, P2-2), `cursor`, `limit` (default 50).

Customer role: automatically filtered to their own records (cannot pass a different `customer_id`).

**Wire-shape fix (2026-07-16, P2 audit):** list rows previously returned **raw DB rows** (`total_cartons`, `is_partial`, `created_at`) while the frontend expected the detail shape (`carton_count`, `is_partial_release`, `authorized_at`) — so the release-note list page crashed on `authorized_at` and the warehouse queue showed undefined carton counts against real data. The list now joins billing (`payment_status`, `billing_total_cartons`) and maps every row through `_fmt_release_note`, making list and detail responses the same shape. Also added `picked_up_at` (proxy: `updated_at` when status is `picked_up`, same pattern as `expired_at`) — feeds the warehouse "completed today" count.

## POST /v1/release-notes/{id}/split

Request body: `{ "carton_tags": ["TAG-001", "TAG-002"], "notes": "..." }`.

Creates a child release note for un-collected carton tags, linking it via `parent_release_note_id`.

Guards:
- Parent release note must be `active`.
- All tags must exist in the parent's `carton_tags`.
- Tags must not have already been picked up (checked via pickup_record).

On success: publishes `ReleaseNoteSplit` event; returns the new child release note.

## POST /v1/release-notes/{id}/reissue

Re-issues an expired release note with a fresh 14-day validity window.

- Only notes with `status = 'expired'` may be re-issued.
- Creates a new release note with the same `billing_id`, `customer_id`, `container_id`, and `carton_tags`.
- Sets `parent_release_note_id = original note id` and `valid_until = today + 14 days`.
- The original expired note is preserved for audit purposes.
- Publishes `ReleaseNoteReissued` event.

Response: the new release note (same shape as `GET /v1/release-notes/{id}`).

## GET /v1/release-notes/{id} — Wire Format

```json
{
  "id": "...",
  "reference_number": "ABC-RN-20240301-0001",
  "valid_until": "2024-03-15",
  "expired_at": null,
  "storage_fees_ngn": "0",
  "parent_release_note_id": null,
  "warehouse_name": "Main Warehouse",
  "warehouse_phone": "+2348012345678",
  "physical_document_number": "GRN-4471",
  "packing_list_invoice_numbers": ["INV-1", "INV-2"],
  "packages_released": 3,
  "package_unit": "cartons",
  "packages_balance": 2,
  "is_on_credit": false,
  "credit_granted_by_name": null,
  "receipt_number": null,
  "amount_paid_ngn": "133700.00",
  "balance_ngn": "5800.00",
  "total_ngn": "139500.00",
  "debt_due_date": null,
  ...
}
```

- `valid_until`: ISO date string set at creation (`today + 14 days`).
- `expired_at`: ISO datetime string when status flipped to `expired` (proxy: `updated_at`), null otherwise.
- `storage_fees_ngn`: outstanding storage fees from the linked billing record (string); `"0"` when none.
- `parent_release_note_id`: non-null on split and re-issued notes.
- `warehouse_name`/`warehouse_phone`: from the linked `warehouse` row (migration 041); null on older notes with no `warehouse_id`.
- `physical_document_number`/`packing_list_invoice_numbers`: the paper-form document number and comma-parsed invoice numbers captured at generation time; null/`[]` when not supplied.
- `packages_released`/`package_unit`/`packages_balance`: set only for count-based (non-tag) releases; null on carton-tag-based notes.
- `is_on_credit`/`credit_granted_by_name`/`debt_due_date`: set when the note was generated with `release_with_outstanding` and credit was extended; `debt_due_date` also appears immediately on the `POST /v1/release-notes` response (not just on a subsequent GET) since it's stamped onto the in-memory result before returning.
- `receipt_number`/`amount_paid_ngn`/`balance_ngn`/`total_ngn`: resolved from whichever of the note's own aliased billing columns or the joined `billing` row is present (`_first_present()` helper — the two call sites alias these fields differently). `amount_paid_ngn`/`balance_ngn` are `"0.00"` (not omitted) when genuinely zero — a `Decimal("0.00") or "0"` bug that collapsed a real zero balance into `"0"` was caught and fixed via an explicit `is not None` check.

### Ground-truth gaps closed (2026-09-13) — audited against a real paper "Goods Release Note"

The user supplied photos of a real "Goods Release Note" form from a Nigerian logistics company to audit against. Migration 041 had already added the schema for everything on that form (the `warehouse` table; `release_note.warehouse_id`/`physical_document_number`/`packing_list_invoice_numbers`/`packages_released`/`package_unit`/`packages_balance`/`is_on_credit`/`credit_granted_by(_name)`; `pickup_record` officer columns) — the gaps were all in code silently dropping these columns rather than in the schema:

- `get_release_note_by_id`/`list_release_notes` didn't join `warehouse.phone` or `carryover_ledger.due_date` — now do.
- `create_split_release_note` only inserted migration-003 columns, silently dropping every migration-041 field on **every split and every reissue** (reissue reuses the same insert helper). Rewritten to carry all of them. Split and reissue have deliberately different carry-forward semantics: **split** creates a genuinely new sub-release for un-collected cartons — it carries forward `warehouse_id`/`packing_list_invoice_numbers`/`is_on_credit`/`credit_granted_by(_name)` (same shipment, same credit terms) but *not* `packages_released`/`package_unit`/`packages_balance` (a split is inherently tag-based, not a re-run of count-based accounting). **Reissue** is a near-identical clone of an expired note — it carries forward *every* migration-041 field, including the package-count fields.
- `record_pickup` now resolves `customer_service_officer_id`/`accounting_officer_id` to names (`customer_service_officer_name`/`accounting_officer_name`) via `repo.get_tenant_user_name()`, returned on the pickup response.
- New warehouse CRUD (routes above). A tenant's first-ever warehouse auto-becomes the default (`is_default = TRUE`) since nothing else could ever set that flag for a fresh tenant otherwise — found live when a freshly created warehouse came back `is_default: false` with no way to promote it, which `PATCH /v1/warehouses/{id}/set-default` now also solves for later warehouses. A second gap found live in the same pass: the *current* local dev tenant had zero warehouse rows despite migration 041's one-time backfill, because any tenant onboarded after that backfill ran never got one — fixed by creating a default warehouse as part of `services/tenant_management/service.py::create_tenant`.
- `GET /v1/tenant/users` (list only) widened to `nigeria_office_staff`/`warehouse_attendant` — needed so `RecordPickupModal`'s Customer-Service-Officer/Accounting-Officer pickers can populate for the roles that actually record pickups; `china_office_staff` deliberately not widened (never touches release-note pickups).
- **PDF export** (`export_release_note_pdf.py`) had the identical silent-drop bug — see `19_excel_import_export.md` for the fix and the unrelated QR-rendering crash bug found and fixed alongside it.

**Immediate-response gap fixed (2026-09-13):** `create_release_note`'s `RETURNING` row carries no joins, so `_fmt_release_note` — which expects the joined shape `get_release_note_by_id` produces — rendered `customer_name`/`container_number`/`warehouse_name`/`warehouse_address`/`warehouse_phone` as null on the **immediate `POST /v1/release-notes` response**, even though a subsequent `GET` on the same note showed them correctly (found live: generating a note with an explicit `warehouse_id` still came back with `warehouse_name: null`). Fixed by backfilling those fields onto the in-memory `note` dict from data already in hand — `billing` (already fetched for the payment check, already carries `customer_name`/`container_number`) and the resolved warehouse row (now fetched via `get_warehouse_by_id` when the caller supplies `warehouse_id`, falling back to `get_default_warehouse` exactly as before when they don't) — before formatting the response. No second query added for the already-available fields.

### POST /v1/release-notes — new optional fields (migration 041)

`warehouse_id`, `physical_document_number`, `packing_list_invoice_numbers` (array of strings), `packages_released`, `package_unit`, and — only meaningful together with `release_with_outstanding: true` — `credit_granted_by_name` and `due_date` (stored on the `carryover_ledger` row created for the debt). All optional; a note generated with none of them behaves exactly as before migration 041.

## Warehouses (migration 041)

Per-tenant branches, used to (a) let a multi-branch tenant print the correct office address/phone on each release note instead of one tenant-wide singleton, and (b) let `RecordPickupModal` attribute a pickup to the branch that handled it.

- `GET /v1/warehouses` — list (`?include_inactive=true` to include soft-deleted ones). Roles: tenant_admin, nigeria_office_staff, warehouse_attendant.
- `POST /v1/warehouses` — `{ "name": "...", "address"?, "city"?, "state"?, "phone"? }`. tenant_admin only. The tenant's first warehouse is forced `is_default = TRUE` regardless of the request body.
- `PATCH /v1/warehouses/{id}/set-default` — atomically clears the previous default and sets the new one (two statements inside `execute_transaction`, required because `idx_warehouse_one_default` is a partial unique index). tenant_admin only. 404 if the warehouse doesn't exist for this tenant.

All three actions are audited (`CREATE`/`UPDATE` on entity_type `warehouse`).

## Release Note States

```
active → picked_up (warehouse confirms)
       → expired (scheduled job fires when valid_until < today)
       → cancelled (staff cancels)
expired → active (via POST /{id}/reissue — creates new note; original stays expired)
```

## Acceptance Criteria

- [x] Idempotency-Key header on POST /payments/{billing-id}/confirm prevents double-counting on retries
- [x] Payment updates billing totals and status correctly (`unpaid/partially_paid/paid/overpaid`)
- [x] Overpayment auto-creates refund request
- [x] Release blocked without payment (returns 422 PAYMENT_REQUIRED)
- [x] Partial release proportional payment calculation
- [x] Release with outstanding creates carryover_ledger entry and sets `billing.released_with_outstanding = true`
- [x] Reference number auto-generated with tenant prefix
- [x] `valid_until` set to today + 14 days on every new release note (create, split, reissue)
- [x] Pickup records delegate details captured (`collected_by_name` nullable)
- [x] Shipment tracking updated to `picked_up` when all customer cartons released
- [x] Container status auto-updated to `fully_released` when all customers done
- [x] Events: PaymentConfirmed, ReleaseNoteGenerated, ReleaseNoteReissued
- [x] Payment gateway webhook: Paystack + Flutterwave HMAC verified; duplicate-safe via gateway_transaction_id UNIQUE index (migration 018)
- [x] Multi-tenant Paystack (2026-07-19): each tenant connects their own key (`PUT /v1/tenant/config/paystack`, encrypted at rest); no platform-wide fallback; webhook signature verification resolves tenant from the billing reference *before* verifying, against that tenant's own key
- [x] GET /v1/release-notes: paginated list with customer_id/container_id/status filters; customer-scoped
- [x] POST /v1/release-notes/{id}/split: creates child release note for remaining tags; guards active status + valid tags + not-yet-picked
- [x] POST /v1/release-notes/{id}/reissue: guards expired status; creates new note with valid_until + parent link
- [x] GET /v1/release-notes/{id}: exposes valid_until, expired_at, storage_fees_ngn, parent_release_note_id

## Online payment initialization — Paystack (audit gap B12, 2026-07-12)

**POST `/v1/payments/{billing-id}/initialize`** — customer role only (own billing record; ownership resolved via `customer.user_id = ctx.user_id`). Body: `{"callback_url": "https://…"}` (optional, http(s) only — UX redirect target, e.g. `/my-billing/{id}/payment-success`). Guards: outstanding (`balance_ngn`) > 0; billing not `cancelled`/`waived`; customer must have an email (Paystack requires one); **the tenant must have their own Paystack key connected** (`PAYMENT_GATEWAY_NOT_CONFIGURED`, 422, otherwise — see below). Response: `{authorization_url, access_code, reference, amount_ngn}` — the frontend redirects to `authorization_url` (Paystack hosted checkout).

**Reference format:** `{billing_id}.{nonce}` — Paystack rejects duplicate references (a bare billing UUID would make retrying an abandoned payment impossible) and only accepts alphanumerics + `-.=` (verified live; `:` is rejected with `invalid_character_in_reference`). The webhook recovers the billing id by splitting on the first `.`; bare-UUID references still parse.

**Source of truth (was webhook-only; no longer, see below):** `POST /v1/webhooks/payment` (HMAC-SHA512, `x-paystack-signature`) is still the primary confirmation path. **Ground-truth fix:** that webhook route (and `/v1/webhooks/whatsapp`) existed in the handlers but was registered in neither API Gateway's route table nor `scripts/local_server.py` — the receiver was unreachable everywhere. Both are now routed (`POST /v1/webhooks/payment` public in Terraform, HMAC replaces JWT as the auth).

### POST `/v1/payments/{billing-id}/verify` — direct reconciliation (ground-truth gap, 2026-09-19)

**A webhook-only design has a structural hole a local dev environment makes impossible to miss: Paystack's servers can never reach `http://localhost`.** User report: "when i pay a bill as a customer through paystack, it showed successful, view invoice and when i clicked view invoice, it took be back to the same billing page and on that page the payment is not made. if i click pay it attempts making the payment again." Paystack's own hosted checkout correctly showed success — our backend simply never heard about it, because the webhook that was supposed to record it had nowhere reachable to fire. The same failure mode is a real (if rarer) risk in production too: a webhook can be delayed, retried, or dropped.

**Fix:** `POST /v1/payments/{billing-id}/verify` — customer role only, same ownership check as `initialize`. Body: `{"reference": "..."}` (the value Paystack appends to the browser's `callback_url` as `?reference=`/`?trxref=`). Calls Paystack's own `GET /transaction/verify/:reference` directly (`paystack.verify_transaction()`) — the reference is checked to actually belong to the given billing id (`BR-PAY-VERIFY-001`) before anything else, since it's client-supplied. If Paystack reports `status: "success"`, the result is fed into the *same* `process_webhook_payment()` the real webhook uses — sharing one confirmation code path rather than a second copy of the business logic. `gateway_transaction_id`'s existing `ON CONFLICT DO NOTHING` (migration 018) makes calling this **and** having the webhook eventually also fire completely safe — whichever arrives first wins, the other is a no-op, verified live by calling this endpoint twice against the same real Paystack test transaction and confirming only one `payment_record` row exists. If Paystack reports anything other than `"success"` (e.g. `"abandoned"`), this is not an error — the response reports Paystack's own status (`gateway_status`) alongside the billing's current (unchanged) numbers, so the frontend can show "not yet confirmed" rather than a scary failure.

Response: `{"gateway_status": "success" | <paystack's own status string>, "new_payment_status"?, "outstanding_ngn"?, "release_note_available"?, ...}` — the same shape `process_webhook_payment`/`confirm_payment` already return, when the payment is (or was already) successful.

**Frontend:** `PaymentSuccess.tsx` (`/my-billing/{id}/payment-success`, the page Paystack's hosted checkout redirects back to) used to unconditionally show a static "being confirmed automatically" message and trust the webhook alone. It now reads `reference`/`trxref` from the URL and calls this endpoint on mount, showing one of four real states: verifying (loading) → success, pending (Paystack itself hasn't confirmed), or a non-scary error state if the verify call itself fails (network/gateway issue) — never a raw stack trace.

**Verified live against the real Paystack test API** (not mocked) — the practice that's caught a real bug in every pass this session: initialized a real transaction for the exact billing record from the bug report, confirmed `verify_transaction` correctly reported `"abandoned"` before payment; completed the transaction for real via Paystack's server-to-server test Charge API (`4084084084084081`, no OTP required in test mode) to get a genuinely successful reference without needing browser automation against Paystack's own hosted UI; called the new confirmation path against that real reference and confirmed the exact billing record from the report flipped to `status: "paid"`, `balance_ngn: "0.00"`, with a real `payment_record` row referencing the real Paystack gateway transaction id — reproduced via the actual `GET /v1/billing/{customer_id}` HTTP endpoint, not just a direct DB read. Calling it a second time with the same reference correctly reported success again with no duplicate `payment_record` row.

**Secrets (multi-tenant, 2026-07-19):** each tenant connects their own Paystack secret key via `PUT /v1/tenant/config/paystack` — encrypted at rest (`shared/encryption.py`, KMS + Fernet), resolved per-request by `services/payment_release/repository.py::get_tenant_paystack_secret()`. There is **no platform-wide key** — `PAYSTACK_SECRET_KEY` was removed from every env var / Terraform variable. `paystack.initialize_transaction()` now takes `secret_key` as a required parameter (never reads `os.environ`); a tenant with nothing configured gets a clear `PAYMENT_GATEWAY_NOT_CONFIGURED` error and customers fall back to bank transfer. Full design rationale in `07_api_tenant_management.md`'s "Multi-Tenant Paystack" section.

**Ground-truth gap found live while auditing log coverage elsewhere (2026-09-07):** `process_webhook_payment`'s `log_audit()` call passed `actor_id="gateway"` — not a UUID, though `audit_log.actor_id` is a `UUID REFERENCES tenant_user(id)` column. Since `log_audit()` never raises (failures are caught and logged as a WARNING only), **every webhook-confirmed payment had silently never been written to the audit trail** since this code was first written — real money, gateway-triggered, with zero audit record and nothing surfacing the failure. Confirmed live: reproduced `invalid input syntax for type uuid: "gateway"` directly against the local DB. Fixed by passing `actor_id=None` (a legitimate "no human actor" value the column already supports; `actor_role="system"` says who/what it was) — see `02_shared_utilities.md`'s `log_audit` write-up and `07_api_tenant_management.md`'s "Tenant Activity Log" section for the full account, including a second call site with the identical bug found in the same pass.

**Customer bell (2026-09-12):** confirming/rejecting a claim now also writes an in-app customer notification (`target_user_id`, not `target_role` — a customer notification is always 1:1), reusing the same `staff_notification` table as the staff bell above. Only customers with a portal account (`customer.user_id` set) receive it. Full account in `15_api_notifications.md`.

## Payment-claim evidence upload — file name sanitisation (2026-09-23)

**Upload file names are sanitised (2026-09-23).** The client's `filename` is passed through `shared.validation.safe_filename()` before it is used in the S3 key or stored: directory components dropped, anything outside Unicode word characters / `. ( ) space -` replaced with `_`, no leading/trailing dots, ≤100 chars with the extension kept (Chinese names like `装箱单.xlsx` survive). A name that reduces to nothing is a `422`. The download `Content-Disposition` is sanitised again on read, since rows written earlier may hold an unsafe name. See `00_CROSS_CUTTING_STANDARDS.md` §2.2.

**Manual payments refuse closed invoices (2026-11-14).** `POST /v1/payments/{billing-id}/confirm` returns
`422 BILLING_NOT_PAYABLE` when the invoice is `cancelled` or `waived`, like the gateway webhook already did (`BR-WEBHOOK-001`).
Before, the status recompute would have flipped a cancelled invoice to `paid`. **Release-note numbers** now come from the
`tenant_counter` (`release_note`) instead of `COUNT(*)+1`, so two notes created together can no longer share a reference;
a number is skipped if the note insert then fails (uniqueness, not gap-free).

## Pickup code (2026-11-16, audit UX-09, ADR-008, migration 065)

**Problem:** an in-person pickup needed only a typed collector name, so anyone who knew a release-note reference could collect the goods.

| Change | Detail |
|---|---|
| `POST /v1/release-notes`, `.../split`, `.../reissue` | Each new note is given a six digit pickup code, sent to the customer by SMS and email (`pickup_code_issued`). Best effort: a note is never refused because a code could not be issued. |
| `GET /v1/release-notes[/{id}]` | Two new fields: **`pickup_code_required`** (the note is active and carries a code) and **`pickup_code_locked`** (five wrong codes). The code and its hash are never returned. |
| `PATCH /v1/release-notes/{id}/release` | New optional body field **`pickup_code`** (spaces and dashes ignored). For a note that carries a code: missing is `422 PICKUP_CODE_REQUIRED` (not counted), wrong is `422 PICKUP_CODE_INVALID` with the tries left, the fifth wrong one and everything after is `422 PICKUP_CODE_LOCKED`, and a missing pepper is `503`. No pickup record is written on a refusal. The pickup audit entry records `pickup_code_verified`. A note without a code is unchanged. |
| **`POST /v1/release-notes/{id}/pickup-code`** (new) | tenant_admin, nigeria_office_staff. Sends the customer a fresh code for an active note, retires the old one and unlocks the note. `200 {release_note_id, sent_via: ["sms","email"]}`. `422 RELEASE_NOTE_NOT_ACTIVE`, `422 PICKUP_CODE_NOT_DELIVERABLE` (no phone or email, or channels off), `422 PICKUP_CODES_NOT_CONFIGURED`. Audited (`pickup_code_reissued`, `sent_via`). |

Design, storage (keyed hash only), the lock and the consequences are in `docs/adr/008-release-note-pickup-code.md`. Env: `PICKUP_CODE_PEPPER` (at least 16 characters; unset means no codes are issued and none are required).

**Ground-truth gap found on the way:** the warehouse dashboard's quick pickup sheet sent only the carton count, and `RecordPickupRequest` requires `collected_by_name` for a non-delegate pickup, so every in-person pickup recorded from the dashboard was refused with a 422 (the release-note page's form was fixed for this earlier; the dashboard sheet was not). It now has a "Collected by" field, defaulted to the customer.

Tests: `tests/unit/test_pickup_code.py` (30), `test_pickup_code_release.py` (46), `test_pickup_code_notification.py` (13), nine security properties mutation-checked. `tests/db/test_pickup_code.py` (11) and **migration 065 itself have not been run** (no Docker): run `make migrate` and `make test-db`.
