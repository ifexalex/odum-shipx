"""Pydantic models for the Notification service."""

from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field

# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------


class NotificationChannel(StrEnum):
    sms = "sms"
    whatsapp = "whatsapp"
    email = "email"


class NotificationEvent(StrEnum):
    shipment_update = "shipment_update"
    payment_due = "payment_due"
    release_note_generated = "release_note_generated"
    cbm_dispute_update = "cbm_dispute_update"
    damage_claim_update = "damage_claim_update"
    packing_list_approved = "packing_list_approved"
    tenant_onboarded = "tenant_onboarded"
    tenant_suspended = "tenant_suspended"


class AnnouncementAudience(StrEnum):
    all_staff = "all_staff"
    all_customers = "all_customers"


# ---------------------------------------------------------------------------
# Request models
# ---------------------------------------------------------------------------


class SendNotificationRequest(BaseModel):
    event_type: NotificationEvent
    recipient_phone: str | None = None
    recipient_email: str | None = None
    template_data: dict[str, Any] = Field(default_factory=dict)
    tenant_id: str


class SendAnnouncementRequest(BaseModel):
    """A manual broadcast composed by tenant_admin/nigeria_office_staff —
    e.g. a holiday-hours notice or an import-maintenance window — not a
    system-triggered event. Delivered via the same staff_notification bell
    as every other in-app notification, broadcast to a whole audience via
    target_role rather than any single target_user_id."""

    title: str = Field(min_length=1, max_length=200)
    body: str | None = Field(default=None, max_length=2000)
    audience: AnnouncementAudience


class RejectAnnouncementRequestBody(BaseModel):
    """Optional reason a tenant_admin gives when rejecting a staff-submitted
    announcement request — surfaced back to the requester's own bell."""

    reason: str | None = Field(default=None, max_length=500)


class UpdateAnnouncementBody(BaseModel):
    """Edits a still-pending request's title/body (the requester) or an
    already-sent announcement's title/body (tenant_admin) — same shape as
    SendAnnouncementRequest minus audience, which isn't editable after
    creation (changing it would mean re-fanning-out to different roles)."""

    title: str = Field(min_length=1, max_length=200)
    body: str | None = Field(default=None, max_length=2000)
