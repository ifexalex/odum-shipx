# Task 11 — API Service: Billing Calculation + CBM Disputes

## Objective

Implement the Billing Lambda service: auto-billing on customs clearance, CBM-based pricing, misc charges, carryover application, CBM dispute lifecycle.

## Depends On

- Task 06 (shared layer)

## Files: `services/billing/handler.py`, `service.py`, `repository.py`, `models.py`

## Routes

| Method | Path | Roles |
|---|---|---|
| GET | `/v1/billing/{customer-id}` | tenant_admin, nigeria_office_staff, customer (own only) |
| POST | `/v1/billing/{id}/dispute` | customer |
| GET | `/v1/billing/{id}/disputes` | nigeria_office_staff, tenant_admin, customer (own) |
| PATCH | `/v1/billing/disputes/{id}/acknowledge` | nigeria_office_staff |
| PATCH | `/v1/billing/disputes/{id}/resolve` | nigeria_office_staff, china_office_staff, tenant_admin |
| POST | `/v1/billing/disputes` | nigeria_office_staff, tenant_admin (staff-created disputes) |
| PATCH | `/v1/billing/disputes/{id}/reject` | nigeria_office_staff, tenant_admin |

## Billing Calculation (Rule BR-BL-001)

Triggered when container status → `cleared`. For **each customer** in the container:

1. Sum CBM from all `packing_list_item` rows (via approved packing lists for this customer+container)
2. Fetch `cbm_rate_usd` from `tenant_config` key `'cbm_rate_per_unit'`
3. Fetch `dollar_rate` from `tenant_config` key `'dollar_rate'`
4. Calculate:
   ```
   subtotal_usd = total_cbm × cbm_rate_usd
   subtotal_ngn = subtotal_usd × dollar_rate
   ```
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

**Key rules:**
- Acknowledgement must happen within 24h (SLA tracked)
- `investigating → escalated_china`: auto after N days (tenant_config `dispute_escalation.auto_escalate_days`) or manual
- `resolved_adjusted`: corrected_cbm must differ from original; recalculates billing
- `resolved_no_change`: must provide resolution_notes

### Billing Recalculation on Dispute Resolution
When `resolved_adjusted`:
1. Update `billing.total_cbm` = dispute.corrected_cbm
2. Recalculate: subtotal_usd, subtotal_ngn, total_due_usd, total_due_ngn, outstanding_ngn
3. Publish `CBMDisputeResolved` event
4. If customer already paid and new total < paid → create overpayment refund_request

## GET /billing/{customer-id} Response

Include nested data: payments list, carryovers list, misc_fees list, active disputes. Filter by `?container_id=`.

## Acceptance Criteria

- [x] Billing auto-calculated on `cleared` container status
- [x] CBM summed correctly from packing list items
- [x] Carryover balances applied from carryover_ledger
- [x] Credits from approved refunds applied
- [x] CBM dispute full lifecycle with 8 states (including `rejected`)
- [x] Billing recalculated on dispute adjustment
- [x] `PaymentDue` and `CBMDisputeResolved` events published
- [x] Customer sees only own billing records
