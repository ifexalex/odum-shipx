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


# ---------------------------------------------------------------------------
# Request models
# ---------------------------------------------------------------------------


class SendNotificationRequest(BaseModel):
    event_type: NotificationEvent
    recipient_phone: str | None = None
    recipient_email: str | None = None
    template_data: dict[str, Any] = Field(default_factory=dict)
    tenant_id: str
