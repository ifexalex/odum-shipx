"""Pydantic models for the Claims service."""

from datetime import datetime
from decimal import Decimal
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field

# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------


class DamageClaimStatus(StrEnum):
    filed = "filed"
    under_inspection = "under_inspection"
    inspection_complete = "inspection_complete"
    pending_resolution = "pending_resolution"
    resolved = "resolved"
    closed = "closed"


class InspectionMethod(StrEnum):
    delegate_visit = "delegate_visit"
    customer_evidence = "customer_evidence"


class ResolutionType(StrEnum):
    refund = "refund"
    discount = "discount"
    no_action = "no_action"
    compensation = "compensation"


class ApprovalLevel(StrEnum):
    nigeria_staff = "nigeria_staff"
    tenant_admin = "tenant_admin"
    head_of_finance = "head_of_finance"


class MissingItemStatus(StrEnum):
    reported = "reported"
    investigating = "investigating"
    found_and_shipping = "found_and_shipping"
    confirmed_lost = "confirmed_lost"
    resolved = "resolved"


class SeizedItemStatus(StrEnum):
    seized = "seized"
    recovery_in_progress = "recovery_in_progress"
    recovered = "recovered"
    permanently_lost = "permanently_lost"


# ---------------------------------------------------------------------------
# Request models
# ---------------------------------------------------------------------------


class FileDamageClaimRequest(BaseModel):
    container_id: str
    cartons_affected: int | list[str | int] = Field(default=0)
    description: str = Field(min_length=1)


class StartInspectionRequest(BaseModel):
    inspection_method: InspectionMethod


class ResolveClaimRequest(BaseModel):
    resolution_type: ResolutionType
    amount_usd: Decimal | None = Field(default=None, ge=Decimal("0"))
    settlement_amount_usd: Decimal | None = Field(default=None, ge=Decimal("0"))
    amount_ngn: Decimal | None = Field(default=None, ge=Decimal("0"))
    discount_percentage: Decimal | None = Field(default=None, ge=Decimal("0"), le=Decimal("100"))
    reason: str = Field(default="")
    notes: str | None = Field(default=None)


class LogMissingItemRequest(BaseModel):
    manifest_id: str
    customer_id: str
    carton_tags: list[str] = Field(min_length=1)
    description: str = Field(min_length=1)


class LogSeizedItemRequest(BaseModel):
    container_id: str
    customer_id: str
    carton_tags: list[str] = Field(min_length=1)
    reason: str = Field(min_length=1)


# ---------------------------------------------------------------------------
# Response models
# ---------------------------------------------------------------------------


class DamageClaimResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    status: DamageClaimStatus
    cartons_affected: list[str] = Field(default_factory=list)
    upload_urls: list[str] | None = None
    created_at: datetime


class ClaimResolutionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    resolution_type: ResolutionType
    amount_usd: Decimal | None = None
    amount_ngn: Decimal | None = None
    approval_level: ApprovalLevel
    refund_request_id: str | None = None


class MissingItemResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    manifest_id: str
    customer_id: str
    carton_tags: list[str] = Field(default_factory=list)
    description: str
    status: MissingItemStatus
    created_at: datetime


class SeizedItemResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    container_id: str
    customer_id: str
    carton_tags: list[str] = Field(default_factory=list)
    reason: str
    status: SeizedItemStatus
    created_at: datetime
