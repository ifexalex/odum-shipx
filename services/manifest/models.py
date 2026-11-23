"""Pydantic models for the Manifest service."""

from datetime import datetime
from decimal import Decimal
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------


class VerificationStatus(StrEnum):
    pending = "pending"
    verified = "verified"
    discrepancies_found = "discrepancies_found"
    resolved = "resolved"


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


class ResolveDiscrepancyRequest(BaseModel):
    resolution_notes: str = Field(min_length=1, max_length=1000)
    final_counts: dict[str, int] | None = None


class EvidenceUploadRequest(BaseModel):
    """Presigned-upload request for a manifest-verification photo/doc (§6.3)."""

    filename: str = Field(min_length=1, max_length=255)
    content_type: str = Field(min_length=1, max_length=100)
    label: str | None = Field(default=None, max_length=255)
    #: The file's size in bytes; at most 5 MB (shared.uploads.MAX_UPLOAD_BYTES), checked by the upload policy.
    size_bytes: int | None = None


# ---------------------------------------------------------------------------
# Response models
# ---------------------------------------------------------------------------


class ManifestCustomerSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    customer_id: str
    customer_name: str | None = None
    # The source manifest pairs NAME with CONTACT on every row — staff call the
    # customer when cargo lands, so the number belongs beside the name.
    customer_phone: str | None = None
    packing_list_id: str | None = None
    carton_count: int = 0
    total_weight_kg: Decimal | None = None
    total_cbm: Decimal | None = None
    carton_tags: list[str] = Field(default_factory=list)


class ManifestEvidence(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    file_name: str
    file_type: str
    label: str | None = None
    download_url: str | None = None
    created_at: datetime | None = None


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
    evidence: list[ManifestEvidence] = Field(default_factory=list)
    created_at: datetime
