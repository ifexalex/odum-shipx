"""Notification Lambda handlers.

Three separate Lambda entry points, each consuming from a dedicated SQS queue:
  - sms_handler      → SMS queue  (Africa's Talking)
  - whatsapp_handler → WhatsApp queue (Meta Cloud API)
  - email_handler    → Email queue (Amazon SES)

Each handler returns batchItemFailures so that only failed messages are
retried and routed to the DLQ after the queue's maxReceiveCount is reached.

A fourth HTTP entry point (http_handler) serves the notification log API:
  - GET  /v1/notifications/log
  - GET  /v1/notifications/log/{id}
  - POST /v1/notifications/log/{id}/retry
"""

import json
import logging
from typing import Any

from shared.auth import get_tenant_context
from shared.exceptions import LogisticsBaseError, ResourceNotFoundError
from shared.idempotency import check_idempotency, get_idempotency_key, store_idempotency
from shared.logging_config import bind_log_context, clear_log_context, setup_logging
from shared.metering import record_usage
from shared.observability import init_tracing
from shared.pagination import parse_pagination_params
from shared.responses import created, error_response, paginated, success
from shared.tenant_context import UserRole
from shared.validation import parse_validated

from . import service
from .models import (
    AnnouncementAudience,
    RejectAnnouncementRequestBody,
    SendAnnouncementRequest,
    UpdateAnnouncementBody,
)
from .tenant_branding import extract_branding

# Module-level init (runs once on cold start)
setup_logging()
init_tracing()

logger = logging.getLogger(__name__)

# Meta delivery status → notification_log status. Anything absent (e.g. Meta's
# "accepted") is ignored rather than written through as an unknown status.
_WA_STATUS_MAP = {
    "sent": "sent",
    "delivered": "delivered",
    "read": "read",
    "failed": "failed",
}


# ---------------------------------------------------------------------------
# SMS handler
# ---------------------------------------------------------------------------


def sms_handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
    """SQS consumer for the SMS notification queue."""
    batch_item_failures = []
    for record in event.get("Records", []):
        msg_id = record.get("messageId", "unknown")
        clear_log_context()
        bind_log_context(request_id=msg_id)
        try:
            body = json.loads(record["body"])
            _process_sms(body)
        except Exception:
            logger.exception("SMS processing failed for message %s", msg_id)
            batch_item_failures.append({"itemIdentifier": msg_id})

    return {"batchItemFailures": batch_item_failures}


def _process_sms(body: dict[str, Any]) -> None:
    tenant_id = body.get("tenant_id", "")
    bind_log_context(tenant_id=tenant_id or None)
    event_type = body.get("event_type") or body.get("template_id") or ""
    raw_recipient = body.get("recipient")
    recipient = {"phone": raw_recipient} if isinstance(raw_recipient, str) else (raw_recipient or {})
    phone = recipient.get("phone", "")
    recipient_name = recipient.get("name")
    customer_id = body.get("customer_id")
    branding = extract_branding(body)
    template_data = body.get("template_data") or body.get("template_vars") or {}
    locale = body.get("locale", "en")

    if not phone:
        logger.warning(
            "SMS message missing recipient phone — skipping",
            extra={"tenant_id": tenant_id},
        )
        return

    retry_of = body.get("_retry_of_log_id")
    template_override = (body.get("template_override") or {}).get("sms")
    message = service.format_sms(event_type, branding, template_data, template_override=template_override, locale=locale)
    log_id = body.get("_queued_log_id") or service.log_queued(
        tenant_id,
        "sms",
        event_type,
        phone,
        recipient_name,
        customer_id,
        template_data,
        retry_of,
        message_body=message,
        locale=locale,
    )

    try:
        if service.send_sms(phone, message, tenant_id):
            service.log_sent(tenant_id, log_id, "africastalking", "", {})
            record_usage(tenant_id, "sms_sent")
        else:
            # Provider not configured, or the recipient guard blocked a
            # non-allowlisted number. Nothing was sent, so nothing is metered.
            service.log_failed(tenant_id, log_id, "SMS not sent (provider unconfigured or recipient suppressed)")
    except Exception:
        service.log_failed(tenant_id, log_id, "send_sms raised an exception")
        raise


# ---------------------------------------------------------------------------
# WhatsApp handler
# ---------------------------------------------------------------------------


def whatsapp_handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
    """SQS consumer for the WhatsApp notification queue."""
    batch_item_failures = []
    for record in event.get("Records", []):
        msg_id = record.get("messageId", "unknown")
        clear_log_context()
        bind_log_context(request_id=msg_id)
        try:
            body = json.loads(record["body"])
            _process_whatsapp(body)
        except Exception:
            logger.exception("WhatsApp processing failed for message %s", msg_id)
            batch_item_failures.append({"itemIdentifier": msg_id})

    return {"batchItemFailures": batch_item_failures}


def _process_whatsapp(body: dict[str, Any]) -> None:
    tenant_id = body.get("tenant_id", "")
    bind_log_context(tenant_id=tenant_id or None)
    event_type = body.get("event_type") or body.get("template_id") or ""
    raw_recipient = body.get("recipient")
    recipient = {"phone": raw_recipient} if isinstance(raw_recipient, str) else (raw_recipient or {})
    phone = recipient.get("whatsapp") or recipient.get("phone", "")
    recipient_name = recipient.get("name")
    customer_id = body.get("customer_id")
    branding = extract_branding(body)
    template_data = body.get("template_data") or body.get("template_vars") or {}

    if not phone:
        logger.warning(
            "WhatsApp message missing recipient phone — skipping",
            extra={"tenant_id": tenant_id},
        )
        return

    retry_of = body.get("_retry_of_log_id")
    locale = body.get("locale", "en")
    wa_overrides = body.get("template_override") or {}
    if wa_overrides.get("whatsapp"):
        template_name = wa_overrides["whatsapp"]
    elif locale == "zh":
        template_name = service.WA_TEMPLATE_MAP_ZH.get(event_type, "generic_notification_zh")
    else:
        template_name = service.WA_TEMPLATE_MAP.get(event_type, "generic_notification")
    log_id = body.get("_queued_log_id") or service.log_queued(
        tenant_id,
        "whatsapp",
        event_type,
        phone,
        recipient_name,
        customer_id,
        template_data,
        retry_of,
        message_body=template_name,
        locale=locale,
    )

    try:
        components = service.build_wa_components(branding, template_data, event_type)
        # Meta's message id is what the delivery-status webhook matches on —
        # storing "" here meant every delivered/failed callback matched nothing.
        provider_message_id = service.send_whatsapp(phone, template_name, components, tenant_id, service.wa_language_code(locale))
        if not provider_message_id:
            # send_whatsapp returns "" without raising when the Meta credentials
            # are missing or the recipient is suppressed. This used to fall
            # straight through to log_sent + record_usage, which meant: the log
            # said "sent" when nothing was sent, the tenant was metered for a
            # message that never left, and — because no exception was raised —
            # the SMS fallback below never fired, so the customer got nothing on
            # either channel. The staff-facing invite screen said it had gone.
            service.log_failed(tenant_id, log_id, "WhatsApp not sent (provider unconfigured or recipient suppressed)")
            if log_id:
                try:
                    service.trigger_sms_fallback(tenant_id, log_id, "whatsapp_unconfigured")
                except Exception:
                    logger.exception("SMS fallback failed after unconfigured WhatsApp send")
            return
        service.log_sent(tenant_id, log_id, "meta_whatsapp", provider_message_id, {})
        record_usage(tenant_id, "whatsapp_sent")
    except Exception as exc:
        reason = str(exc) if isinstance(exc, service.WhatsAppSendError) else "send_whatsapp raised an exception"
        service.log_failed(tenant_id, log_id, reason)
        # WhatsApp is the primary channel, so a rejected send (no WhatsApp
        # account, bad number, template not approved) falls back to SMS rather
        # than leaving the customer with nothing.
        if log_id:
            try:
                service.trigger_sms_fallback(tenant_id, log_id, "whatsapp_rejected")
            except Exception:
                logger.exception("SMS fallback failed after WhatsApp rejection")
        raise


# ---------------------------------------------------------------------------
# Email handler
# ---------------------------------------------------------------------------


def email_handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
    """SQS consumer for the Email notification queue."""
    batch_item_failures = []
    for record in event.get("Records", []):
        msg_id = record.get("messageId", "unknown")
        clear_log_context()
        bind_log_context(request_id=msg_id)
        try:
            body = json.loads(record["body"])
            _process_email(body)
        except Exception:
            logger.exception("Email processing failed for message %s", msg_id)
            batch_item_failures.append({"itemIdentifier": msg_id})

    return {"batchItemFailures": batch_item_failures}


def _process_email(body: dict[str, Any]) -> None:
    tenant_id = body.get("tenant_id", "")
    bind_log_context(tenant_id=tenant_id or None)
    event_type = body.get("event_type") or body.get("template_id") or ""
    raw_recipient = body.get("recipient")
    recipient = {"email": raw_recipient} if isinstance(raw_recipient, str) else (raw_recipient or {})
    to_email = recipient.get("email", "")
    to_name = recipient.get("name")
    customer_id = body.get("customer_id")
    branding = extract_branding(body)
    template_data = body.get("template_data") or body.get("template_vars") or {}

    if not to_email:
        logger.warning(
            "Email message missing recipient email — skipping",
            extra={"tenant_id": tenant_id},
        )
        return

    retry_of = body.get("_retry_of_log_id")
    locale = body.get("locale", "en")
    email_overrides = (body.get("template_override") or {}).get("email") or {}
    subject = service.email_subject(event_type, branding, template_data, email_overrides.get("subject"), locale)
    # A tenant's custom body was previously used as-is, so its `{name}` and
    # `{invite_link}` placeholders were emailed literally — the link arrived as
    # the eight characters "{invite_link}". It now goes through the same
    # substitution the SMS path has always used.
    html_body = ""
    if email_overrides.get("body"):
        html_body = service.render_email_override(email_overrides["body"], branding, template_data)
    if not html_body:
        # Either no override, or one whose placeholders could not be
        # substituted — an empty body must never be what goes out.
        html_body = service.render_email_html(branding, event_type, to_name, template_data, locale)
    # The text alternative is derived from the same override, so the two parts
    # of a multipart message cannot disagree about what was sent.
    text_body = service.render_email_text(
        branding, event_type, to_name, template_data, locale, body_override=email_overrides.get("body")
    )
    log_id = body.get("_queued_log_id") or service.log_queued(
        tenant_id,
        "email",
        event_type,
        to_email,
        to_name,
        customer_id,
        template_data,
        retry_of,
        message_body=text_body,
        locale=locale,
    )

    try:
        if service.send_email(to_email, to_name, subject, html_body, text_body, tenant_id):
            service.log_sent(tenant_id, log_id, "ses", "", {})
            record_usage(tenant_id, "emails_sent")
        else:
            service.log_failed(tenant_id, log_id, "Email not sent (provider unconfigured or recipient suppressed)")
    except Exception:
        service.log_failed(tenant_id, log_id, "send_email raised an exception")
        raise


# ---------------------------------------------------------------------------
# WhatsApp webhook handler (Meta Cloud API verification + delivery status)
# ---------------------------------------------------------------------------


def webhook_handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
    """HTTP Lambda for WhatsApp webhook verification and delivery status callbacks.

    Routes:
      GET  /v1/webhooks/whatsapp — Meta hub challenge verification
      POST /v1/webhooks/whatsapp — Delivery status updates
    """

    http = event.get("requestContext", {}).get("http", {})
    method = http.get("method", event.get("httpMethod", "GET"))

    if method == "GET":
        return _handle_whatsapp_verify(event)
    if method == "POST":
        return _handle_whatsapp_delivery_status(event)

    return {"statusCode": 405, "body": "Method Not Allowed"}


def _handle_whatsapp_verify(event: dict[str, Any]) -> dict[str, Any]:
    """Respond to Meta's hub challenge for webhook subscription."""
    import hmac
    import os

    params = event.get("queryStringParameters") or {}
    mode = params.get("hub.mode", "")
    token = params.get("hub.verify_token", "")
    challenge = params.get("hub.challenge", "")

    verify_token = os.environ.get("WHATSAPP_VERIFY_TOKEN", "")
    if mode == "subscribe" and verify_token and hmac.compare_digest(token, verify_token):
        logger.info("WhatsApp webhook verified successfully")
        return {"statusCode": 200, "body": challenge}

    logger.warning("WhatsApp webhook verification failed: mode=%s", mode)
    return {"statusCode": 403, "body": "Forbidden"}


def _handle_whatsapp_delivery_status(event: dict[str, Any]) -> dict[str, Any]:
    """Process delivery status updates from Meta Cloud API.

    Updates the matching notification_log row by provider_message_id when a
    delivered/read/failed status arrives. Always returns 200 — Meta retries on
    non-2xx responses which creates duplicate events.
    """
    import base64
    import hashlib
    import hmac
    import json as _json
    import os

    headers = {k.lower(): v for k, v in (event.get("headers") or {}).items() if isinstance(k, str)}
    sig_header = str(headers.get("x-hub-signature-256") or "")
    app_secret = os.environ.get("META_WHATSAPP_APP_SECRET", "").strip()
    raw_body_str = event.get("body") or ""
    if event.get("isBase64Encoded") and isinstance(raw_body_str, str):
        try:
            raw_bytes = base64.b64decode(raw_body_str)
            raw_body_str = raw_bytes.decode("utf-8", errors="replace")
        except Exception:
            logger.warning("Failed to base64-decode WhatsApp webhook body")
            return {"statusCode": 400, "body": "Bad Request"}
    else:
        raw_bytes = raw_body_str.encode("utf-8") if isinstance(raw_body_str, str) else raw_body_str

    env = os.environ.get("ENVIRONMENT", "").strip().lower()
    if app_secret or env not in ("", "local", "test"):
        if not app_secret or not sig_header.startswith("sha256="):
            logger.warning("WhatsApp webhook missing secret or X-Hub-Signature-256 header")
            return {"statusCode": 401, "body": "Unauthorized"}
        expected_sig = "sha256=" + hmac.new(app_secret.encode("utf-8"), raw_bytes, hashlib.sha256).hexdigest()
        if not hmac.compare_digest(sig_header, expected_sig):
            logger.warning("WhatsApp webhook signature mismatch")
            return {"statusCode": 401, "body": "Unauthorized"}

    try:
        body = _json.loads(raw_body_str or "{}")
        for entry in body.get("entry", []):
            for change in entry.get("changes", []):
                value = change.get("value", {})
                for status_obj in value.get("statuses", []):
                    msg_id = status_obj.get("id", "")
                    raw_status = status_obj.get("status", "")
                    mapped_status = _WA_STATUS_MAP.get(raw_status)
                    logger.info(
                        "WhatsApp delivery status: msg=%s status=%s",
                        msg_id,
                        raw_status,
                    )
                    if msg_id and mapped_status == "failed":
                        try:
                            from . import repository as repo

                            failed_row = repo.get_log_by_provider_message_id(msg_id)
                            if failed_row:
                                service.trigger_sms_fallback(
                                    str(failed_row["tenant_id"]),
                                    str(failed_row["id"]),
                                    "whatsapp_undelivered",
                                )
                        except Exception:
                            logger.exception("SMS fallback failed for WhatsApp msg %s", msg_id)
                    if msg_id and mapped_status:
                        try:
                            from . import repository as repo

                            repo.update_delivery_status(
                                msg_id,
                                mapped_status,
                                _json.dumps(status_obj),
                            )
                        except Exception:
                            logger.warning("Failed to update notification_log for WhatsApp msg %s", msg_id)
    except Exception:
        logger.exception("Failed to process WhatsApp delivery status")

    # Always return 200 to prevent Meta from retrying
    return {"statusCode": 200, "body": "OK"}


# ---------------------------------------------------------------------------
# HTTP API — notification log
# ---------------------------------------------------------------------------

_LOG_READ_ROLES = (UserRole.TENANT_ADMIN, UserRole.NIGERIA_OFFICE_STAFF)

# Every non-customer, non-platform role — the staff bell is for anyone who
# works inside a tenant (unlike the notification log, which is a
# compliance/audit view scoped to admin + nigeria office staff only).
_STAFF_NOTIF_ROLES = (
    UserRole.TENANT_ADMIN,
    UserRole.NIGERIA_OFFICE_STAFF,
    UserRole.CHINA_OFFICE_STAFF,
    UserRole.WAREHOUSE_ATTENDANT,
)


def http_handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
    """HTTP Lambda entry point for the notification log API.

    Routes:
      GET   /v1/notifications/log                     — list (tenant_admin, nigeria_office_staff)
      GET   /v1/notifications/log/{id}                — get one (same roles)
      POST  /v1/notifications/log/{id}/retry          — retry failed (tenant_admin)
      GET   /v1/notifications/staff                   — TopBar bell feed (any staff role)
      GET   /v1/notifications/staff/unread-count       — TopBar bell badge count
      PATCH /v1/notifications/staff/{id}/read          — mark one read
      PATCH /v1/notifications/staff/mark-all-read      — mark every unread-and-visible one read
      GET   /v1/notifications/staff/banner              — the active announcement banner, if any
      POST  /v1/notifications/announce                 — tenant_admin: immediate send;
                                                          nigeria_office_staff: submit for approval
      GET    /v1/notifications/announcements                       — tenant_admin: history/management list
      GET    /v1/notifications/announcements/pending                — tenant_admin: review queue
      GET    /v1/notifications/announcements/mine                    — nigeria_office_staff: own requests
      PATCH  /v1/notifications/announcements/requests/{id}/approve    — tenant_admin
      PATCH  /v1/notifications/announcements/requests/{id}/reject     — tenant_admin
      PATCH  /v1/notifications/announcements/requests/{id}            — nigeria_office_staff: edit own pending
      DELETE /v1/notifications/announcements/requests/{id}            — nigeria_office_staff: withdraw own pending
      PATCH  /v1/notifications/announcements/{group_id}/activate       — tenant_admin: (re)show a banner
      PATCH  /v1/notifications/announcements/{group_id}/deactivate     — tenant_admin: hide a banner
      PATCH  /v1/notifications/announcements/{group_id}                — tenant_admin: edit a sent announcement
      DELETE /v1/notifications/announcements/{group_id}                — tenant_admin: delete a sent announcement
    """
    import uuid as _uuid

    http = event.get("requestContext", {}).get("http", {})
    method = http.get("method", "")
    path = http.get("path", "")
    request_id = event.get("requestContext", {}).get("requestId") or str(_uuid.uuid4())
    clear_log_context()
    bind_log_context(request_id=request_id)

    try:
        tenant_ctx = get_tenant_context(event)

        idempotency_key = None
        if method == "POST":
            idempotency_key = get_idempotency_key(event)
            cached = check_idempotency(
                idempotency_key,
                tenant_ctx.tenant_id,
                actor_id=tenant_ctx.user_id,
                method=method,
                path=path,
            )
            if cached:
                return cached

        parts = path.strip("/").split("/")
        section = parts[2] if len(parts) > 2 else None
        if section == "staff":
            response = _dispatch_staff_notifications(event, method, parts, tenant_ctx, request_id)
        elif section == "customer":
            response = _dispatch_customer_notifications(event, method, parts, tenant_ctx, request_id)
        elif section == "announce" and method == "POST":
            response = _handle_send_announcement(event, tenant_ctx, request_id)
        elif section == "announcements":
            response = _dispatch_announcements(event, method, parts, tenant_ctx, request_id)
        else:
            response = _dispatch_log(event, method, path, tenant_ctx, request_id)

        if method == "POST" and idempotency_key and response.get("statusCode", 500) < 400:
            store_idempotency(
                idempotency_key,
                response,
                tenant_ctx.tenant_id,
                actor_id=tenant_ctx.user_id,
                method=method,
                path=path,
            )

        record_usage(tenant_ctx.tenant_id, "api_calls", request_id=request_id)
        return response

    except LogisticsBaseError as exc:
        return error_response(exc, instance=path, request_id=request_id)
    except Exception:
        logger.exception("Unhandled error in notification http_handler")
        return error_response(
            LogisticsBaseError("Internal server error", "INTERNAL_ERROR", 500),
            instance=path,
            request_id=request_id,
        )


def _dispatch_log(
    event: dict[str, Any],
    method: str,
    path: str,
    ctx: Any,
    request_id: str,
) -> dict[str, Any]:
    parts = path.strip("/").split("/")
    # Expected: ["v1", "notifications", "log"] or ["v1", "notifications", "log", id]
    # or ["v1", "notifications", "log", id, "retry"]
    if len(parts) < 3 or parts[0] != "v1" or parts[1] != "notifications" or parts[2] != "log":
        raise ResourceNotFoundError("route", path)

    log_id = parts[3] if len(parts) > 3 else None
    action = parts[4] if len(parts) > 4 else None

    qp = event.get("queryStringParameters") or {}

    # GET /v1/notifications/log
    if log_id is None and method == "GET":
        ctx.assert_role(*_LOG_READ_ROLES)
        filters = {
            k: qp[k] for k in ("channel", "status", "event_type", "customer_id", "created_after", "created_before") if qp.get(k)
        }
        cursor, limit = parse_pagination_params(qp)
        page, next_cursor, has_more = service.list_logs(ctx.tenant_id, filters, limit, cursor)
        return paginated(page, next_cursor, has_more, request_id=request_id)

    # GET /v1/notifications/log/{id}
    if log_id and action is None and method == "GET":
        ctx.assert_role(*_LOG_READ_ROLES)
        row = service.get_log(ctx.tenant_id, log_id)
        return success(row, request_id=request_id)

    # POST /v1/notifications/log/{id}/retry
    if log_id and action == "retry" and method == "POST":
        ctx.assert_role(UserRole.TENANT_ADMIN)
        result = service.retry_notification(ctx.tenant_id, log_id, ctx.user_id)
        return success(result, request_id=request_id)

    raise ResourceNotFoundError("route", path)


def _dispatch_staff_notifications(
    event: dict[str, Any],
    method: str,
    parts: list[str],
    ctx: Any,
    request_id: str,
) -> dict[str, Any]:
    """Routes under /v1/notifications/staff/... — the TopBar bell.

    Expected: ["v1", "notifications", "staff"] or [..., "unread-count"]
    or [..., "mark-all-read"] or [..., "clear-all"] or [..., "{id}", "read"]
    or DELETE [..., "{id}"].
    """
    ctx.assert_role(*_STAFF_NOTIF_ROLES)
    sub = parts[3] if len(parts) > 3 else None
    action = parts[4] if len(parts) > 4 else None
    qp = event.get("queryStringParameters") or {}

    # GET /v1/notifications/staff
    if sub is None and method == "GET":
        cursor, limit = parse_pagination_params(qp)
        unread_only = qp.get("unread_only") == "true"
        page, next_cursor, has_more = service.list_staff_notifications(
            ctx.tenant_id,
            ctx.user_id,
            str(ctx.role),
            limit,
            cursor,
            unread_only=unread_only,
        )
        return paginated(page, next_cursor, has_more, request_id=request_id)

    # GET /v1/notifications/staff/unread-count
    if sub == "unread-count" and method == "GET":
        result: Any = service.count_unread_staff_notifications(ctx.tenant_id, ctx.user_id, str(ctx.role))
        return success(result, request_id=request_id)

    # GET /v1/notifications/staff/banner — the single active announcement to
    # show as a page banner, or null if none is currently active.
    if sub == "banner" and method == "GET":
        result = service.get_active_banner(ctx.tenant_id, ctx.user_id, str(ctx.role))
        return success(result, request_id=request_id)

    # PATCH /v1/notifications/staff/mark-all-read
    if sub == "mark-all-read" and method == "PATCH":
        result = service.mark_all_staff_notifications_read(ctx.tenant_id, ctx.user_id, str(ctx.role))
        return success(result, request_id=request_id)

    # DELETE /v1/notifications/staff/clear-all
    if sub == "clear-all" and method == "DELETE":
        result = service.dismiss_all_staff_notifications(ctx.tenant_id, ctx.user_id, str(ctx.role))
        return success(result, request_id=request_id)

    # PATCH /v1/notifications/staff/{id}/read
    if sub and action == "read" and method == "PATCH":
        result = service.mark_staff_notification_read(ctx.tenant_id, sub, ctx.user_id)
        return success(result, request_id=request_id)

    # DELETE /v1/notifications/staff/{id} — clear one
    if sub and action is None and method == "DELETE":
        result = service.dismiss_staff_notification(ctx.tenant_id, sub, ctx.user_id)
        return success(result, request_id=request_id)

    raise ResourceNotFoundError("route", "/".join(parts))


def _dispatch_customer_notifications(
    event: dict[str, Any],
    method: str,
    parts: list[str],
    ctx: Any,
    request_id: str,
) -> dict[str, Any]:
    """Routes under /v1/notifications/customer/... — the customer portal's
    bell. Reuses the exact same `staff_notification` table and service
    functions as the staff bell above (they're already generic: tenant_id +
    user_id + role, no staff-specific logic) — a customer with a portal
    account is targeted via `target_user_id`, never `target_role`, so their
    own visibility scope only ever contains rows meant for them.

    Ground-truth gap found live, reported by the user: they rejected a
    payment claim and, checking as the customer, "did not see the
    notification when I logged in" — SMS/WhatsApp/email can each fail for
    reasons entirely outside this app, and until this route existed the
    customer portal had no in-app signal at all beyond a banner on the one
    specific billing page.

    Expected: ["v1", "notifications", "customer"] or [..., "unread-count"]
    or [..., "mark-all-read"] or [..., "clear-all"] or [..., "{id}", "read"]
    or DELETE [..., "{id}"].
    """
    ctx.assert_role(UserRole.CUSTOMER)
    sub = parts[3] if len(parts) > 3 else None
    action = parts[4] if len(parts) > 4 else None
    qp = event.get("queryStringParameters") or {}

    # GET /v1/notifications/customer
    if sub is None and method == "GET":
        cursor, limit = parse_pagination_params(qp)
        unread_only = qp.get("unread_only") == "true"
        page, next_cursor, has_more = service.list_staff_notifications(
            ctx.tenant_id,
            ctx.user_id,
            str(ctx.role),
            limit,
            cursor,
            unread_only=unread_only,
        )
        return paginated(page, next_cursor, has_more, request_id=request_id)

    # GET /v1/notifications/customer/unread-count
    if sub == "unread-count" and method == "GET":
        result: Any = service.count_unread_staff_notifications(ctx.tenant_id, ctx.user_id, str(ctx.role))
        return success(result, request_id=request_id)

    # GET /v1/notifications/customer/banner — the single active announcement
    # to show as a page banner, or null if none is currently active.
    if sub == "banner" and method == "GET":
        result = service.get_active_banner(ctx.tenant_id, ctx.user_id, str(ctx.role))
        return success(result, request_id=request_id)

    # PATCH /v1/notifications/customer/mark-all-read
    if sub == "mark-all-read" and method == "PATCH":
        result = service.mark_all_staff_notifications_read(ctx.tenant_id, ctx.user_id, str(ctx.role))
        return success(result, request_id=request_id)

    # DELETE /v1/notifications/customer/clear-all
    if sub == "clear-all" and method == "DELETE":
        result = service.dismiss_all_staff_notifications(ctx.tenant_id, ctx.user_id, str(ctx.role))
        return success(result, request_id=request_id)

    # PATCH /v1/notifications/customer/{id}/read
    if sub and action == "read" and method == "PATCH":
        result = service.mark_staff_notification_read(ctx.tenant_id, sub, ctx.user_id)
        return success(result, request_id=request_id)

    # DELETE /v1/notifications/customer/{id} — clear one
    if sub and action is None and method == "DELETE":
        result = service.dismiss_staff_notification(ctx.tenant_id, sub, ctx.user_id)
        return success(result, request_id=request_id)

    raise ResourceNotFoundError("route", "/".join(parts))


def _parse_body(event: dict[str, Any]) -> dict[str, Any]:
    raw = event.get("body") or "{}"
    try:
        return json.loads(raw)  # type: ignore[no-any-return]
    except json.JSONDecodeError:
        return {}


# tenant_admin and nigeria_office_staff only — matches the roles the user
# asked for directly ("tenant admin and nigeria staff should be able to send
# announcements").
_ANNOUNCE_ROLES = (UserRole.TENANT_ADMIN, UserRole.NIGERIA_OFFICE_STAFF)


def _handle_send_announcement(event: dict[str, Any], ctx: Any, request_id: str) -> dict[str, Any]:
    """POST /v1/notifications/announce — a manual broadcast, not a
    system-triggered event (e.g. a holiday-hours notice, or an
    import-maintenance window). Delivered via the same staff_notification
    bell as everything else, to a whole audience ("all_staff" or
    "all_customers") rather than any single person.

    tenant_admin can reach either audience and it goes out immediately.
    nigeria_office_staff can only target "all_customers", and it does not go
    out immediately — it's queued as a pending `announcement_request` for a
    tenant_admin to approve or reject first. Direct user requirement: "the
    staff can only send to customers, which should be approved by the
    tenant admins, this is to ensure that a compromised staff does not
    misinformation the customers."
    """
    ctx.assert_role(*_ANNOUNCE_ROLES)
    body = _parse_body(event)
    req = parse_validated(SendAnnouncementRequest, body)

    if not ctx.has_role(UserRole.TENANT_ADMIN):
        if req.audience != AnnouncementAudience.all_customers:
            from shared.exceptions import InsufficientPermissionsError

            raise InsufficientPermissionsError(
                "Staff may only send announcements to customers, and only a tenant admin can approve them. "
                "A tenant-wide staff announcement requires a tenant admin."
            )
        result = service.request_announcement(
            ctx.tenant_id,
            title=req.title,
            body=req.body,
            audience=req.audience.value,
            actor_id=ctx.user_id,
        )
        return created(result, location="/v1/notifications/announcements/pending", request_id=request_id)

    result = service.send_announcement(
        ctx.tenant_id,
        title=req.title,
        body=req.body,
        audience=req.audience.value,
        actor_id=ctx.user_id,
        actor_role=str(UserRole.TENANT_ADMIN),
    )
    return created(result, location="/v1/notifications/announce", request_id=request_id)


def _dispatch_announcements(
    event: dict[str, Any],
    method: str,
    parts: list[str],
    ctx: Any,
    request_id: str,
) -> dict[str, Any]:
    """Routes under /v1/notifications/announcements/... — the dedicated
    Announcements page's backend: tenant_admin's review queue + full CRUD
    over every sent announcement (banner toggle, edit, delete), and
    nigeria_office_staff's own "my announcements" list + edit/withdraw of a
    still-pending request. Unlike every other dispatcher in this file, role
    checks happen per-branch below rather than once at the top, since the
    two roles are allowed disjoint subsets of these routes.

    Two separate id spaces share this path tree, disambiguated by a literal
    "requests" segment: `announcement_request.id` under .../requests/{id}
    (a staff submission, pending tenant_admin review) vs.
    `staff_notification.announcement_group_id` directly under .../{id} (an
    already-live announcement — either sent immediately by tenant_admin, or
    created by approving a request).

    Expected shapes:
      GET    .../announcements                          (tenant_admin: history)
      GET    .../announcements/pending                   (tenant_admin: review queue)
      GET    .../announcements/mine                       (nigeria_office_staff: own requests)
      PATCH  .../announcements/requests/{id}/approve       (tenant_admin)
      PATCH  .../announcements/requests/{id}/reject        (tenant_admin)
      PATCH  .../announcements/requests/{id}               (nigeria_office_staff, own+pending: edit)
      DELETE .../announcements/requests/{id}               (nigeria_office_staff, own+pending: withdraw)
      PATCH  .../announcements/{group_id}/activate          (tenant_admin)
      PATCH  .../announcements/{group_id}/deactivate        (tenant_admin)
      PATCH  .../announcements/{group_id}                   (tenant_admin: edit)
      DELETE .../announcements/{group_id}                   (tenant_admin: delete)
    """
    sub = parts[3] if len(parts) > 3 else None
    p4 = parts[4] if len(parts) > 4 else None
    p5 = parts[5] if len(parts) > 5 else None
    qp = event.get("queryStringParameters") or {}

    # GET /v1/notifications/announcements — banner management history
    if sub is None and method == "GET":
        ctx.assert_role(UserRole.TENANT_ADMIN)
        result: Any = service.list_announcements(ctx.tenant_id)
        return success(result, request_id=request_id)

    # GET /v1/notifications/announcements/pending
    if sub == "pending" and p4 is None and method == "GET":
        ctx.assert_role(UserRole.TENANT_ADMIN)
        cursor, limit = parse_pagination_params(qp)
        page, next_cursor, has_more = service.list_pending_announcement_requests(ctx.tenant_id, limit, cursor)
        return paginated(page, next_cursor, has_more, request_id=request_id)

    # GET /v1/notifications/announcements/mine
    if sub == "mine" and method == "GET":
        ctx.assert_role(UserRole.NIGERIA_OFFICE_STAFF)
        result = service.list_my_announcement_requests(ctx.tenant_id, ctx.user_id)
        return success(result, request_id=request_id)

    # /v1/notifications/announcements/requests/{id}[/approve|reject]
    if sub == "requests" and p4:
        request_id_param = p4

        if p5 == "approve" and method == "PATCH":
            ctx.assert_role(UserRole.TENANT_ADMIN)
            result = service.approve_announcement_request(ctx.tenant_id, request_id_param, ctx.user_id, str(ctx.role))
            return success(result, request_id=request_id)

        if p5 == "reject" and method == "PATCH":
            ctx.assert_role(UserRole.TENANT_ADMIN)
            body = _parse_body(event)
            req = parse_validated(RejectAnnouncementRequestBody, body)
            result = service.reject_announcement_request(
                ctx.tenant_id,
                request_id_param,
                ctx.user_id,
                str(ctx.role),
                reason=req.reason,
            )
            return success(result, request_id=request_id)

        if p5 is None and method == "PATCH":
            ctx.assert_role(UserRole.NIGERIA_OFFICE_STAFF)
            body = _parse_body(event)
            req = parse_validated(UpdateAnnouncementBody, body)
            result = service.update_my_announcement_request(
                ctx.tenant_id,
                request_id_param,
                ctx.user_id,
                req.title,
                req.body,
            )
            return success(result, request_id=request_id)

        if p5 is None and method == "DELETE":
            ctx.assert_role(UserRole.NIGERIA_OFFICE_STAFF)
            result = service.delete_my_announcement_request(ctx.tenant_id, request_id_param, ctx.user_id)
            return success(result, request_id=request_id)

        raise ResourceNotFoundError("route", "/".join(parts))

    # Everything else under /v1/notifications/announcements/{group_id}... is
    # tenant_admin-only banner/CRUD management of an already-live announcement.
    if sub:
        group_id = sub
        ctx.assert_role(UserRole.TENANT_ADMIN)

        if p4 == "activate" and method == "PATCH":
            result = service.activate_announcement(ctx.tenant_id, group_id, ctx.user_id, str(ctx.role))
            return success(result, request_id=request_id)

        if p4 == "deactivate" and method == "PATCH":
            result = service.deactivate_announcement(ctx.tenant_id, group_id, ctx.user_id, str(ctx.role))
            return success(result, request_id=request_id)

        if p4 is None and method == "PATCH":
            body = _parse_body(event)
            req = parse_validated(UpdateAnnouncementBody, body)
            result = service.update_announcement(
                ctx.tenant_id,
                group_id,
                req.title,
                req.body,
                ctx.user_id,
                str(ctx.role),
            )
            return success(result, request_id=request_id)

        if p4 is None and method == "DELETE":
            result = service.delete_announcement(ctx.tenant_id, group_id, ctx.user_id, str(ctx.role))
            return success(result, request_id=request_id)

    raise ResourceNotFoundError("route", "/".join(parts))
