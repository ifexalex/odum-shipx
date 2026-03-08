"""Notification Lambda handlers.

Three separate Lambda entry points, each consuming from a dedicated SQS queue:
  - sms_handler      → SMS queue  (Africa's Talking)
  - whatsapp_handler → WhatsApp queue (Meta Cloud API)
  - email_handler    → Email queue (Amazon SES)

Each handler returns batchItemFailures so that only failed messages are
retried and routed to the DLQ after the queue's maxReceiveCount is reached.
These Lambdas run outside the VPC — no DB access is needed because all
message data (including tenant branding) is embedded in the SQS event payload.
"""

import json
import logging

from aws_xray_sdk.core import patch_all

from shared.logging_config import setup_logging
from shared.metering import record_usage

from . import service
from .tenant_branding import extract_branding

# Module-level init (runs once on cold start)
setup_logging()
patch_all()

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# SMS handler
# ---------------------------------------------------------------------------


def sms_handler(event: dict, context) -> dict:
    """SQS consumer for the SMS notification queue."""
    batch_item_failures = []
    for record in event.get("Records", []):
        msg_id = record.get("messageId", "unknown")
        try:
            body = json.loads(record["body"])
            _process_sms(body)
        except Exception:
            logger.exception(
                "SMS processing failed for message %s", msg_id
            )
            batch_item_failures.append({"itemIdentifier": msg_id})

    return {"batchItemFailures": batch_item_failures}


def _process_sms(body: dict) -> None:
    tenant_id = body.get("tenant_id", "")
    event_type = body.get("event_type", "")
    recipient = body.get("recipient") or {}
    phone = recipient.get("phone", "")
    branding = extract_branding(body)
    template_data = body.get("template_data") or {}

    if not phone:
        logger.warning(
            "SMS message missing recipient phone — skipping",
            extra={"tenant_id": tenant_id},
        )
        return

    message = service.format_sms(event_type, branding, template_data)
    service.send_sms(phone, message, tenant_id)
    record_usage(tenant_id, "sms_sent")


# ---------------------------------------------------------------------------
# WhatsApp handler
# ---------------------------------------------------------------------------


def whatsapp_handler(event: dict, context) -> dict:
    """SQS consumer for the WhatsApp notification queue."""
    batch_item_failures = []
    for record in event.get("Records", []):
        msg_id = record.get("messageId", "unknown")
        try:
            body = json.loads(record["body"])
            _process_whatsapp(body)
        except Exception:
            logger.exception(
                "WhatsApp processing failed for message %s", msg_id
            )
            batch_item_failures.append({"itemIdentifier": msg_id})

    return {"batchItemFailures": batch_item_failures}


def _process_whatsapp(body: dict) -> None:
    tenant_id = body.get("tenant_id", "")
    event_type = body.get("event_type", "")
    recipient = body.get("recipient") or {}
    phone = recipient.get("phone", "")
    branding = extract_branding(body)
    template_data = body.get("template_data") or {}

    if not phone:
        logger.warning(
            "WhatsApp message missing recipient phone — skipping",
            extra={"tenant_id": tenant_id},
        )
        return

    template_name = service.WA_TEMPLATE_MAP.get(event_type, "generic_notification")
    components = service.build_wa_components(branding, template_data)
    service.send_whatsapp(phone, template_name, components, tenant_id)
    record_usage(tenant_id, "whatsapp_sent")


# ---------------------------------------------------------------------------
# Email handler
# ---------------------------------------------------------------------------


def email_handler(event: dict, context) -> dict:
    """SQS consumer for the Email notification queue."""
    batch_item_failures = []
    for record in event.get("Records", []):
        msg_id = record.get("messageId", "unknown")
        try:
            body = json.loads(record["body"])
            _process_email(body)
        except Exception:
            logger.exception(
                "Email processing failed for message %s", msg_id
            )
            batch_item_failures.append({"itemIdentifier": msg_id})

    return {"batchItemFailures": batch_item_failures}


def _process_email(body: dict) -> None:
    tenant_id = body.get("tenant_id", "")
    event_type = body.get("event_type", "")
    recipient = body.get("recipient") or {}
    to_email = recipient.get("email", "")
    to_name = recipient.get("name")
    branding = extract_branding(body)
    template_data = body.get("template_data") or {}

    if not to_email:
        logger.warning(
            "Email message missing recipient email — skipping",
            extra={"tenant_id": tenant_id},
        )
        return

    subject = service.EMAIL_SUBJECTS.get(event_type, service._DEFAULT_EMAIL_SUBJECT)
    html_body = service.render_email_html(branding, event_type, to_name, template_data)
    text_body = service.render_email_text(branding, event_type, to_name, template_data)
    service.send_email(to_email, to_name, subject, html_body, text_body, tenant_id)
    record_usage(tenant_id, "emails_sent")


# ---------------------------------------------------------------------------
# WhatsApp webhook handler (Meta Cloud API verification + delivery status)
# ---------------------------------------------------------------------------


def webhook_handler(event: dict, context) -> dict:
    """HTTP Lambda for WhatsApp webhook verification and delivery status callbacks.

    Routes:
      GET  /v1/webhooks/whatsapp — Meta hub challenge verification
      POST /v1/webhooks/whatsapp — Delivery status updates
    """
    import json as _json
    import os as _os

    http = event.get("requestContext", {}).get("http", {})
    method = http.get("method", event.get("httpMethod", "GET"))

    if method == "GET":
        return _handle_whatsapp_verify(event)
    if method == "POST":
        return _handle_whatsapp_delivery_status(event)

    return {"statusCode": 405, "body": "Method Not Allowed"}


def _handle_whatsapp_verify(event: dict) -> dict:
    """Respond to Meta's hub challenge for webhook subscription."""
    import hmac
    import os
    params = event.get("queryStringParameters") or {}
    mode      = params.get("hub.mode", "")
    token     = params.get("hub.verify_token", "")
    challenge = params.get("hub.challenge", "")

    verify_token = os.environ.get("WHATSAPP_VERIFY_TOKEN", "")
    if mode == "subscribe" and verify_token and hmac.compare_digest(token, verify_token):
        logger.info("WhatsApp webhook verified successfully")
        return {"statusCode": 200, "body": challenge}

    logger.warning("WhatsApp webhook verification failed: mode=%s", mode)
    return {"statusCode": 403, "body": "Forbidden"}


def _handle_whatsapp_delivery_status(event: dict) -> dict:
    """Process delivery status updates from Meta Cloud API."""
    import json as _json
    try:
        body = _json.loads(event.get("body") or "{}")
        # Meta sends statuses in body.entry[].changes[].value.statuses[]
        for entry in body.get("entry", []):
            for change in entry.get("changes", []):
                value = change.get("value", {})
                for status_obj in value.get("statuses", []):
                    msg_id    = status_obj.get("id", "")
                    status    = status_obj.get("status", "")
                    timestamp = status_obj.get("timestamp", "")
                    logger.info(
                        "WhatsApp delivery status: msg=%s status=%s ts=%s",
                        msg_id, status, timestamp,
                    )
    except Exception:
        logger.exception("Failed to process WhatsApp delivery status")

    # Always return 200 to prevent Meta from retrying
    return {"statusCode": 200, "body": "OK"}
