"""Pydantic models for the Payment Release service."""

from datetime import date, datetime
from decimal import Decimal
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field

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


class GenerateReleaseNoteRequest(BaseModel):
    billing_id: str
    carton_tags: list[str] = Field(min_length=1)
    release_with_outstanding: bool = False
    approval_notes: str | None = None


class RecordPickupRequest(BaseModel):
    cartons_released: int = Field(gt=0)
    is_delegate: bool = False
    delegate_name: str | None = None
    delegate_phone: str | None = None
    delegate_id_type: DelegateIdType | None = None
    delegate_id_number: str | None = None
    notes: str | None = None


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
    payment_status: str
    status: ReleaseNoteStatus
    authorized_at: datetime
    warehouse_address: str | None = None


class PickupRecordResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    release_note_id: str
    release_note_status: ReleaseNoteStatus
    pickup_record_id: str
    pickup_date: date
    pickup_time: str | None = None
    attendant_name: str | None = None
    remaining_cartons: int = 0
    shipment_status: str | None = None
