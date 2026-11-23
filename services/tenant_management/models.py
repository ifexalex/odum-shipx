"""Pydantic models for the Tenant Management service."""

from datetime import datetime
from decimal import Decimal
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from shared.url_safety import UnsafeUrlError, validate_public_https_url

# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------


class SubscriptionTier(StrEnum):
    starter = "starter"
    business = "business"
    enterprise = "enterprise"


class TenantStatus(StrEnum):
    active = "active"
    suspended = "suspended"
    offboarded = "offboarded"


class TenantUserRole(StrEnum):
    tenant_admin = "tenant_admin"
    china_office_staff = "china_office_staff"
    nigeria_office_staff = "nigeria_office_staff"
    warehouse_attendant = "warehouse_attendant"
    customer = "customer"


class TenantUserStatus(StrEnum):
    active = "active"
    deactivated = "deactivated"


class OnboardingRequestStatus(StrEnum):
    new = "new"
    contacted = "contacted"
    approved = "approved"
    rejected = "rejected"
    provisioned = "provisioned"


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
    # When provisioning from a company onboarding lead: links the tenant back to
    # the request and flips it to 'provisioned' (see service.create_tenant).
    onboarding_request_id: str | None = None


# ---------------------------------------------------------------------------
# Company onboarding (shipping-company leads — NOT customer sign-up)
# ---------------------------------------------------------------------------


class CreateOnboardingRequest(BaseModel):
    """Public lead form for a shipping COMPANY requesting onboarding.

    Deliberately collects no password and no tenant slug, and creates no account
    — a platform admin reviews and provisions later. This shape is what keeps it
    from being confused with customer self-registration (CustomerRegistrationRequest).
    """

    company_name: str = Field(min_length=1, max_length=200)
    contact_name: str = Field(min_length=1, max_length=200)
    contact_email: str = Field(min_length=3, max_length=320)
    contact_phone: str | None = Field(default=None, max_length=40)
    origin_country: str = Field(default="China", max_length=100)
    destination_country: str = Field(default="Nigeria", max_length=100)
    monthly_volume: str | None = Field(default=None, max_length=100)
    notes: str | None = Field(default=None, max_length=2000)


class OnboardingRequestStatusUpdate(BaseModel):
    status: OnboardingRequestStatus
    rejection_reason: str | None = Field(default=None, max_length=2000)


class UpdateTenantRequest(BaseModel):
    company_name: str | None = Field(default=None, min_length=1)
    primary_contact_email: str | None = None
    subscription_tier: SubscriptionTier | None = None
    branding_config: dict[str, Any] | None = None
    notification_preferences: dict[str, Any] | None = None


class SuspendTenantRequest(BaseModel):
    reason: str = Field(min_length=1)


class CreateTenantUserRequest(BaseModel):
    """Create a staff/customer tenant_user.

    Breaking change (2026-07-20): `role` (singular) → `roles` + `primary_role`,
    the natural N=1 case of the general multi-role model — there are no
    production tenants yet, so no dual-path back-compat is kept.
    """

    email: str
    full_name: str = Field(min_length=1)
    roles: list[TenantUserRole] = Field(min_length=1)
    primary_role: TenantUserRole | None = None

    @model_validator(mode="after")
    def _default_and_validate_primary_role(self) -> "CreateTenantUserRequest":
        # Deduplicate while preserving order so duplicate roles cannot violate PK(tenant_user_id, role).
        self.roles = list(dict.fromkeys(self.roles))
        if self.primary_role is None:
            self.primary_role = self.roles[0]
        elif self.primary_role not in self.roles:
            raise ValueError("primary_role must be one of the assigned roles")
        return self


class UpdateTenantUserRequest(BaseModel):
    """Partial update of a tenant_user — all fields optional.

    Replaces the previous unvalidated raw-dict filter in handler.py. When
    `roles` is present, `primary_role` (if also present) must be one of them;
    if absent, it defaults to `roles[0]`.
    """

    full_name: str | None = Field(default=None, min_length=1)
    locale: str | None = None
    roles: list[TenantUserRole] | None = Field(default=None, min_length=1)
    primary_role: TenantUserRole | None = None

    @model_validator(mode="after")
    def _default_and_validate_primary_role(self) -> "UpdateTenantUserRequest":
        if self.roles is not None:
            self.roles = list(dict.fromkeys(self.roles))
            if self.primary_role is None:
                self.primary_role = self.roles[0]
            elif self.primary_role not in self.roles:
                raise ValueError("primary_role must be one of the assigned roles")
        elif self.primary_role is not None:
            raise ValueError("primary_role requires roles to also be provided")
        return self


class WebhookEventType(StrEnum):
    container_status_updated = "container.status_updated"
    billing_payment_due = "billing.payment_due"
    release_note_generated = "release_note.generated"
    packing_list_approved = "packing_list.approved"


class WebhookConfigRequest(BaseModel):
    """Webhook configuration update.

    The signing secret is managed server-side. Use the rotate-secret endpoint
    to generate or rotate the HMAC-SHA256 signing key.
    """

    endpoint_url: str = Field(pattern=r"^https://")
    enabled: bool
    events: list[WebhookEventType] = Field(default_factory=list)

    @field_validator("endpoint_url")
    @classmethod
    def _endpoint_must_be_public(cls, value: str) -> str:
        # Syntactic SSRF check only (no DNS at validation time); the delivery
        # path re-resolves and pins the address — see shared/url_safety.py.
        try:
            validate_public_https_url(value)
        except UnsafeUrlError as exc:
            raise ValueError(str(exc)) from exc
        return value


class BankTransferConfigRequest(BaseModel):
    """This tenant's own bank account for the customer-facing manual
    "Manual bank transfer" payment option (MyBillingDetail.tsx).

    Ground-truth gap found live: the frontend previously hardcoded a single
    tenant's bank details and showed them to every tenant's customers — a
    Global Cargo customer transferring money would have been shown Acme's
    account. This makes it a real per-tenant setting instead.
    """

    model_config = ConfigDict(str_strip_whitespace=True)

    bank_name: str = Field(min_length=1, max_length=100)
    account_name: str = Field(min_length=1, max_length=200)
    account_number: str = Field(min_length=1, max_length=50)
    sort_code: str | None = Field(default=None, max_length=20)
    instructions: str | None = Field(default=None, max_length=500)


class UpdateTenantConfigRequest(BaseModel):
    branding: dict[str, Any] | None = None
    notification_preferences: dict[str, Any] | None = None
    webhook_config: WebhookConfigRequest | None = None
    bank_transfer_config: BankTransferConfigRequest | None = None


class LogoUploadRequest(BaseModel):
    """Presigned-upload request for the tenant's logo (FD-29)."""

    filename: str = Field(min_length=1, max_length=255)
    content_type: str = Field(min_length=1, max_length=100)
    #: The file's size in bytes; at most 1 MB (shared.uploads.TENANT_LOGO), checked by the upload policy.
    size_bytes: int | None = None


class SetLogoRequest(BaseModel):
    """Use an uploaded file as the tenant's logo (FD-29). The key must be one this tenant's presign returned."""

    file_key: str = Field(min_length=1, max_length=512)


class PaystackConfigRequest(BaseModel):
    """Connect this tenant's own Paystack account (audit gap: multi-tenant
    payment gateway, 2026-07-19).

    Unlike webhook_config, there is nothing to partially merge — a new key
    always fully replaces whatever was stored (same posture as webhook
    secret rotation). The key is validated for shape here; PUT
    /v1/tenant/config/paystack/test proves it actually works against the
    live Paystack API.
    """

    secret_key: str = Field(pattern=r"^sk_(test|live)_[A-Za-z0-9]{20,}$")


class MarkupType(StrEnum):
    percentage = "percentage"
    flat = "flat"


class UpdateDollarRateMarkupRequest(BaseModel):
    """The dollar rate is no longer typed in directly — the base rate is
    fetched live from Bybit's P2P order book (shared/fx_rate.py) and a
    tenant only controls the markup layered on top of it. `ge=0` on both:
    a markup discounting below Bybit's own rate isn't a "markup"."""

    markup_type: MarkupType
    markup_value: Decimal = Field(ge=Decimal("0"))


class CbmRateCurrency(StrEnum):
    usd = "usd"
    ngn = "ngn"


class CbmRateMode(StrEnum):
    flat = "flat"
    per_package_type = "per_package_type"


class UpdateCbmRateRequest(BaseModel):
    """CBM rate is priced per package type (carton/bag/bale) — "flat" is
    just the case where all three rates are equal, enforced here rather
    than as a separate code path downstream. Package types other than
    carton/bag/bale (pallet, item, mixed, unspecified, or any other free-
    text value) bill at the carton rate (shared/cbm_rate.py)."""

    currency: CbmRateCurrency
    rate_mode: CbmRateMode
    carton_rate: Decimal = Field(gt=Decimal("0"))
    bag_rate: Decimal | None = Field(default=None, gt=Decimal("0"))
    bale_rate: Decimal | None = Field(default=None, gt=Decimal("0"))
    # Minimum billable CBM per line item (floor applied at packing-list entry).
    # Optional — omit to leave the current value unchanged.
    min_cbm_per_item: Decimal | None = Field(default=None, gt=Decimal("0"))

    @model_validator(mode="after")
    def _resolve_per_type_rates(self) -> "UpdateCbmRateRequest":
        if self.rate_mode == CbmRateMode.flat:
            self.bag_rate = self.carton_rate
            self.bale_rate = self.carton_rate
        elif self.bag_rate is None or self.bale_rate is None:
            raise ValueError("bag_rate and bale_rate are required when rate_mode is per_package_type")
        return self


class NotificationChannel(StrEnum):
    sms = "sms"
    email = "email"
    whatsapp = "whatsapp"


class UpsertNotificationTemplateRequest(BaseModel):
    template_body: str = Field(min_length=1)
    subject: str | None = None


class CustomerRegistrationRequest(BaseModel):
    name: str = Field(min_length=1)
    email: str = Field(min_length=5)
    phone: str = Field(min_length=1)
    whatsapp: str | None = None
    notification_consent: list[str] | None = None
    # Optional so POST /v1/register (body-resolved tenant, kept for backward
    # compatibility) keeps working; POST /v1/register/{slug} supplies the
    # slug via the path instead and this field is ignored there.
    slug: str | None = None


class AcceptCustomerInviteRequest(BaseModel):
    """Body for POST /v1/invites/{token}/accept — claims an invite."""

    email: str = Field(min_length=5)
    password: str = Field(min_length=8)


class ActivateAccountRequest(BaseModel):
    """Body for POST /v1/activate/{token} — a provisioned staff/admin sets their
    own password via the ShipX activation link."""

    password: str = Field(min_length=8)


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
    role: TenantUserRole  # Primary role — kept for every existing single-role consumer
    roles: list[TenantUserRole] = Field(default_factory=list)
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
