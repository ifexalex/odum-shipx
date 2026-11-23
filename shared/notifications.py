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

from shared import notification_consent
from shared.cache import Cache
from shared.db import execute_with_tenant, execute_write_with_tenant
from shared.observability import record_failure
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


def _customer_preferences(tenant_id: str, customer_id: str) -> dict[str, Any] | None:
    """The customer's recorded notification preferences, or None if there is no such customer."""
    rows = execute_with_tenant(
        tenant_id=tenant_id,
        query="SELECT notification_consent, consent_given_at FROM customer WHERE tenant_id = %s AND id = %s LIMIT 1",
        params=(tenant_id, customer_id),
    )
    return rows[0] if rows else None


def record_suppressed(
    tenant_id: str,
    event_type: str,
    channel: str,
    customer_id: str | None,
    contact: str,
    reason: str,
) -> None:
    """Record in notification_log that a message was held back, and why. Best effort: never blocks a send."""
    try:
        execute_write_with_tenant(
            tenant_id,
            """
            INSERT INTO notification_log (tenant_id, event_type, channel, recipient_masked, customer_id, status, error_detail)
            VALUES (%(tenant_id)s, %(event_type)s, %(channel)s, %(masked)s, %(customer_id)s, 'suppressed', %(reason)s)
            RETURNING id
            """,
            {
                "tenant_id": tenant_id,
                "event_type": event_type,
                "channel": channel,
                "masked": _mask(contact),
                "customer_id": customer_id,
                "reason": reason,
            },
        )
    except Exception:
        logger.warning("Could not record a suppressed %s notification for event %s", channel, event_type)


class ConsentVerdict:
    """What a customer's recorded preferences allow for one event.

    `prefs` is None when nothing can be sent: no customer to look up, or the lookup failed. A consent-bound
    message fails closed, because the alternative is sending something the customer may have declined.
    """

    def __init__(self, prefs: dict[str, Any] | None) -> None:
        self._prefs = prefs

    def permits(self, channel: str) -> bool:
        if self._prefs is None:
            return False
        return notification_consent.permits(self._prefs["notification_consent"], self._prefs["consent_given_at"], channel)


def consent_verdict(tenant_id: str, event_type: str, customer_id: str | None) -> ConsentVerdict | None:
    """The customer's say over this event, or None when it is not theirs to decide.

    None means the event is account or operational (shared/notification_consent.py) and goes out whatever
    their preferences say. Otherwise the returned verdict answers `permits(channel)`.
    """
    if not notification_consent.is_consent_bound(event_type):
        return None
    if not customer_id:
        logger.warning("Event %s is bound by customer preferences but carries no customer_id — nothing sent", event_type)
        return ConsentVerdict(None)
    try:
        return ConsentVerdict(_customer_preferences(tenant_id, customer_id))
    except Exception:
        logger.warning("Could not read notification preferences for customer %s — event %s not sent", customer_id, event_type)
        return ConsentVerdict(None)


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

    # The customer's own preferences, for the events they govern (shared/notification_consent.py).
    verdict = consent_verdict(tenant_id, template_id, customer_id)
    if verdict is not None and not verdict.permits(channel):
        record_suppressed(tenant_id, template_id, channel, customer_id, recipient, f"customer has not agreed to {channel}")
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

    try:
        get_queue_provider().send(destination=queue_url, body=message_body)
    except Exception:
        record_failure("notification_enqueue")  # the caller may swallow it; the count does not depend on that
        raise
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

# Environment names that mean "this is production, send for real". Both spellings
# are accepted deliberately: every tfvars file (AWS and Azure) sets
# `environment = "prod"` — and that value also feeds resource name prefixes, so it
# cannot be renamed to "production" without recreating infrastructure. Matching
# only "production" meant the guard could never switch itself off in any deployed
# environment, silently suppressing *every* customer notification in production.
_PRODUCTION_ENVIRONMENTS = frozenset({"production", "prod"})


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

    Production always sends — see `_PRODUCTION_ENVIRONMENTS` for why both "prod"
    and "production" count. Every other environment **fails closed**: nothing is
    messaged unless the contact appears in NOTIFICATION_ALLOWLIST.

    Dev and staging databases hold real imported customer contacts — a manifest
    import creates customers straight from the forwarder's file, phone numbers
    and all. Without this, pointing a dev environment at real SMS credentials
    (or simply running the notification consumer against a dev database) would
    text real customers. Opt-in is the only safe default; an allowlist that
    someone forgot to populate must send nothing, not everything.
    """
    if os.environ.get("ENVIRONMENT", "").strip().lower() in _PRODUCTION_ENVIRONMENTS:
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


def _tenant_branding(tenant_id: str) -> dict[str, Any]:
    """Branding embedded in the queued message, so consumers need no DB access.

    Selects `company_name` alongside `branding_config` because the notification
    service needs a company name and `branding_config` is not guaranteed to
    carry one. It is optional (tenants set `display_name` only if their trading
    name differs from the legal one) and is frequently `{}` outright, in which
    case every notification on every channel was branded with the literal word
    "Logistics" — the hardcoded fallback in
    `services/notification/tenant_branding.py`. The legal `company_name` on the
    tenant row always exists, so it is the floor beneath the optional override.

    `company_name` is set here rather than read from the DB in the consumer
    because the notification Lambdas deliberately run outside the VPC and have
    no database access at all.
    """
    try:
        rows = execute_with_tenant(
            tenant_id=PLATFORM_TENANT_ID,  # bypass RLS — reading the tenant row itself
            query="SELECT company_name, branding_config FROM tenant WHERE id = %s LIMIT 1",
            params=(tenant_id,),
        )
    except Exception:
        logger.warning("Could not load branding for tenant %s — notifications will use defaults", tenant_id)
        return {}
    if not rows:
        return {}
    branding: dict[str, Any] = dict(rows[0]["branding_config"] or {})
    # Only as a floor: a tenant that set `display_name` keeps it.
    branding.setdefault("company_name", rows[0]["company_name"] or "")
    return branding


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
    branding = _tenant_branding(tenant_id)

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
    #
    # primary_channel is "email" for a recipient with no phone, so without dedupe that recipient was
    # sent every email twice.
    primary = primary_channel(tenant_id, event_type, recipient)
    channels = tuple(dict.fromkeys((primary, "email")))

    verdict = consent_verdict(tenant_id, event_type, customer_id)
    if verdict is not None:
        contacts = {
            "sms": str(recipient.get("phone") or ""),
            "whatsapp": str(recipient.get("whatsapp") or recipient.get("phone") or ""),
            "email": str(recipient.get("email") or ""),
        }
        permitted: list[str] = []
        for wanted in channels:
            use = wanted
            # WhatsApp is only the preferred way to reach a phone: a customer who agreed to SMS but not
            # WhatsApp is still reachable, so use SMS rather than going silent.
            if wanted == "whatsapp" and not verdict.permits("whatsapp") and verdict.permits("sms"):
                use = "sms"
            if verdict.permits(use):
                permitted.append(use)
            else:
                record_suppressed(
                    tenant_id, event_type, wanted, customer_id, contacts.get(wanted, ""), f"customer has not agreed to {wanted}"
                )
        channels = tuple(permitted)

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
            record_failure("notification_enqueue")
