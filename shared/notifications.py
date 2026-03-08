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
from typing import Any

import boto3

from shared.cache import Cache
from shared.db import execute_with_tenant
from shared.tenant_context import PLATFORM_TENANT_ID

logger = logging.getLogger(__name__)

# 60-second cache for tenant notification preferences
_prefs_cache: Cache = Cache(default_ttl=60)

# Module-level SQS client (reused across warm invocations)
_sqs_client = None

# Maps channel name → environment variable holding the queue URL
_QUEUE_URL_ENV: dict[str, str] = {
    "sms":       "SQS_SMS_QUEUE_URL",
    "whatsapp":  "SQS_WHATSAPP_QUEUE_URL",
    "email":     "SQS_EMAIL_QUEUE_URL",
}


def _get_sqs():
    global _sqs_client
    if _sqs_client is None:
        _sqs_client = boto3.client(
            "sqs",
            region_name=os.environ.get("AWS_REGION", "eu-west-1"),
        )
    return _sqs_client


def _get_notification_prefs(tenant_id: str) -> dict:
    """Fetch and cache the tenant's notification_preferences JSONB column."""
    cached = _prefs_cache.get(tenant_id)
    if cached is not None:
        return cached

    rows = execute_with_tenant(
        tenant_id=PLATFORM_TENANT_ID,  # bypass RLS — reading the tenant row itself
        query="SELECT notification_preferences FROM tenant WHERE id = %s LIMIT 1",
        params=(tenant_id,),
    )
    prefs: dict = rows[0]["notification_preferences"] if rows else {}
    _prefs_cache.set(tenant_id, prefs)
    return prefs


def enqueue_notification(
    tenant_id: str,
    channel: str,
    recipient: str,
    template_id: str,
    template_vars: dict[str, Any],
    request_id: str = "",
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
        request_id: Correlation ID for tracing.

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
                channel, tenant_id,
            )
            return False
    except Exception as exc:
        # Preference check failure — fail-open and attempt to send
        logger.warning(
            "Could not fetch notification prefs for tenant %s: %s — proceeding",
            tenant_id, exc,
        )

    queue_url = os.environ.get(queue_url_env, "")
    if not queue_url:
        logger.warning(
            "Queue URL env var '%s' not set — notification dropped (channel=%s)",
            queue_url_env, channel,
        )
        return False

    message_body = json.dumps({
        "tenant_id": tenant_id,
        "channel": channel,
        "recipient": recipient,
        "template_id": template_id,
        "template_vars": template_vars,
        "request_id": request_id,
    })

    _get_sqs().send_message(QueueUrl=queue_url, MessageBody=message_body)
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
            tenant_id, exc,
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


def enqueue_notifications(
    tenant_id: str,
    event_type: str,
    recipient: dict,
    template_data: dict,
    request_id: str = "",
) -> None:
    """Enqueue notification messages for all enabled channels for an event.

    Args:
        tenant_id: The tenant UUID.
        event_type: Logical event type (e.g. "packing_list_approved").
        recipient: Dict with keys: phone, email, name, whatsapp (as available).
        template_data: Variables for the notification template.
        request_id: Correlation ID for tracing.
    """
    # Fetch branding for tenant (use same cache path)
    try:
        rows = execute_with_tenant(
            tenant_id=PLATFORM_TENANT_ID,
            query="SELECT branding_config FROM tenant WHERE id = %s LIMIT 1",
            params=(tenant_id,),
        )
        branding: dict = (rows[0]["branding_config"] if rows else None) or {}
    except Exception:
        branding = {}

    for channel in ("sms", "whatsapp", "email"):
        if not should_notify(tenant_id, event_type, channel):
            continue
        queue_url_env = _QUEUE_URL_ENV.get(channel, "")
        queue_url = os.environ.get(queue_url_env, "")
        if not queue_url:
            logger.warning(
                "Queue URL env var '%s' not set — skipping channel %s",
                queue_url_env, channel,
            )
            continue
        try:
            _get_sqs().send_message(
                QueueUrl=queue_url,
                MessageBody=json.dumps({
                    "tenant_id":     tenant_id,
                    "event_type":    event_type,
                    "channel":       channel,
                    "recipient":     recipient,
                    "tenant_branding": branding,
                    "template_data": template_data,
                    "request_id":    request_id,
                }),
            )
            logger.info(
                "Event notification enqueued: %s via %s for tenant %s",
                event_type, channel, tenant_id,
            )
        except Exception:
            logger.exception(
                "Failed to enqueue %s notification for event %s", channel, event_type
            )
