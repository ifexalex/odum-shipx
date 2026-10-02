"""Outbound webhook dispatcher for tenant ERP/WMS integrations.

Fires a signed HTTP POST to the tenant's configured webhook URL for key
domain events. Fire-and-forget: failures are logged but never propagate to
the caller.

Configuration is stored in `tenant_config` under key `webhook_config`:
  {
    "url": "https://erp.acme.com/hooks/shipx",
    "secret": "hmac-secret-key",
    "enabled": true,
    "events": ["container_arrived", "payment_due", "release_note_generated"]
  }

Signature: HMAC-SHA256 of the raw JSON body, sent as `X-ShipX-Signature-256`.
"""

import hashlib
import hmac
import json
import logging
import urllib.error
import urllib.request
from typing import Any

from shared.db import execute_with_tenant
from shared.url_safety import UnsafeUrlError, open_public_https

logger = logging.getLogger(__name__)

_TIMEOUT_SECONDS = 5


def _get_webhook_config(tenant_id: str) -> dict[str, Any] | None:
    """Fetch the tenant's webhook_config from tenant_config table."""
    try:
        rows = execute_with_tenant(
            tenant_id,
            "SELECT config_value FROM tenant_config WHERE tenant_id = %s AND config_key = 'webhook_config' LIMIT 1",
            (tenant_id,),
        )
        if not rows:
            return None
        val = rows[0]["config_value"]
        return val if isinstance(val, dict) else None
    except Exception as exc:
        logger.warning("Could not fetch webhook_config for tenant %s: %s", tenant_id, exc)
        return None


def _build_signed_request(
    url: str,
    secret: str,
    body: dict[str, Any],
    request_id: str = "",
) -> tuple[urllib.request.Request, bytes]:
    """Build a signed HTTP POST request for the given webhook payload."""
    raw_body = json.dumps(body, default=str).encode("utf-8")
    headers: dict[str, str] = {
        "Content-Type": "application/json",
        "X-ShipX-Event": str(body.get("event_type", "")),
        "X-Request-Id": request_id,
    }
    if secret:
        sig = hmac.new(secret.encode("utf-8"), raw_body, hashlib.sha256).hexdigest()
        headers["X-ShipX-Signature-256"] = f"sha256={sig}"
    return urllib.request.Request(url, data=raw_body, headers=headers, method="POST"), raw_body


def test_fire_tenant_webhook(
    tenant_id: str,
    request_id: str = "",
) -> dict[str, Any]:
    """Send a signed test event to the configured webhook URL and return the result.

    Unlike fire_tenant_webhook, this function returns delivery details so the
    caller can surface them to the tenant admin.

    Returns:
        Dict with keys: success (bool), status_code (int | None), error (str | None).
    """
    config = _get_webhook_config(tenant_id)
    if not config:
        return {"success": False, "status_code": None, "error": "No webhook_config found for tenant"}

    url: str = config.get("url", "")
    secret: str = config.get("secret", "")
    if not url:
        return {"success": False, "status_code": None, "error": "No endpoint URL configured"}

    body: dict[str, Any] = {
        "event_type": "test",
        "tenant_id": tenant_id,
        "request_id": request_id,
        "data": {"message": "This is a ShipX webhook test event"},
    }
    try:
        req, _ = _build_signed_request(url, secret, body, request_id)
        with open_public_https(req, _TIMEOUT_SECONDS) as resp:
            return {"success": True, "status_code": resp.status, "error": None}
    except UnsafeUrlError as exc:
        return {"success": False, "status_code": None, "error": str(exc)}
    except urllib.error.HTTPError as exc:
        return {"success": False, "status_code": exc.code, "error": f"HTTP {exc.code}"}
    except Exception as exc:
        return {"success": False, "status_code": None, "error": str(exc)}


def fire_tenant_webhook(
    tenant_id: str,
    event_type: str,
    payload: dict[str, Any],
    request_id: str = "",
) -> None:
    """Dispatch a signed HTTP POST webhook to the tenant's configured endpoint.

    Completely fire-and-forget — never raises. Failures are logged at WARNING.

    Args:
        tenant_id: The tenant UUID.
        event_type: The domain event type (e.g. "container_arrived").
        payload: The event-specific payload to include in the POST body.
        request_id: Correlation ID for tracing.
    """
    config = _get_webhook_config(tenant_id)
    if not config:
        return

    if not config.get("enabled", False):
        return

    allowed_events: list[str] | None = config.get("events")
    if allowed_events is not None and event_type not in allowed_events:
        return

    url: str = config.get("url", "")
    secret: str = config.get("secret", "")
    if not url:
        return

    body: dict[str, Any] = {
        "event_type": event_type,
        "tenant_id": tenant_id,
        "request_id": request_id,
        "data": payload,
    }
    try:
        req, _ = _build_signed_request(url, secret, body, request_id)
        with open_public_https(req, _TIMEOUT_SECONDS) as resp:
            status = resp.status
            logger.info(
                "Webhook delivered: event=%s tenant=%s status=%s",
                event_type,
                tenant_id,
                status,
            )
    except urllib.error.HTTPError as exc:
        logger.warning(
            "Webhook HTTP error: event=%s tenant=%s status=%s",
            event_type,
            tenant_id,
            exc.code,
        )
    except Exception as exc:
        logger.warning(
            "Webhook delivery failed: event=%s tenant=%s error=%s",
            event_type,
            tenant_id,
            exc,
        )
