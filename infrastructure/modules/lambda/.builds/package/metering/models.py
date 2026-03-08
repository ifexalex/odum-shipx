"""Pydantic models for the Metering service."""

from datetime import datetime
from enum import Enum

from pydantic import BaseModel, ConfigDict, Field

# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------


class MetricType(str, Enum):
    api_calls = "api_calls"
    containers_processed = "containers_processed"
    storage_bytes = "storage_bytes"
    users_active = "users_active"
    sms_sent = "sms_sent"
    whatsapp_sent = "whatsapp_sent"
    emails_sent = "emails_sent"


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------


class TierLimits(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    users: int = Field(ge=0)
    containers_per_month: int = Field(ge=0)
    storage_gb: float = Field(ge=0)


class UsageRecordResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    tenant_id: str
    metric_type: MetricType
    value: float
    period_start: datetime
    period_end: datetime
