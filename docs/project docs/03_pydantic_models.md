# Task 03 — Pydantic Models & Validation (All Entities)

## Objective

Define all Pydantic v2 models for request validation, response serialization, and internal domain objects across every service. These models are the single source of truth for data shapes.

## Depends On

- Task 01 (project structure)

## Conventions

- All models inherit from a `TenantScopedBase` that includes `tenant_id`
- Request models use `*Request` suffix; response models use `*Response`
- UUID fields use `str` type (not `uuid.UUID`) for JSON serialization simplicity
- Dates use `datetime` or `date` from stdlib; serialized as ISO 8601
- All monetary fields use `Decimal` with explicit precision
- Enums for all status/state fields

## Deliverables

### File: `shared/models.py` — Base Models

```python
from datetime import datetime
from decimal import Decimal
from pydantic import BaseModel, Field, ConfigDict

class TenantScopedBase(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    tenant_id: str

class TimestampMixin(BaseModel):
    created_at: datetime
    updated_at: datetime | None = None

class PaginationMeta(BaseModel):
    cursor: str | None = None
    has_more: bool = False
    total_count: int | None = None
```

### File: `services/tenant_management/models.py`

**Enums:**
- `SubscriptionTier`: starter, business, enterprise
- `TenantStatus`: active, suspended, offboarded
- `TenantUserRole`: tenant_admin, china_office_staff, nigeria_office_staff, warehouse_attendant, customer
- `TenantUserStatus`: active, deactivated

**Request Models:**
- `CreateTenantRequest`: company_name, primary_contact_email, primary_contact_phone?, origin_country (default "China"), destination_country (default "Nigeria"), subscription_tier, initial_admin: { email, full_name }
- `UpdateTenantRequest`: company_name?, primary_contact_email?, subscription_tier?, branding_config?, notification_preferences?
- `SuspendTenantRequest`: reason (required)
- `CreateTenantUserRequest`: email, full_name, role (TenantUserRole)
- `UpdateTenantConfigRequest`: branding?, notification_preferences?
- `UpdateDollarRateRequest`: rate (Decimal), currency_pair (default "USD_NGN")

**Response Models:**
- `TenantResponse`: id, company_name, primary_contact_email, subscription_tier, status, created_at
- `TenantDetailResponse`: extends TenantResponse + branding_config, notification_preferences, metrics
- `TenantUserResponse`: id, email, full_name, role, status, cognito_sub, created_at
- `TenantUsageResponse`: tenant_id, period, subscription_tier, limits (nested), api_calls, notifications (nested)
- `DollarRateResponse`: rate, currency_pair, effective_from, previous_rate

### File: `services/packing_list/models.py`

**Enums:**
- `PackingListStatus`: draft, pending_approval, approved, rejected

**Request Models:**
- `CreatePackingListRequest`: container_id, customer_id, items: list[PackingListItemInput]
- `PackingListItemInput`: description, weight_dispatch_kg?, weight_actual_kg?, length_cm?, width_cm?, height_cm?, received_date?
- `UpdatePackingListRequest`: items: list[UpdatePackingListItemInput] (allows adding/modifying items)
- `ApprovePackingListRequest`: comments?
- `RejectPackingListRequest`: comments (required), item_rejections?: list[{ item_id, reason }]

**Response Models:**
- `PackingListResponse`: id, container_id, customer_id, customer_name, status, items: list[PackingListItemResponse], total_cbm, total_weight_kg, carton_count, created_at
- `PackingListItemResponse`: id, description, weight_dispatch_kg, weight_actual_kg, carton_tag, tracking_code, cbm, length_cm, width_cm, height_cm, received_date

**Auto-generated fields (not in request, computed by service):**
- `carton_tag`: format `{tenant_short_code}-{container_number}-{zero_padded_sequence}`
- `tracking_code`: format `{tenant_short_code}-TRK-{YYYYMMDD}-{sequence}`
- `cbm`: `(length_cm × width_cm × height_cm) / 1_000_000`

### File: `services/manifest/models.py`

**Enums:**
- `VerificationStatus`: pending, verified, discrepancies_found

**Request Models:**
- `VerifyManifestRequest`: verification_status, discrepancies?: list[{ customer_id, carton_tags, type: "missing"|"damaged", notes }]

**Response Models:**
- `ManifestResponse`: id, container_id, container_number, total_customers, total_cartons, total_weight_kg, total_cbm, verification_status, customers: list[ManifestCustomerSummary], created_at
- `ManifestCustomerSummary`: customer_id, customer_name, packing_list_id, carton_count, total_weight_kg, total_cbm, carton_tags

### File: `services/tracking/models.py`

**Enums:**
- `TrackingStage`: received_china, packed, in_transit, arrived_nigeria, customs_clearance, cleared, ready_for_pickup, picked_up

**Request Models:**
- `UpdateShipmentStatusRequest`: stage (TrackingStage), notes?

**Response Models:**
- `TrackingResponse`: tracking_code, current_stage, company_name, stage_history: list[StageEvent], estimated_stages?: list[EstimatedStage]
- `StageEvent`: stage, occurred_at, notes?
- `EstimatedStage`: stage, estimated (date)

### File: `services/billing/models.py`

**Enums:**
- `PaymentStatus`: unpaid, partially_paid, paid, overpaid, waived, released_with_outstanding
- `CBMDisputeStatus`: submitted, acknowledged, investigating, escalated_china, resolved_adjusted, resolved_no_change, closed

**Request Models:**
- `FileCBMDisputeRequest`: reason (required), customer_measured_cbm?
- `ResolveCBMDisputeRequest`: status (resolved_adjusted | resolved_no_change), corrected_cbm? (required if adjusted), resolution_notes (required)

**Response Models:**
- `BillingResponse`: id, container_id, container_number, total_cbm, cbm_rate_usd, dollar_rate, subtotal_usd, subtotal_ngn, misc_fees: list, misc_fees_ngn, adjustments_ngn, carryover_ngn, storage_fees_ngn, total_due_ngn, total_paid_ngn, outstanding_ngn, payment_status, released_with_outstanding, billed_at, payments: list, carryovers: list
- `CBMDisputeResponse`: id, billing_id, original_cbm, corrected_cbm?, status, submitted_at

### File: `services/claims/models.py`

**Enums:**
- `DamageClaimStatus`: filed, under_inspection, inspection_complete, pending_resolution, resolved, closed
- `InspectionMethod`: delegate_visit, customer_evidence
- `ResolutionType`: refund, discount, no_action
- `ApprovalLevel`: nigeria_staff, tenant_admin, head_of_finance
- `MissingItemStatus`: reported, investigating, found_and_shipping, confirmed_lost, resolved
- `SeizedItemStatus`: seized, recovery_in_progress, recovered, permanently_lost

**Request Models:**
- `FileDamageClaimRequest`: container_id, cartons_affected: list[str], description
- `StartInspectionRequest`: inspection_method (InspectionMethod)
- `ResolveClaimRequest`: resolution_type, amount_usd?, amount_ngn?, discount_percentage?, reason (max 2,000 characters; **required, non-blank, when `resolution_type` is `no_action`**, validated by a model validator, because the customer is shown it)
- `LogMissingItemRequest`: manifest_id, customer_id, carton_tags: list[str], description
- `LogSeizedItemRequest`: container_id, customer_id, carton_tags: list[str], reason

**Response Models:**
- `DamageClaimResponse`: id, status, cartons_affected, upload_urls?, created_at
- `ClaimResolutionResponse`: resolution_type, amount_usd?, amount_ngn?, approval_level, refund_request_id?

### File: `services/payment_release/models.py`

**Enums:**
- `ReleaseNoteStatus`: active, picked_up, expired, cancelled
- `DelegateIdType`: national_id, drivers_license, passport

**Request Models:**
- `ConfirmPaymentRequest`: amount_ngn (Decimal), payment_method?, payment_reference?
- `GenerateReleaseNoteRequest`: billing_id, carton_tags: list[str], release_with_outstanding: bool = False, approval_notes? (required if release_with_outstanding)
- `RecordPickupRequest`: cartons_released (int), is_delegate: bool = False, collected_by_name? (required when not a delegate), delegate_name?, delegate_phone?, delegate_id_type?, delegate_id_number?, notes?, pickup_code? (max 20; checked only for a release note that carries a code, UX-09)

**Response Models:**
- `PaymentConfirmationResponse`: payment_id, billing_id, amount_ngn, new_payment_status, outstanding_ngn, release_note_available, confirmed_at
- `ReleaseNoteResponse`: id, reference_number, customer_name, container_number, carton_count, total_cartons_for_customer, is_partial_release, carton_tags, payment_status, status, authorized_at, warehouse_address
- `PickupRecordResponse`: release_note_id, release_note_status, pickup_record_id, pickup_date, pickup_time, attendant_name, remaining_cartons, shipment_status

### File: `services/refunds/models.py`

**Enums:**
- `RefundType`: overpayment, cbm_correction, damage_or_loss
- `RefundStatus`: pending_review, accounts_reviewed, pending_approval, approved, rejected, processed, applied_as_credit
- `CustomerChoice`: immediate_refund, credit_next_shipment

**Request Models:**
- `CreateRefundRequest`: customer_id, billing_id?, damage_claim_id?, refund_type, amount_requested_ngn, customer_choice?, notes?
- `AccountsReviewRequest`: debt_check_passed (bool), debt_check_notes (required)
- `ApproveRefundRequest`: amount_approved_ngn, approval_level

**Response Models:**
- `RefundRequestResponse`: id, status, refund_type, amount_requested_ngn, amount_approved_ngn?, customer_choice, created_at

### File: `services/notification/models.py`

- `NotificationChannel`: sms, whatsapp, email
- `NotificationEvent`: shipment_update, payment_due, release_note_generated, cbm_dispute_update, damage_claim_update, packing_list_approved, tenant_onboarded, tenant_suspended
- `SendNotificationRequest`: event_type, recipient_phone?, recipient_email?, template_data: dict, tenant_id

### File: `services/metering/models.py`

- `MetricType`: api_calls, containers_processed, storage_bytes, users_active, sms_sent, whatsapp_sent, emails_sent
- `TierLimits`: users (int), containers_per_month (int), storage_gb (float)
- `UsageRecordResponse`: tenant_id, metric_type, value, period_start, period_end

## Acceptance Criteria

- [x] All enums match exactly the CHECK constraints in the database DDL
- [x] All request models have proper Pydantic validators (e.g., positive numbers, non-empty strings)
- [x] CBM auto-calculation in `PackingListItemInput` (`services/packing_list/models.py`) — note it divides by `Decimal("1000000")`, not the literal `1_000_000`, so a grep for the underscored form finds nothing (verified 2026-11-11).
- [x] Monetary fields use `Decimal` with `ge=0` where appropriate
- [x] All response models have `model_config = ConfigDict(from_attributes=True)` for ORM compatibility
- [x] Carton tag and tracking code format patterns are validated via regex where used as input

## `PackingListItemInput` — quantity & declared value (2026-11-12; updated 2026-11-25, PR #174)

```python
quantity: int = Field(default=1, ge=1)
identical_confirmed: bool = False
batch_ref: str | None = None
```

- **2026-11-25 (PR #174):** `MAX_ITEM_QUANTITY = 500` was removed — `quantity` has no artificial upper cap (`ge=1`) because the packing-list service enforces container CBM capacity (`CONTAINER_CAPACITY_EXCEEDED`) directly.
- Each line item is stored as a **single row with a single `carton_tag`** carrying `quantity = N` and line-total `cbm`/weights (no row expansion). `declared_value_usd` is stored **per unit**.
- `identical_confirmed` remains validated by the model whenever `quantity > 1`. See `08_api_packing_list.md`.

## Platform admin models (2026-11-28, platform audit Phase 0)

`services/tenant_management/models.py`:
- `OffboardTenantRequest` — `reason: str` (1–2000 characters; a blank reason is refused). The body of `DELETE /v1/platform/tenants/{id}`, stored on the `TENANT_OFFBOARDED` audit row (PA-04).
- `TenantListQuery` — `status: TenantStatus | None`, `tier: SubscriptionTier | None`, `q: str | None` (≤ 200; blank becomes `None`). The filters of `GET /v1/platform/tenants` (PA-02).
