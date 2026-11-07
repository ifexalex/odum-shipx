# Task 11 — API Service: Billing Calculation + CBM Disputes

## Objective

Implement the Billing Lambda service: auto-billing on customs clearance, CBM-based pricing, misc charges, carryover application, CBM dispute lifecycle.

## Depends On

- Task 06 (shared layer)

## Files: `services/billing/handler.py`, `service.py`, `repository.py`, `models.py`

## Routes

| Method | Path | Roles |
|---|---|---|
| GET | `/v1/billing` | tenant_admin, nigeria_office_staff, customer (own only, force-scoped server-side) — paginated list, filterable by `?status=` / `?customer_id=` (staff only — a customer's `customer_id` filter is always overridden to their own) / `?q=` (free-text over invoice_number, customer name, container_number) / `?created_after=&created_before=` (over `billed_at`); sortable via `?sort=&direction=` |
| GET | `/v1/billing/{customer-id}` | tenant_admin, nigeria_office_staff, customer (own only) |
| GET | `/v1/billing/{billing-id}/detail` | tenant_admin, nigeria_office_staff, customer (own only) — one record by its **own** id; response is byte-identical to the matching `GET /v1/billing` row. The `/detail` suffix is required because the bare `/v1/billing/{id}` shape above takes a *customer* id and both ids are UUIDs |
| POST | `/v1/billing/{id}/dispute` | customer |
| GET | `/v1/billing/{id}/disputes` | nigeria_office_staff, tenant_admin, customer (own) |
| PATCH | `/v1/billing/disputes/{id}/acknowledge` | nigeria_office_staff |
| PATCH | `/v1/billing/disputes/{id}/resolve` | nigeria_office_staff, china_office_staff, tenant_admin |
| POST | `/v1/billing/disputes` | nigeria_office_staff, tenant_admin (staff-created disputes) |
| PATCH | `/v1/billing/disputes/{id}/reject` | nigeria_office_staff, tenant_admin |
| PATCH | `/v1/billing/{id}/cancel` | tenant_admin, nigeria_office_staff |
| PATCH | `/v1/billing/{id}/apply-carryover` | tenant_admin, nigeria_office_staff |
| GET | `/v1/billing/payments` | tenant_admin, nigeria_office_staff — recent payments across all billings (`?limit=`, default 8, max 50); feeds the §6.1 dashboard "Recent payments" table (P2-5) |
| POST | `/v1/billing/{id}/charges` | tenant_admin, nigeria_office_staff |
| GET | `/v1/billing/{id}/charges` | tenant_admin, nigeria_office_staff, customer (own) |
| DELETE | `/v1/billing/{id}/charges/{charge-id}` | tenant_admin, nigeria_office_staff |

**Add misc charge** — `POST /v1/billing/{id}/charges` body:
```json
{
  "description": "Customs examination",
  "amount_ngn": "15000",
  "charge_type": "service_charge",
  "charge_type_id": "uuid"
}
```
- `charge_type` is the enum category (`storage_fee`, `service_charge`, `other`, …) used for totals.
- `charge_type_id` (optional) attributes the charge back to a configured `charge_type` row so it
  counts toward that type's `usage_count` (migration 035, §4.4). Omit / NULL for free-form charges.

### GET /v1/billing — ground-truth security fix (2026-07-19)

`_BILLING_READ_ROLES` allows the `customer` role to call this endpoint, but `service.list_billing()` had **no ownership scoping at all** — any authenticated customer hitting `GET /v1/billing` with no filters got every billing record in the tenant (amounts, payment status, other customers' names), a cross-customer financial-data leak. Same bug class as the `GET /v1/customers` gap fixed 2026-07-09 (see `07_api_tenant_management.md`).

Fixed: `list_billing()` now takes an optional `ctx`; when `ctx.role == CUSTOMER`, it resolves the caller's own `customer_id` via `get_customer_by_user_id()` and **force-overrides** `filters["customer_id"]` to it — a customer's own `?customer_id=` query param is silently discarded rather than trusted, so there is no way to request someone else's records by passing a different ID. A customer with no linked `customer` row gets an empty page, not an error. Staff calls (`ctx.role != CUSTOMER`, or no `ctx` passed at all for internal callers) are completely unaffected.

Verified live: a customer (`Emeka Obi`) hitting `GET /v1/billing` now gets 0 results instead of another customer's (`Funmilayo Adeyemi`'s) `paid` billing record with full amounts. Tests: `TestListBilling` (5 cases) in `tests/unit/test_billing.py`.

### GET /v1/billing — `sort`/`direction` (row 7.37)

| Param | Type | Notes |
|---|---|---|
| `sort` | string | `invoice_number` or `billed_at` (default `created_at`) — must be a single identifier from `shared/pagination.py::ALLOWED_SORT_FIELDS`; anything else is `422`. (Until 2026-09-23 a payload ending in `.created_at` bypassed validation and reached `ORDER BY` — a CRITICAL SQL injection reachable by the customer role; see `00_CROSS_CUTTING_STANDARDS.md` §2.2) |
| `direction` | `asc` \| `desc` | default `desc` |

Wires up BillingList's 'Reference'/'Billed' columns, which declared `sortable: true` on the shared `Table` component but had no `onSort` handler and no backend support — the sort chevrons were purely decorative. `list_billing_all()` prefixes `sort_field` with the `b.` table alias before calling `build_paginated_query()` (it sorts the aliased `billing b` table directly, not a flattened subquery like `tracking/repository.py::list_containers` does). Note the 'Reference' column renders `invoice_number`, not `reference_number` — the latter belongs to `payment_record`/`release_note`, not `billing`; `billed_at` (migration 006) is the real column backing the 'Billed' column, not `created_at`.

### GET /v1/billing — `status` (multi-select), `created_after`/`created_before` (2026-09-07)

Ground-truth gap found live, reported by the user: "let's double check the billing details filters and date ranges search and other filters are correctly doing what they should do." `BillingList.tsx`'s "calendar" button and "Filters" button both rendered with no `onClick` handler at all — pure dead UI, indistinguishable from a working date-range picker and filters panel. Investigation found the backend had zero support to back them: `BillingListParams` had no date fields, `handler.py` parsed only a single `status` value, and `list_billing_all()` only ever compared `b.status = %(status)s`.

| Param | Type | Notes |
|---|---|---|
| `status` | comma-separated string | multi-select — `b.status = ANY(%(statuses)s)`, same idiom as `tracking/repository.py::list_containers`'s `status = ANY(...)`. A bare single value is a 1-element list. |
| `created_after` | ISO date (`YYYY-MM-DD`) | filters `b.billed_at >= %(created_after)s` — records with `billed_at IS NULL` (never billed) are correctly excluded by SQL NULL semantics, not a bug. |
| `created_before` | ISO date (`YYYY-MM-DD`) | filters `b.billed_at <= %(created_before)s` |

Fixed by wiring `BillingList.tsx`'s calendar button to the shared `DateRangeFilter` component (against `billed_at`, since that's the column the 'Billed' column and its sort already use — not `created_at`) and building a real Filters panel with a granular multi-select over `PaymentStatus`, following the exact `china/ContainerList.tsx` pattern (`filtersWrap`/`filtersPanel`/`toggleStatus`/`clearAllFilters`). The single-select status chips and the panel's multi-select share one `activeStatuses` array so the two entry points can never silently combine.

### GET /v1/billing — `?q=` search was silently dropped + record-payment context (2026-10-03)

Reported live: "billing filters and search… not working properly." Two issues:

1. **Search did nothing.** `BillingList.tsx`'s search box sends `?q=`, and `list_billing_all()` already had the `ILIKE` predicate (`b.invoice_number`/`cu.name`/`c.container_number`), but **`handler.py` never read the `q` query param** into `filters` — so it was discarded before reaching the service. Fixed by parsing `q` in the `GET /v1/billing` branch (the one line between `created_before` and `limit`). Regression test: `TestBillingHandlerQueryParams::test_search_query_param_reaches_the_service`. Verified live: `?q=Amara` → 6 matches, `?q=INV-S-0309` → 1, container number → container-scoped, nonsense → 0.
2. **Record-payment modal lacked context.** The modal showed only Amount/Method/Reference — nothing about *who* is paying or *what* for. `list_billing_all()` now also selects `cu.phone AS customer_phone, cu.email AS customer_email` (and `_enrich_billing` passes them through), so the list/detail response carries the customer's contact. The `RecordPaymentModal` (`BillingDetail.tsx`) now leads with a context card: customer name + phone + email, invoice number, container, status badge, and a Total due / Already paid / Outstanding summary; the amount field pre-fills with the outstanding balance (editable for partials). New response keys: `customer_phone`, `customer_email` (nullable).

### PATCH /v1/billing/{id}/apply-carryover — 500 (uuid cast) + status recompute + detail context (2026-10-03)

Reported live: "carry over payment seems not to be working." Three issues:

1. **Apply always 500'd.** `repo.mark_carryovers_applied()` and `mark_credit_refunds_applied()` compared a `uuid` PK against a **bound Python-string array** — `AND id = ANY(%(ids)s)` → `psycopg2 UndefinedFunction: operator does not exist: uuid = text`. Every manual carryover application raised a 500 (and the same function on the billing-generation auto-apply path and the CBM-dispute credit-refund path shared the latent fault). Fixed with an explicit `::uuid[]` cast on the bound array. **Unit tests can't catch this** — they mock `execute_write_with_tenant`, so the SQL never runs; verified live instead (apply → 200, ledger row flips to `applied` with `target_billing_id`/`applied_at`, billing total/balance updated).
2. **Status not recomputed.** Applying carried-forward debt raises `total_ngn`, so the generated `balance_ngn` grows — but `status` was never recomputed, leaving a formerly-`paid` record `paid` while now owing. `apply_carryover` now recomputes the money status (`unpaid`/`partially_paid`/`paid`/`overpaid`) from the fresh balance via the new `repo.set_billing_status()`, for the four money statuses only (`released_with_outstanding` left untouched; `cancelled`/`waived` already blocked). New test `test_applying_to_a_paid_billing_recomputes_status_to_partially_paid`.
3. **Picker offered un-appliable credits + thin detail header.** The "Apply carryover" modal loaded **every customer's** outstanding carryovers, but `apply_carryover` rejects a customer mismatch (`BR-CARRYOVER-003`) — so most picks 422'd. `loadCarryovers()` now scopes to `customer_id: billing.customer_id`. Separately, the `BillingDetail` hero now leads with the **customer name** (was the container number) plus invoice number, container, and the customer's phone/email (same fields added in the 7.88 note above).

Note on semantics: a carryover is **outstanding debt carried forward** to the next shipment (migration 003's `carryover_ledger` — "outstanding balance carried forward"), so applying one *increases* the target invoice. Overpayments are a separate path (`create_overpayment_refund_request`), not carryovers.

Verified live against the real local stack: `GET /v1/billing?status=unpaid,released_with_outstanding` returned exactly the 3 matching records out of 4 total; `created_after=2099-01-01` returned 0; `created_after=2020-01-01` returned only the 1 record with a non-null `billed_at`. Tests: `TestListBillingAllRepositoryFilters` (5 cases) and `TestBillingListHandlerQueryParams` (3 cases) in `tests/unit/test_billing.py`; `BillingList.test.tsx` gained 3 cases covering the date filter, the multi-select panel, and Clear all filters.

**Follow-up (2026-09-07):** the user asked to check every page with a "calendar" filter, not just billing. Added an exact custom From/To date pair next to `BillingList.tsx`'s preset button (the backend already accepted `created_before` from the fix above, but the frontend never sent it) — same shared `useDateRangeFilter` hook now used by ContainerList, ClaimList, NotificationLog, and TenantReports. Tests: `BillingList.test.tsx` gained 1 more case.

### GET /v1/billing/{billing-id}/detail — billing had no by-id read at all (2026-11-07)

Ground-truth gap: the API had **no endpoint that reads one billing record by its own id**. The bare
`GET /v1/billing/{resource-id}` route takes a *customer* id, and since both are UUIDs the two shapes
cannot be told apart, so the single-record read needed its own path.

Both detail pages worked around it the same way — `BillingDetail.tsx` and
`MyBillingDetail.tsx` called `billingApi.list()` and searched the result client-side:

```ts
const result = await billingApi.list()
const found = result.data.find((b) => b.id === id) ?? null
if (!found) { setError('Billing record not found.') }
```

`billingApi.list()` passes no `limit`, so it got the server default of **50 rows**. Consequences:

1. **Any record past the first page was unreachable.** Record 51+ opened as "Billing record not
   found." on a direct link or a page refresh — the record exists, the customer is entitled to it,
   and the page says it does not exist.
2. **Worse after a mutation, not just on arrival.** `load()` is the refresh after recording a
   payment, confirming a payment claim, waiving storage fees and removing a charge (6 call sites).
   Arriving from the list seeded `billing` from router state, so an off-page record *displayed*
   correctly — then the first payment recorded against it replaced the open record with "not found."
3. **50 enriched rows fetched to display one.** `_enrich_billing()` issues 4 queries per row, so each
   refresh of one invoice cost ~200 queries.

Fixed by adding `GET /v1/billing/{billing-id}/detail` (`service.get_billing`), which returns the
**byte-identical** shape to the matching `GET /v1/billing` row — verified by diffing both responses
key-for-key against the live stack (no missing keys, no extra keys, no differing values). This
required adding the `customer` join to `repo.get_billing_by_id()`, which previously selected only
`b.* , c.container_number`; without it `_enrich_billing` would have returned a record whose
`customer_name` / `customer_phone` / `customer_email` were all null while the same record carried
them when listed.

**Authorization.** A by-id read is addressable by guessing, so the ownership check lives in the
service, not the caller: `CUSTOMER` role is resolved to its own `customer_id` and compared to the
record's, the same force-scoping `list_billing()` and `get_billing_for_customer()` already use, and
it **fails closed** — a customer-role token with no `customer` row is denied, not served. Verified
live: owner → 200; a different customer → 403; `china_office_staff` (not a billing read role) → 403;
another tenant's staff reading this id → 404, not a leak; unknown id → 404.

Tests: 5 cases in `tests/unit/test_billing.py::TestBillingService` (enriched shape, 404, another
customer refused, own record allowed, unmapped customer fails closed). `BillingDetail.test.tsx`
asserts the page calls `billingApi.get(id)` and **never** `billingApi.list()`.

## Billing Calculation (Rule BR-BL-001)

Triggered when container status → `cleared`. For **each customer** in the container:

**Ground-truth fix (2026-07-18):** `services/billing/handler.py`'s EventBridge branch (`source=logistics.tracking, detail-type=PaymentDue → auto-create billing`) was correctly implemented but **never actually invoked** — `infrastructure/aws/modules/eventbridge/main.tf`'s routing rules only fan `PaymentDue` out to the SMS/WhatsApp notification queues; there was no rule/target wiring EventBridge to invoke the billing Lambda itself. A container could sail through `cleared` → `at_warehouse` ("ready for pickup") with **zero billing records ever created**, in both local dev and production — the customer would see no bill at all. Fixed by having `services/tracking/service.py`'s `cleared`-transition handler call `services/billing/service.py`'s `handle_payment_due()` directly (synchronous cross-service call — same precedent as `check_container_limit` in the same file). The `PaymentDue` event publish is unchanged and still fires (it's what the SMS/WhatsApp routing rules key off for the customer notification); billing generation no longer depends on it. Verified live end-to-end: fresh container walked through the full state machine via the real API → billing row appeared the instant `cleared` fired, visible to the customer via their own `GET /v1/billing/{customer-id}` call. Tests: `test_cleared_publishes_payment_due_per_customer` (updated) + `test_cleared_still_publishes_events_when_billing_generation_fails` (new) in `tests/unit/test_tracking.py`.

1. Sum CBM from all `packing_list_item` rows (via approved packing lists for this customer+container), **grouped by package type** (`repo.get_cbm_by_package_type`, `GROUP BY package_unit`) — `repo.get_cbm_and_carton_totals` (flat sum) is still called too, for `total_cartons` and the overall `total_cbm` used in the skip-guard.
2. Fetch the CBM rate config via `shared.cbm_rate.get_cbm_rate_config(tenant_id)` — **not** a raw `tenant_config` read (2026-09-20). Returns `{currency: "usd"|"ngn", rate_mode: "flat"|"per_package_type", carton_rate, bag_rate, bale_rate}`, backward-compatible with the pre-2026-09-20 single-rate shape at read time (no migration needed). See `07_api_tenant_management.md`'s CBM Rate section for the full config shape and the `rate_mode`/currency semantics.
3. Fetch `dollar_rate` via `shared.fx_rate.get_effective_dollar_rate(tenant_id)["rate"]` — **not** `tenant_config` directly (2026-09-19). The base rate is Bybit's live P2P black-market rate plus this tenant's markup; see `07_api_tenant_management.md`'s Dollar Rate section for the fetch/cache/fallback chain. The resolved rate is frozen into `billing.exchange_rate_ngn` at creation time exactly as before — only where the number comes from changed, not the freeze-at-creation behavior.
4. Price each package-type bucket at its own rate (`shared.cbm_rate.compute_cbm_charge`) — a normalized bucket, `carton`/`bag`/`bale`, with any other `package_unit` (pallet, item, mixed, unspecified, or any other free-text value) folded into the `carton` bucket. Each bucket's subtotal is rounded to 2dp independently, then summed — so the stored `cbm_breakdown` always sums exactly to the total charged, never off by a cent from rounding a combined figure. "Flat" mode is not a separate branch here — it's simply the case where `carton_rate == bag_rate == bale_rate`, so a flat-rate tenant's math is identical to today's pre-2026-09-20 behavior.
   ```
   charge = Σ bucket_cbm × bucket_rate   (in the tenant's configured currency)
   if currency == usd:  subtotal_usd = charge;  subtotal_ngn = subtotal_usd × dollar_rate
   if currency == ngn:  subtotal_ngn = charge;  subtotal_usd = subtotal_ngn / dollar_rate   (back-derived, for the columns/exports/UI that already expect a USD figure)
   ```
   `billing.cbm_rate_usd` (the pre-existing single-scalar column, still read by CBM dispute resolution, exports, and staff/customer UI) is set **exactly** to the tenant's one effective rate (in USD terms) whenever `carton_rate == bag_rate == bale_rate` — no rounding drift introduced for the common case — and only falls back to the blended average (`subtotal_usd / total_cbm`) when the three rates genuinely differ, since no single "the rate" exists to report exactly in that case.
   `billing` gains three new columns (migration 050) recording *how* the invoice was actually priced: `cbm_rate_currency` ('USD'/'NGN'), `cbm_rate_mode` ('flat'/'per_package_type', purely descriptive), and `cbm_breakdown` (JSONB, always populated — `{"carton": {"cbm", "rate", "subtotal"}, "bag": {...}, "bale": {...}}`, in the tenant's configured currency). `cbm_breakdown` becomes historical record only, not reconciled, if a later CBM dispute adjusts `total_cbm` — disputes are whole-invoice corrections with no notion of *which* package type's count was wrong (see CBM Dispute section below).
5. Check `carryover_ledger` for outstanding entries for this customer → sum as `carryover_ngn`
6. Check `refund_request` with status='approved', customer_choice='credit_next_shipment' → sum as credit
7. Calculate totals:
   ```
   total_due_usd = subtotal_usd + misc_fees_usd + carryover_usd - credits_usd
   total_due_ngn = subtotal_ngn + misc_fees_ngn + carryover_ngn - credits_ngn + storage_fees_ngn
   outstanding_ngn = total_due_ngn
   ```
8. Insert `billing` record (payment_status = 'unpaid')
9. Mark applied carryovers as 'applied' with `target_billing_id`
10. Mark applied credits as 'applied_as_credit' with `applied_to_billing_id`
11. Publish `PaymentDue` event per customer

## CBM Dispute State Machine

```
submitted → acknowledged → investigating → escalated_china → resolved_adjusted → closed
                                         → resolved_no_change → closed
```

**Staff bell (2026-09-12):** filing a dispute (`file_cbm_dispute`) now also writes a `staff_notification` row for `nigeria_office_staff`/`tenant_admin`; the SLA-breach and auto-escalation cron jobs (`scheduled/sla_check.py`, `scheduled/dispute_escalation.py`) each gained a matching in-app notification alongside their pre-existing email. Full account in `15_api_notifications.md`.

**Key rules:**
- Acknowledgement must happen within 24h (SLA tracked)
- `investigating → escalated_china`: auto after N days (tenant_config `dispute_escalation.auto_escalate_days`) or manual
- `resolved_adjusted`: corrected_cbm must differ from original; recalculates billing — always as `corrected_cbm × billing.cbm_rate_usd` (the invoice's own frozen per-invoice rate), unchanged by the 2026-09-20 per-package-type work above; no code changes were needed there since that rate is already exact (or the correct blended average) regardless of how many package types went into the original invoice — live-verified against a real per-package-type invoice.
- `resolved_no_change`: must provide resolution_notes

### CBMDispute Wire Format — SLA Fields

`_fmt_dispute` computes and returns these SLA fields (all ISO datetime strings or null):

| Field | Source | SLA window |
|---|---|---|
| `submitted_at` | `created_at` | — |
| `acknowledged_at` | `acknowledged_at` column | — |
| `acknowledge_due_by` | `submitted_at + 24h` | Match `sla_check.py._SLA_WINDOW` |
| `investigate_due_by` | `acknowledged_at + 5d` | Match `dispute_escalation._DEFAULT_ESCALATE_DAYS` |
| `resolve_due_by` | `acknowledged_at + 7d` | — |
| `auto_escalated_at` | `updated_at` proxy when `status ∈ {escalated, escalated_china}` | — |

These fields are present on all dispute objects (embedded in billing response `_active_disputes`, list endpoint, and detail endpoint).

### Billing Recalculation on Dispute Resolution
When `resolved_adjusted`:
1. Update `billing.total_cbm` = dispute.corrected_cbm
2. Recalculate: subtotal_usd, subtotal_ngn, total_due_usd, total_due_ngn, outstanding_ngn
3. Publish `CBMDisputeResolved` event
4. If customer already paid and new total < paid → create overpayment refund_request

## GET /billing/{customer-id} Response

Include nested data: payments list, carryovers list, misc_fees list, active disputes. Filter by `?container_id=`.

## Billing Void / Cancel (PATCH /billing/{id}/cancel)

Request body: `{ "cancel_reason": "string" }` (required, max 500 chars).

Guards (all must pass; any violation → 422 `BUSINESS_RULE_VIOLATION`):
1. Billing status must be `unpaid` — billing with any payment cannot be cancelled.
2. No confirmed `payment_record` rows linked to this billing.
3. No active (non-terminal) `release_note` rows linked to this billing.

On success:
- Sets `billing.status = 'cancelled'`; records `cancel_reason`, `cancelled_by`, `cancelled_at`.
- Writes an audit log entry.
- Returns the updated billing row.

Billing status values (migration 017 adds `cancelled` to existing CHECK constraint):
`unpaid | partially_paid | paid | overpaid | waived | released_with_outstanding | cancelled`

## Acceptance Criteria

- [x] Billing auto-calculated on `cleared` container status
- [x] CBM summed correctly from packing list items
- [x] Carryover balances applied from carryover_ledger
- [x] Credits from approved refunds applied
- [x] CBM dispute full lifecycle with 8 states (including `rejected`)
- [x] Billing recalculated on dispute adjustment
- [x] `PaymentDue` and `CBMDisputeResolved` events published
- [x] Customer sees only own billing records
- [x] Billing cancel endpoint guards: unpaid status, no payments, no active release notes (migration 017)
- [x] Apply carryover endpoint: PATCH /billing/{id}/apply-carryover links an outstanding carryover to a billing and adds its amount to the total (guards: billing not cancelled/waived; carryover must be outstanding and same customer)
- [x] `GET /v1/billing?sort=&direction=` — `invoice_number`/`billed_at`, wired to BillingList's `sortable: true` columns (previously dead UI)

**Ground-truth gap found while auditing log coverage (2026-09-07):** two money-affecting writes had no `log_audit()` call. `handle_payment_due` (the EventBridge-triggered function that creates the invoice itself) was completely unaudited — the one real billing-money write with zero trail. `reject_dispute` was the one CBM-dispute status transition not logged (acknowledge/escalate/resolve all were). Both now log (`entity_type="billing"`/`"cbm_dispute"`). Fixing `handle_payment_due` also surfaced a separate, more serious bug — see `02_shared_utilities.md`'s `log_audit` write-up: passing a non-UUID `actor_id` placeholder for a system-triggered action silently fails the insert entirely (caught here, and in the pre-existing `payment_release/service.py::process_webhook_payment`, which had the same bug). Full account in `07_api_tenant_management.md`'s "Tenant Activity Log" section.

**Correction (2026-09-09) to the "it's what the SMS/WhatsApp routing rules key off for" claim above:** that was wrong — the routed EventBridge envelope never actually reaches `shared/notifications.py`'s SQS pipeline at all (confirmed while investigating a separate reported bug: a rejected payment claim sent no notification to anyone). `handle_payment_due` never called `enqueue_notifications`, so a fresh invoice generated **zero customer notification**, same silent gap as everywhere else the EventBridge-only pattern was used. Fixed by calling `enqueue_notifications(event_type="payment_due", ...)` directly at the end of `handle_payment_due` — best-effort, wrapped in try/except so a notification failure can never fail billing generation. Full account, including the other 5 events found in the same state, in `15_api_notifications.md`. Tests: `TestHandlePaymentDueNotification` in `tests/unit/test_billing.py`.

**Customer bell (2026-09-12):** `handle_payment_due` now also writes an in-app customer notification when the invoiced customer has a portal account, reusing the same `staff_notification` table as the staff bell (see this doc's earlier "Correction" entry). Full account in `15_api_notifications.md`.
