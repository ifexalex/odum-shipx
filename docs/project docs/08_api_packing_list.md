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
