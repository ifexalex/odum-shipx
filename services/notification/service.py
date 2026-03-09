"""Channel-specific send logic for the Notification service.

Three channels:
  - SMS via Africa's Talking API
  - WhatsApp via Meta Cloud API (pre-approved templates)
  - Email via Amazon SES (tenant-branded HTML)

All send functions raise on hard failures so that the SQS handler can
return the message ID in batchItemFailures and let SQS retry / DLQ.
"""

import json
import logging
import os
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

import boto3

from .tenant_branding import get_company_name, get_primary_color

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Module-level boto3 client (reused across warm invocations)
# ---------------------------------------------------------------------------

_ses_client = None


def _get_ses() -> Any:
    global _ses_client
    if _ses_client is None:
        _ses_client = boto3.client("ses", region_name=os.environ.get("AWS_REGION", "eu-west-1"))
    return _ses_client


# ---------------------------------------------------------------------------
# SMS — Africa's Talking
# ---------------------------------------------------------------------------

_SMS_TEMPLATES: dict[str, str] = {
    "shipment_update": ("{company_name}: Your shipment {tracking_code} is now {status}."),
    "payment_due": (
        "{company_name}: Container {container_number} arrived. " "Amount: {currency} {amount}. Pickup: {warehouse_address}"
    ),
    "release_note_generated": ("{company_name}: Release note ready. " "Ref: {reference_number}. Collect {carton_count} cartons."),
}

_DEFAULT_SMS_TEMPLATE = "{company_name}: You have a new notification."


class _SafeFormatMap(dict):  # type: ignore[type-arg]
    """dict subclass that returns {key} for missing keys instead of raising."""

    def __missing__(self, key: str) -> str:
        return f"{{{key}}}"


def format_sms(event_type: str, branding: dict[str, Any], template_data: dict[str, Any]) -> str:
    """Format an SMS message body from event type + template data."""
    template = _SMS_TEMPLATES.get(event_type, _DEFAULT_SMS_TEMPLATE)
    data = _SafeFormatMap({"company_name": get_company_name(branding), **template_data})
    try:
        return template.format_map(data)
    except Exception:
        company = get_company_name(branding)
        return f"{company}: You have a notification regarding your shipment."


def send_sms(phone: str, message: str, tenant_id: str) -> bool:
    """Send an SMS via Africa's Talking. Raises on API errors.

    Returns True on confirmed delivery, False if credentials missing.
    """
    api_key = os.environ.get("AFRICASTALKING_API_KEY", "")
    username = os.environ.get("AFRICASTALKING_USERNAME", "sandbox")
    sender_id = os.environ.get("AFRICASTALKING_SENDER_ID", "")

    if not api_key:
        logger.warning(
            "AFRICASTALKING_API_KEY not configured — SMS not sent",
            extra={"tenant_id": tenant_id},
        )
        return False

    payload: dict[str, Any] = {"username": username, "to": phone, "message": message}
    if sender_id:
        payload["from"] = sender_id

    data = urllib.parse.urlencode(payload).encode("utf-8")
    req = urllib.request.Request(
        "https://api.africastalking.com/version1/messaging",
        data=data,
        headers={
            "apiKey": api_key,
            "Accept": "application/json",
            "Content-Type": "application/x-www-form-urlencoded",
        },
        method="POST",
    )

    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            resp_body = json.loads(resp.read())
            sms_data = resp_body.get("SMSMessageData", {})
            recipients = sms_data.get("Recipients", [])
            if recipients and recipients[0].get("status") == "Success":
                logger.info(
                    "SMS sent",
                    extra={"tenant_id": tenant_id},
                )
                return True
            logger.warning(
                "SMS delivery issue: %s",
                sms_data.get("Message", "unknown"),
                extra={"tenant_id": tenant_id},
            )
            return False
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        logger.error(
            "Africa's Talking HTTP error %s: %s",
            exc.code,
            body,
            extra={"tenant_id": tenant_id},
        )
        raise
    except Exception:
        logger.exception("Africa's Talking send_sms failed", extra={"tenant_id": tenant_id})
        raise


# ---------------------------------------------------------------------------
# WhatsApp — Meta Cloud API
# ---------------------------------------------------------------------------

# Maps internal event_type → pre-approved WhatsApp template name
WA_TEMPLATE_MAP: dict[str, str] = {
    "shipment_update": "shipment_status_update",
    "payment_due": "payment_due_notification",
    "release_note_generated": "release_note_ready",
    "damage_claim_update": "damage_claim_update",
    "cbm_dispute_update": "cbm_dispute_update",
    "packing_list_approved": "packing_list_approved",
    "tenant_onboarded": "tenant_welcome",
    "tenant_suspended": "tenant_suspended",
}

_WA_MAX_PARAMS = 5


def build_wa_components(branding: dict[str, Any], template_data: dict[str, Any]) -> list[dict[str, Any]]:
    """Build WhatsApp template body components.

    First parameter is always the company name; subsequent params come from
    template_data values (in insertion order) up to _WA_MAX_PARAMS total.
    """
    params: list[dict[str, Any]] = [{"type": "text", "text": get_company_name(branding)}]
    for val in template_data.values():
        if len(params) >= _WA_MAX_PARAMS:
            break
        params.append({"type": "text", "text": str(val)})

    return [{"type": "body", "parameters": params}]


def send_whatsapp(
    phone: str,
    template_name: str,
    components: list[dict[str, Any]],
    tenant_id: str,
) -> bool:
    """Send a WhatsApp template message via Meta Cloud API. Raises on errors.

    Returns True on success, False if credentials missing.
    """
    phone_id = os.environ.get("META_WHATSAPP_PHONE_ID", "")
    access_token = os.environ.get("META_WHATSAPP_ACCESS_TOKEN", "")

    if not phone_id or not access_token:
        logger.warning(
            "WhatsApp credentials not configured — message not sent",
            extra={"tenant_id": tenant_id},
        )
        return False

    url = f"https://graph.facebook.com/v17.0/{phone_id}/messages"
    payload = json.dumps(
        {
            "messaging_product": "whatsapp",
            "to": phone,
            "type": "template",
            "template": {
                "name": template_name,
                "language": {"code": "en"},
                "components": components,
            },
        }
    ).encode("utf-8")

    req = urllib.request.Request(
        url,
        data=payload,
        headers={
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json",
        },
        method="POST",
    )

    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            resp_body = json.loads(resp.read())
            # 200 with a messages array means the message was accepted
            if resp_body.get("messages"):
                logger.info(
                    "WhatsApp message sent",
                    extra={"tenant_id": tenant_id},
                )
            return True
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        logger.error(
            "Meta WhatsApp HTTP error %s: %s",
            exc.code,
            body,
            extra={"tenant_id": tenant_id},
        )
        raise
    except Exception:
        logger.exception("Meta WhatsApp send failed", extra={"tenant_id": tenant_id})
        raise


# ---------------------------------------------------------------------------
# Email — Amazon SES
# ---------------------------------------------------------------------------

EMAIL_SUBJECTS: dict[str, str] = {
    "shipment_update": "Shipment status update",
    "payment_due": "Payment due for your shipment",
    "release_note_generated": "Release note ready for collection",
    "damage_claim_update": "Update on your damage claim",
    "cbm_dispute_update": "CBM dispute update",
    "packing_list_approved": "Your packing list has been approved",
    "tenant_onboarded": "Welcome to the platform",
    "tenant_suspended": "Account suspended",
}

_DEFAULT_EMAIL_SUBJECT = "Notification from your logistics provider"


def render_email_html(
    branding: dict[str, Any],
    event_type: str,
    recipient_name: str | None,
    template_data: dict[str, Any],
) -> str:
    """Render a tenant-branded HTML email body."""
    company_name = get_company_name(branding)
    color = get_primary_color(branding)
    greeting = f"Hello {recipient_name}," if recipient_name else "Hello,"

    rows = "".join(
        f"<tr>"
        f"<td style='padding:4px 8px;color:#555;font-size:13px;white-space:nowrap;'>"
        f"{k.replace('_', ' ').title()}"
        f"</td>"
        f"<td style='padding:4px 8px;font-size:13px;'>{v}</td>"
        f"</tr>"
        for k, v in template_data.items()
        if v is not None
    )
    table = f"<table style='border-collapse:collapse;width:100%;margin-top:12px;'>" f"{rows}</table>" if rows else ""

    return (
        "<!DOCTYPE html>"
        "<html><head><meta charset='UTF-8'></head>"
        "<body style='margin:0;padding:0;background:#f4f4f4;"
        "font-family:Arial,sans-serif;'>"
        "<table width='100%' cellpadding='0' cellspacing='0'"
        " style='background:#f4f4f4;'>"
        "<tr><td align='center' style='padding:20px;'>"
        "<table width='600' cellpadding='0' cellspacing='0'"
        " style='background:#ffffff;border-radius:8px;overflow:hidden;'>"
        f"<tr><td style='background:{color};padding:20px 24px;'>"
        f"<span style='color:#ffffff;font-size:20px;font-weight:bold;'>"
        f"{company_name}</span></td></tr>"
        "<tr><td style='padding:24px;'>"
        f"<p style='margin:0 0 16px 0;font-size:15px;color:#222;'>{greeting}</p>"
        f"{table}"
        f"<p style='margin:16px 0 0 0;font-size:12px;color:#888;'>"
        f"This is an automated notification from {company_name}.</p>"
        "</td></tr>"
        "</table>"
        "</td></tr></table>"
        "</body></html>"
    )


def render_email_text(
    branding: dict[str, Any],
    event_type: str,
    recipient_name: str | None,
    template_data: dict[str, Any],
) -> str:
    """Render a plain-text fallback email body."""
    company_name = get_company_name(branding)
    greeting = f"Hello {recipient_name}," if recipient_name else "Hello,"
    lines = [company_name, "", greeting, ""]
    for k, v in template_data.items():
        if v is not None:
            lines.append(f"  {k.replace('_', ' ').title()}: {v}")
    lines += ["", f"This is an automated notification from {company_name}."]
    return "\n".join(lines)


def send_email(
    to_email: str,
    to_name: str | None,
    subject: str,
    html_body: str,
    text_body: str,
    tenant_id: str,
) -> bool:
    """Send an email via Amazon SES. Raises on API errors.

    Returns True on success.
    """
    from_address = os.environ.get("SES_FROM_ADDRESS", "notifications@logistics.example.com")

    try:
        _get_ses().send_email(
            Source=from_address,
            Destination={"ToAddresses": [to_email]},
            Message={
                "Subject": {"Data": subject, "Charset": "UTF-8"},
                "Body": {
                    "Html": {"Data": html_body, "Charset": "UTF-8"},
                    "Text": {"Data": text_body, "Charset": "UTF-8"},
                },
            },
        )
        logger.info(
            "Email sent",
            extra={"tenant_id": tenant_id},
        )
        return True
    except Exception:
        logger.exception(
            "SES send_email failed",
            extra={"tenant_id": tenant_id, "to": to_email},
        )
        raise
