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
| `cleared → at_warehouse` | Bulk-update tracking to 'ready_for_pickup'; publish payment notifications |
| `at_warehouse → fully_released` | System-triggered when all release notes are 'picked_up' |

**ILLEGAL:** Any backward or skip transition → return 409

### Customer Tracking Lookup (GET /shipments/{tracking-code})
- No full auth required — tracking code + phone number verification
- Query: match tracking_code AND customer phone
- Return: current_stage, stage_history, estimated_stages (optional)
- Include tenant's company_name from branding config

### Bulk Tracking Update
When container status changes, all `shipment_tracking` records for that container are bulk-updated to the corresponding tracking stage (see mapping in spec §2.3).

## Acceptance Criteria

- [x] Container CRUD with correct role authorization
- [x] Container state machine enforced (sequential, no skip/backward)
- [x] Role-based stage authorization (China vs Nigeria stages)
- [x] Bulk tracking update when container status changes
- [x] `customs_clearance → cleared` triggers billing calculation event
- [x] Customer tracking lookup works with tracking code + phone
- [x] `ShipmentStatusUpdated` events published for each stage change
- [x] Container search by container_number
