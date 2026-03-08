"""Pydantic models for the Refunds service."""

from datetime import datetime
from decimal import Decimal
from enum import Enum

from pydantic import BaseModel, ConfigDict, Field


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------


class RefundType(str, Enum):
    overpayment = "overpayment"
    cbm_correction = "cbm_correction"
    damage_or_loss = "damage_or_loss"


class RefundStatus(str, Enum):
    pending_review = "pending_review"
    accounts_reviewed = "accounts_reviewed"
    pending_approval = "pending_approval"
    approved = "approved"
    rejected = "rejected"
    processed = "processed"
    applied_as_credit = "applied_as_credit"


class CustomerChoice(str, Enum):
    immediate_refund = "immediate_refund"
    credit_next_shipment = "credit_next_shipment"


# ---------------------------------------------------------------------------
# Request models
# ---------------------------------------------------------------------------


class CreateRefundRequest(BaseModel):
    customer_id: str
    billing_id: str | None = None
    damage_claim_id: str | None = None
    refund_type: RefundType
    amount_requested_ngn: Decimal = Field(gt=Decimal("0"))
    customer_choice: CustomerChoice | None = None
    notes: str | None = None


class AccountsReviewRequest(BaseModel):
    debt_check_passed: bool
    debt_check_notes: str = Field(min_length=1)


class ApproveRefundRequest(BaseModel):
    amount_approved_ngn: Decimal = Field(gt=Decimal("0"))
    approval_level: str = Field(min_length=1)


# ---------------------------------------------------------------------------
# Response models
# ---------------------------------------------------------------------------


class RefundRequestResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    status: RefundStatus
    refund_type: RefundType
    amount_requested_ngn: Decimal
    amount_approved_ngn: Decimal | None = None
    customer_choice: CustomerChoice | None = None
    created_at: datetime
