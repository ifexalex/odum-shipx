# Task 14 — API Service: Refund Requests + Approval Workflow

## Objective

Implement the Refund Lambda service: refund request creation (overpayment, CBM correction, damage/loss), accounts review with debt check, tiered approval, and credit application.

## Depends On

- Task 06, Task 11 (billing), Task 12 (claims create refund requests)

## Files: `services/refunds/handler.py`, `service.py`, `repository.py`, `models.py`

## Routes

| Method | Path | Roles |
|---|---|---|
| POST | `/v1/refunds` | system (auto), nigeria_office_staff |
| GET | `/v1/refunds` | tenant_admin, nigeria_office_staff |
| GET | `/v1/refunds/{id}` | tenant_admin, nigeria_office_staff, customer (own) |
| PATCH | `/v1/refunds/{id}/review` | nigeria_office_staff (accounts team) |
| PATCH | `/v1/refunds/{id}/approve` | tenant_admin, nigeria_office_staff |
| PATCH | `/v1/refunds/{id}/reject` | tenant_admin, nigeria_office_staff |

## State Machine

```
pending_review → accounts_reviewed → pending_approval → approved → processed (immediate)
                                                                → applied_as_credit (next shipment)
                                                      → rejected
               → rejected (debt check failed)
```

## Key Business Logic

### Refund Types (BR-RF-001)
Stored in `refund_request.refund_type` (migration 009):
1. **`overpayment`**: `billing.outstanding_ngn < 0`. Customer chooses immediate refund or credit.
2. **`cbm_correction`**: Auto-created when CBM dispute resolved with adjustment.
3. **`damage_or_loss`**: Created when claim resolved with `refund` resolution type, linked via `damage_claim_id`.

### Accounts Review (BR-RF-002)
1. Check customer debt records: query carryover_ledger (outstanding), billing (unpaid)
2. If debts exist:
   - Option: offset refund against outstanding debt
   - If debt > refund → apply refund to debt, set debt_check_passed = false
   - If debt < refund → clear debt, refund remainder
3. If no debts: debt_check_passed = true → auto-advance to pending_approval

### Approval Authority (BR-RF-003)
`approval_level` values (migration 009): `manager`, `head_of_finance` (nullable)
- Overpayment: `manager` approval
- CBM correction: `head_of_finance`
- Damage/loss ≤ $50: Already approved via claim resolution (auto-advance to approved)
- Damage/loss > $50: `head_of_finance`

`amount_approved_ngn` (migration 009) records the final approved payout amount.

### Invoice Adjustment (BR-RF-004)
`customer_choice` values (migration 009): `immediate_refund`, `credit_next_shipment`

On approval with `customer_choice = 'immediate_refund'`:
1. Update `billing.adjustments_ngn` (subtract refund amount)
2. Recalculate billing totals
3. If customer already overpaid → create new overpayment refund_request
4. Status transitions to `processed`

On `customer_choice = 'credit_next_shipment'`:
1. Status transitions to `applied_as_credit`
2. When next billing is generated (Task 11), it reads approved credits and applies them

## Schema Notes (Migration 009)

| Column | Change |
|---|---|
| `refund_request.status` | New values: `pending_review/accounts_reviewed/pending_approval/approved/rejected/processed/applied_as_credit` |
| `refund_request.customer_choice` | New values: `immediate_refund/credit_next_shipment` |
| `refund_request.approval_level` | New values: `manager/head_of_finance` (nullable) |
| `refund_request.refund_type` | New: `overpayment/cbm_correction/damage_or_loss` |
| `refund_request.amount_approved_ngn` | New: `DECIMAL(15,2)` — approved payout |
| `refund_request.damage_claim_id` | New: UUID FK → `damage_claim` |
| `refund_request.debt_check_passed` | New: `BOOLEAN` |
| `refund_request.debt_check_notes` | New: `TEXT` |

## Acceptance Criteria

- [x] All 3 refund types handled (`overpayment`, `cbm_correction`, `damage_or_loss`)
- [x] Accounts review with debt offset logic (`debt_check_passed`, `debt_check_notes`)
- [x] Approval authority enforced by role and amount (`manager` / `head_of_finance`)
- [x] Billing adjustments recalculate correctly
- [x] Credit-next-shipment tracked (`applied_as_credit` status)
- [x] Events: RefundApproved
