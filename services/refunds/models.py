"""Pydantic models for the Refunds service."""

from datetime import datetime
from decimal import Decimal
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, model_validator

# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------


class RefundType(StrEnum):
    overpayment = "overpayment"
    cbm_correction = "cbm_correction"
    damage_or_loss = "damage_or_loss"
    missing_item = "missing_item"
    seized_item = "seized_item"


class RefundStatus(StrEnum):
    pending_review = "pending_review"
    accounts_reviewed = "accounts_reviewed"
    pending_approval = "pending_approval"
    approved = "approved"
    rejected = "rejected"
    processed = "processed"
    applied_as_credit = "applied_as_credit"


class CustomerChoice(StrEnum):
    immediate_refund = "immediate_refund"
    credit_next_shipment = "credit_next_shipment"


# ---------------------------------------------------------------------------
# Request models
# ---------------------------------------------------------------------------


class CreateRefundRequest(BaseModel):
    """A refund request. A refund to a bank account carries the account it is paid into.

    ``account_number`` and ``account_name`` are PII: stored encrypted (``shared.encryption``), never logged, and
    masked in the audit log. A credit for the next shipment pays nothing out, so it takes no bank details (they are
    refused rather than stored for no purpose).
    """

    model_config = ConfigDict(str_strip_whitespace=True)

    customer_id: str
    billing_id: str | None = None
    damage_claim_id: str | None = None
    refund_type: RefundType
    amount_requested_ngn: Decimal = Field(gt=Decimal("0"))
    customer_choice: CustomerChoice | None = None
    notes: str | None = None
    bank_name: str | None = Field(default=None, min_length=2, max_length=100)
    #: A Nigerian bank account number (NUBAN) is 10 digits.
    account_number: str | None = Field(default=None, pattern=r"^\d{10}$")
    account_name: str | None = Field(default=None, min_length=2, max_length=255)

    @model_validator(mode="after")
    def _bank_details_match_the_choice(self) -> "CreateRefundRequest":
        details = (self.bank_name, self.account_number, self.account_name)
        if self.customer_choice == CustomerChoice.immediate_refund and not all(details):
            raise ValueError("A refund to a bank account needs bank_name, account_number and account_name.")
        if self.customer_choice != CustomerChoice.immediate_refund and any(details):
            raise ValueError("Bank details are only taken for a refund to a bank account.")
        return self


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
