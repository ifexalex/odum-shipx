"""Notification enqueuing — routes messages to SQS for SMS, WhatsApp, and email delivery.

Checks the tenant's `notification_preferences` (from the `tenant` table) before
enqueuing. Preferences are cached for 60 seconds to avoid repeated DB reads.

The notification Lambda consumers (notif_sms, notif_whatsapp, notif_email) read
from the SQS queues and call the external APIs (Africa's Talking, Meta, SES).

Queue URLs are read from environment variables:
    SQS_SMS_QUEUE_URL
    SQS_WHATSAPP_QUEUE_URL
    SQS_EMAIL_QUEUE_URL

Usage:
    from shared.notifications import enqueue_notification

    enqueue_notification(
        tenant_id=ctx.tenant_id,
        channel="sms",
        recipient="+2348012345678",
        template_id="packing_list_approved",
        template_vars={"customer_name": "Ngozi", "container": "ACME001"},
        request_id=request_id,
    )
"""

import json
import logging
import os
from typing import Any, cast

from shared.cache import Cache
from shared.db import execute_with_tenant
from shared.providers import get_queue_provider
from shared.tenant_context import PLATFORM_TENANT_ID

logger = logging.getLogger(__name__)

# 60-second cache for tenant notification preferences
_prefs_cache: Cache = Cache(default_ttl=60)

# Maps channel name → environment variable holding the queue URL
_QUEUE_URL_ENV: dict[str, str] = {
    "sms": "SQS_SMS_QUEUE_URL",
    "whatsapp": "SQS_WHATSAPP_QUEUE_URL",
    "email": "SQS_EMAIL_QUEUE_URL",
}


def _get_notification_prefs(tenant_id: str) -> dict[str, Any]:
    """Fetch and cache the tenant's notification_preferences JSONB column."""
    cached = _prefs_cache.get(tenant_id)
    if cached is not None:
        return cast(dict[str, Any], cached)

    rows = execute_with_tenant(
        tenant_id=PLATFORM_TENANT_ID,  # bypass RLS — reading the tenant row itself
        query="SELECT notification_preferences FROM tenant WHERE id = %s LIMIT 1",
        params=(tenant_id,),
    )
    prefs: dict[str, Any] = rows[0]["notification_preferences"] if rows else {}
    _prefs_cache.set(tenant_id, prefs)
    return prefs


def enqueue_notification(
    tenant_id: str,
    channel: str,
    recipient: str,
    template_id: str,
    template_vars: dict[str, Any],
    locale: str = "en",
    request_id: str = "",
    customer_id: str | None = None,
) -> bool:
    """Enqueue a notification message to the appropriate SQS queue.

    Respects the tenant's notification preferences — if a channel is explicitly
    disabled (``{"sms": {"enabled": false}}``), the message is suppressed and
    False is returned.

    Args:
        tenant_id: The tenant UUID.
        channel: Delivery channel: "sms", "whatsapp", or "email".
        recipient: Phone number (E.164 for SMS/WhatsApp) or email address.
        template_id: Template identifier understood by the notification Lambda.
        template_vars: Variables interpolated into the template at send time.
        locale: BCP-47 locale ('en' or 'zh'). Selects the template language.
        request_id: Correlation ID for tracing.
        customer_id: Customer this notification concerns, recorded on the
            notification_log row. Required for the WhatsApp→SMS fallback, which
            re-reads the recipient's phone from the customer record.

    Returns:
        True if the message was enqueued, False if suppressed by preferences.
    """
    # Validate channel early
    queue_url_env = _QUEUE_URL_ENV.get(channel)
    if not queue_url_env:
        logger.warning("Unknown notification channel '%s' — message dropped", channel)
        return False

    # Check tenant notification preferences
    try:
        prefs = _get_notification_prefs(tenant_id)
        channel_prefs = prefs.get(channel, {})
        if isinstance(channel_prefs, dict) and channel_prefs.get("enabled") is False:
            logger.info(
                "Notification channel '%s' disabled for tenant %s — suppressed",
                channel,
                tenant_id,
            )
            return False
    except Exception as exc:
        # Preference check failure — fail-open and attempt to send
        logger.warning(
            "Could not fetch notification prefs for tenant %s: %s — proceeding",
            tenant_id,
            exc,
        )

    queue_url = os.environ.get(queue_url_env, "")
    if not queue_url:
        logger.warning(
            "Queue URL env var '%s' not set — notification dropped (channel=%s)",
            queue_url_env,
            channel,
        )
        return False

    message_body = json.dumps(
        {
            "tenant_id": tenant_id,
            "channel": channel,
            "recipient": recipient,
            "template_id": template_id,
            "template_vars": template_vars,
            "locale": locale,
            "request_id": request_id,
            "customer_id": customer_id,
        }
    )

    get_queue_provider().send(destination=queue_url, body=message_body)
    logger.info(
        "Notification enqueued",
        extra={
            "channel": channel,
            "tenant_id": tenant_id,
            "template_id": template_id,
            "request_id": request_id,
        },
    )
    return True


# ---------------------------------------------------------------------------
# Event-driven helpers (Part 11 — Task 21)
# ---------------------------------------------------------------------------


def should_notify(tenant_id: str, event_type: str, channel: str) -> bool:
    """Return True if the tenant has this channel enabled for this event type.

    Preference structure expected in tenant.notification_preferences:
      {
        "sms_enabled": true,
        "whatsapp_enabled": true,
        "email_enabled": true,
        "events": {
          "packing_list_approved": ["sms", "whatsapp"],
          "payment_due": ["sms", "email"],
          ...
        }
      }
    """
    try:
        prefs = _get_notification_prefs(tenant_id)
    except Exception as exc:
        logger.warning(
            "could not fetch prefs for tenant %s: %s — defaulting to True",
            tenant_id,
            exc,
        )
        return True

    # Global channel toggle (defaults to enabled if key absent)
    if not prefs.get(f"{channel}_enabled", True):
        return False

    # Event-specific channel list (defaults to all channels enabled if absent)
    event_channels = prefs.get("events", {}).get(event_type)
    if event_channels is None:
        return True
    return channel in event_channels


def _get_custom_template(tenant_id: str, event_type: str, channel: str) -> dict[str, Any] | None:
    """Return the tenant's custom notification_template row for this event+channel, or None."""
    try:
        rows = execute_with_tenant(
            tenant_id=tenant_id,
            query="""
                SELECT template_body, subject FROM notification_template
                WHERE tenant_id = %s AND event_type = %s AND channel = %s
                LIMIT 1
            """,
            params=(tenant_id, event_type, channel),
        )
        return rows[0] if rows else None
    except Exception:
        return None


def _build_template_override(channel: str, row: dict[str, Any]) -> dict[str, Any]:
    """Convert a notification_template row into the template_override dict shape."""
    if channel == "email":
        return {"email": {"subject": row.get("subject") or "", "body": row["template_body"]}}
    return {channel: row["template_body"]}


# ---------------------------------------------------------------------------
# Non-production recipient guard
# ---------------------------------------------------------------------------

_ALLOWLIST_ENV = "NOTIFICATION_ALLOWLIST"


def _allowlist() -> set[str]:
    """Recipients that may be messaged outside production, from env."""
    raw = os.environ.get(_ALLOWLIST_ENV, "")
    return {entry.strip().lower() for entry in raw.split(",") if entry.strip()}


def _mask(value: str) -> str:
    """Mask a phone/email for logging — never log a contact in full."""
    if not value:
        return ""
    if "@" in value:
        name, _, domain = value.partition("@")
        return f"{name[:2]}***@{domain}"
    return f"{value[:5]}***{value[-3:]}" if len(value) > 8 else "***"


def is_recipient_allowed(recipient: dict[str, Any]) -> bool:
    """True when this recipient may actually be messaged.

    Production always sends. Every other environment **fails closed**: nothing
    is messaged unless the contact appears in NOTIFICATION_ALLOWLIST.

    Dev and staging databases hold real imported customer contacts — a manifest
    import creates customers straight from the forwarder's file, phone numbers
    and all. Without this, pointing a dev environment at real SMS credentials
    (or simply running the notification consumer against a dev database) would
    text real customers. Opt-in is the only safe default; an allowlist that
    someone forgot to populate must send nothing, not everything.
    """
    if os.environ.get("ENVIRONMENT", "").lower() == "production":
        return True
    allowed = _allowlist()
    if not allowed:
        return False
    return any(str(recipient.get(field) or "").strip().lower() in allowed for field in ("phone", "email", "whatsapp"))


def primary_channel(tenant_id: str, event_type: str, recipient: dict[str, Any]) -> str:
    """Return the channel that will actually carry this notification.

    WhatsApp is preferred: most customers are reached there, and it costs less
    than SMS. SMS becomes the fallback rather than a parallel send — see
    `services/notification/service.py::trigger_sms_fallback`. Email is a
    different medium, not a worse SMS, so it always goes out alongside per the
    tenant's own preferences and is never returned here.

    Callers that need to *report* the delivery channel (the customer-invite
    endpoint tells staff how the link was sent) must use this rather than
    guessing, or they will describe a channel the message never used.
    """
    if not recipient.get("phone"):
        return "email"
    whatsapp_possible = should_notify(tenant_id, event_type, "whatsapp") and bool(os.environ.get(_QUEUE_URL_ENV["whatsapp"], ""))
    return "whatsapp" if whatsapp_possible else "sms"


def enqueue_notifications(
    tenant_id: str,
    event_type: str,
    recipient: dict[str, Any],
    template_data: dict[str, Any],
    request_id: str = "",
    locale: str = "en",
    customer_id: str | None = None,
) -> None:
    """Enqueue notification messages for all enabled channels for an event.

    Looks up tenant-custom templates from notification_template and embeds them
    as template_override in the SQS payload so the notification Lambda uses
    the custom copy instead of the hardcoded defaults.

    Args:
        tenant_id: The tenant UUID.
        event_type: Logical event type (e.g. "packing_list_approved").
        recipient: Dict with keys: phone, email, name, whatsapp (as available).
        template_data: Variables for the notification template.
        request_id: Correlation ID for tracing.
        locale: BCP-47 locale code ('en' or 'zh'). Selects template language.
        customer_id: Customer this notification concerns. Threaded onto the
            queued message so notification_log records it — without it the
            WhatsApp→SMS fallback cannot look up a phone and silently gives up.
    """
    # Fetch branding for tenant (use same cache path)
    try:
        rows = execute_with_tenant(
            tenant_id=PLATFORM_TENANT_ID,
            query="SELECT branding_config FROM tenant WHERE id = %s LIMIT 1",
            params=(tenant_id,),
        )
        branding: dict[str, Any] = (rows[0]["branding_config"] if rows else None) or {}
    except Exception:
        branding = {}

    if not is_recipient_allowed(recipient):
        logger.warning(
            "Notification suppressed outside production — recipient not in %s "
            "(event=%s, to=%s). Set %s to test against a real contact.",
            _ALLOWLIST_ENV,
            event_type,
            _mask(str(recipient.get("phone") or recipient.get("email") or "")),
            _ALLOWLIST_ENV,
        )
        return

    # WhatsApp first, SMS only as a fallback. Most customers here are reached
    # on WhatsApp, and sending both every time doubles cost for no benefit.
    # SMS is queued up-front only when WhatsApp cannot even be attempted (no
    # phone, channel muted for this tenant, or no queue configured); when
    # WhatsApp *is* attempted and then fails, the fallback is triggered by the
    # consumer or the delivery-status webhook — see
    # services/notification/service.py::trigger_sms_fallback.
    #
    # Email is unaffected: it is a different medium, not a worse SMS, so it
    # still goes out in parallel per the tenant's own preferences.
    channels = (primary_channel(tenant_id, event_type, recipient), "email")

    for channel in channels:
        if not should_notify(tenant_id, event_type, channel):
            continue
        queue_url_env = _QUEUE_URL_ENV.get(channel, "")
        queue_url = os.environ.get(queue_url_env, "")
        if not queue_url:
            logger.warning(
                "Queue URL env var '%s' not set — skipping channel %s",
                queue_url_env,
                channel,
            )
            continue

        # Look up tenant-custom template override for this channel
        custom_tmpl = _get_custom_template(tenant_id, event_type, channel)
        template_override = _build_template_override(channel, custom_tmpl) if custom_tmpl else None

        try:
            body: dict[str, Any] = {
                "tenant_id": tenant_id,
                "event_type": event_type,
                "channel": channel,
                "recipient": recipient,
                "tenant_branding": branding,
                "template_data": template_data,
                "request_id": request_id,
                "locale": locale,
                "customer_id": customer_id,
            }
            if template_override:
                body["template_override"] = template_override

            get_queue_provider().send(destination=queue_url, body=json.dumps(body))
            logger.info(
                "Event notification enqueued: %s via %s for tenant %s",
                event_type,
                channel,
                tenant_id,
            )
        except Exception:
            logger.exception("Failed to enqueue %s notification for event %s", channel, event_type)
