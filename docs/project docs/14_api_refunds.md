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

### Staff Approval Threshold (BR-RF-005)
When the approver is `nigeria_office_staff`, `approve_refund` reads `refund_threshold_usd.staff_limit` (default 50) and `dollar_rate.rate` (default 1550) from `tenant_config` via `repo.get_refund_threshold_config`. If `amount_approved_ngn > staff_limit × rate`, an `ApprovalThresholdExceededError` (`APPROVAL_THRESHOLD_EXCEEDED`, **HTTP 403**) is raised — the staff member must escalate to `tenant_admin`.

The 403 body includes structured `threshold_details`:
```json
{
  "error_code": "APPROVAL_THRESHOLD_EXCEEDED",
  "threshold_details": {
    "staff_limit_usd": 50,
    "staff_limit_ngn": 77500,
    "dollar_rate": 1550,
    "amount_ngn": 120000
  }
}
```

`GET /v1/refunds/{id}` includes a `threshold` object in the response (populated from the same tenant config) so the frontend can pre-render the approval limit meter without waiting for a 403:
```json
{
  "threshold": {
    "staff_limit_usd": 50,
    "staff_limit_ngn": 77500,
    "dollar_rate": 1550,
    "exceeds_staff_limit": true
  }
}
```
`threshold` is `null` if the config read fails.

Falls back silently if the config read fails (infra error), so the threshold is enforced best-effort. This does not bypass the role-level authority checks in BR-RF-003 (both checks apply independently).

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

## Ground-truth gap found (2026-09-06): claim-triggered refunds had no refund_type

`services/claims/repository.py::create_refund_request_for_claim()` — the only
path that creates a `refund_request` from a resolved damage claim — never set
`refund_type`, though migration 009's CHECK constraint added `damage_or_loss`
specifically for this case. Every such refund had `refund_type` `NULL`, and
the frontend's `refundTypeLabel()` had no fallback for an unmapped value —
`RefundDetail.tsx`'s page `<h1>` silently rendered blank. Found live running
the real customer-claim → staff-resolve → refund chain end to end, not from
inspecting this file directly — see `12_api_claims.md`'s matching entry for
the full account. Fixed at the source (the INSERT now sets
`'damage_or_loss'`) and defensively in the frontend label function.

## Acceptance Criteria

- [x] All 3 refund types handled (`overpayment`, `cbm_correction`, `damage_or_loss`)
- [x] Accounts review with debt offset logic (`debt_check_passed`, `debt_check_notes`)
- [x] Approval authority enforced by role and amount (`manager` / `head_of_finance`)
- [x] Staff approval threshold enforced: `nigeria_office_staff` capped at `refund_threshold_usd.staff_limit × dollar_rate` NGN (BR-RF-005); raises `ApprovalThresholdExceededError` (HTTP 403, `APPROVAL_THRESHOLD_EXCEEDED`) with structured `threshold_details` on breach
- [x] `GET /v1/refunds/{id}` includes `threshold` object for frontend pre-computation of approval limit meter
- [x] Billing adjustments recalculate correctly
- [x] Credit-next-shipment tracked (`applied_as_credit` status)
- [x] Events: RefundApproved
