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
| GET | `/v1/claims` | nigeria_office_staff, tenant_admin, customer (own) |
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
1. Validate claim_id exists in tenant scope
2. Generate S3 presigned POST URL:
   - Key: `{tenant_id}/claims/{claim_id}/{filename}`
   - Expires in 1 hour
   - Max file size: 10MB
   - Allowed content types: image/jpeg, image/png, application/pdf
3. Insert `claim_evidence` record
4. Return upload URL + fields

### Missing Items (POST /claims/missing-items)
- Create `missing_item` record linked to manifest
- `carton_tags TEXT[]` — array of carton tag identifiers (added migration 007)
- Status: `reported → investigating → found_and_shipping / confirmed_lost → resolved`

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
- [x] Events published: DamageClaimFiled, DamageClaimResolved
- [x] Customer can only file and view own claims
