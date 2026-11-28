"""A tenant's own settings.

Configuration keys, the outbound webhook and its secret, the Paystack gateway, notification templates, and the
tenant report.

Split out of ``service.py`` (audit BE-13); ``service`` re-exports every public function, so callers are unchanged.
"""

import json
import logging
import re
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from shared.audit import log_audit
from shared.encryption import decrypt_field, encrypt_field
from shared.exceptions import (
    BusinessRuleViolationError,
    ResourceNotFoundError,
    ValidationError,
)
from shared.webhook import test_fire_tenant_webhook

from . import repository as repo
from .branding_logo import keep_server_owned, with_logo_url
from .models import (
    PaystackConfigRequest,
    UpdateTenantConfigRequest,
    UpsertNotificationTemplateRequest,
    WebhookConfigRequest,
)

if TYPE_CHECKING:
    pass


logger = logging.getLogger(__name__)


def _generate_webhook_secret() -> str:
    """Generate a cryptographically random 32-byte hex secret for HMAC signing."""
    import secrets

    return secrets.token_hex(32)


def _mask_webhook_config(config_map: dict[str, Any]) -> dict[str, Any]:
    """Return config_map with webhook_config.secret replaced by '****'."""
    wh = config_map.get("webhook_config")
    if isinstance(wh, dict) and wh.get("secret"):
        config_map = {**config_map, "webhook_config": {**wh, "secret": "****"}}
    return config_map


def _mask_paystack_config(config_map: dict[str, Any]) -> dict[str, Any]:
    """Strip the encrypted key entirely — GET /v1/tenant/config never returns
    it, not even encrypted. Only last4/environment/enabled are client-safe."""
    ps = config_map.get("paystack_config")
    if isinstance(ps, dict) and "secret_key_encrypted" in ps:
        stripped = {k: v for k, v in ps.items() if k != "secret_key_encrypted"}
        config_map = {**config_map, "paystack_config": stripped}
    return config_map


# ---------------------------------------------------------------------------
# Tenant config
# ---------------------------------------------------------------------------


DEFAULT_TRANSIT_DAYS = 45


def _parse_transit_days(raw: Any) -> int:
    """Coerce a stored default_transit_days value to a positive int, else DEFAULT_TRANSIT_DAYS (45)."""
    if isinstance(raw, bool):
        return DEFAULT_TRANSIT_DAYS
    if isinstance(raw, int) and 1 <= raw <= 365:
        return raw
    if isinstance(raw, dict):
        return _parse_transit_days(raw.get("days") or raw.get("default_transit_days"))
    try:
        parsed = int(raw)
        if 1 <= parsed <= 365:
            return parsed
    except (TypeError, ValueError):
        pass
    return DEFAULT_TRANSIT_DAYS


def get_default_transit_days(tenant_id: str) -> int:
    """Return this tenant's configured transit duration in days, defaulting to 45."""
    rows = repo.get_all_configs(tenant_id)
    for row in rows:
        if row.get("config_key") == "default_transit_days":
            return _parse_transit_days(row.get("config_value"))
    return DEFAULT_TRANSIT_DAYS


_CUSTOMER_VISIBLE_CONFIG_KEYS: frozenset[str] = frozenset(
    {
        "branding_config",
        "bank_transfer_config",
        "default_transit_days",
        "paystack_config",
    }
)
_STAFF_VISIBLE_CONFIG_KEYS: frozenset[str] = _CUSTOMER_VISIBLE_CONFIG_KEYS | frozenset({"warehouse_address"})


def get_tenant_config(tenant_id: str, *, ctx: Any = None) -> dict[str, Any]:
    """Return tenant config as a flat dict keyed by config_key, scoped by caller role.

    - ``TENANT_ADMIN`` (or internal callers with ``ctx=None``): full config with
      ``webhook_config.secret`` masked and ``paystack_config.secret_key_encrypted`` stripped.
    - Non-admin staff: branding, bank transfer, transit days, warehouse address, and
      ``paystack_config.enabled`` only.
    - ``CUSTOMER``: branding, bank transfer, transit days, and ``paystack_config.enabled`` only
      (never internal FX markup, CBM rates, approval thresholds, or webhook URLs).
    """
    from shared.tenant_context import UserRole

    rows = repo.get_all_configs(tenant_id)
    config_map = {row["config_key"]: row["config_value"] for row in rows}
    # The logo is shown through a short-lived link, never its storage key (FD-29).
    if "branding_config" in config_map:
        config_map["branding_config"] = with_logo_url(tenant_id, config_map["branding_config"])
    # Always expose the effective default transit duration (45 days unless overridden).
    config_map["default_transit_days"] = _parse_transit_days(config_map.get("default_transit_days"))
    masked = _mask_paystack_config(_mask_webhook_config(config_map))

    if ctx is None or ctx.has_role(UserRole.TENANT_ADMIN):
        return masked

    is_staff = ctx.has_role(
        UserRole.CHINA_OFFICE_STAFF,
        UserRole.NIGERIA_OFFICE_STAFF,
        UserRole.WAREHOUSE_ATTENDANT,
    )
    allowed_keys = _STAFF_VISIBLE_CONFIG_KEYS if is_staff else _CUSTOMER_VISIBLE_CONFIG_KEYS
    filtered = {k: v for k, v in masked.items() if k in allowed_keys}
    if "paystack_config" in filtered and isinstance(filtered["paystack_config"], dict):
        filtered["paystack_config"] = {"enabled": bool(filtered["paystack_config"].get("enabled"))}
    return filtered


_HEX_COLOR_RE = re.compile(r"^#[0-9A-Fa-f]{6}$")
_BRANDING_COLOR_KEYS = ("primary_color", "secondary_color", "accent_color")


def _validate_branding(branding: dict[str, Any]) -> None:
    for key in _BRANDING_COLOR_KEYS:
        val = branding.get(key)
        if val is not None and val != "" and (not isinstance(val, str) or not _HEX_COLOR_RE.fullmatch(val)):
            raise ValidationError(
                f"branding.{key} must be a 6-digit hex color (e.g. #1a2b3c)",
                field_errors={f"branding.{key}": "must be #RRGGBB"},
            )


def update_tenant_config(
    tenant_id: str,
    req: UpdateTenantConfigRequest,
    actor_id: str,
    ip_address: str | None = None,
) -> dict[str, Any]:
    if req.branding is not None:
        _validate_branding(req.branding)
        # The logo fields are the server's (FD-29): a save from the settings form keeps the stored logo, and a client
        # can never point it at a file of its choosing.
        branding = keep_server_owned(tenant_id, req.branding)
        repo.upsert_config(tenant_id, "branding_config", branding, updated_by=actor_id)
        # Also update tenant.branding_config column
        repo.update_tenant(tenant_id, {"branding_config": json.dumps(branding)})
        log_audit(
            tenant_id=tenant_id,
            entity_type="tenant_config",
            entity_id=tenant_id,
            action="UPDATE",
            actor_id=actor_id,
            actor_role="tenant_admin",
            after_state={"branding_config": branding},
            ip_address=ip_address,
        )
    if req.notification_preferences is not None:
        repo.upsert_config(tenant_id, "notification_preferences", req.notification_preferences, updated_by=actor_id)
        repo.update_tenant(tenant_id, {"notification_preferences": json.dumps(req.notification_preferences)})
        log_audit(
            tenant_id=tenant_id,
            entity_type="tenant_config",
            entity_id=tenant_id,
            action="UPDATE",
            actor_id=actor_id,
            actor_role="tenant_admin",
            after_state={"notification_preferences": req.notification_preferences},
            ip_address=ip_address,
        )
    if req.webhook_config is not None:
        _update_webhook_config(tenant_id, req.webhook_config, actor_id, ip_address)
    if req.bank_transfer_config is not None:
        bank_cfg = req.bank_transfer_config.model_dump()
        repo.upsert_config(tenant_id, "bank_transfer_config", bank_cfg, updated_by=actor_id)
        log_audit(
            tenant_id=tenant_id,
            entity_type="tenant_config",
            entity_id=tenant_id,
            action="UPDATE",
            actor_id=actor_id,
            actor_role="tenant_admin",
            after_state={"bank_transfer_config": bank_cfg},
            ip_address=ip_address,
        )
    if req.default_transit_days is not None:
        repo.upsert_config(tenant_id, "default_transit_days", {"days": req.default_transit_days}, updated_by=actor_id)
        log_audit(
            tenant_id=tenant_id,
            entity_type="tenant_config",
            entity_id=tenant_id,
            action="UPDATE",
            actor_id=actor_id,
            actor_role="tenant_admin",
            after_state={"default_transit_days": req.default_transit_days},
            ip_address=ip_address,
        )
    return get_tenant_config(tenant_id)


def _update_webhook_config(
    tenant_id: str,
    req: WebhookConfigRequest,
    actor_id: str,
    ip_address: str | None = None,
) -> None:
    """Persist webhook_config, preserving the existing signing secret."""
    rows = repo.get_all_configs(tenant_id)
    existing_map = {r["config_key"]: r["config_value"] for r in rows}
    existing_wh: dict[str, Any] = existing_map.get("webhook_config") or {}
    existing_secret: str = existing_wh.get("secret", "") or _generate_webhook_secret()

    new_wh: dict[str, Any] = {
        "enabled": req.enabled,
        "url": req.endpoint_url,
        "secret": existing_secret,
        "events": [e.value for e in req.events],
    }
    repo.upsert_config(tenant_id, "webhook_config", new_wh, updated_by=actor_id)
    log_audit(
        tenant_id=tenant_id,
        entity_type="tenant_config",
        entity_id=tenant_id,
        action="UPDATE",
        actor_id=actor_id,
        actor_role="tenant_admin",
        before_state={**existing_wh, "secret": "****"} if existing_wh else None,
        after_state={**new_wh, "secret": "****"},
        ip_address=ip_address,
    )


def rotate_webhook_secret(
    tenant_id: str,
    actor_id: str,
    ip_address: str | None = None,
) -> dict[str, Any]:
    """Generate a new HMAC signing secret, store it, and return it once in plaintext.

    The caller is responsible for immediately distributing the secret to their
    integration. Subsequent reads of /v1/tenant/config return '****'.
    """
    rows = repo.get_all_configs(tenant_id)
    existing_map = {r["config_key"]: r["config_value"] for r in rows}
    existing_wh: dict[str, Any] = dict(existing_map.get("webhook_config") or {})

    new_secret = _generate_webhook_secret()
    updated_wh = {**existing_wh, "secret": new_secret}
    repo.upsert_config(tenant_id, "webhook_config", updated_wh, updated_by=actor_id)
    log_audit(
        tenant_id=tenant_id,
        entity_type="tenant_config",
        entity_id=tenant_id,
        action="UPDATE",
        actor_id=actor_id,
        actor_role="tenant_admin",
        before_state={"action": "webhook_secret_rotated", "secret": "****"},
        after_state={"action": "webhook_secret_rotated", "secret": "****"},
        ip_address=ip_address,
    )
    return {"secret": new_secret}


def test_webhook_delivery(
    tenant_id: str,
    actor_id: str,
    request_id: str = "",
) -> dict[str, Any]:
    """Send a signed test event to the configured webhook URL.

    Uses the same signing path as real events. Returns delivery result.
    """
    result = test_fire_tenant_webhook(tenant_id, request_id=request_id)
    log_audit(
        tenant_id=tenant_id,
        entity_type="tenant_config",
        entity_id=tenant_id,
        action="UPDATE",
        actor_id=actor_id,
        actor_role="tenant_admin",
        after_state={"action": "webhook_test", **result},
    )
    return result


# ---------------------------------------------------------------------------
# Paystack config — multi-tenant payment gateway (2026-07-19)
#
# Each tenant connects their own Paystack secret key so customer payments
# land directly in that tenant's own account — there is no platform-wide
# key anywhere in this system. The key is encrypted at rest via
# shared/encryption.py (KMS + Fernet) — a stronger posture than
# webhook_config.secret's plaintext storage, deliberately: a Paystack
# secret key can move real money out of the tenant's account, whereas the
# webhook secret only signs outbound payloads ShipX sends. See
# 11_api_billing.md / 07_api_tenant_management.md for the full design note.
# ---------------------------------------------------------------------------


def update_paystack_config(
    tenant_id: str,
    req: PaystackConfigRequest,
    actor_id: str,
    ip_address: str | None = None,
) -> dict[str, Any]:
    """Connect (or replace) this tenant's Paystack secret key.

    Always a full replace, never a partial merge — there is nothing to
    preserve across a resubmission, unlike webhook_config's secret.
    """
    environment = "live" if req.secret_key.startswith("sk_live_") else "test"
    last4 = req.secret_key[-4:]

    new_ps = {
        "enabled": True,
        "secret_key_encrypted": encrypt_field(req.secret_key),
        "last4": last4,
        "environment": environment,
        "configured_by": actor_id,
        "configured_at": datetime.now(UTC).isoformat(),
    }
    repo.upsert_config(tenant_id, "paystack_config", new_ps, updated_by=actor_id)
    log_audit(
        tenant_id=tenant_id,
        entity_type="tenant_config",
        entity_id=tenant_id,
        action="UPDATE",
        actor_id=actor_id,
        actor_role="tenant_admin",
        after_state={"action": "paystack_configured", "environment": environment, "last4": last4},
        ip_address=ip_address,
    )
    return {k: v for k, v in new_ps.items() if k != "secret_key_encrypted"}


def delete_paystack_config(
    tenant_id: str,
    actor_id: str,
    ip_address: str | None = None,
) -> dict[str, Any]:
    """Disconnect Paystack — online payment reverts to bank-transfer-only
    for this tenant's customers until reconfigured."""
    repo.delete_config(tenant_id, "paystack_config")
    log_audit(
        tenant_id=tenant_id,
        entity_type="tenant_config",
        entity_id=tenant_id,
        action="UPDATE",
        actor_id=actor_id,
        actor_role="tenant_admin",
        after_state={"action": "paystack_disconnected"},
        ip_address=ip_address,
    )
    return {"enabled": False}


def test_paystack_connection(tenant_id: str, actor_id: str, request_id: str = "") -> dict[str, Any]:
    """Prove the stored key actually works against the live Paystack API.

    Raises BusinessRuleViolationError if nothing is configured yet;
    propagates ExternalServiceError (with a tenant-safe message) if
    Paystack rejects the key or is unreachable.
    """
    from services.payment_release import paystack as paystack_client

    rows = repo.get_all_configs(tenant_id)
    config_map = {r["config_key"]: r["config_value"] for r in rows}
    ps = config_map.get("paystack_config") or {}
    if not ps.get("enabled") or not ps.get("secret_key_encrypted"):
        raise BusinessRuleViolationError(
            "Connect a Paystack secret key before testing the connection.",
            rule_id="PAYMENT_GATEWAY_NOT_CONFIGURED",
        )

    secret_key = decrypt_field(ps["secret_key_encrypted"])
    if secret_key is None:
        raise BusinessRuleViolationError(
            "Connect a Paystack secret key before testing the connection.",
            rule_id="PAYMENT_GATEWAY_NOT_CONFIGURED",
        )
    paystack_client.test_connection(secret_key)  # raises ExternalServiceError on failure

    log_audit(
        tenant_id=tenant_id,
        entity_type="tenant_config",
        entity_id=tenant_id,
        action="UPDATE",
        actor_id=actor_id,
        actor_role="tenant_admin",
        after_state={"action": "paystack_test", "result": "success"},
    )
    return {"success": True, "environment": ps.get("environment")}


# ---------------------------------------------------------------------------
# Tenant reports (tenant_admin)
# ---------------------------------------------------------------------------


def get_tenant_report(tenant_id: str) -> dict[str, Any]:
    """Return aggregated analytics for the tenant's current calendar month."""
    from datetime import date

    period = date.today().strftime("%Y-%m")
    return repo.get_tenant_report_data(tenant_id, period)


# ---------------------------------------------------------------------------
# Notification templates (tenant_admin)
# ---------------------------------------------------------------------------


def list_notification_templates(tenant_id: str) -> list[dict[str, Any]]:
    return repo.list_notification_templates(tenant_id)


def get_notification_template(
    tenant_id: str,
    event_type: str,
    channel: str,
) -> dict[str, Any]:
    template = repo.get_notification_template(tenant_id, event_type, channel)
    if not template:
        raise ResourceNotFoundError("notification_template", f"{event_type}/{channel}")
    return template


def upsert_notification_template(
    tenant_id: str,
    event_type: str,
    channel: str,
    req: UpsertNotificationTemplateRequest,
    actor_id: str,
    ip_address: str | None = None,
) -> dict[str, Any]:
    existing = repo.get_notification_template(tenant_id, event_type, channel)
    row = repo.upsert_notification_template(
        tenant_id,
        {
            "tenant_id": tenant_id,
            "event_type": event_type,
            "channel": channel,
            "template_body": req.template_body,
            "subject": req.subject,
            "updated_by": actor_id,
        },
    )
    if row is None:
        raise RuntimeError("upsert_notification_template returned None unexpectedly")
    log_audit(
        tenant_id=tenant_id,
        entity_type="notification_template",
        entity_id=str(row.get("id") or tenant_id),
        action="UPDATE" if existing else "CREATE",
        actor_id=actor_id,
        actor_role="tenant_admin",
        before_state=existing,
        after_state=row,
        ip_address=ip_address,
    )
    return row
