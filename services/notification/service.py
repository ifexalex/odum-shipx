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
    "container_arrived": (
        "{company_name}: Your goods have arrived at our warehouse! "
        "Container {container_number}. Your invoice is being prepared."
    ),
    "customer_registered": ("{company_name}: Welcome! Your account is ready. Check your email to set your password."),
    "customer_invite": (
        "{company_name}: Hi {name}, create your account to track your shipments: {invite_link} " "(link expires in 48 hours)"
    ),
    "payment_claim_confirmed": ("{company_name}: Your payment of NGN {amount_ngn} has been confirmed. Thank you!"),
    "payment_claim_rejected": (
        "{company_name}: Your payment claim of NGN {amount_ngn} was not confirmed. "
        "Reason: {reason}. Please contact us or resubmit with correct evidence."
    ),
    "damage_claim_update": ("{company_name}: Your damage claim {claim_reference} is now {status}."),
    "packing_list_approved": ("{company_name}: Your packing list {reference} has been approved."),
}

_DEFAULT_SMS_TEMPLATE = "{company_name}: You have a new notification."

_SMS_TEMPLATES_ZH: dict[str, str] = {
    "shipment_update": "{company_name}: 您的货物 {tracking_code} 当前状态：{status}。",
    "payment_due": (
        "{company_name}: 集装箱 {container_number} 已抵达。" "应付金额：{currency} {amount}。提货地址：{warehouse_address}"
    ),
    "release_note_generated": "{company_name}: 提货单已生成。单号：{reference_number}，共 {carton_count} 件。",
    "container_arrived": "{company_name}: 您的货物已到达仓库！集装箱 {container_number}，正在准备账单。",
    "customer_registered": "{company_name}: 欢迎！您的账户已创建。请查收邮件以设置密码。",
    "customer_invite": "{company_name}: 您好 {name}，创建账户以跟踪您的货物：{invite_link}（链接48小时后失效）",
    "payment_claim_confirmed": "{company_name}: 您的付款 NGN {amount_ngn} 已确认。谢谢！",
    "payment_claim_rejected": (
        "{company_name}: 您的付款申报 NGN {amount_ngn} 未通过确认。" "原因：{reason}。请联系我们或重新提交正确的凭证。"
    ),
    "damage_claim_update": "{company_name}: 您的损坏索赔 {claim_reference} 当前状态：{status}。",
    "packing_list_approved": "{company_name}: 您的装箱单 {reference} 已获批准。",
}
_DEFAULT_SMS_TEMPLATE_ZH = "{company_name}: 您有一条新通知。"

# Maps event_type → ZH WhatsApp pre-approved template name (Meta must approve each)
WA_TEMPLATE_MAP_ZH: dict[str, str] = {
    "shipment_update": "shipment_status_update_zh",
    "payment_due": "payment_due_notification_zh",
    "release_note_generated": "release_note_ready_zh",
    "damage_claim_update": "damage_claim_update_zh",
    "cbm_dispute_update": "cbm_dispute_update_zh",
    "packing_list_approved": "packing_list_approved_zh",
    "tenant_onboarded": "tenant_welcome_zh",
    "tenant_suspended": "tenant_suspended_zh",
    "container_arrived": "container_arrived_warehouse_zh",
    "customer_registered": "customer_welcome_zh",
    "customer_invite": "customer_invite_zh",
    "payment_claim_confirmed": "payment_claim_confirmed_zh",
    "payment_claim_rejected": "payment_claim_rejected_zh",
}


class _SafeFormatMap(dict):  # type: ignore[type-arg]
    """dict subclass that returns {key} for missing keys instead of raising."""

    def __missing__(self, key: str) -> str:
        return f"{{{key}}}"


def format_sms(
    event_type: str,
    branding: dict[str, Any],
    template_data: dict[str, Any],
    template_override: str | None = None,
    locale: str = "en",
) -> str:
    """Format an SMS message body. Uses tenant custom template when provided.

    Selects the ZH template set when locale == 'zh'; falls back to EN for all
    other locale values.
    """
    if template_override:
        template = template_override
    elif locale == "zh":
        template = _SMS_TEMPLATES_ZH.get(event_type, _DEFAULT_SMS_TEMPLATE_ZH)
    else:
        template = _SMS_TEMPLATES.get(event_type, _DEFAULT_SMS_TEMPLATE)
    data = _SafeFormatMap({"company_name": get_company_name(branding), **template_data})
    try:
        return template.format_map(data)
    except Exception:
        # A malformed template (bad placeholder/format spec) must never block a
        # notification — fall back to a safe generic message, but surface the
        # misconfiguration so it can be fixed.
        logger.warning("SMS template render failed for event %s; using generic fallback", event_type)
        company = get_company_name(branding)
        return f"{company}: You have a notification regarding your shipment."


def _assert_deliverable(phone_or_email: str, channel: str, tenant_id: str) -> bool:
    """Last line of defence before a real network send.

    The producer already filters recipients (shared/notifications.py), but that
    only covers messages queued *now*. A message queued earlier, a direct call
    to a send_* function, or a consumer replaying an old queue item would all
    bypass it — and this database holds real customer phone numbers imported
    from client manifests. Enforcing the same allowlist here means no code path
    can text a real customer from a non-production environment.
    """
    from shared.notifications import is_recipient_allowed

    field = "email" if channel == "email" else "phone"
    if is_recipient_allowed({field: phone_or_email}):
        return True
    logger.warning(
        "Blocked %s send to a non-allowlisted recipient outside production",
        channel,
        extra={"tenant_id": tenant_id},
    )
    return False


def send_sms(phone: str, message: str, tenant_id: str) -> bool:
    """Send an SMS via Africa's Talking. Raises on API errors.

    Returns True on confirmed delivery, False if credentials missing.
    """
    if not _assert_deliverable(phone, "sms", tenant_id):
        return False
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
class WhatsAppSendError(RuntimeError):
    """Meta rejected a WhatsApp send. Message carries Meta's code and reason."""


def _describe_meta_error(http_status: int, raw_body: str) -> str:
    """Summarise a Meta error response for notification_log.error_detail."""
    try:
        err = json.loads(raw_body).get("error", {})
    except json.JSONDecodeError:
        return f"Meta HTTP {http_status}"
    code = err.get("code", http_status)
    detail = (err.get("error_data") or {}).get("details") or err.get("message") or ""
    return f"Meta {code}: {detail}"[:400]


WA_TEMPLATE_MAP: dict[str, str] = {
    "shipment_update": "shipment_status_update",
    "payment_due": "payment_due_notification",
    "release_note_generated": "release_note_ready",
    "damage_claim_update": "damage_claim_update",
    "cbm_dispute_update": "cbm_dispute_update",
    "packing_list_approved": "packing_list_approved",
    "tenant_onboarded": "tenant_welcome",
    "tenant_suspended": "tenant_suspended",
    "container_arrived": "container_arrived_warehouse",
    "customer_registered": "customer_welcome",
    "customer_invite": "customer_invite",
    "payment_claim_confirmed": "payment_claim_confirmed",
    "payment_claim_rejected": "payment_claim_rejected",
}

_WA_MAX_PARAMS = 5


# Which template_data keys fill {{2}}, {{3}}… for each event, in order.
# {{1}} is always the company name and is not listed here.
#
# Declared explicitly rather than taking template_data.values(): Meta matches
# parameters positionally and rejects a count mismatch (132000), so relying on
# dict insertion order meant adding a key to any template_data dict silently
# broke that event's WhatsApp send, and reordering keys silently swapped values
# between placeholders — a wrong message to a customer, with no error at all.
#
# Keep in step with docs/project docs/whatsapp_templates.md; a template whose
# declared parameters do not match the approved body will be rejected by Meta.
WA_TEMPLATE_PARAMS: dict[str, tuple[str, ...]] = {
    "customer_invite": ("name", "invite_link"),
    "customer_registered": ("name",),
    "container_arrived": ("container_number",),
    "shipment_update": ("tracking_code", "status"),
    "release_note_generated": ("reference_number", "carton_count"),
    "payment_due": ("container_number", "currency", "amount", "warehouse_address"),
    "damage_claim_update": ("claim_reference", "status"),
    "cbm_dispute_update": ("reference_number", "status"),
    "packing_list_approved": ("reference",),
    "tenant_onboarded": ("company_name",),
    "tenant_suspended": ("reason",),
    "payment_claim_confirmed": ("amount_ngn",),
    "payment_claim_rejected": ("amount_ngn", "reason"),
}


def build_wa_components(
    branding: dict[str, Any],
    template_data: dict[str, Any],
    event_type: str | None = None,
) -> list[dict[str, Any]]:
    """Build WhatsApp template body components.

    {{1}} is always the company name. When `event_type` has a declaration in
    WA_TEMPLATE_PARAMS, the remaining placeholders are filled from those keys in
    that exact order — so the parameter count is a property of the template, not
    of whatever the caller happened to put in template_data.

    Falls back to insertion order for an undeclared event, preserving the old
    behaviour rather than sending nothing.
    """
    params: list[dict[str, Any]] = [{"type": "text", "text": get_company_name(branding)}]

    declared = WA_TEMPLATE_PARAMS.get(event_type or "")
    if declared is not None:
        # A missing key becomes an empty string: Meta rejects the whole message
        # if the parameter count is short, so a blank is better than no message.
        values: list[Any] = [template_data.get(key, "") for key in declared]
    else:
        values = list(template_data.values())

    for val in values:
        if len(params) >= _WA_MAX_PARAMS:
            break
        params.append({"type": "text", "text": str(val)})

    return [{"type": "body", "parameters": params}]


# Meta template language codes. Templates are registered per language, and a
# request must ask for the exact code the template was approved under — Meta's
# own samples (hello_world) are en_US, not en. Overridable because a tenant may
# register its templates under a different English variant.
_WA_DEFAULT_LANG = os.environ.get("META_WHATSAPP_TEMPLATE_LANG", "en_US")
_WA_LOCALE_LANG = {"en": _WA_DEFAULT_LANG, "zh": "zh_CN"}


def wa_language_code(locale: str | None) -> str:
    """Meta language code for a ShipX locale."""
    return _WA_LOCALE_LANG.get((locale or "en").lower(), _WA_DEFAULT_LANG)


def send_whatsapp(
    phone: str,
    template_name: str,
    components: list[dict[str, Any]],
    tenant_id: str,
    language_code: str | None = None,
) -> str:
    """Send a WhatsApp template message via Meta Cloud API. Raises on errors.

    Returns Meta's message id, or "" when credentials are missing. The id is
    what the delivery-status webhook matches on, so it must be stored.
    """
    if not _assert_deliverable(phone, "whatsapp", tenant_id):
        return ""
    phone_id = os.environ.get("META_WHATSAPP_PHONE_ID", "")
    access_token = os.environ.get("META_WHATSAPP_ACCESS_TOKEN", "")

    if not phone_id or not access_token:
        logger.warning(
            "WhatsApp credentials not configured — message not sent",
            extra={"tenant_id": tenant_id},
        )
        return ""

    url = f"https://graph.facebook.com/v17.0/{phone_id}/messages"
    payload = json.dumps(
        {
            "messaging_product": "whatsapp",
            "to": phone,
            "type": "template",
            "template": {
                "name": template_name,
                # Was hardcoded "en", so Meta's en_US templates 404'd and the
                # zh template map (WA_TEMPLATE_MAP_ZH) could never resolve.
                "language": {"code": language_code or _WA_DEFAULT_LANG},
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
            # 200 with a messages array means Meta accepted the message. Return
            # its id: the delivery-status webhook matches rows by
            # provider_message_id, so discarding it (as this used to) meant
            # every delivered/read/failed callback silently matched nothing —
            # and SMS fallback on a failed delivery could never fire.
            messages = resp_body.get("messages") or []
            message_id = str(messages[0].get("id", "")) if messages else ""
            if messages:
                logger.info("WhatsApp message accepted", extra={"tenant_id": tenant_id})
            return message_id
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        logger.error(
            "Meta WhatsApp HTTP error %s: %s",
            exc.code,
            body,
            extra={"tenant_id": tenant_id},
        )
        # Re-raised with Meta's own code and message so notification_log records
        # *why* a send failed ("132001 template does not exist in en_US") rather
        # than a generic "raised an exception", which told staff nothing and
        # made every failure look alike. Meta's error body carries no PII.
        raise WhatsAppSendError(_describe_meta_error(exc.code, body)) from exc
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
    "container_arrived": "Your goods have arrived at the warehouse",
    "customer_registered": "Welcome — your account is ready",
    "customer_invite": "Create your account to track your shipment",
    "payment_claim_confirmed": "Your payment has been confirmed",
    "payment_claim_rejected": "Your payment claim needs attention",
}

_DEFAULT_EMAIL_SUBJECT = "Notification from your logistics provider"

EMAIL_SUBJECTS_ZH: dict[str, str] = {
    "shipment_update": "货运状态更新",
    "payment_due": "您的货物付款通知",
    "release_note_generated": "提货单已生成",
    "damage_claim_update": "损坏索赔更新",
    "cbm_dispute_update": "CBM争议更新",
    "packing_list_approved": "装箱单已审批",
    "tenant_onboarded": "欢迎加入平台",
    "tenant_suspended": "账户已暂停",
    "container_arrived": "您的货物已到达仓库",
    "customer_registered": "欢迎 — 您的账户已准备就绪",
    "customer_invite": "创建账户以跟踪您的货物",
    "payment_claim_confirmed": "您的付款已确认",
    "payment_claim_rejected": "您的付款申报需要关注",
}
_DEFAULT_EMAIL_SUBJECT_ZH = "来自您的物流服务商的通知"


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
    if not _assert_deliverable(to_email, "email", tenant_id):
        return False
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


# ---------------------------------------------------------------------------
# Notification log service functions
# ---------------------------------------------------------------------------


def log_queued(
    tenant_id: str,
    channel: str,
    event_type: str,
    recipient_raw: str,
    recipient_name: str | None,
    customer_id: str | None,
    template_data: dict[str, Any],
    retry_of: str | None = None,
    message_body: str | None = None,
    locale: str = "en",
) -> str | None:
    """Insert a 'queued' notification_log row; return its id or None on failure.

    Never raises — logging failures must not interrupt the send path.
    """
    try:
        from . import repository as repo

        masked = repo.mask_email(recipient_raw) if "@" in recipient_raw else repo.mask_phone(recipient_raw)
        row = repo.insert_log(
            tenant_id,
            {
                "tenant_id": tenant_id,
                "event_type": event_type,
                "channel": channel,
                "recipient_masked": masked,
                "recipient_name": recipient_name,
                "customer_id": customer_id,
                "status": "queued",
                "provider": None,
                "provider_message_id": None,
                "gateway_response": None,
                "error_detail": None,
                "retry_of": retry_of,
                "template_data": json.dumps(template_data),
                "message_body": message_body,
                # Persisted so an SMS falling back from a failed WhatsApp send
                # is rendered in the recipient's language, not always English.
                "locale": locale,
            },
        )
        return str(row["id"]) if row else None
    except Exception as exc:
        logger.warning("notification_log insert failed (queued): %s", exc)
        return None


def log_sent(
    tenant_id: str,
    log_id: str | None,
    provider: str,
    provider_message_id: str,
    gateway_response: dict[str, Any],
) -> None:
    """Mark an existing notification_log row as 'sent'. Silent on failure."""
    if not log_id:
        return
    try:
        from . import repository as repo

        repo.mark_sent(
            tenant_id,
            log_id,
            provider,
            provider_message_id,
            json.dumps(gateway_response),
        )
    except Exception as exc:
        logger.warning("notification_log update failed (sent): %s", exc)


def log_failed(
    tenant_id: str,
    log_id: str | None,
    error_detail: str,
    gateway_response: dict[str, Any] | None = None,
) -> None:
    """Mark an existing notification_log row as 'failed'. Silent on failure."""
    if not log_id:
        return
    try:
        from . import repository as repo

        repo.mark_failed(
            tenant_id,
            log_id,
            error_detail,
            json.dumps(gateway_response) if gateway_response else None,
        )
    except Exception as exc:
        logger.warning("notification_log update failed (failed): %s", exc)


def trigger_sms_fallback(tenant_id: str, whatsapp_log_id: str, reason: str) -> bool:
    """Queue an SMS because a WhatsApp message could not be delivered.

    WhatsApp is the primary channel (most customers are reached there), so SMS
    is now an exception path rather than a parallel send. Two things can fail:
    Meta rejecting the send outright, and Meta accepting it then reporting
    `failed` later via the status webhook. Both call this, so it must be
    idempotent — otherwise a number with no WhatsApp account gets two texts.

    The guard is the existing `retry_of` column: a fallback SMS records the
    WhatsApp log row it replaces, so a second attempt finds it and stops. The
    recipient's phone is read from the linked customer rather than the log,
    because notification_log deliberately stores only a masked contact.

    Returns True when an SMS was queued.
    """
    import json as _json
    import os as _os

    from . import repository as repo

    log_row = repo.get_log_for_fallback(tenant_id, whatsapp_log_id)
    if not log_row:
        logger.warning("SMS fallback: no notification_log row %s", whatsapp_log_id)
        return False
    if repo.fallback_already_sent(tenant_id, whatsapp_log_id):
        logger.info("SMS fallback already sent for %s — skipping", whatsapp_log_id)
        return False

    customer_id = log_row.get("customer_id")
    phone = repo.get_customer_phone(tenant_id, str(customer_id)) if customer_id else None
    if not phone:
        logger.warning(
            "SMS fallback: no phone for notification_log %s (customer_id=%s)",
            whatsapp_log_id,
            customer_id,
        )
        return False

    queue_url = _os.environ.get("SQS_SMS_QUEUE_URL", "")
    if not queue_url:
        logger.warning("SMS fallback: SQS_SMS_QUEUE_URL not set")
        return False

    from shared.notifications import _get_sqs, is_recipient_allowed

    recipient = {"phone": phone, "name": log_row.get("recipient_name")}
    # The non-production recipient guard applies to fallbacks too — a dev
    # environment must not text a real customer just because WhatsApp failed.
    if not is_recipient_allowed(recipient):
        logger.warning("SMS fallback suppressed outside production for log %s", whatsapp_log_id)
        return False

    body = {
        "tenant_id": tenant_id,
        "event_type": log_row.get("event_type", ""),
        "channel": "sms",
        "recipient": recipient,
        "customer_id": str(customer_id) if customer_id else None,
        "template_data": log_row.get("template_data") or {},
        "locale": log_row.get("locale") or "en",
        "_retry_of_log_id": whatsapp_log_id,
        "_fallback_reason": reason,
    }
    try:
        _get_sqs().send_message(QueueUrl=queue_url, MessageBody=_json.dumps(body, default=str))
    except Exception:
        logger.exception("SMS fallback enqueue failed for log %s", whatsapp_log_id)
        return False

    logger.info("SMS fallback queued for log %s (reason=%s)", whatsapp_log_id, reason)
    return True


def retry_notification(
    tenant_id: str,
    log_id: str,
    actor_id: str,
) -> dict[str, Any]:
    """Re-enqueue a failed notification_log row to its SQS channel.

    Creates a new 'queued' log row linked via retry_of, and writes an audit
    record. Raises ResourceNotFoundError if the log does not exist, and
    BusinessRuleViolationError if it is not in 'failed' status.
    """
    from shared.audit import log_audit
    from shared.exceptions import BusinessRuleViolationError, ResourceNotFoundError

    from . import repository as repo

    original = repo.get_log_by_id(tenant_id, log_id)
    if not original:
        raise ResourceNotFoundError("notification_log", log_id)
    if original["status"] != "failed":
        raise BusinessRuleViolationError(
            f"Only 'failed' notifications can be retried; current status is '{original['status']}'",
            rule_id="NOTIFICATION_NOT_FAILED",
        )

    channel = original["channel"]
    queue_url_env_map = {
        "sms": "SQS_SMS_QUEUE_URL",
        "whatsapp": "SQS_WHATSAPP_QUEUE_URL",
        "email": "SQS_EMAIL_QUEUE_URL",
    }
    queue_url = os.environ.get(queue_url_env_map.get(channel, ""), "")
    if not queue_url:
        raise BusinessRuleViolationError(
            f"Queue URL not configured for channel '{channel}'",
            rule_id="QUEUE_URL_MISSING",
        )

    # Build the SQS payload from the original log's template_data
    template_data: dict[str, Any] = original.get("template_data") or {}
    sqs_body = json.dumps(
        {
            "tenant_id": tenant_id,
            "event_type": original["event_type"],
            "channel": channel,
            "recipient": {"masked": original.get("recipient_masked")},
            "template_data": template_data,
            "_retry_of_log_id": log_id,
        }
    )

    import boto3 as _boto3

    _boto3.client("sqs", region_name=os.environ.get("AWS_REGION", "eu-west-1")).send_message(
        QueueUrl=queue_url,
        MessageBody=sqs_body,
    )

    new_row = repo.insert_log(
        tenant_id,
        {
            "tenant_id": tenant_id,
            "event_type": original["event_type"],
            "channel": channel,
            "recipient_masked": original.get("recipient_masked"),
            "recipient_name": original.get("recipient_name"),
            "customer_id": original.get("customer_id") and str(original["customer_id"]),
            "status": "queued",
            "provider": None,
            "provider_message_id": None,
            "gateway_response": None,
            "error_detail": None,
            "retry_of": log_id,
            "template_data": json.dumps(template_data),
        },
    )

    log_audit(
        tenant_id=tenant_id,
        entity_type="notification_log",
        entity_id=log_id,
        action="RETRY",
        actor_id=actor_id,
        actor_role="tenant_admin",
        after_state={"new_log_id": str(new_row["id"]) if new_row else None, "channel": channel},
    )

    return {"new_log_id": str(new_row["id"]) if new_row else None, "original_log_id": log_id}


def get_log(tenant_id: str, log_id: str) -> dict[str, Any]:
    from shared.exceptions import ResourceNotFoundError

    from . import repository as repo

    row = repo.get_log_by_id(tenant_id, log_id)
    if not row:
        raise ResourceNotFoundError("notification_log", log_id)
    return dict(row)


def list_logs(
    tenant_id: str,
    filters: dict[str, Any],
    limit: int,
    cursor: dict[str, Any] | None,
) -> tuple[list[dict[str, Any]], str | None, bool]:
    from . import repository as repo

    return repo.list_logs(tenant_id, filters, limit, cursor)


# ---------------------------------------------------------------------------
# Staff notifications (in-app bell — migration 046)
# ---------------------------------------------------------------------------


def list_staff_notifications(
    tenant_id: str,
    user_id: str,
    role: str,
    limit: int,
    cursor: dict[str, Any] | None,
    unread_only: bool = False,
) -> tuple[list[dict[str, Any]], str | None, bool]:
    from . import repository as repo

    return repo.list_staff_notifications(tenant_id, user_id, role, limit, cursor, unread_only)


def count_unread_staff_notifications(tenant_id: str, user_id: str, role: str) -> dict[str, int]:
    from . import repository as repo

    return {"unread_count": repo.count_unread_staff_notifications(tenant_id, user_id, role)}


def mark_staff_notification_read(tenant_id: str, notification_id: str, user_id: str) -> dict[str, Any]:
    from shared.exceptions import ResourceNotFoundError

    from . import repository as repo

    notification = repo.get_staff_notification_by_id(tenant_id, notification_id)
    if not notification:
        raise ResourceNotFoundError("staff_notification", notification_id)
    row = repo.mark_staff_notification_read(tenant_id, notification_id, user_id)
    if row is None:
        raise RuntimeError("mark_staff_notification_read returned None unexpectedly")
    return dict(row)


def mark_all_staff_notifications_read(tenant_id: str, user_id: str, role: str) -> dict[str, int]:
    from . import repository as repo

    return {"marked_read": repo.mark_all_staff_notifications_read(tenant_id, user_id, role)}


def dismiss_staff_notification(tenant_id: str, notification_id: str, user_id: str) -> dict[str, Any]:
    from shared.exceptions import ResourceNotFoundError

    from . import repository as repo

    notification = repo.get_staff_notification_by_id(tenant_id, notification_id)
    if not notification:
        raise ResourceNotFoundError("staff_notification", notification_id)
    row = repo.mark_staff_notification_dismissed(tenant_id, notification_id, user_id)
    if row is None:
        raise RuntimeError("mark_staff_notification_dismissed returned None unexpectedly")
    return dict(row)


def dismiss_all_staff_notifications(tenant_id: str, user_id: str, role: str) -> dict[str, int]:
    from . import repository as repo

    return {"cleared": repo.dismiss_all_staff_notifications(tenant_id, user_id, role)}


# Every non-customer, non-platform role — mirrors handler.py's
# _STAFF_NOTIF_ROLES (kept as a separate list here since handler.py imports
# this module, not the other way around).
_ALL_STAFF_ROLES = ("tenant_admin", "nigeria_office_staff", "china_office_staff", "warehouse_attendant")


def _create_announcement_notifications(
    tenant_id: str,
    title: str,
    body: str | None,
    audience: str,
) -> list[dict[str, Any]]:
    """The actual `staff_notification` fan-out, shared by an immediate
    tenant_admin send and an approved staff request. "all_staff" is
    broadcast as one row per staff role (never a bare NULL/NULL row)
    specifically so it can never also match a customer's visibility query —
    the customer route checks the exact same `target_role = %(role)s`
    condition, and a NULL/NULL row is "visible to literally everyone"
    regardless of role. "all_customers" is the one target_role value a
    customer's own role actually equals, so it's naturally scoped to that
    audience alone.

    All rows from one call share a fresh `announcement_group_id` and are
    inserted with `banner_active=True` after first deactivating whatever was
    previously active for the same audience — direct user requirement:
    "more can be created but only one can be visible per time." A staff
    announcement's banner and a customer announcement's banner are
    independent audiences, so sending one never retires the other.
    """
    import uuid

    from . import repository as repo

    target_roles = list(_ALL_STAFF_ROLES) if audience == "all_staff" else ["customer"]
    repo.deactivate_active_banners_for_roles(tenant_id, target_roles)

    group_id = str(uuid.uuid4())
    created: list[dict[str, Any]] = []
    for role in target_roles:
        row = repo.create_staff_notification(
            tenant_id,
            event_type="announcement",
            entity_type="announcement",
            title=title,
            body=body,
            target_role=role,
            announcement_group_id=group_id,
            banner_active=True,
        )
        if row:
            created.append(dict(row))
    return created


def send_announcement(
    tenant_id: str,
    title: str,
    body: str | None,
    audience: str,
    actor_id: str,
    actor_role: str,
) -> dict[str, Any]:
    """A manual broadcast sent immediately — tenant_admin only, either
    audience. (A nigeria_office_staff customer announcement instead goes
    through request_announcement()/approve_announcement_request() below —
    held for review so a compromised staff account can't broadcast
    misinformation straight to customers.)
    """
    from shared.audit import log_audit

    created = _create_announcement_notifications(tenant_id, title, body, audience)

    # audit_log.entity_id is NOT NULL — only log when at least one
    # notification row actually exists to reference; nothing created means
    # every insert failed, which is a repository-layer exception already
    # propagating past this point, not a case that reaches here.
    if created:
        log_audit(
            tenant_id=tenant_id,
            entity_type="announcement",
            entity_id=str(created[0]["id"]),
            action="CREATE",
            actor_id=actor_id,
            actor_role=actor_role,
            after_state={"title": title, "audience": audience, "notification_count": len(created)},
        )
    return {"status": "sent", "audience": audience, "notifications_created": len(created)}


# ---------------------------------------------------------------------------
# Announcement requests (staff-composed customer announcements pending
# tenant_admin approval — migration 048)
# ---------------------------------------------------------------------------


def request_announcement(
    tenant_id: str,
    title: str,
    body: str | None,
    audience: str,
    actor_id: str,
) -> dict[str, Any]:
    """A nigeria_office_staff-composed customer announcement, held pending
    rather than sent immediately. Direct user requirement: "the staff can
    only send to customers, which should be approved by the tenant admins,
    this is to ensure that a compromised staff does not misinformation the
    customers." Notifies every tenant_admin so the review queue doesn't rely
    on someone remembering to check it.
    """
    from shared.audit import log_audit
    from shared.staff_notifications import notify_staff

    from . import repository as repo

    row = repo.create_announcement_request(tenant_id, title, body, audience, requested_by=actor_id)
    if row is None:
        raise RuntimeError("create_announcement_request returned None unexpectedly")
    row = dict(row)

    log_audit(
        tenant_id=tenant_id,
        entity_type="announcement_request",
        entity_id=str(row["id"]),
        action="CREATE",
        actor_id=actor_id,
        actor_role="nigeria_office_staff",
        after_state={"title": title, "audience": audience, "status": "pending"},
    )
    notify_staff(
        tenant_id=tenant_id,
        event_type="announcement_request_submitted",
        entity_type="announcement_request",
        entity_id=str(row["id"]),
        title="Announcement awaiting approval",
        body=f'"{title}" was submitted and needs your approval before it reaches customers.',
        target_role="tenant_admin",
    )
    return {"status": "pending", "request_id": str(row["id"]), "audience": audience}


def list_pending_announcement_requests(
    tenant_id: str,
    limit: int,
    cursor: dict[str, Any] | None,
) -> tuple[list[dict[str, Any]], str | None, bool]:
    from . import repository as repo

    return repo.list_pending_announcement_requests(tenant_id, limit, cursor)


def _get_pending_announcement_request(tenant_id: str, request_id: str) -> dict[str, Any]:
    from shared.exceptions import IllegalTransitionError, ResourceNotFoundError

    from . import repository as repo

    row = repo.get_announcement_request_by_id(tenant_id, request_id)
    if not row:
        raise ResourceNotFoundError("announcement_request", request_id)
    row = dict(row)
    if row["status"] != "pending":
        raise IllegalTransitionError(
            entity="announcement_request",
            current_state=row["status"],
            requested_state="reviewed",
            allowed=["pending"],
        )
    return row


def approve_announcement_request(tenant_id: str, request_id: str, actor_id: str, actor_role: str) -> dict[str, Any]:
    """Approving creates the real staff_notification row(s) — the pending
    request itself never reached a customer's bell — then notifies the
    original requester that it went out."""
    from shared.audit import log_audit
    from shared.staff_notifications import notify_staff

    from . import repository as repo

    request_row = _get_pending_announcement_request(tenant_id, request_id)
    created = _create_announcement_notifications(
        tenant_id,
        request_row["title"],
        request_row["body"],
        request_row["audience"],
    )

    reviewed = repo.mark_announcement_request_reviewed(tenant_id, request_id, "approved", reviewed_by=actor_id)
    if reviewed is None:
        raise RuntimeError("mark_announcement_request_reviewed returned None unexpectedly")

    log_audit(
        tenant_id=tenant_id,
        entity_type="announcement_request",
        entity_id=request_id,
        action="APPROVE",
        actor_id=actor_id,
        actor_role=actor_role,
        before_state={"status": "pending"},
        after_state={"status": "approved", "notification_count": len(created)},
    )
    notify_staff(
        tenant_id=tenant_id,
        event_type="announcement_request_approved",
        entity_type="announcement_request",
        entity_id=request_id,
        title="Your announcement was approved",
        body=f'"{request_row["title"]}" was approved and sent to customers.',
        target_user_id=str(request_row["requested_by"]),
    )
    return {"status": "approved", "audience": request_row["audience"], "notifications_created": len(created)}


def reject_announcement_request(
    tenant_id: str,
    request_id: str,
    actor_id: str,
    actor_role: str,
    reason: str | None = None,
) -> dict[str, Any]:
    from shared.audit import log_audit
    from shared.staff_notifications import notify_staff

    from . import repository as repo

    request_row = _get_pending_announcement_request(tenant_id, request_id)

    reviewed = repo.mark_announcement_request_reviewed(
        tenant_id,
        request_id,
        "rejected",
        reviewed_by=actor_id,
        rejection_reason=reason,
    )
    if reviewed is None:
        raise RuntimeError("mark_announcement_request_reviewed returned None unexpectedly")

    log_audit(
        tenant_id=tenant_id,
        entity_type="announcement_request",
        entity_id=request_id,
        action="REJECT",
        actor_id=actor_id,
        actor_role=actor_role,
        before_state={"status": "pending"},
        after_state={"status": "rejected", "reason": reason},
    )
    notification_body = f'"{request_row["title"]}" was not approved.'
    if reason:
        notification_body += f" Reason: {reason}"
    notify_staff(
        tenant_id=tenant_id,
        event_type="announcement_request_rejected",
        entity_type="announcement_request",
        entity_id=request_id,
        title="Your announcement was rejected",
        body=notification_body,
        target_user_id=str(request_row["requested_by"]),
    )
    return {"status": "rejected"}


# ---------------------------------------------------------------------------
# Announcement banners (migration 049)
# ---------------------------------------------------------------------------


def get_active_banner(tenant_id: str, user_id: str, role: str) -> dict[str, Any] | None:
    """The single announcement (if any) this viewer should currently see as
    a page banner, not just a bell entry."""
    from . import repository as repo

    row = repo.get_active_banner(tenant_id, user_id, role)
    return dict(row) if row else None


def list_announcements(tenant_id: str) -> list[dict[str, Any]]:
    """tenant_admin's management list — one entry per send, newest first,
    each showing whether its banner is currently active."""
    from . import repository as repo

    rows = repo.list_announcement_groups(tenant_id)
    return [
        {
            "announcement_group_id": str(r["announcement_group_id"]),
            "title": r["title"],
            "body": r["body"],
            "audience": "all_staff" if r["target_role"] != "customer" else "all_customers",
            "banner_active": r["banner_active"],
            "created_at": r["created_at"],
        }
        for r in rows
    ]


def deactivate_announcement(tenant_id: str, group_id: str, actor_id: str, actor_role: str) -> dict[str, Any]:
    from shared.audit import log_audit
    from shared.exceptions import ResourceNotFoundError

    from . import repository as repo

    updated = repo.set_banner_active_for_group(tenant_id, group_id, active=False)
    if updated == 0:
        raise ResourceNotFoundError("announcement", group_id)

    log_audit(
        tenant_id=tenant_id,
        entity_type="announcement",
        entity_id=group_id,
        action="DEACTIVATE",
        actor_id=actor_id,
        actor_role=actor_role,
        after_state={"banner_active": False},
    )
    return {"announcement_group_id": group_id, "banner_active": False}


def activate_announcement(tenant_id: str, group_id: str, actor_id: str, actor_role: str) -> dict[str, Any]:
    """Re-shows a past announcement's banner — first retiring whatever is
    currently active for the same audience, same "only one visible per
    time" rule a fresh send already follows."""
    from shared.audit import log_audit
    from shared.exceptions import ResourceNotFoundError

    from . import repository as repo

    target_roles = repo.get_announcement_group_target_roles(tenant_id, group_id)
    if not target_roles:
        raise ResourceNotFoundError("announcement", group_id)

    repo.deactivate_active_banners_for_roles(tenant_id, target_roles)
    updated = repo.set_banner_active_for_group(tenant_id, group_id, active=True)
    if updated == 0:
        raise ResourceNotFoundError("announcement", group_id)

    log_audit(
        tenant_id=tenant_id,
        entity_type="announcement",
        entity_id=group_id,
        action="ACTIVATE",
        actor_id=actor_id,
        actor_role=actor_role,
        after_state={"banner_active": True},
    )
    return {"announcement_group_id": group_id, "banner_active": True}


# ---------------------------------------------------------------------------
# Announcement CRUD (dedicated Announcements page — 2026-09-13)
# ---------------------------------------------------------------------------


def list_my_announcement_requests(tenant_id: str, requested_by: str) -> list[dict[str, Any]]:
    from . import repository as repo

    return [dict(r) for r in repo.list_my_announcement_requests(tenant_id, requested_by)]


def _get_own_pending_request(tenant_id: str, request_id: str, requested_by: str) -> dict[str, Any]:
    """Fetch-then-check so a wrong owner or a wrong status both surface as a
    plain 404 rather than leaking whether the id exists at all to someone
    who doesn't own it."""
    from shared.exceptions import ResourceNotFoundError

    from . import repository as repo

    row = repo.get_announcement_request_by_id(tenant_id, request_id)
    if not row or str(row["requested_by"]) != requested_by or row["status"] != "pending":
        raise ResourceNotFoundError("announcement_request", request_id)
    return dict(row)


def update_my_announcement_request(
    tenant_id: str,
    request_id: str,
    requested_by: str,
    title: str,
    body: str | None,
) -> dict[str, Any]:
    from . import repository as repo

    _get_own_pending_request(tenant_id, request_id, requested_by)
    row = repo.update_announcement_request(tenant_id, request_id, requested_by, title, body)
    if row is None:
        raise RuntimeError("update_announcement_request returned None unexpectedly")
    return dict(row)


def delete_my_announcement_request(tenant_id: str, request_id: str, requested_by: str) -> dict[str, Any]:
    from . import repository as repo

    _get_own_pending_request(tenant_id, request_id, requested_by)
    deleted = repo.delete_announcement_request(tenant_id, request_id, requested_by)
    if deleted == 0:
        raise RuntimeError("delete_announcement_request affected 0 rows unexpectedly")
    return {"deleted": True}


def update_announcement(
    tenant_id: str,
    group_id: str,
    title: str,
    body: str | None,
    actor_id: str,
    actor_role: str,
) -> dict[str, Any]:
    from shared.audit import log_audit
    from shared.exceptions import ResourceNotFoundError

    from . import repository as repo

    updated = repo.update_announcement_group(tenant_id, group_id, title, body)
    if updated == 0:
        raise ResourceNotFoundError("announcement", group_id)

    log_audit(
        tenant_id=tenant_id,
        entity_type="announcement",
        entity_id=group_id,
        action="UPDATE",
        actor_id=actor_id,
        actor_role=actor_role,
        after_state={"title": title, "body": body},
    )
    return {"announcement_group_id": group_id, "title": title, "body": body}


def delete_announcement(tenant_id: str, group_id: str, actor_id: str, actor_role: str) -> dict[str, Any]:
    from shared.audit import log_audit
    from shared.exceptions import ResourceNotFoundError

    from . import repository as repo

    deleted = repo.delete_announcement_group(tenant_id, group_id)
    if deleted == 0:
        raise ResourceNotFoundError("announcement", group_id)

    log_audit(
        tenant_id=tenant_id,
        entity_type="announcement",
        entity_id=group_id,
        action="DELETE",
        actor_id=actor_id,
        actor_role=actor_role,
        before_state={"deleted": True},
    )
    return {"deleted": True}
