# Task 09 — API Service: Manifest Generation + Verification

## Objective

Implement the Manifest Lambda service: auto-generation from approved packing lists, verification workflow, discrepancy logging (missing items).

## Depends On

- Task 06 (shared layer), Task 08 (packing list approval creates manifests)

## Files: `services/manifest/handler.py`, `service.py`, `repository.py`, `models.py`

## Routes

| Method | Path | Roles |
|---|---|---|
| GET | `/v1/manifests` | china_office_staff, nigeria_office_staff, tenant_admin |
| GET | `/v1/manifests/{id}` | same |
| PATCH | `/v1/manifests/{id}/verify` | nigeria_office_staff, china_office_staff |
| PATCH | `/v1/manifests/{id}/resolve-discrepancy` | nigeria_office_staff, tenant_admin |
| PATCH | `/v1/manifests/{id}/revoke-verification` | china_office_staff, nigeria_office_staff, tenant_admin |
| POST | `/v1/manifests/{id}/evidence` | nigeria_office_staff, china_office_staff |
| GET | `/v1/manifests/stats` | china_office_staff, nigeria_office_staff, tenant_admin — per-status counts `{pending, verified, discrepancies_found, resolved, overdue}` for the §6.2 stats row (P2-4); `overdue` = pending manifests whose container has reached Nigeria (B11 predicate) |
| GET | `/v1/manifests/{id}/export` | china_office_staff, nigeria_office_staff, tenant_admin — manifest .xlsx/csv/pdf export; served by `services/excel/handler.py`, not this service. See `19_excel_import_export.md`. |
| POST | `/v1/manifests/import` | china_office_staff — imports a China-side freight-forwarder manifest .xlsx (flexible header matching; auto-creates container/customers/packing lists from it). Despite the `/v1/manifests/` path, this is served by `services/excel/handler.py` (Task 040), not this service — the `manifest` table/verification workflow below is untouched by it. Full spec: `19_excel_import_export.md` §"Manifest Import". |

**Note:** Manifests (the `manifest` table / verification workflow below) are auto-created when packing lists are approved (Task 08). The only POST against *this* service is the verification-evidence presigned-upload contract below — `POST /v1/manifests/import` above is a separate, `services/excel`-owned route that happens to share the `/v1/manifests/` path prefix.

### Verification evidence upload (POST /{id}/evidence) — §6.3, F-D3

Manifest-scoped presigned S3 upload for a verification photo/doc (mirrors the claims
evidence flow). Request body:
```json
{ "filename": "damage.jpg", "content_type": "image/jpeg", "label": "Damaged — Acme (SHX-00001)" }
```
- `content_type` must be one of `image/jpeg`, `image/png`, `application/pdf` (else 422 `INVALID_CONTENT_TYPE`); max 10 MB (enforced in the S3 POST policy).
- `label` (optional) is a human descriptor stored on the row — the frontend sets it from the discrepancy's customer + type + carton tags.
- Records a `manifest_evidence` row (migration 036) and returns `{ upload_url, fields, evidence_id, file_key }`. The browser then POSTs the file straight to S3 with `upload_url` + `fields`. The S3 key is `{tenant_id}/manifests/{manifest_id}/{filename}` (tenant isolation).

**Upload file names are sanitised (2026-09-23).** The client's `filename` is passed through `shared.validation.safe_filename()` before it is used in the S3 key or stored: directory components dropped, anything outside Unicode word characters / `. ( ) space -` replaced with `_`, no leading/trailing dots, ≤100 chars with the extension kept (Chinese names like `装箱单.xlsx` survive). A name that reduces to nothing is a `422`. The download `Content-Disposition` is sanitised again on read, since rows written earlier may hold an unsafe name. See `00_CROSS_CUTTING_STANDARDS.md` §2.2.

`GET /v1/manifests/{id}` returns an `evidence[]` array: `{ id, file_name, file_type, label, download_url, created_at }`, where `download_url` is a short-lived (1 h) presigned GET.

## Key Business Logic

### Get Manifest (GET /{id})
Return manifest with customer summary: for each customer with approved packing lists in this container, aggregate carton_count, total_weight_kg, total_cbm, carton_tags list.

### Verify Manifest (PATCH /verify)
1. Validate manifest exists, verification_status = 'pending'
2. If `verification_status = 'verified'`: mark verified, set verified_by, verified_at
3. If `verification_status = 'discrepancies_found'`:
   - For each discrepancy with type='missing': create `missing_item` record
   - For each discrepancy with type='damaged': these are noted but damage claims are filed separately
   - Set manifest to 'discrepancies_found'
4. Audit log the verification

### Resolve Discrepancy (PATCH /resolve-discrepancy)

Request body: `{ "resolution_notes": "string (required, max 1000 chars)", "final_counts": {"TAG-001": 1, ...} (optional) }`.

Transitions: `discrepancies_found → resolved` (migration 021 adds `resolved` to CHECK constraint).

Guards: manifest must be in `discrepancies_found` state; otherwise returns 422 `MANIFEST_NOT_DISCREPANCIES_FOUND`.

On success: updates manifest, writes audit log, returns updated manifest with customer summaries.

### Revoke Verification (PATCH /revoke-verification)

Transitions `verified → pending`, clearing `verified_by` and `verified_at` so the manifest can be re-verified.

Guards: manifest must be in `verified` state; returns 422 `MANIFEST_NOT_VERIFIED` otherwise. The `discrepancies_found` and `resolved` states cannot be reverted — only `verified` can.

On success: returns updated manifest with `verification_status = 'pending'` and customer summaries. Audit log entry is written.

**Wire note:** Both `GET /v1/manifests` and `GET /v1/manifests/{id}` now include `container_number` and `container_status` (joined from the `container` table). Previously they returned only `container_id`.

**Wire note (2026-10-03):** Both list and detail now also include `package_mix` — a JSONB map of package unit → total quantity for the container, e.g. `{ "carton": 120, "bale": 8, "bag": 30 }` (NULL when the manifest has no approved packing-list items). Computed live in `repository.py` via a LATERAL subquery over the manifest's **approved** packing lists (`_PACKAGE_MIX_LATERAL`, summing each item's `quantity` per `package_unit`; blank units fall under `unspecified`). This is more accurate than the stored, denormalised `total_cartons`, which counts item *rows* and so (a) can go stale between `recalculate_manifest_totals` runs and (b) under-reports mixed cargo — a container with 5 cartons + 4 bales stored `total_cartons = 5`, hiding the bales. The `ManifestList` table replaced its "Cartons" column with a **"Packages"** breakdown cell (`5 ctn · 4 bale`) and added a **Weight** column; `ManifestDetail` shows a "Packages" stat card (`9`, sub-label `5 ctn · 4 bale`). Frontend helper: `orderedPackageMix()` + `PACKAGE_UNIT_ORDER`/`ABBR` in `frontend/src/api/manifest.ts`.

**Revoke-verification guard — container must be `loading`.** `revoke_verification()` in `service.py` checks `manifest["container_status"]`. If the container has already advanced past `loading` (e.g., `sealed`, `in_transit`), the request is rejected with HTTP 422 `CONTAINER_ALREADY_ADVANCED`: `"Cannot revoke verification — the container is already '{status}'. Verification can only be revoked while the container is still in 'loading' status."` This prevents undoing a manifest verification after the physical container has departed.

### Implementation notes / ground-truth gaps found

**Both queries now include `container_number` and `container_status`.** `get_manifest_by_id()` and `list_manifests()` in `repository.py` JOIN `container` with `SELECT m.*, co.container_number, co.status AS container_status`. The list query uses a subquery wrapper pattern to avoid column ambiguity in `build_paginated_query`'s cursor condition (`AND id > ...` would be ambiguous with two tables both having `id`). `container_status` is needed by the revoke-verification guard and by the frontend's `canRevokeVerification()` rule.

**`new_status` key (not `status`) in PATCH /containers/{id}/status body.** The tracking handler reads `body.get("new_status", "")`. The frontend initially sent `{ status: "sealed" }` causing the error "Cannot transition container from 'loading' to ''" (empty string). Fixed by renaming `UpdateContainerStatusInput.status` to `new_status` in `tracking.ts`.

## Acceptance Criteria

- [x] Manifest aggregates data from all approved packing lists for a container
- [x] Verification creates missing_item records for discrepancies
- [x] Manifest totals recalculate correctly when new packing lists are approved
- [x] Filtering by container_id and verification_status
- [x] PATCH /manifests/{id}/resolve-discrepancy: transitions discrepancies_found → resolved; requires resolution_notes (migration 021)
- [x] Weight reconciliation: `GET /v1/manifests/{id}` and `PATCH .../verify` both return `weight_discrepancies` — items where `|actual − dispatch|` exceeds 5 % of dispatch weight or 0.1 kg (whichever is larger)


## Customer contact on list responses (2026-08-30)

`customer_phone` is returned alongside `customer_name` wherever a customer appears as a row:
`get_customer_summaries` (manifest customer table) and the packing-list detail/list queries
(`services/packing_list/repository.py`). The joins on `customer` already existed — only the name was
being selected.

The source manifest pairs **NAME** with **CONTACT** on every row for a reason: when cargo lands,
staff ring the customer. Requiring a click through to the customer record to get the number made the
operational tables less useful than the paper document they replace.
