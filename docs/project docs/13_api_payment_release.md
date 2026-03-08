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
| POST | `/v1/release-notes` | tenant_admin, nigeria_office_staff |
| GET | `/v1/release-notes/{id}` | tenant_admin, nigeria_office_staff, warehouse_attendant, customer (own) |
| PATCH | `/v1/release-notes/{id}/release` | warehouse_attendant |

## Payment Confirmation (POST /payments/{billing-id}/confirm)

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
3. Insert `release_note` record (status = 'active')
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

## Release Note States

```
active → picked_up (warehouse confirms)
       → expired (scheduled job, if expires_at set)
       → cancelled (staff cancels)
```

## Schema Notes (Migration 008)

| Column | Change |
|---|---|
| `release_note.status` | Values: `active/picked_up/expired/cancelled` (default: `active`) |
| `shipment_tracking.status` | Added `picked_up` to existing statuses |
| `payment_record.payment_method` | Made nullable (method may be recorded separately) |
| `pickup_record.collected_by_name` | Made nullable (delegate flow may populate differently) |

## Acceptance Criteria

- [x] Payment updates billing totals and status correctly (`unpaid/partially_paid/paid/overpaid`)
- [x] Overpayment auto-creates refund request
- [x] Release blocked without payment (returns 422 PAYMENT_REQUIRED)
- [x] Partial release proportional payment calculation
- [x] Release with outstanding creates carryover_ledger entry and sets `billing.released_with_outstanding = true`
- [x] Reference number auto-generated with tenant prefix
- [x] Pickup records delegate details captured (`collected_by_name` nullable)
- [x] Shipment tracking updated to `picked_up` when all customer cartons released
- [x] Container status auto-updated to `fully_released` when all customers done
- [x] Events: PaymentConfirmed, ReleaseNoteGenerated
