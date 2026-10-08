"""Pydantic models for the Billing service."""

from datetime import datetime
from decimal import Decimal
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field

# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------


class PaymentStatus(StrEnum):
    unpaid = "unpaid"
    partially_paid = "partially_paid"
    paid = "paid"
    overpaid = "overpaid"
    waived = "waived"
    released_with_outstanding = "released_with_outstanding"
    cancelled = "cancelled"


class CBMDisputeStatus(StrEnum):
    submitted = "submitted"
    acknowledged = "acknowledged"
    investigating = "investigating"
    escalated_china = "escalated_china"
    resolved_adjusted = "resolved_adjusted"
    resolved_no_change = "resolved_no_change"
    closed = "closed"


# ---------------------------------------------------------------------------
# Request models
# ---------------------------------------------------------------------------


class CancelBillingRequest(BaseModel):
    cancel_reason: str = Field(min_length=1, max_length=500)


class ExemptCarryoverRequest(BaseModel):
    notes: str | None = Field(default=None, max_length=1000)


class FileCBMDisputeRequest(BaseModel):
    reason: str = Field(min_length=1)
    customer_measured_cbm: Decimal | None = Field(default=None, gt=Decimal("0"))


class ResolveCBMDisputeRequest(BaseModel):
    status: CBMDisputeStatus = Field(description="Must be resolved_adjusted or resolved_no_change")
    corrected_cbm: Decimal | None = Field(default=None, gt=Decimal("0"))
    resolution_notes: str = Field(min_length=1)


# ---------------------------------------------------------------------------
# Nested response models
# ---------------------------------------------------------------------------


class MiscFeeItem(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    description: str
    amount_ngn: Decimal


class PaymentRecord(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    amount_ngn: Decimal
    payment_method: str | None = None
    payment_reference: str | None = None
    confirmed_at: datetime


class CarryoverRecord(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    amount_ngn: Decimal
    source_billing_id: str
    created_at: datetime


# ---------------------------------------------------------------------------
# Response models
# ---------------------------------------------------------------------------


class CbmBreakdownItem(BaseModel):
    cbm: Decimal
    rate: Decimal
    subtotal: Decimal


class BillingResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    container_id: str
    container_number: str | None = None
    total_cbm: Decimal
    cbm_rate_usd: Decimal
    # cbm_rate_usd is always a USD-equivalent figure regardless of these —
    # cbm_rate_currency/cbm_rate_mode describe how the tenant actually
    # configured pricing at billing time, cbm_breakdown the per-package-type
    # (carton/bag/bale) detail in that currency (see shared/cbm_rate.py).
    cbm_rate_currency: str = "USD"
    cbm_rate_mode: str = "flat"
    cbm_breakdown: dict[str, CbmBreakdownItem] | None = None
    dollar_rate: Decimal
    subtotal_usd: Decimal
    subtotal_ngn: Decimal
    misc_fees: list[MiscFeeItem] = Field(default_factory=list)
    misc_fees_ngn: Decimal = Decimal("0")
    adjustments_ngn: Decimal = Decimal("0")
    carryover_ngn: Decimal = Decimal("0")
    storage_fees_ngn: Decimal = Decimal("0")
    total_due_ngn: Decimal
    total_paid_ngn: Decimal = Decimal("0")
    outstanding_ngn: Decimal
    payment_status: PaymentStatus
    released_with_outstanding: bool = False
    billed_at: datetime | None = None
    payments: list[PaymentRecord] = Field(default_factory=list)
    carryovers: list[CarryoverRecord] = Field(default_factory=list)


class CBMDisputeResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    billing_id: str
    original_cbm: Decimal
    corrected_cbm: Decimal | None = None
    status: CBMDisputeStatus
    submitted_at: datetime
