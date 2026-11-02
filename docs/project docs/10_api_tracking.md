# Task 10 — API Service: Shipment Tracking + Container Status + Stage Transitions

## Objective

Implement the Tracking Lambda service: container CRUD, container status transitions (8 stages), shipment tracking queries, and customer-facing tracking lookup by tracking code.

## Depends On

- Task 06 (shared layer)

## Files: `services/tracking/handler.py`, `service.py`, `repository.py`, `models.py`

## Routes

| Method | Path | Roles |
|---|---|---|
| POST | `/v1/containers` | china_office_staff |
| GET | `/v1/containers` | china_office_staff, nigeria_office_staff, tenant_admin |
| GET | `/v1/containers/{id}` | same |
| PATCH | `/v1/containers/{id}/status` | china_office_staff (China stages), nigeria_office_staff (Nigeria stages) |
| GET | `/v1/containers/{id}/events` | tenant_admin, nigeria_office_staff, china_office_staff, warehouse_attendant |
| GET | `/v1/containers/{id}/documents` | china_office_staff, nigeria_office_staff, tenant_admin |
| POST | `/v1/containers/{id}/documents/presigned-url` | china_office_staff, nigeria_office_staff, tenant_admin |
| GET | `/v1/containers/{id}/documents/{doc-id}/download` | china_office_staff, nigeria_office_staff, tenant_admin |
| GET | `/v1/shipments` | all roles |
| GET | `/v1/shipments/{tracking-code}` | customer (own only, with phone verification) |
| PATCH | `/v1/shipments/{id}/status` | internal (triggered by container status change) |

## Container State Machine (strictly sequential, no skipping)

```
loading → sealed → in_transit → arrived → customs_clearance → cleared → at_warehouse → fully_released
```

**China stages** (china_office_staff): loading → sealed → in_transit
**Nigeria stages** (nigeria_office_staff): arrived → customs_clearance → cleared → at_warehouse
**Auto** (system): at_warehouse → fully_released (when all cartons picked up)

### Side Effects per Transition

| Transition | Side Effects |
|---|---|
| `loading → sealed` | Require ≥1 approved packing list + manifest |
| `sealed → in_transit` | Set ship_date; bulk-update tracking to 'in_transit' |
| `in_transit → arrived` | Set actual_arrival_date; bulk-update tracking to 'arrived_nigeria' |
| `arrived → customs_clearance` | Bulk-update tracking to 'customs_clearance' |
| `customs_clearance → cleared` | Bulk-update tracking to 'cleared'; **trigger billing calculation** for all customers; publish `PaymentDue` per customer |
| `cleared → at_warehouse` | Bulk-update tracking to 'ready_for_pickup'; enqueue `container_arrived` notification per customer (SMS/WhatsApp/email via `enqueue_notifications`) |
| `at_warehouse → fully_released` | System-triggered when all release notes are 'picked_up' |

**ILLEGAL:** Any backward or skip transition → return 409

**Request body key is `new_status`, not `status`.** `PATCH /v1/containers/{id}/status` reads `body.get("new_status", "")`. Sending `{ "status": "sealed" }` results in an empty string and the error "Cannot transition container from 'loading' to ''". The Postman collection uses `new_status` correctly — the frontend `UpdateContainerStatusInput` was fixed to match (`new_status: ContainerStatus`).

### POST /v1/containers — request body

`container_number` is the only required field. All others are optional and default server-side (`origin` → "China", `destination` → "Nigeria").

| Field | Type | Notes |
|---|---|---|
| `container_number` | string (required) | ISO 6346 identifier |
| `parcel_number` | string | optional |
| `origin` / `destination` | string | default China / Nigeria |
| `estimated_arrival_date` | date | optional |
| `notes` | string | optional |
| `vessel_name` | string | **migration 030** — optional |
| `voyage_number` | string | **migration 030** — optional |
| `shipping_line` | string | **migration 030** — optional |
| `seal_number` | string | **migration 030** — optional |
| `container_type` | string | **migration 030** — optional; now set from the chosen capacity preset's name (still free text, no CHECK) |
| `capacity_cbm` | number | **migration 051** — optional usable volume, snapshotted from the chosen capacity preset |
| `recommended_cbm` | number | **migration 051** — optional recommended load, snapshotted from the preset |

Blank/zero/negative/non-numeric `capacity_cbm`/`recommended_cbm` are coerced to NULL (`_positive_or_none`), so the NUMERIC(>0) CHECK never 422s on an empty picker. The frontend create-container form selects a preset from `GET /v1/tenant/container-capacities` (searchable Combobox) and sends the preset's `container_type` (name) + `capacity_cbm` + `recommended_cbm`.

**Container utilization bar (frontend, `ContainerDetail`).** The bar fills to `packed_cbm / capacity_cbm` (capacity from the stored `capacity_cbm`, falling back to a type-name volume estimate for pre-051 containers; hidden when neither is known). Its **colour is a business rule on absolute packed CBM**, not % of capacity: **≥70 CBM green, 65–69 yellow, <65 red** (the "50 and below" case falls in red). The recommended load is shown as a target on the bar's sub-line.

**`GET /v1/containers` and `GET /v1/containers/{id}` responses** include a derived `packing_list_count` (correlated `COUNT(*)` over `packing_list` for that container) alongside all stored columns above. Used by the container list and the packing-list wizard's container picker card ("N PLs").

### GET /v1/containers — query params

| Param | Type | Notes |
|---|---|---|
| `status` | string, comma-separated | one or more of `container.status`'s 9 values, e.g. `status=sealed,in_transit,cleared`. Matched via a parameterized `status = ANY(%(statuses)s)` — never string-interpolated. A single value is just a 1-element list. |
| `q` | string | `ILIKE` free-text search over `container_number`, `vessel_name`, `voyage_number` |
| `created_after` | date (`YYYY-MM-DD`) | `container.created_at >= created_after` — same param name/semantics as `GET /v1/packing-lists`'s `created_after`/`created_before` |
| `created_before` | date (`YYYY-MM-DD`) | `container.created_at <= created_before` |
| `eta_after` | date (`YYYY-MM-DD`) | `container.estimated_arrival_date >= eta_after` |
| `eta_before` | date (`YYYY-MM-DD`) | `container.estimated_arrival_date <= eta_before` |
| `sort` | string | `container_number` or `estimated_arrival_date` (default `created_at`) — must be a single identifier from `shared/pagination.py::ALLOWED_SORT_FIELDS`; anything else (including any expression or an alias-suffixed payload) is `422` — see the SQL-injection fix in `00_CROSS_CUTTING_STANDARDS.md` §2.2 |
| `direction` | `asc` \| `desc` | default `desc` |
| `limit`, `cursor` | — | standard cursor pagination |

No date filter is applied when `created_after`/`created_before` (or `eta_after`/`eta_before`) are omitted — the frontend's `DateRangeFilter` control defaults to "All time" and never silently scopes the list, since dev/prod tenants can have hundreds of containers.

**Ground-truth gap found live (2026-09-07):** the backend already accepted `created_before`, but `ContainerList.tsx` only ever sent `created_after` (from the preset), so an exact "on this one specific day" range was never reachable from the UI — found while auditing every page's "calendar" filter after the same dead-UI bug was fixed on `GET /v1/billing` (row 7.63). Added an exact custom From/To date pair next to the preset button, via the shared `useDateRangeFilter` hook (extracted from `ActivityLog.tsx`'s original hand-rolled preset+custom logic) — a custom date always overrides and clears the preset, and now correctly sends both `created_after` and `created_before`. No backend change needed here. Tests: `ContainerList.test.tsx` gained 1 case.

**Ground-truth gap found and fixed:** `list_containers()`'s `q` filter used to be folded into a blanket `f"c.{cond}"`-prefixed condition list alongside the simple `status`/`tenant_id` equality filters, producing invalid SQL (`c.(c.container_number ILIKE %(q)s OR ...)`) — every request with a non-empty `q` failed with a Postgres syntax error (`500`). This made the ContainerList table search box, and the app-wide TopBar header search box once wired up, non-functional. Fixed by appending the free-text clause separately (`q_clause`), matching the existing pattern in `services/packing_list/repository.py::list_packing_lists`. See `frontend/07_domain_modules.md` for the frontend-side fix (header search wiring, debounce, date-range control).

**Ground-truth gap found and fixed (row 7.37):** `status` used to accept only a single value, and the ContainerList frontend's grouped status chips (e.g. "Cleared" = `cleared` + `at_warehouse` + `fully_released`) only ever sent `activeStatuses[0]` to the API — clicking "Cleared" silently fetched just `status=cleared`, dropping `at_warehouse`/`fully_released` rows. Fixed on both ends: the backend now accepts a comma-separated list via `ANY(%(statuses)s)`, and the frontend sends the full joined list. The Table sort UI (`sortable: true` on the 'Container'/'ETA' columns) was also fully dead — `shared/pagination.py::build_paginated_query()` already supported `sort_field`/`sort_direction`, but no caller ever varied it from the hardcoded `"created_at"` default and no handler read a `sort` query param. `estimated_arrival_date` (the container table's actual ETA column) was missing from `ALLOWED_SORT_FIELDS` — the allowlist instead had `arrival_date`/`departure_date`/`total_amount_ngn`, none of which match any real column on any table in the schema (dead injection-surface entries, removed).

### Customer Tracking Lookup (GET /shipments/{tracking-code})
- No full auth required — tracking code + phone number verification
- Query: match tracking_code AND customer phone
- Return: current_stage, stage_history, estimated_stages (optional)
- Include tenant's company_name from branding config

**Ground-truth gap found and fixed (2026-11-02): the phone match was
unnormalised, so public tracking did not work for most customers.** The query
compared the submitted number against `customer.phone` as **one exact string**:

```sql
WHERE st.tracking_code = %s
  AND (c.phone = %s OR c.whatsapp = %s)
```

Customer phones are stored **E.164** (`shared/phone.py` normalises every write
path), so a customer entering their number the way they always write it —
`08012345678` — never matched their own stored `+2348012345678` and got a bare
404. The feature only worked if you happened to type the full `+234` form.

`service._phone_match_candidates()` now normalises the input and passes a **list**
of acceptable forms, matched with `= ANY(...)`. Both forms are offered because:
- the normalised value is what current rows hold, and
- the **raw** value still matters — rows written before normalisation existed may
  hold a local-format string, and a foreign number would be mangled by the
  default dial code.

No tenant is in scope at this point (a tracking code spans tenants), so the
platform default dial code (Nigeria) is used. Fixing it server-side rather than
only in the browser is deliberate: the endpoint is **public**, so saved links,
old clients and direct API callers would otherwise still silently fail. Tests:
`TestGetShipmentByCodeAndPhone` (+3).

### Bulk Tracking Update
When container status changes, all `shipment_tracking` records for that container are bulk-updated to the corresponding tracking stage (see mapping in spec §2.3).

## Container Event Audit Trail (GET /containers/{id}/events)

Every call to `PATCH /v1/containers/{id}/status` writes a row to `container_event` (append-only, no RLS — PLATFORM scope, migration 019). Response is an ordered list of status transitions.

Each event: `{ id, from_status, to_status, actor_id, notes, created_at }`

## Acceptance Criteria

- [x] Container CRUD with correct role authorization
- [x] Container state machine enforced (sequential, no skip/backward)
- [x] Role-based stage authorization (China vs Nigeria stages)
- [x] Bulk tracking update when container status changes
- [x] `customs_clearance → cleared` triggers billing calculation event
- [x] Customer tracking lookup works with tracking code + phone
- [x] `ShipmentStatusUpdated` events published for each stage change
- [x] Container search by container_number
- [x] Container status audit trail: every PATCH /containers/{id}/status writes to container_event; GET /containers/{id}/events returns ordered history (migration 019)
- [x] POST /containers/{id}/documents/presigned-url (`filename` sanitised via `safe_filename`, 2026-09-23 — see `00_CROSS_CUTTING_STANDARDS.md` §2.2): generates a cloud-neutral presigned **PUT** URL (2026-10-05; was S3 presigned-POST — see cloud-portability note in `09_api_manifest.md`), returning `{ upload_url, upload_method, upload_headers, document_id, s3_key, expires_in_seconds }`; creates container_document row (migration 022); supports 5 document types (bill_of_lading, customs_certificate, insurance, inspection_report, other)
- [x] GET /containers/{id}/documents: lists all uploaded documents for a container; service + handler wired to existing repo function
- [x] GET /containers/{id}/documents/{doc-id}/download: returns 5-min S3 presigned GET URL with Content-Disposition; validates tenant prefix on s3_key; 404 (never 403) for wrong-tenant/container; writes EXPORT audit record
- [x] `cleared → at_warehouse` enqueues `container_arrived` notification per customer across all three channels
- [x] `GET /v1/containers?created_after=&created_before=` date-range filter (opt-in, no default scope) — fixes ContainerList's "Last 30 days"/"Filters" controls; also fixed a pre-existing `q` filter SQL bug that 500'd every free-text container search
- [x] `GET /v1/containers?status=` accepts a comma-separated list (parameterized `ANY(...)`, never string-interpolated) — powers the Filters panel's granular multi-select across all 9 statuses; fixes a real bug where grouped chips only ever sent the first status in their group
- [x] `GET /v1/containers?eta_after=&eta_before=` — "Arriving" ETA-range filter, distinct from `created_after`/`created_before`
- [x] `GET /v1/containers?sort=&direction=` — `container_number`/`estimated_arrival_date`, wired to the ContainerList Table's `sortable: true` columns (previously dead UI — see `frontend/07_domain_modules.md`)

**Ground-truth gap found live, reported by the user (2026-09-09) while investigating a separate missing notification on payment-claim rejection — asked to check every notification in the app:** `shipment_update` had full SMS/WhatsApp/email templates defined but no call site ever used it. `update_container_status` now enqueues it for the customer-visible transitions `in_transit`/`arrived`/`customs_clearance`/`fully_released` (not `at_warehouse`, which already has its own richer `container_arrived` notification above; not `cleared`, which is covered by `handle_payment_due`'s own `payment_due` notification — see `11_api_billing.md` — since a bare "status changed" ping would be redundant with "here's what you owe"). Best-effort, including the customer lookup itself — a DB read failure fetching affected customers must not abort an already-committed status transition. Full account in `15_api_notifications.md`. Tests: `TestShipmentUpdateNotification` in `tests/unit/test_tracking.py`.

**Customer bell (2026-09-12):** both `container_arrived` and `shipment_update`'s customer notifications now also write an in-app row when the customer has a portal account, reusing the same `staff_notification` table as the staff bell (see `15_api_notifications.md`).
