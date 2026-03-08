"""Pydantic models for the Tenant Management service."""

from datetime import datetime
from decimal import Decimal
from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------


class SubscriptionTier(str, Enum):
    starter = "starter"
    business = "business"
    enterprise = "enterprise"


class TenantStatus(str, Enum):
    active = "active"
    suspended = "suspended"
    offboarded = "offboarded"


class TenantUserRole(str, Enum):
    tenant_admin = "tenant_admin"
    china_office_staff = "china_office_staff"
    nigeria_office_staff = "nigeria_office_staff"
    warehouse_attendant = "warehouse_attendant"
    customer = "customer"


class TenantUserStatus(str, Enum):
    active = "active"
    deactivated = "deactivated"


# ---------------------------------------------------------------------------
# Nested input models
# ---------------------------------------------------------------------------


class InitialAdminInput(BaseModel):
    email: str
    full_name: str = Field(min_length=1)


# ---------------------------------------------------------------------------
# Request models
# ---------------------------------------------------------------------------


class CreateTenantRequest(BaseModel):
    company_name: str = Field(min_length=1)
    primary_contact_email: str
    primary_contact_phone: str | None = None
    origin_country: str = "China"
    destination_country: str = "Nigeria"
    subscription_tier: SubscriptionTier
    initial_admin: InitialAdminInput


class UpdateTenantRequest(BaseModel):
    company_name: str | None = Field(default=None, min_length=1)
    primary_contact_email: str | None = None
    subscription_tier: SubscriptionTier | None = None
    branding_config: dict[str, Any] | None = None
    notification_preferences: dict[str, Any] | None = None


class SuspendTenantRequest(BaseModel):
    reason: str = Field(min_length=1)


class CreateTenantUserRequest(BaseModel):
    email: str
    full_name: str = Field(min_length=1)
    role: TenantUserRole


class UpdateTenantConfigRequest(BaseModel):
    branding: dict[str, Any] | None = None
    notification_preferences: dict[str, Any] | None = None


class UpdateDollarRateRequest(BaseModel):
    rate: Decimal = Field(gt=Decimal("0"))
    currency_pair: str = "USD_NGN"


# ---------------------------------------------------------------------------
# Response models
# ---------------------------------------------------------------------------


class TenantResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    company_name: str
    primary_contact_email: str
    subscription_tier: SubscriptionTier
    status: TenantStatus
    created_at: datetime


class TenantDetailResponse(TenantResponse):
    branding_config: dict[str, Any] | None = None
    notification_preferences: dict[str, Any] | None = None
    metrics: dict[str, Any] | None = None


class TenantUserResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    email: str
    full_name: str
    role: TenantUserRole
    status: TenantUserStatus
    cognito_sub: str | None = None
    created_at: datetime


class UsageLimitsNested(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    users: int
    containers_per_month: int
    storage_gb: float


class NotificationsNested(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    sms_sent: int = 0
    whatsapp_sent: int = 0
    emails_sent: int = 0


class TenantUsageResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    tenant_id: str
    period: str
    subscription_tier: SubscriptionTier
    limits: UsageLimitsNested
    api_calls: int = 0
    notifications: NotificationsNested


class DollarRateResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    rate: Decimal
    currency_pair: str
    effective_from: datetime
    previous_rate: Decimal | None = None
