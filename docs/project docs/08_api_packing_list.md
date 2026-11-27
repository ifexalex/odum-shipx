# Task 08 — API Service: Packing List CRUD + Approval Workflow

## Objective

Implement the Packing List Lambda service: create/update/list/get packing lists, manage approval workflow (submit → approve/reject → revise cycle), auto-generate carton tags and tracking codes, calculate CBM.

## Depends On

- Task 06 (shared layer), Task 03 (models)

## Files to Create

```
services/packing_list/
├── handler.py
├── service.py
├── repository.py
└── models.py
```

## Routes

| Method | Path | Roles |
|---|---|---|
| POST | `/v1/packing-lists` | china_office_staff |
| GET | `/v1/packing-lists` | china_office_staff, tenant_admin, nigeria_office_staff, customer (own only) |
| GET | `/v1/packing-lists/{id}` | same as list |
| PUT | `/v1/packing-lists/{id}` | china_office_staff (only in draft status) |
| PATCH | `/v1/packing-lists/{id}/approve` | china_office_staff, tenant_admin (not the creator) |
| PATCH | `/v1/packing-lists/{id}/reject` | china_office_staff, tenant_admin |
| POST | `/v1/packing-lists/bulk-approve` | china_office_staff, tenant_admin |
| POST | `/v1/packing-lists/bulk-reject` | china_office_staff, tenant_admin |
| GET | `/v1/containers/{id}/packing-lists` | china_office_staff, tenant_admin, nigeria_office_staff, customer (own only) |

## State Machine

```
draft → pending_approval → approved
                         → rejected → draft (revision cycle)
```

**Transitions:**
- `draft → pending_approval`: Staff submits. Must have ≥1 item.
- `pending_approval → approved`: Reviewer ≠ creator. Creates/updates manifest. Publishes `PackingListApproved`.
- `pending_approval → rejected`: Must provide comments. Stores in approval_comments JSONB.
- `rejected → draft`: Creator revises. Must change ≥1 field. Retains comment history.

**ILLEGAL:** draft→approved, approved→draft, approved→rejected, rejected→approved, rejected→pending_approval

## Key Business Logic

### Create Packing List (POST)
1. Validate container exists in tenant scope, status = 'loading'
2. Validate customer exists in tenant scope
3. For each item:
   - Auto-generate `carton_tag`: `{tenant_short}-{container_number}-{zero_padded_seq}` (query max existing sequence)
   - Auto-generate `tracking_code`: Items with same customer + received_date share one code: `{tenant_short}-TRK-{YYYYMMDD}-{seq}`
   - Calculate `cbm = (length_cm × width_cm × height_cm) / 1_000_000` (0 if dimensions missing)
4. Insert `packing_list` (status='draft') + `packing_list_item` rows
5. Return full packing list with computed fields

### Approve (PATCH /approve)
1. Validate packing list is in `pending_approval`
2. Validate approver ≠ creator (prevent self-approval)
3. Update status to `approved`, set approved_by, approved_at
4. Create manifest for container if not exists; associate packing list with manifest
5. Recalculate manifest totals (customers, cartons, weight, CBM)
6. Create `shipment_tracking` records for each unique tracking_code (if not exists)
7. Publish `PackingListApproved` event

### Customer Access
- Customers see only their own packing lists: `WHERE tenant_id = :tid AND customer_id = :customer_id`

## Filtering & Pagination

- `?status=draft` — filter by status
- `?container_id=uuid` — filter by container
- `?customer_id=uuid` — filter by customer
- `?created_after=ISO&created_before=ISO` — date range
- `?sort=-created_at` — sort (default: newest first)
- Cursor-based pagination

## Excel Import (POST /packing-lists/import)

- Accept `.xlsx` upload (multipart or S3 presigned URL)
- Parse with `openpyxl`, validate headers
- Look up customers by name within tenant
- Group items by customer + received_date
- Create packing lists in 'draft' status
- Return summary: total_rows, imported, errors, packing_lists_created, error_details[]

## Implementation notes / ground-truth gaps found

**List query (`GET /v1/packing-lists`) now includes `customer_name`, `container_number`, `carton_count`, and `total_cbm`.** The `packing_list` table stores no computed columns — `carton_count` and `total_cbm` were only computed by `_assemble_response()` which was called by single-record endpoints (get, create, update, approve). The list endpoint previously returned raw DB rows with these fields entirely absent. `list_packing_lists()` in `repository.py` now uses a subquery wrapper that:
  1. LEFT JOINs `customer` to add `customer_name`
  2. LEFT JOINs `container` to add `container_number`
  3. LEFT JOINs an aggregated subquery on `packing_list_item` for `carton_count`, `total_cbm`, `total_weight_kg`
  4. Wraps all three in an outer `SELECT * FROM (...) AS t WHERE 1=1` so `build_paginated_query`'s cursor condition (`AND id > ...`) references unambiguous columns rather than clashing with `container.id` or `customer.id`

**`wrong_status:draft` on bulk approve/reject.** The bulk endpoints skip items not in `pending_approval` status and return them in a `failed` list with `reason: wrong_status:{status}`. Items in `draft`, `approved`, or `rejected` states are silently skipped server-side. The frontend guards this at the UI level — checkboxes render for `pending_approval` rows (bulk approve/reject) *and* `draft` rows (bulk submit), via `PackingListList.tsx`'s `selectable`; every other status has no bulk action to select it for. See "Bulk submit checkbox gap" below for the correction to this.

**Draft packing lists have no submit action from the detail view (fixed).** After saving a packing list as draft via `POST /v1/packing-lists` (without immediately submitting), there was no way to submit it for approval from the `PackingListDetail` page — the "Edit & resubmit" button only appeared for `rejected` status. A "Submit for approval" button now appears for `draft` status when the list has at least one item and the viewer has the china_office_staff role.

**Edit & resubmit now replaces all items.** `PUT /v1/packing-lists/{id}` in `service.py` calls `repo.delete_items_by_packing_list()` then re-inserts all items with fresh carton tag sequences — item `id` values in the request body are ignored server-side. The frontend edit mode sends all items (both existing and newly added) as a flat list; carton tags are reassigned from scratch.

## Acceptance Criteria

- [x] CRUD operations with correct authorization
- [x] State machine enforced (illegal transitions return 409)
- [x] Self-approval prevention (approver ≠ creator)
- [x] Carton tag auto-generation with tenant prefix
- [x] Tracking code grouping (same customer + date = same code)
- [x] CBM calculation from dimensions
- [x] Manifest created/updated on approval
- [x] Shipment tracking records created on approval
- [x] `PackingListApproved` event published
- [x] Customer sees only own data
- [x] Filtering, sorting, cursor pagination work correctly
- [x] POST /packing-lists/bulk-approve: approves up to 100 pending_approval PLs; returns succeeded/failed lists; self-approval still blocked per item
- [x] POST /packing-lists/bulk-reject: rejects up to 100 pending_approval PLs; returns succeeded/failed lists
- [x] GET /containers/{id}/packing-lists: ergonomic sub-resource alias; delegates to list_packing_lists with container_id pre-set
- [x] `declared_value_usd` optional field on `PackingListItemInput` (migration 026) — stored for insurance and customs valuation
- [x] Rejection audit log includes item snapshot in `before_state` (captures exact item versions at time of rejection)


## Customer contact on list responses (2026-08-30)

`customer_phone` is returned alongside `customer_name` wherever a customer appears as a row:
`get_customer_summaries` (manifest customer table) and the packing-list detail/list queries
(`services/packing_list/repository.py`). The joins on `customer` already existed — only the name was
being selected.

The source manifest pairs **NAME** with **CONTACT** on every row for a reason: when cargo lands,
staff ring the customer. Requiring a click through to the customer record to get the number made the
operational tables less useful than the paper document they replace.


## Bulk submit + imported-list status (2026-08-30)

**New route:** `POST /v1/packing-lists/bulk-submit` — `china_office_staff`, `tenant_admin`.
Moves `draft` -> `pending_approval` for up to 100 ids, mirroring `bulk-approve`/`bulk-reject`
(`{succeeded, failed:[{id, reason}], total}`). Self-submission is allowed: the two-person control
lives on approval, not submission.

**Imports now land in `pending_approval`, not `draft`** (`services/excel/repository.py::create_packing_list`).

### Ground-truth gaps found

Reported live: bulk-approving a freshly imported manifest returned `wrong_status:draft` for all 68
lists. Two separate walls:

1. The state machine is `draft -> pending_approval -> approved`, and bulk approve only accepts
   `pending_approval` — but **no bulk submit existed**. `submit` was single-item only, so 68
   imported lists needed 68 individual submits. `draft` also bought nothing for imported data: an
   imported file is complete on arrival, so imports now skip it.
2. Even after submitting, the importer could not approve their own import — `bulk_approve` rejects
   `created_by == actor`. That guard is **kept deliberately**: imported cargo drives billing, so a
   second person signs it off. The flow is: staff imports -> (already pending) -> tenant_admin or
   another china staff member bulk approves.

**Latent data-corruption bug fixed in the same pass:** `repository.bulk_set_status` branched
`if status == "approved" ... else: rejected`, silently coercing *any* other status to `rejected`.
The first `bulk_set_status(..., "pending_approval", ...)` call marked five packing lists **rejected**
instead. It now dispatches explicitly on `approved` / `rejected` / `pending_approval` and raises
`ValueError` on anything else rather than guessing.


## Package mix on list responses (2026-09-01)

The packing-list list query now returns, alongside `carton_count`:

| Field | Meaning |
|---|---|
| `package_count` | Total **packages** — sums each row's bulk `quantity` |
| `package_mix` | Packages keyed by normalised unit, e.g. 2 bale + 16 bag |

`carton_count` is retained and still means **item rows**. It is not a package
count and has not been one since migration 040 made a row a bulk quantity
("16BAGS" is one row). Rows carrying no unit are grouped as `unspecified` so
they still contribute to the total rather than disappearing.

Aggregation is deliberately two-level — sum per `(packing_list_id, unit)`
first, then fold into one row. A single-level `jsonb_object_agg` over raw items
collapses duplicate keys, so two separate `bale` rows would report as one.

`SUM(...)::int` casts matter: `COUNT()` returns a bigint that serialises as a
JSON number, but `SUM()` over numeric returns a Decimal that serialises as a
**string** — without the cast the frontend concatenated counts instead of
adding them (a container total rendered as `01113131641111...`).

### Known inconsistency, not changed here

`billing.total_cartons` (`services/billing/repository.py`) and storage-fee
accrual (`services/scheduled/storage_fee.py`, `unreleased × daily_rate`) still
count **rows**, not packages. Billing charges on CBM so invoice *amounts* are
unaffected, but the carton figure printed on an invoice, and per-carton storage
fees, both under-count for bulk-quantity rows. Flagged rather than silently
changed: it moves money and needs an explicit decision.


## Free-text search on packing lists (2026-09-01)

`GET /v1/packing-lists` and `GET /v1/containers/{id}/packing-lists` accept `?q=`,
matching **customer name**, **container number**, or **packing-list reference**
(case-insensitive, substring).

### Ground-truth gaps found

Reported live: searching packing lists by customer name did nothing. Two
separate defects on the same feature:

1. **The handler never read the `q` param.** The frontend had always sent it and
   the repository SQL had always supported it, but `_packing_list_routes` built
   its `filters` dict from `status` / `container_id` / `customer_id` /
   `created_after` / `created_before` and simply omitted `q` — so the predicate
   was never applied and every search returned the unfiltered list. Confirmed
   before the fix by a real term and a nonsense term both returning 76 rows.
   The container-scoped sub-route had the same omission.
2. **`reference` was missing from the search predicate.** The search box's own
   placeholder reads "Reference, customer name, container…", but the SQL only
   matched `cu.name` and `c.container_number`, so searching for a PL number
   would still have found nothing once the filter was wired up.

This is the third instance of this shape in the codebase (see
`10_api_tracking.md`'s container `q` filter, which was malformed SQL): a search
feature that is wired at the UI and the SQL but broken at the layer between.
Worth checking the remaining list endpoints that expose a search box.


## Total count on list responses (2026-09-01)

`GET /v1/packing-lists` and `GET /v1/containers/{id}/packing-lists` now populate
`meta.pagination.total_count` (previously always absent). Backed by
`repository.count_packing_lists`, which shares its predicate with
`list_packing_lists` via `_packing_list_predicates` — a count built from a
different WHERE clause than the rows it describes is worse than no count.

The COUNT only runs when `has_more` is true; otherwise the page length *is* the
total and the extra query is skipped.

### Ground-truth gap found

Reported live: searching packing lists for `STL409` showed 50 rows, but filtering
to "Pending approval" revealed more under the same container. Not data loss —
the container has 68 (50 approved + 18 pending) and the endpoint returns 50 per
page. With no total in the response and "Load more" sitting below 50 rows of
scroll, a full page read as the complete result: *"this container has 50 packing
lists"*. The status filter then surfaced the remainder, which looks like an
inconsistency. Fixed by returning a real total and stating it in the UI
("Showing 50 of 68 packing lists", "Load more · 18 remaining").


## Approval side effects are shared by both paths (2026-09-01)

Approving a packing list does far more than set a status:

1. find-or-create the container's `manifest`
2. link the list to it (`packing_list.manifest_id`)
3. recalculate manifest totals
4. create a `shipment_tracking` row per distinct tracking code
5. publish `PackingListApproved`

These live in `service._apply_approval_side_effects()` and are called by **both**
`approve_packing_list` and `bulk_approve_packing_lists`.

### Ground-truth gap found

`bulk_approve_packing_lists` did none of the above — it only called
`bulk_set_status`. A bulk-approved container therefore had:

- **no manifest**, so `PATCH /v1/containers/{id}/status → sealed` failed with
  `NO_MANIFEST` ("Container must have a manifest before sealing") even though
  every packing list on it was approved;
- **no `manifest_id` links**, so the manifest customer table would be empty;
- **no `shipment_tracking` rows** — the most damaging: customers could not track
  cargo the system considered fully approved, and the container status pipeline
  had nothing to bulk-update on later transitions.

Confirmed on real data before the fix: 68 approved packing lists, 0 linked to a
manifest, 0 tracking rows. After: 1 manifest (68 customers, 72.55 CBM), 68/68
linked, 68 tracking rows, and the container sealed once the manifest was
verified.

The two paths drifted because the side effects were inline in the single-item
function; sharing one helper is what stops it recurring.

## Bulk submit checkbox gap (2026-09-06)

**Ground-truth gap found and fixed.** `PackingListList.tsx`'s row `selectable` was
`pl.status === 'pending_approval'` only — draft rows never got a checkbox, so "Submit
for approval" (`bulk_submit_packing_lists`, draft-only per its own guard) could never
be clicked with anything it would actually accept. Caught by an e2e test attempting to
select a draft row for bulk submit and finding no checkbox rendered at all.

Now `selectable: pl.status === 'pending_approval' || pl.status === 'draft'`, and a new
`submittableCount` (mirroring the existing `approvableCount` pattern for bulk approve)
disables "Submit for approval" and shows the count of *actually submittable* rows in
the selection, rather than the raw selection size — clicking it no longer fires a
request that a mixed selection is partly guaranteed to fail.

Since [imports land in `pending_approval` directly](#bulk-submit--imported-list-status-2026-08-30),
`draft` rows exist today only from the single-item "Create packing list" flow
(`services/packing_list/repository.py`) — `bulk_submit_packing_lists`'s docstring
previously credited manifest imports for this need, which stopped being true once
imports moved off `draft`. Docstring corrected to match.

`ImportPackingLists.tsx`'s wizard copy claimed imports create packing lists "in draft
status" — also stale since the same 2026-08-30 change. Corrected to describe them as
landing in pending approval.

## Ground-truth gap found live (2026-09-09)

Reported by the user while investigating a separate missing notification on payment-claim rejection — asked to check every notification in the app: `packing_list_approved` had full SMS/WhatsApp/email templates defined but no call site ever used it — approving a packing list (single-item or bulk) sent no notification to the customer at all, only an EventBridge `PackingListApproved` event that no consumer ever routed anywhere. Wired directly into `_apply_approval_side_effects` (shared by `approve_packing_list` and `bulk_approve_packing_lists`), best-effort and never able to fail approval itself. Full account in `15_api_notifications.md`. Tests: `TestApprovalNotifiesCustomer` in `tests/unit/test_packing_list.py`.

**Staff bell (2026-09-12):** submitting a packing list for approval (`submit_packing_list`, `bulk_submit_packing_lists`) now also writes a `staff_notification` row for `china_office_staff`/`tenant_admin` — the roles who can approve it. The bulk path passes `entity_id=None` rather than a comma-joined id list (a single-row UUID column can't hold several ids — see `15_api_notifications.md`). Full account there.

**Customer bell (2026-09-12):** approving a packing list now also writes an in-app customer notification when the customer has a portal account, reusing the same `staff_notification` table as the staff bell above. Full account in `15_api_notifications.md`.

## Item-entry enhancements: package type, bale sizing, min-CBM floor, dates, draft edit (2026-10-02)

Create/edit wizard (`CreatePackingList.tsx`) and the `POST`/`PUT /v1/packing-lists` contract gained:

- **Package type per item** — `PackingListItemInput.package_unit` (`carton` | `bag` | `pallet` | `bale` | `sack`, default `carton`). Reuses the existing `packing_list_item.package_unit` column and feeds CBM-rate bucketing (`shared/cbm_rate.normalize_package_unit`).
- **Bale sizing** — for bale items the backend sets `packing_list_item.bale_type` to `BIG BALE` (effective CBM ≥ 0.3) or `SMALL BALE` (`services/packing_list/service.py::_bale_type_for`). The wizard shows an abbreviated `BIG BALE`/`SM BALE` badge live.
- **Minimum CBM floor** — each line item's `cbm` is floored at the tenant's `min_cbm_per_item` (`shared/cbm_rate.apply_min_cbm`; default 0.1, configurable). A sub-0.1 parcel is stored/billed at the floor; the wizard shows the floored value with a `min` tag. The setting lives in `tenant_config` (`min_cbm_per_item`) and is surfaced on the CBM-rate admin page — see `07_api_tenant_management.md` (GET/PUT `/v1/tenant/cbm-rate` now carry `min_cbm_per_item`).
- **Goods dates** — `delivery_date`/`loading_date` on
  `CreatePackingListRequest`/`UpdatePackingListRequest` (migration 052), captured
  per packing list. Both origin-side events, validated in order:
  - `delivery_date` — the date the supplier **delivered the goods to the China
    warehouse**. **Cannot be in the future** (it records something that happened).
    Note this is *not* the expected customer delivery, which the original
    migration comment wrongly implied; that estimate lives on
    `container.estimated_delivery_date`.
  - `loading_date` — the date the goods were **loaded into the container**. Must
    be **on or after `delivery_date`**; same day is allowed, since goods received
    in the morning are often loaded that afternoon. Deliberately **unbounded
    above**: a packing list is written against a container still in `loading`
    status, so a planned load date is legitimate.
  - Both remain nullable; the rules apply only to values actually supplied.
  - A `422` is returned on violation. The rule lives on a shared
    `_ShipmentDatesMixin` used by both request models, so the PATCH path cannot
    write an ordering the POST path refuses.
  - **Timezone note:** "not in the future" allows one day past the server's UTC
    date. The China office is UTC+8, so for several hours each evening their local
    calendar date is already tomorrow in UTC — comparing against UTC "today"
    would reject the date on their own wall calendar. One day covers every real
    timezone (max UTC+14) and still rejects next week.
- **Arrival warehouse** — `arrival_warehouse_id` on `CreatePackingListRequest`/`UpdatePackingListRequest` (migration 053: `packing_list.arrival_warehouse_id` FK → `warehouse`, `ON DELETE SET NULL`). Records which destination warehouse the customer's goods are bound for, chosen from the tenant's warehouses (`GET /v1/warehouses`). Server-side resolution (`service._resolve_arrival_warehouse`): an explicit id is validated to belong to the tenant (unknown → 404); when omitted it falls back to the tenant's **default** warehouse (same fallback the release-note flow uses), so a list always records a destination when one is configured. The wizard pre-selects the default and offers a searchable `Combobox`; create/detail/list responses carry `arrival_warehouse_name` (LEFT JOIN `warehouse`). Managed on the `Warehouses` admin config page — see `13_api_payment_release.md`.
- **Draft editing** — `canEditPackingList` drafts now open the wizard at `/packing-lists/:id/edit` (reuses the create flow via `PUT /v1/packing-lists/{id}`, which was already draft/rejected-only). Customer/container are fixed; items + dates + arrival warehouse are editable. A new **Edit** button on `PackingListDetail` for draft lists links here.
- **Input hardening (frontend)** — the quantity fields (weights, L×W×H, declared value) block negatives and non-numeric keystrokes (`min=0` + keydown guard + `sanitizeNumber`); the backend already rejected them (`ge=0`/`gt=0` on the Pydantic model), so this is purely entry UX.

Verified live: a 0.06-CBM bale floored to 0.100 shows `0.100 · min · SM BALE`; a 0.4-CBM bale shows `BIG BALE`; a draft opens prefilled with customer/container fixed; negative/alpha input rejected.

## Bulk quantity on a line item (2026-11-12; **superseded 2026-11-25, PR #174**)

> **Superseded (2026-11-25, PR #174):** Row expansion and the `MAX_ITEM_QUANTITY = 500` cap were replaced with the **single-row, single-tag quantity model** below. Historical rationale kept for context; see the 2026-11-25 section for current behaviour.

Staff receiving 100 cartons of one size had to key 100 separate lines. Originally a line
expanded into N rows; as of 2026-11-25 it stays **one row with one `carton_tag` and `quantity = N`**.

## Single-tag quantities, per-unit declared value, and container CBM capacity guard (2026-11-25, PR #174)

- **One row & one tag per line item (`quantity >= 1`, no 500 cap):** `POST`/`PUT /v1/packing-lists` no longer expands a multi-quantity line into N rows (`for _ in range(quantity)` removed) and `MAX_ITEM_QUANTITY = 500` is removed. Each line item stores **1 row** with **1 `carton_tag`**, `quantity = N`, and **line-total** `cbm` (per-unit CBM after `min_cbm_per_item` floor × `quantity`) and line-total weights. Container CBM capacity is the real upper bound instead of an arbitrary quantity cap.
- **Per-unit declared value:** `declared_value_usd` is entered and stored **per unit** (displayed in detail views as `$X/unit ($total)` when `quantity > 1`).
- **Container CBM capacity guard:** `services/packing_list/service.py` enforces `used_cbm + added_cbm <= container_capacity_cbm` on create and update (excluding the packing list's own existing CBM when editing a draft), returning `422` with `rule_id: CONTAINER_CAPACITY_EXCEEDED` when exceeded.

### Packing list PDF rebuilt (FD-40/41, 2026-11-21)

`GET /v1/packing-lists/{id}/pdf` is the one packing-list document (the `/packing-lists/:id/print` page is retired; "Print" opens the PDF). Now with type, quantity, dimensions, CBM to 3 decimals and kg to 1, wrapping 40-character tags, page numbers, and packed by / approved by with dates. `GET /v1/packing-lists/{id}/export?format=pdf` is now 422. See `19_excel_import_export.md`.

## Delivery date modes, shared tracking code, per-item loading dates & Loading Receipts (ENG-2/3/4, migration 073, 2026-11-27)

- **Schema (migration `073_transit_dates_and_loading_receipts.py`):** Added `packing_list.{ship_date, estimated_arrival_date, delivery_date_mode, loading_receipt_number, loaded_at, supplier_name, supplier_phone, remarks}` (with partial unique index `uq_packing_list_loading_receipt_number` and `delivery_date_mode IN ('same_day','multiple_days')`) and `packing_list_item.loading_date`.
- **Delivery date modes (`ENG-3`):** `POST`/`PUT /v1/packing-lists` accept `delivery_date_mode` (`same_day` default | `multiple_days`), optional `supplier_name`/`supplier_phone`/`remarks`, and optional per-item `loading_date` overrides. In `same_day` mode, header `delivery_date` propagates to every item's `received_date`; in `multiple_days` mode, each item records its own `received_date` validated `<= today + 1d UTC` and `<= effective loading_date`.
- **Shared tracking code invariant (`ENG-3`):** All line items inside one packing list share a **single tracking code**, even when items have different delivery dates (`multiple_days` mode).
- **Automatic Loading Receipt on approval (`ENG-4`):** Both single `PATCH /v1/packing-lists/{id}/approve` and `POST /v1/packing-lists/bulk-approve` atomically stamp `loading_receipt_number` (`LR-YYYYMMDD-NNN`) and `loaded_at = NOW()` inside `tenant_transaction`.
- **Tests:** `tests/unit/test_transit_and_documents.py`.
