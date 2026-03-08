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

**Note:** Manifests are auto-created when packing lists are approved (Task 08). No manual POST.

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

## Acceptance Criteria

- [x] Manifest aggregates data from all approved packing lists for a container
- [x] Verification creates missing_item records for discrepancies
- [x] Manifest totals recalculate correctly when new packing lists are approved
- [x] Filtering by container_id and verification_status
