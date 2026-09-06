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
| GET | `/v1/release-notes` | tenant_admin, nigeria_office_staff, warehouse_attendant, customer (own only) |
| GET | `/v1/release-notes/stats` | tenant_admin, nigeria_office_staff, warehouse_attendant |
| POST | `/v1/release-notes` | tenant_admin, nigeria_office_staff |
| GET | `/v1/release-notes/{id}` | tenant_admin, nigeria_office_staff, warehouse_attendant, customer (own) |
| PATCH | `/v1/release-notes/{id}/release` | warehouse_attendant |
| POST | `/v1/release-notes/{id}/split` | tenant_admin, nigeria_office_staff |
| POST | `/v1/release-notes/{id}/reissue` | tenant_admin, nigeria_office_staff |
| POST | `/v1/webhooks/payment` | No JWT — HMAC signature (Paystack / Flutterwave) |

## Payment Confirmation (POST /payments/{billing-id}/confirm)

**Idempotency:** Supply `Idempotency-Key: <uuid>` header to make retries safe. Duplicate keys within 24 hours return the original cached response without double-counting payments. Key max length: 100 characters.

1. Validate billing exists in tenant scope
2. Create `payment_record` (`payment_method` is nullable — migration 008)
3. Update billing:
   - `total_paid_ngn += amount_ngn`
   - `outstanding_ngn = total_due_ngn - total_paid_ngn`
   - Update `billing.status` (values from migration 006):
     - If outstanding == 0 (±0.01 tolerance) → `paid`
     - If outstanding < 0 → `overpaid` (auto-create refund_request for overpayment)
     - If outstanding > 0 → `partially_paid`
4. Publish `PaymentConfirmed` event
5. Return: payment_id, new status, outstanding, release_note_available flag

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
  ...
}
```

- `valid_until`: ISO date string set at creation (`today + 14 days`).
- `expired_at`: ISO datetime string when status flipped to `expired` (proxy: `updated_at`), null otherwise.
- `storage_fees_ngn`: outstanding storage fees from the linked billing record (string); `"0"` when none.
- `parent_release_note_id`: non-null on split and re-issued notes.

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

**Source of truth:** the payment is recorded exclusively by `POST /v1/webhooks/payment` (HMAC-SHA512, `x-paystack-signature`) — never the browser redirect. **Ground-truth fix:** that webhook route (and `/v1/webhooks/whatsapp`) existed in the handlers but was registered in neither API Gateway's route table nor `scripts/local_server.py` — the receiver was unreachable everywhere. Both are now routed (`POST /v1/webhooks/payment` public in Terraform, HMAC replaces JWT as the auth).

**Secrets (multi-tenant, 2026-07-19):** each tenant connects their own Paystack secret key via `PUT /v1/tenant/config/paystack` — encrypted at rest (`shared/encryption.py`, KMS + Fernet), resolved per-request by `services/payment_release/repository.py::get_tenant_paystack_secret()`. There is **no platform-wide key** — `PAYSTACK_SECRET_KEY` was removed from every env var / Terraform variable. `paystack.initialize_transaction()` now takes `secret_key` as a required parameter (never reads `os.environ`); a tenant with nothing configured gets a clear `PAYMENT_GATEWAY_NOT_CONFIGURED` error and customers fall back to bank transfer. Full design rationale in `07_api_tenant_management.md`'s "Multi-Tenant Paystack" section.
