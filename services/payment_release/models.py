"""Pydantic models for the Payment Release service."""

from datetime import date, datetime
from decimal import Decimal
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, model_validator

# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------


class ReleaseNoteStatus(StrEnum):
    active = "active"
    picked_up = "picked_up"
    expired = "expired"
    cancelled = "cancelled"


class DelegateIdType(StrEnum):
    national_id = "national_id"
    drivers_license = "drivers_license"
    passport = "passport"


# ---------------------------------------------------------------------------
# Request models
# ---------------------------------------------------------------------------


class ConfirmPaymentRequest(BaseModel):
    amount_ngn: Decimal = Field(gt=Decimal("0"))
    payment_method: str | None = None
    payment_reference: str | None = None
    payer_name: str | None = None
    payer_address: str | None = None
    bank_name: str | None = None
    cheque_number: str | None = None
    warehouse_id: str | None = None
    physical_receipt_number: str | None = None


class VerifyOnlinePaymentRequest(BaseModel):
    """Reconciles a Paystack payment directly against Paystack's own API —
    see services/payment_release/service.py::confirm_online_payment for why
    this exists (the webhook alone is not reliable enough, and can never
    reach a local dev URL at all)."""

    reference: str = Field(min_length=1)


class SubmitPaymentClaimRequest(BaseModel):
    """Customer's "I've made this payment" submission — evidence is mandatory,
    not optional, so a claim can never reach staff without proof attached."""

    amount_ngn: Decimal = Field(gt=Decimal("0"))
    evidence_file_key: str = Field(min_length=1)
    evidence_file_name: str = Field(min_length=1)
    customer_note: str | None = None


class RejectPaymentClaimRequest(BaseModel):
    reason: str = Field(min_length=1)


class GenerateReleaseNoteRequest(BaseModel):
    billing_id: str
    carton_tags: list[str] = Field(default_factory=list)
    packages_released: int | None = Field(default=None, gt=0)
    package_unit: str | None = None
    release_with_outstanding: bool = False
    approval_notes: str | None = None
    warehouse_id: str | None = None
    physical_document_number: str | None = None
    credit_granted_by_name: str | None = None
    due_date: date | None = None
    packing_list_invoice_numbers: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def _require_carton_tags_or_package_count(self) -> "GenerateReleaseNoteRequest":
        """Either carton_tags (per-carton, existing flow) or packages_released +
        package_unit (count-based, new flow) must be supplied — never neither.
        Both may be supplied (count-based releases against bulk-quantity
        manifest data, 7.41, that also happen to carry tags).
        """
        if not self.carton_tags and self.packages_released is None:
            raise ValueError("Either carton_tags or packages_released is required")
        if self.packages_released is not None and not self.package_unit:
            raise ValueError("package_unit is required when packages_released is supplied")
        return self


class RecordPickupRequest(BaseModel):
    cartons_released: int = Field(gt=0)
    carton_tags_picked: list[str] = Field(default_factory=list)
    is_delegate: bool = False
    collected_by_name: str | None = None
    delegate_name: str | None = None
    delegate_phone: str | None = None
    delegate_id_type: DelegateIdType | None = None
    delegate_id_number: str | None = None
    warehouse_id: str | None = None
    customer_service_officer_id: str | None = None
    accounting_officer_id: str | None = None
    warehouse_attendant_id: str | None = None
    notes: str | None = None

    @model_validator(mode="after")
    def _require_collector_name_for_non_delegate(self) -> "RecordPickupRequest":
        """Bug fix regression guard: when the customer collects in person
        (not via a delegate), collected_by_name must be supplied — previously
        nothing captured a collector name at all on the non-delegate path.
        """
        if not self.is_delegate and not self.collected_by_name:
            raise ValueError("collected_by_name is required when is_delegate is false")
        return self


class SplitReleaseNoteRequest(BaseModel):
    carton_tags: list[str] = Field(min_length=1)
    notes: str | None = None


class CreateWarehouseRequest(BaseModel):
    """A branch/office letterhead — the paper form this mirrors lists ~9 of
    these for one company; every tenant needs to be able to add its own,
    not just the single default migration 041 backfills."""

    name: str = Field(min_length=1, max_length=120)
    address: str | None = None
    city: str | None = None
    state: str | None = None
    phone: str | None = None
    # Promote this warehouse to the tenant's default as part of creating it.
    # The first warehouse becomes the default regardless (nothing else sets it,
    # and a tenant with no default cannot generate a release note); this lets a
    # later one be promoted in the same action instead of requiring a separate
    # "Set default" click the operator has to go and find.
    is_default: bool = False


class UpdateWarehouseRequest(BaseModel):
    """Partial edit of a warehouse's letterhead fields. Every field is optional;
    only those sent are patched (service uses exclude_unset). is_default is not
    editable here — promoting a default is the dedicated set-default route."""

    name: str | None = Field(default=None, min_length=1, max_length=120)
    address: str | None = None
    city: str | None = None
    state: str | None = None
    phone: str | None = None
    # Reactivating a retired warehouse. Deactivating goes through the dedicated
    # DELETE/deactivate path instead, which enforces the default-warehouse and
    # last-active guards that a bare PATCH would bypass.
    is_active: bool | None = None


# ---------------------------------------------------------------------------
# Response models
# ---------------------------------------------------------------------------


class PaymentConfirmationResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    payment_id: str
    billing_id: str
    amount_ngn: Decimal
    new_payment_status: str
    outstanding_ngn: Decimal
    release_note_available: bool = False
    confirmed_at: datetime
    receipt_number: str | None = None


class ReleaseNoteResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    reference_number: str
    customer_name: str | None = None
    container_number: str | None = None
    carton_count: int
    total_cartons_for_customer: int
    is_partial_release: bool = False
    carton_tags: list[str] = Field(default_factory=list)
    packages_released: int | None = None
    package_unit: str | None = None
    packages_balance: int | None = None
    payment_status: str
    status: ReleaseNoteStatus
    authorized_at: datetime
    warehouse_address: str | None = None
    warehouse_name: str | None = None
    warehouse_phone: str | None = None
    is_on_credit: bool = False
    credit_granted_by_name: str | None = None
    receipt_number: str | None = None
    physical_document_number: str | None = None
    packing_list_invoice_numbers: list[str] = Field(default_factory=list)
    amount_paid_ngn: Decimal | None = None
    balance_ngn: Decimal | None = None
    total_ngn: Decimal | None = None
    debt_due_date: date | None = None


class PickupRecordResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    release_note_id: str
    release_note_status: ReleaseNoteStatus
    pickup_record_id: str
    pickup_date: date
    pickup_time: str | None = None
    attendant_name: str | None = None
    customer_service_officer_name: str | None = None
    accounting_officer_name: str | None = None
    collected_by_name: str | None = None
    delegate_phone: str | None = None
    remaining_cartons: int = 0
    shipment_status: str | None = None


class WarehouseResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    name: str
    address: str | None = None
    city: str | None = None
    state: str | None = None
    phone: str | None = None
    is_default: bool = False
