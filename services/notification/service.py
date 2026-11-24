"""Channel-specific send logic for the Notification service.

Three channels:
  - SMS via Africa's Talking API
  - WhatsApp via Meta Cloud API (pre-approved templates)
  - Email via Amazon SES (tenant-branded HTML)

All send functions raise on hard failures so that the SQS handler can
return the message ID in batchItemFailures and let SQS retry / DLQ.
"""

import html
import json
import logging
import os
import re
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

from shared.observability import record_outcome
from shared.providers import get_email_provider, get_queue_provider

from .tenant_branding import (
    get_company_name,
    get_document_footer,
    get_primary_color,
    get_support_email,
    get_support_whatsapp,
    get_tagline,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# SMS — Africa's Talking
# ---------------------------------------------------------------------------

_SMS_TEMPLATES: dict[str, str] = {
    "shipment_update": ("{company_name}: Your shipment {tracking_code} is now {status}."),
    "payment_due": (
        "{company_name}: Container {container_number} arrived. Amount: {currency} {amount}. Pickup: {warehouse_address}"
    ),
    "release_note_generated": ("{company_name}: Release note ready. Ref: {reference_number}. Collect {carton_count} cartons."),
    "pickup_code_issued": (
        "{company_name}: Pickup code for release note {reference_number}: {pickup_code}. "
        "Give it to the person collecting your goods. Do not share it with anyone else."
    ),
    "container_arrived": (
        "{company_name}: Your goods have arrived at our warehouse! Container {container_number}. Your invoice is being prepared."
    ),
    "customer_registered": ("{company_name}: Welcome! Your account is ready. Check your email to set your password."),
    "customer_invite": (
        "{company_name}: Hi {name}, create your account to track your shipments: {invite_link} (link expires in 48 hours)"
    ),
    "account_activation": (
        "{company_name}: Hi {name}, activate your account and set your password: {activation_link} (link expires in 48 hours)"
    ),
    "payment_claim_confirmed": ("{company_name}: Your payment of NGN {amount_ngn} has been confirmed. Thank you!"),
    "payment_claim_rejected": (
        "{company_name}: Your payment claim of NGN {amount_ngn} was not confirmed. "
        "Reason: {reason}. Please contact us or resubmit with correct evidence."
    ),
    "damage_claim_update": ("{company_name}: Your damage claim {claim_reference} is now {status}."),
    "cbm_dispute_update": ("{company_name}: Your CBM dispute {reference_number} is now {status}."),
    "packing_list_approved": ("{company_name}: Your packing list {reference} has been approved."),
    "storage_first_reminder": (
        "{company_name}: Reminder: Release note {reference_number} ({carton_count} cartons) is ready for pickup. "
        "{days_remaining} days of free storage remaining."
    ),
    "storage_final_reminder": (
        "{company_name}: Final reminder: Release note {reference_number} ({carton_count} cartons) has 1 day of free "
        "storage remaining. Storage fees begin tomorrow."
    ),
    "release_note_expired": (
        "{company_name}: Release note {reference_number} expired on {valid_until}. "
        "Please contact us to reissue your release note."
    ),
}

_DEFAULT_SMS_TEMPLATE = "{company_name}: You have a new notification."

_SMS_TEMPLATES_ZH: dict[str, str] = {
    "shipment_update": "{company_name}: 您的货物 {tracking_code} 当前状态：{status}。",
    "payment_due": (
        "{company_name}: 集装箱 {container_number} 已抵达。应付金额：{currency} {amount}。提货地址：{warehouse_address}"
    ),
    "release_note_generated": "{company_name}: 提货单已生成。单号：{reference_number}，共 {carton_count} 件。",
    "pickup_code_issued": (
        "{company_name}: 提货单 {reference_number} 的取货码：{pickup_code}。请仅告知前来提货的人，切勿告知他人。"
    ),
    "container_arrived": "{company_name}: 您的货物已到达仓库！集装箱 {container_number}，正在准备账单。",
    "customer_registered": "{company_name}: 欢迎！您的账户已创建。请查收邮件以设置密码。",
    "customer_invite": "{company_name}: 您好 {name}，创建账户以跟踪您的货物：{invite_link}（链接48小时后失效）",
    "account_activation": "{company_name}: 您好 {name}，激活账户并设置密码：{activation_link}（链接48小时后失效）",
    "payment_claim_confirmed": "{company_name}: 您的付款 NGN {amount_ngn} 已确认。谢谢！",
    "payment_claim_rejected": (
        "{company_name}: 您的付款申报 NGN {amount_ngn} 未通过确认。原因：{reason}。请联系我们或重新提交正确的凭证。"
    ),
    "damage_claim_update": "{company_name}: 您的损坏索赔 {claim_reference} 当前状态：{status}。",
    "cbm_dispute_update": "{company_name}: 您的CBM争议 {reference_number} 当前状态：{status}。",
    "packing_list_approved": "{company_name}: 您的装箱单 {reference} 已获批准。",
    "storage_first_reminder": (
        "{company_name}: 提醒：提货单 {reference_number}（共 {carton_count} 件）待提货，免费仓储还剩 {days_remaining} 天。"
    ),
    "storage_final_reminder": (
        "{company_name}: 最后提醒：提货单 {reference_number}（共 {carton_count} 件）免费仓储明日结束，明日起将产生仓储费。"
    ),
    "release_note_expired": "{company_name}: 提货单 {reference_number} 已于 {valid_until} 过期，请联系我们重新签发。",
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
    "storage_first_reminder": "storage_first_reminder_zh",
    "storage_final_reminder": "storage_final_reminder_zh",
    "release_note_expired": "release_note_expired_zh",
}


class _SafeFormatMap(dict):  # type: ignore[type-arg]
    """dict subclass that returns {key} for missing keys instead of raising."""

    def __missing__(self, key: str) -> str:
        return f"{{{key}}}"


_PLACEHOLDER_RE = re.compile(r"\{([a-zA-Z0-9_]+)\}")


def _safe_substitute(template: str, data: dict[str, Any]) -> str:
    """Safely substitute {identifier} placeholders without attribute or index traversal."""
    stripped = _PLACEHOLDER_RE.sub("", template)
    if "{" in stripped or "}" in stripped:
        raise ValueError("Malformed or disallowed placeholder in template")
    return _PLACEHOLDER_RE.sub(
        lambda m: str(data[m.group(1)]) if m.group(1) in data and data[m.group(1)] is not None else m.group(0),
        template,
    )


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
    data = {"company_name": get_company_name(branding), **template_data}
    try:
        return _safe_substitute(template, data)
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


_AT_SANDBOX_USERNAME = "sandbox"
_PLACEHOLDER_FROM_ADDRESS = "notifications@logistics.example.com"

# Matches the AWS/Azure guards and shared/notifications.py: every tfvars file
# sets environment = "prod", and that value also feeds resource name prefixes,
# so it cannot be renamed. Both spellings are accepted deliberately.
_PRODUCTION_ENVIRONMENTS = frozenset({"production", "prod"})

# Digit runs long enough to be a phone number. Provider error payloads echo the
# recipient, and a phone number in CloudWatch is a GDPR problem regardless of
# which vendor put it there.
_LONG_DIGIT_RUN = re.compile(r"\+?\d[\d\s-]{6,}\d")


def _is_production() -> bool:
    """True when this is a production deployment (see _PRODUCTION_ENVIRONMENTS)."""
    return os.environ.get("ENVIRONMENT", "").strip().lower() in _PRODUCTION_ENVIRONMENTS


def _redact_provider_error(body: str) -> str:
    """Strip anything phone-number-shaped from a provider error body.

    Truncated as well as redacted: these payloads can be an entire HTML error
    page, and a log line is not the place for one.
    """
    return _LONG_DIGIT_RUN.sub("[redacted]", body)[:400]


def send_sms(phone: str, message: str, tenant_id: str) -> bool:
    """Send an SMS via Africa's Talking. Raises on API errors.

    Returns True on confirmed delivery, False if credentials missing.
    """
    if not _assert_deliverable(phone, "sms", tenant_id):
        return False
    api_key = os.environ.get("AFRICASTALKING_API_KEY", "")
    username = os.environ.get("AFRICASTALKING_USERNAME", "").strip() or _AT_SANDBOX_USERNAME
    sender_id = os.environ.get("AFRICASTALKING_SENDER_ID", "")

    if not api_key:
        logger.error(
            "AFRICASTALKING_API_KEY not configured — no SMS can be sent in this environment",
            extra={"tenant_id": tenant_id},
        )
        return False

    if username == _AT_SANDBOX_USERNAME and _is_production():
        # Africa's Talking accepts sandbox traffic and delivers none of it, with
        # a success-shaped response. In production that is indistinguishable
        # from working until a customer says they got nothing, so refuse.
        logger.error(
            "AFRICASTALKING_USERNAME is '%s' in production — refusing to send, nothing would be delivered",
            _AT_SANDBOX_USERNAME,
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
        # Africa's Talking echoes the recipient MSISDN in its error payloads, so
        # the body is not loggable: phone numbers are PII and must never reach
        # CloudWatch. The status code plus the provider's own error name is what
        # an operator needs anyway.
        body = exc.read().decode("utf-8", errors="replace")
        logger.error(
            "Africa's Talking HTTP error %s: %s",
            exc.code,
            _redact_provider_error(body),
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
    "storage_first_reminder": "storage_first_reminder",
    "storage_final_reminder": "storage_final_reminder",
    "release_note_expired": "release_note_expired",
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
    "storage_first_reminder": ("reference_number", "carton_count", "days_remaining"),
    "storage_final_reminder": ("reference_number", "carton_count"),
    "release_note_expired": ("reference_number", "valid_until"),
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
        # ERROR, not WARNING: WhatsApp is the primary customer channel here, so
        # "not configured" means the main way customers are contacted is dead.
        logger.error(
            "WhatsApp credentials not configured — no WhatsApp message can be sent in this environment",
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
    "pickup_code_issued": "Your pickup code",
    "damage_claim_update": "Update on your damage claim",
    "cbm_dispute_update": "CBM dispute update",
    "packing_list_approved": "Your packing list has been approved",
    "tenant_onboarded": "Welcome to the platform",
    "tenant_suspended": "Account suspended",
    "container_arrived": "Your goods have arrived at the warehouse",
    "customer_registered": "Welcome — your account is ready",
    "customer_invite": "Create your account to track your shipment",
    "account_activation": "Activate your account — set your password",
    "registration_existing_account": "You already have an account",
    "payment_claim_confirmed": "Your payment has been confirmed",
    "payment_claim_rejected": "Your payment claim needs attention",
    "storage_first_reminder": "Reminder: Goods ready for pickup",
    "storage_final_reminder": "Final reminder: Storage fees begin tomorrow",
    "release_note_expired": "Release note expired",
}

_DEFAULT_EMAIL_SUBJECT = "Notification from your logistics provider"

EMAIL_SUBJECTS_ZH: dict[str, str] = {
    "shipment_update": "货运状态更新",
    "payment_due": "您的货物付款通知",
    "release_note_generated": "提货单已生成",
    "pickup_code_issued": "您的取货码",
    "damage_claim_update": "损坏索赔更新",
    "cbm_dispute_update": "CBM争议更新",
    "packing_list_approved": "装箱单已审批",
    "tenant_onboarded": "欢迎加入平台",
    "tenant_suspended": "账户已暂停",
    "container_arrived": "您的货物已到达仓库",
    "customer_registered": "欢迎 — 您的账户已准备就绪",
    "customer_invite": "创建账户以跟踪您的货物",
    "account_activation": "激活账户 — 设置您的密码",
    "registration_existing_account": "您已拥有账户",
    "payment_claim_confirmed": "您的付款已确认",
    "payment_claim_rejected": "您的付款申报需要关注",
    "storage_first_reminder": "提货提醒：免费仓储即将到期",
    "storage_final_reminder": "最后提醒：明日起将产生仓储费",
    "release_note_expired": "提货单已过期",
}
_DEFAULT_EMAIL_SUBJECT_ZH = "来自您的物流服务商的通知"


# Lead paragraph per event. Email was previously a greeting, a CTA button and a
# raw dump of every template_data key as "Label: value" rows — so a customer
# being invited to create an account received a header, a button and the single
# row "Name: Ngozi", with nothing saying what the message was about or why they
# had received it. These say it, in the recipient's own terms.
#
# Plain text, never HTML: values are HTML-escaped before substitution, so a
# template that carried its own markup would have no safe way to be rendered.
_EMAIL_BODIES: dict[str, str] = {
    "customer_invite": (
        "{company_name} has created an account for you so you can track your shipments, "
        "see what you owe and download your release notes. "
        "Use the button below to choose a password and finish setting it up. "
        "The link expires in 48 hours — if it does, ask us to send a new one."
    ),
    # The code itself is in the details table below this paragraph. The wording is about what it is for, because
    # the person reading it may be handing it to someone else.
    "pickup_code_issued": (
        "{company_name} has issued a pickup code for your release note. Whoever collects your goods must give the "
        "warehouse this code, so give it only to the person you send to collect them. Keep it private: we will "
        "never ask you for it."
    ),
    "account_activation": (
        "An account has been created for you on {company_name}'s logistics portal. "
        "Use the button below to set your password and sign in. "
        "The link expires in 48 hours."
    ),
    "customer_registered": (
        "Welcome to {company_name}. Your account is ready — check your email for the link to set your password."
    ),
    # Sent when someone signs up with an address that already has an account. The sign-up form
    # answers identically either way (so it cannot be used to find out who is a customer), and this is
    # how the person who owns the address finds out. Deliberately says nothing about who tried.
    "registration_existing_account": (
        "Someone, possibly you, tried to create an account on {company_name}'s logistics portal with this "
        "email address, which already has one. You do not need to do anything. "
        'To get in, use the button below; if you have forgotten your password, choose "Forgot password" '
        "on the sign-in page. If this was not you, you can ignore this message."
    ),
    "shipment_update": "There is an update on your shipment with {company_name}. The details are below.",
    "container_arrived": (
        "Your goods have arrived at {company_name}'s warehouse. "
        "We are preparing your invoice and will be in touch about collection."
    ),
    "payment_due": (
        "Your shipment with {company_name} has arrived and payment is now due. The amount and collection address are below."
    ),
    "release_note_generated": (
        "Your release note is ready. Bring it with you — or quote the reference below — "
        "when you collect your goods from {company_name}."
    ),
    "packing_list_approved": "{company_name} has approved your packing list. The details are below.",
    "damage_claim_update": "There is an update on the damage claim you raised with {company_name}.",
    "cbm_dispute_update": "There is an update on the CBM measurement you queried with {company_name}.",
    "payment_claim_confirmed": ("{company_name} has confirmed your payment. Thank you — nothing further is needed."),
    "payment_claim_rejected": (
        "{company_name} could not confirm the payment you reported. The reason is below. "
        "Please get in touch, or resubmit with the correct proof of payment."
    ),
    "tenant_onboarded": "Your company's {company_name} account is set up and ready to use.",
    "tenant_suspended": "Your company's {company_name} account has been suspended. Please contact support.",
    "storage_first_reminder": (
        "Your goods with {company_name} are ready for collection. Please collect them before your free storage period ends."
    ),
    "storage_final_reminder": (
        "Your free storage period with {company_name} ends today. "
        "Storage fees will begin accruing tomorrow for uncollected cartons."
    ),
    "release_note_expired": (
        "Your release note with {company_name} has expired. Please contact us to have it reissued before collecting your goods."
    ),
}
_DEFAULT_EMAIL_BODY = "You have a new notification from {company_name}. The details are below."

_EMAIL_BODIES_ZH: dict[str, str] = {
    "customer_invite": (
        "{company_name} 已为您创建账户，您可以查询货物状态、应付金额并下载提货单。"
        "请点击下方按钮设置密码以完成开通。链接将在48小时后失效——如已失效，请联系我们重新发送。"
    ),
    "account_activation": ("{company_name} 物流平台已为您创建账户。请点击下方按钮设置密码并登录。链接将在48小时后失效。"),
    "pickup_code_issued": (
        "{company_name} 已为您的提货单生成取货码。提货人须向仓库出示此码，"
        "请仅告知您派去提货的人，并妥善保管：我们绝不会向您索要。"
    ),
    "customer_registered": "欢迎使用 {company_name}。您的账户已就绪——请查收邮件以设置密码。",
    "registration_existing_account": (
        "有人（可能是您本人）尝试使用此邮箱地址在 {company_name} 物流平台创建账户，但该邮箱已有账户。"
        "您无需任何操作。请点击下方按钮登录；如忘记密码，请在登录页选择“忘记密码”。如果这不是您本人操作，请忽略此邮件。"
    ),
    "shipment_update": "您在 {company_name} 的货物有新状态更新，详情如下。",
    "container_arrived": "您的货物已抵达 {company_name} 仓库。我们正在准备账单，并将与您联系提货事宜。",
    "payment_due": "您在 {company_name} 的货物已抵达，现需付款。金额与提货地址如下。",
    "release_note_generated": "您的提货单已生成。提货时请携带提货单或提供下方单号。",
    "packing_list_approved": "{company_name} 已批准您的装箱单，详情如下。",
    "damage_claim_update": "您向 {company_name} 提交的损坏索赔有新进展。",
    "cbm_dispute_update": "您向 {company_name} 提出的CBM测量异议有新进展。",
    "payment_claim_confirmed": "{company_name} 已确认您的付款。谢谢——无需其他操作。",
    "payment_claim_rejected": "{company_name} 未能确认您申报的付款，原因如下。请联系我们或重新提交正确的付款凭证。",
    "tenant_onboarded": "您公司的 {company_name} 账户已开通并可以使用。",
    "tenant_suspended": "您公司的 {company_name} 账户已被暂停，请联系客服。",
    "storage_first_reminder": "您在 {company_name} 的货物已可提货，请在免费仓储期结束前前往提取。",
    "storage_final_reminder": "您在 {company_name} 的免费仓储期今日结束，未提取货物自明日起将按日计收仓储费。",
    "release_note_expired": "您在 {company_name} 的提货单已过期，提货前请联系我们重新签发。",
}
_DEFAULT_EMAIL_BODY_ZH = "您有一条来自 {company_name} 的新通知，详情如下。"

# Keys that are plumbing, not information: already shown elsewhere in the
# message, or meaningless to the person reading it.
_HIDDEN_EMAIL_FIELDS = frozenset({"name", "company_name"})

_LINK_LABELS: dict[str, str] = {
    "activation_link": "Set your password",
    "invite_link": "Create your account",
    "login_link": "Sign in",
}
_LINK_LABELS_ZH: dict[str, str] = {
    "activation_link": "设置密码",
    "invite_link": "创建账户",
    "login_link": "登录",
}


def _field_label(key: str) -> str:
    """Human label for a template_data key, e.g. container_number → Container number."""
    words = key.replace("_", " ").strip()
    return words[:1].upper() + words[1:] if words else key


def _escaped(template_data: dict[str, Any], company_name: str) -> dict[str, str]:
    """Template data with every value HTML-escaped, for embedding in HTML.

    Values come from customer records, staff input and imported manifests. They
    were previously interpolated into the email body raw, so a name or reference
    containing `<` or `"` could break the layout or inject markup into a message
    sent under the tenant's name.
    """
    escaped = {k: html.escape(str(v), quote=True) for k, v in template_data.items() if v is not None}
    escaped.setdefault("company_name", html.escape(company_name, quote=True))
    return escaped


def _render_body_copy(
    event_type: str,
    locale: str,
    data: dict[str, str],
) -> str:
    """The lead paragraph for this event, with placeholders filled.

    Falls back to the generic lead if the event has no copy, or if the rendered
    result still contains an unresolved `{placeholder}` — a half-substituted
    sentence reads as a bug to the recipient, whereas the generic lead plus the
    details table below it is always accurate.
    """
    if locale == "zh":
        template = _EMAIL_BODIES_ZH.get(event_type, _DEFAULT_EMAIL_BODY_ZH)
        default = _DEFAULT_EMAIL_BODY_ZH
    else:
        template = _EMAIL_BODIES.get(event_type, _DEFAULT_EMAIL_BODY)
        default = _DEFAULT_EMAIL_BODY
    try:
        rendered = _safe_substitute(template, data)
    except Exception:
        logger.warning("Email body render failed for event %s; using generic copy", event_type)
        rendered = ""
    if not rendered or "{" in rendered:
        logger.warning("Email body for event %s had unresolved placeholders; using generic copy", event_type)
        rendered = _safe_substitute(default, data)
    return rendered


def _html_to_text(markup: str) -> str:
    """Crude tag strip for deriving a text part from tenant-authored HTML.

    Deliberately not a parser: this runs in a Lambda whose dependencies are
    pinned and minimal, and the result only has to be readable. Block-level
    tags become newlines so the text does not collapse into one paragraph.
    """
    text = re.sub(r"(?i)<br\s*/?>|</(p|div|tr|h[1-6]|li)>", "\n", markup)
    text = re.sub(r"(?i)<(script|style)[^>]*>.*?</\1>", "", text, flags=re.DOTALL)
    text = re.sub(r"<[^>]+>", "", text)
    text = html.unescape(text)
    # Collapse the runs of blank lines the tag strip leaves behind.
    return re.sub(r"\n{3,}", "\n\n", text).strip()


def email_subject(
    event_type: str,
    branding: dict[str, Any],
    template_data: dict[str, Any],
    override: str | None = None,
    locale: str = "en",
) -> str:
    """Subject line, prefixed with the company name.

    The prefix is the point: subjects were bare phrases like "Create your
    account to track your shipment", which in an inbox gives the recipient no
    idea which company is writing or whether it is legitimate. This matches the
    `{company_name}:` convention the SMS templates already use.

    A tenant override is honoured as-is and is *not* prefixed — a tenant that
    wrote its own subject has already said what it wants — but placeholders in
    it are substituted, which they previously were not.
    """
    company_name = get_company_name(branding)
    data = {"company_name": company_name, **{k: v for k, v in template_data.items() if v is not None}}
    if override:
        try:
            return _safe_substitute(str(override), data)
        except Exception:
            logger.warning("Email subject override render failed for event %s; using it verbatim", event_type)
            return str(override)
    if locale == "zh":
        base = EMAIL_SUBJECTS_ZH.get(event_type, _DEFAULT_EMAIL_SUBJECT_ZH)
    else:
        base = EMAIL_SUBJECTS.get(event_type, _DEFAULT_EMAIL_SUBJECT)
    try:
        base = _safe_substitute(base, data)
    except Exception:
        logger.warning("Email subject render failed for event %s", event_type)
    return f"{company_name} — {base}"


def render_email_override(
    body_template: str,
    branding: dict[str, Any],
    template_data: dict[str, Any],
) -> str:
    """Substitute placeholders into a tenant's own HTML email body.

    The HTML is the tenant's, so it is kept; the *values* are escaped, because
    they come from customer records and imported manifests rather than from the
    tenant admin who wrote the template.
    """
    data = _escaped(template_data, get_company_name(branding))
    try:
        return _safe_substitute(body_template, data)
    except Exception:
        # A malformed custom template must not block the notification. Returning
        # it unsubstituted would email literal "{invite_link}" text, so fall
        # back to the default renderer's shell instead.
        logger.warning("Custom email body render failed; falling back to the default template")
        return ""


def render_email_html(
    branding: dict[str, Any],
    event_type: str,
    recipient_name: str | None,
    template_data: dict[str, Any],
    locale: str = "en",
) -> str:
    """Render a tenant-branded HTML email body.

    Everything tenant-specific comes from the canonical `branding_config` shape
    (see `tenant_branding.py`): the company name and colour in the header, the
    tagline beneath it, and the support contacts and boilerplate in the footer.
    """
    company_name = get_company_name(branding)
    color = get_primary_color(branding)
    tagline = get_tagline(branding)
    safe_company = html.escape(company_name, quote=True)
    data = _escaped(template_data, company_name)
    greeting = f"Hello {html.escape(recipient_name, quote=True)}," if recipient_name else "Hello,"
    if locale == "zh":
        greeting = f"{html.escape(recipient_name, quote=True)}，您好：" if recipient_name else "您好："

    lead = _render_body_copy(event_type, locale, data)

    # Action links (keys ending in _link) are a CTA button, not a table row.
    link_labels = _LINK_LABELS_ZH if locale == "zh" else _LINK_LABELS
    links = {k: v for k, v in data.items() if k.endswith("_link") and v}
    buttons = "".join(
        f"<p style='margin:24px 0 8px 0;'>"
        f'<a href="{v}" style=\'display:inline-block;background:{color};color:#ffffff;'
        f"text-decoration:none;padding:13px 24px;border-radius:6px;font-size:15px;font-weight:bold;'>"
        f"{link_labels.get(k, _field_label(k.replace('_link', '')) or 'Continue')}</a></p>"
        f"<p style='margin:0 0 4px 0;font-size:12px;color:#888;word-break:break-all;'>"
        f"{'或将此链接粘贴到浏览器中：' if locale == 'zh' else 'Or paste this link into your browser:'} {v}</p>"
        for k, v in links.items()
    )

    rows = "".join(
        f"<tr>"
        f"<td style='padding:7px 10px;color:#666;font-size:13px;white-space:nowrap;"
        f"border-bottom:1px solid #eee;vertical-align:top;'>{_field_label(k)}</td>"
        f"<td style='padding:7px 10px;font-size:13px;color:#222;border-bottom:1px solid #eee;'>{v}</td>"
        f"</tr>"
        for k, v in data.items()
        if not k.endswith("_link") and k not in _HIDDEN_EMAIL_FIELDS and v != ""
    )
    table = (
        f"<table role='presentation' style='border-collapse:collapse;width:100%;margin-top:20px;'>{rows}</table>" if rows else ""
    )

    # Support contacts turn an automated message into one the recipient can
    # reply to. Omitted entirely when the tenant has published none, rather than
    # printing an empty "Contact:" line.
    support_bits = [
        f"<a href='mailto:{html.escape(e, quote=True)}' style='color:{color};'>{html.escape(e, quote=True)}</a>"
        for e in [get_support_email(branding)]
        if e
    ] + [f"WhatsApp {html.escape(w, quote=True)}" for w in [get_support_whatsapp(branding)] if w]
    support = (
        f"<p style='margin:16px 0 0 0;font-size:12px;color:#777;'>"
        f"{'需要帮助？请联系 ' if locale == 'zh' else 'Need help? Contact '}{' · '.join(support_bits)}</p>"
        if support_bits
        else ""
    )
    footer_text = get_document_footer(branding)
    footer = (
        f"<p style='margin:8px 0 0 0;font-size:11px;color:#999;white-space:pre-line;'>{html.escape(footer_text, quote=True)}</p>"
        if footer_text
        else ""
    )
    automated = f"此邮件由 {safe_company} 自动发送。" if locale == "zh" else f"This is an automated message from {safe_company}."

    return (
        "<!DOCTYPE html>"
        "<html><head><meta charset='UTF-8'>"
        "<meta name='viewport' content='width=device-width,initial-scale=1'></head>"
        "<body style='margin:0;padding:0;background:#f4f4f4;font-family:Arial,Helvetica,sans-serif;'>"
        "<table role='presentation' width='100%' cellpadding='0' cellspacing='0' style='background:#f4f4f4;'>"
        "<tr><td align='center' style='padding:20px 12px;'>"
        "<table role='presentation' width='600' cellpadding='0' cellspacing='0'"
        " style='max-width:600px;width:100%;background:#ffffff;border-radius:8px;overflow:hidden;'>"
        f"<tr><td style='background:{color};padding:20px 24px;'>"
        f"<div style='color:#ffffff;font-size:20px;font-weight:bold;'>{safe_company}</div>"
        + (
            f"<div style='color:#ffffff;opacity:0.85;font-size:12px;margin-top:3px;'>{html.escape(tagline, quote=True)}</div>"
            if tagline
            else ""
        )
        + "</td></tr>"
        "<tr><td style='padding:24px;'>"
        f"<p style='margin:0 0 14px 0;font-size:15px;color:#222;'>{greeting}</p>"
        f"<p style='margin:0;font-size:15px;color:#333;line-height:1.5;'>{lead}</p>"
        f"{buttons}"
        f"{table}"
        f"{support}"
        f"<p style='margin:16px 0 0 0;font-size:11px;color:#999;'>{automated}</p>"
        f"{footer}"
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
    locale: str = "en",
    body_override: str | None = None,
) -> str:
    """Render the plain-text alternative part.

    Carries the same prose and the same links as the HTML part — a text-only
    client previously received an unexplained list of field names. When the
    tenant supplied its own HTML body, that body is stripped to text so the
    two MIME parts say the same thing.
    """
    if body_override:
        rendered = render_email_override(body_override, branding, template_data)
        if rendered:
            return _html_to_text(rendered)
    company_name = get_company_name(branding)
    data = {k: str(v) for k, v in template_data.items() if v is not None}
    data.setdefault("company_name", company_name)
    if locale == "zh":
        greeting = f"{recipient_name}，您好：" if recipient_name else "您好："
    else:
        greeting = f"Hello {recipient_name}," if recipient_name else "Hello,"

    lines = [company_name, "", greeting, "", _render_body_copy(event_type, locale, data), ""]
    for key, value in data.items():
        if key.endswith("_link"):
            lines.append(f"{_field_label(key)}: {value}")
    for key, value in data.items():
        if not key.endswith("_link") and key not in _HIDDEN_EMAIL_FIELDS and value:
            lines.append(f"  {_field_label(key)}: {value}")

    support_email = get_support_email(branding)
    support_whatsapp = get_support_whatsapp(branding)
    if support_email or support_whatsapp:
        contacts = " / ".join(filter(None, [support_email, f"WhatsApp {support_whatsapp}" if support_whatsapp else ""]))
        lines += ["", ("需要帮助？请联系 " if locale == "zh" else "Need help? Contact ") + contacts]
    lines += [
        "",
        (f"此邮件由 {company_name} 自动发送。" if locale == "zh" else f"This is an automated message from {company_name}."),
    ]
    footer_text = get_document_footer(branding)
    if footer_text:
        lines += ["", footer_text]
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
    # `.strip() or` rather than a get() default: Terraform sets this to the
    # empty string when the variable is unconfigured, and an empty string is
    # "set" as far as os.environ.get is concerned — so a default would have
    # been bypassed and SES handed a blank sender.
    from_address = os.environ.get("SES_FROM_ADDRESS", "").strip() or _PLACEHOLDER_FROM_ADDRESS

    if from_address == _PLACEHOLDER_FROM_ADDRESS and _is_production():
        # The default is a documentation address. SES and ACS both reject an
        # unverified sender, so this would fail on every send — but it would
        # fail as a provider error buried in notification_log, which reads as a
        # transient fault rather than a missing environment variable.
        logger.error(
            "SES_FROM_ADDRESS is unset in production — refusing to send from the placeholder address",
            extra={"tenant_id": tenant_id},
        )
        return False

    try:
        get_email_provider().send(
            sender=from_address,
            to_email=to_email,
            subject=subject,
            html_body=html_body,
            text_body=text_body,
        )
        logger.info(
            "Email sent",
            extra={"tenant_id": tenant_id},
        )
        return True
    except Exception:
        from . import repository as repo

        logger.exception(
            "Email send failed",
            extra={"tenant_id": tenant_id, "to": repo.mask_email(to_email)},
        )
        raise


# ---------------------------------------------------------------------------
# Notification log service functions
# ---------------------------------------------------------------------------


# Template variables that are secrets: delivered to the recipient, never kept. The notification log is readable by tenant
# admins and is the source of "retry", so a code that reached it would let staff read every customer's pickup code.
_SECRET_TEMPLATE_KEYS = frozenset({"pickup_code", "activation_link", "invite_link"})
REDACTED = "••••••"


def redact_secrets(template_data: dict[str, Any], message_body: str | None) -> tuple[dict[str, Any], str | None]:
    """`template_data` and `message_body` as they may be stored: each secret value replaced by a mask."""
    secret_values = {str(v) for k, v in template_data.items() if k in _SECRET_TEMPLATE_KEYS and v}
    if not secret_values:
        return template_data, message_body
    redacted = {k: (REDACTED if k in _SECRET_TEMPLATE_KEYS and v else v) for k, v in template_data.items()}
    for value in secret_values:
        if message_body:
            message_body = message_body.replace(value, REDACTED)
    return redacted, message_body


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

        template_data, message_body = redact_secrets(template_data, message_body)
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
    record_outcome("notification_send", failed=False)  # the failure-rate alarm's denominator (audit OPS-04)
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
    record_outcome("notification_send", failed=True)
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

    from shared.notifications import _tenant_branding, consent_verdict, is_recipient_allowed, record_suppressed

    # The fallback is a new SMS, so it needs the same consent as one sent directly: a customer who agreed to
    # WhatsApp but not SMS must not be texted just because WhatsApp failed.
    event_type = str(log_row.get("event_type") or "")
    verdict = consent_verdict(tenant_id, event_type, str(customer_id))
    if verdict is not None and not verdict.permits("sms"):
        record_suppressed(tenant_id, event_type, "sms", str(customer_id), phone, "customer has not agreed to sms")
        return False

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
        "tenant_branding": _tenant_branding(tenant_id),
        "customer_id": str(customer_id) if customer_id else None,
        "template_data": log_row.get("template_data") or {},
        "locale": log_row.get("locale") or "en",
        "_retry_of_log_id": whatsapp_log_id,
        "_fallback_reason": reason,
    }
    try:
        get_queue_provider().send(destination=queue_url, body=_json.dumps(body, default=str))
    except Exception:
        logger.exception("SMS fallback enqueue failed for log %s", whatsapp_log_id)
        return False

    logger.info("SMS fallback queued for log %s (reason=%s)", whatsapp_log_id, reason)
    return True


_NOT_RETRYABLE_EVENTS = frozenset({"pickup_code_issued", "account_activation", "customer_invite"})


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
    from shared.notifications import _tenant_branding, consent_verdict, is_recipient_allowed

    from . import repository as repo

    original = repo.get_log_by_id(tenant_id, log_id)
    if not original:
        raise ResourceNotFoundError("notification_log", log_id)
    if original["status"] != "failed":
        raise BusinessRuleViolationError(
            f"Only 'failed' notifications can be retried; current status is '{original['status']}'",
            rule_id="NOTIFICATION_NOT_FAILED",
        )

    # One-time secret codes/links are redacted on storage, so a retry would send a mask.
    if original["event_type"] in _NOT_RETRYABLE_EVENTS:
        raise BusinessRuleViolationError(
            "This message carried a one-time code that is not kept, so it cannot be re-sent. "
            "Reissue the code from the release note instead.",
            rule_id="NOTIFICATION_NOT_RETRYABLE",
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

    customer_id = str(original["customer_id"]) if original.get("customer_id") else None
    contact = repo.get_customer_contact_for_retry(tenant_id, customer_id) if customer_id else None
    if not contact:
        raise BusinessRuleViolationError(
            "Customer contact is unavailable for retrying this notification.",
            rule_id="NOTIFICATION_CONTACT_UNAVAILABLE",
        )

    phone = str(contact.get("phone") or "").strip()
    whatsapp = str(contact.get("whatsapp") or phone).strip()
    email = str(contact.get("email") or "").strip()
    if channel == "email" and not email:
        raise BusinessRuleViolationError(
            "Customer email address is unavailable for retry.",
            rule_id="NOTIFICATION_CONTACT_UNAVAILABLE",
        )
    if channel == "sms" and not phone:
        raise BusinessRuleViolationError(
            "Customer phone number is unavailable for retry.",
            rule_id="NOTIFICATION_CONTACT_UNAVAILABLE",
        )
    if channel == "whatsapp" and not whatsapp:
        raise BusinessRuleViolationError(
            "Customer WhatsApp number is unavailable for retry.",
            rule_id="NOTIFICATION_CONTACT_UNAVAILABLE",
        )

    recipient = {
        "phone": whatsapp if channel == "whatsapp" else phone,
        "whatsapp": whatsapp,
        "email": email,
        "name": contact.get("name") or original.get("recipient_name"),
    }
    verdict = consent_verdict(tenant_id, original["event_type"], customer_id)
    if verdict is not None and not verdict.permits(channel):
        raise BusinessRuleViolationError(
            f"Customer has not consented to receive '{channel}' notifications.",
            rule_id="NOTIFICATION_CONSENT_DENIED",
        )
    if not is_recipient_allowed(recipient):
        raise BusinessRuleViolationError(
            "Recipient is not allowlisted in this non-production environment.",
            rule_id="NOTIFICATION_RECIPIENT_NOT_ALLOWLISTED",
        )

    template_data: dict[str, Any] = original.get("template_data") or {}
    locale = str(original.get("locale") or contact.get("locale") or "en")
    branding = _tenant_branding(tenant_id)

    new_row = repo.insert_log(
        tenant_id,
        {
            "tenant_id": tenant_id,
            "event_type": original["event_type"],
            "channel": channel,
            "recipient_masked": original.get("recipient_masked")
            or (repo.mask_email(email) if channel == "email" else repo.mask_phone(str(recipient["phone"] or ""))),
            "recipient_name": recipient["name"],
            "customer_id": customer_id,
            "status": "queued",
            "provider": None,
            "provider_message_id": None,
            "gateway_response": None,
            "error_detail": None,
            "retry_of": log_id,
            "template_data": json.dumps(template_data),
            "locale": locale,
        },
    )
    new_log_id = str(new_row["id"]) if new_row else None

    sqs_body = json.dumps(
        {
            "tenant_id": tenant_id,
            "event_type": original["event_type"],
            "channel": channel,
            "recipient": recipient,
            "tenant_branding": branding,
            "template_data": template_data,
            "locale": locale,
            "customer_id": customer_id,
            "_retry_of_log_id": log_id,
            "_queued_log_id": new_log_id,
        }
    )

    get_queue_provider().send(destination=queue_url, body=sqs_body)

    log_audit(
        tenant_id=tenant_id,
        entity_type="notification_log",
        entity_id=log_id,
        action="RETRY",
        actor_id=actor_id,
        actor_role="tenant_admin",
        after_state={"new_log_id": new_log_id, "channel": channel},
    )

    return {"new_log_id": new_log_id, "original_log_id": log_id}


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


def _assert_notification_visible(
    notification: dict[str, Any] | None,
    notification_id: str,
    user_id: str,
    role: str | None = None,
) -> None:
    from shared.exceptions import ResourceNotFoundError

    if not notification:
        raise ResourceNotFoundError("staff_notification", notification_id)
    target_uid = notification.get("target_user_id")
    target_role = notification.get("target_role")
    if target_uid is not None and str(target_uid) != str(user_id):
        raise ResourceNotFoundError("staff_notification", notification_id)
    if role is not None and target_uid is None:
        if role == "customer" and target_role != "customer":
            raise ResourceNotFoundError("staff_notification", notification_id)
        if target_role is not None and str(target_role) != role:
            raise ResourceNotFoundError("staff_notification", notification_id)


def mark_staff_notification_read(
    tenant_id: str,
    notification_id: str,
    user_id: str,
    role: str | None = None,
) -> dict[str, Any]:
    from . import repository as repo

    notification = repo.get_staff_notification_by_id(tenant_id, notification_id)
    _assert_notification_visible(notification, notification_id, user_id, role)
    row = repo.mark_staff_notification_read(tenant_id, notification_id, user_id)
    if row is None:
        raise RuntimeError("mark_staff_notification_read returned None unexpectedly")
    return dict(row)


def mark_all_staff_notifications_read(tenant_id: str, user_id: str, role: str) -> dict[str, int]:
    from . import repository as repo

    return {"marked_read": repo.mark_all_staff_notifications_read(tenant_id, user_id, role)}


def dismiss_staff_notification(
    tenant_id: str,
    notification_id: str,
    user_id: str,
    role: str | None = None,
) -> dict[str, Any]:
    from . import repository as repo

    notification = repo.get_staff_notification_by_id(tenant_id, notification_id)
    _assert_notification_visible(notification, notification_id, user_id, role)
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

    from shared.db import tenant_transaction

    from . import repository as repo

    target_roles = list(_ALL_STAFF_ROLES) if audience == "all_staff" else ["customer"]
    group_id = str(uuid.uuid4())
    created: list[dict[str, Any]] = []
    with tenant_transaction(tenant_id):
        repo.deactivate_active_banners_for_roles(tenant_id, target_roles)
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
    from shared.db import tenant_transaction
    from shared.exceptions import IllegalTransitionError
    from shared.staff_notifications import notify_staff

    from . import repository as repo

    request_row = _get_pending_announcement_request(tenant_id, request_id)
    with tenant_transaction(tenant_id):
        reviewed = repo.mark_announcement_request_reviewed(tenant_id, request_id, "approved", reviewed_by=actor_id)
        if reviewed is None:
            raise IllegalTransitionError(
                entity="announcement_request",
                current_state="reviewed",
                requested_state="approved",
                allowed=["pending"],
            )
        created = _create_announcement_notifications(
            tenant_id,
            request_row["title"],
            request_row["body"],
            request_row["audience"],
        )

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
    from shared.db import tenant_transaction
    from shared.exceptions import ResourceNotFoundError

    from . import repository as repo

    target_roles = repo.get_announcement_group_target_roles(tenant_id, group_id)
    if not target_roles:
        raise ResourceNotFoundError("announcement", group_id)

    with tenant_transaction(tenant_id):
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
