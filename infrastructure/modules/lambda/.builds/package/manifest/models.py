"""Pydantic models for the Manifest service."""

from datetime import datetime
from decimal import Decimal
from enum import Enum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------


class VerificationStatus(str, Enum):
    pending = "pending"
    verified = "verified"
    discrepancies_found = "discrepancies_found"


# ---------------------------------------------------------------------------
# Nested input models
# ---------------------------------------------------------------------------


class DiscrepancyInput(BaseModel):
    customer_id: str
    carton_tags: list[str] = Field(min_length=1)
    type: Literal["missing", "damaged"]
    notes: str | None = None


# ---------------------------------------------------------------------------
# Request models
# ---------------------------------------------------------------------------


class VerifyManifestRequest(BaseModel):
    verification_status: VerificationStatus
    discrepancies: list[DiscrepancyInput] | None = None


# ---------------------------------------------------------------------------
# Response models
# ---------------------------------------------------------------------------


class ManifestCustomerSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    customer_id: str
    customer_name: str | None = None
    packing_list_id: str | None = None
    carton_count: int = 0
    total_weight_kg: Decimal | None = None
    total_cbm: Decimal | None = None
    carton_tags: list[str] = Field(default_factory=list)


class ManifestResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    container_id: str
    container_number: str | None = None
    total_customers: int = 0
    total_cartons: int = 0
    total_weight_kg: Decimal | None = None
    total_cbm: Decimal | None = None
    verification_status: VerificationStatus
    customers: list[ManifestCustomerSummary] = Field(default_factory=list)
    created_at: datetime
