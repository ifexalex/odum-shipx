"""A tenant's own settings.

Configuration keys, the outbound webhook and its secret, the Paystack gateway, notification templates, and the
tenant report.

Split out of ``service.py`` (audit BE-13); ``service`` re-exports every public function, so callers are unchanged.
"""

import json
import logging
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from shared.audit import log_audit
from shared.encryption import decrypt_field, encrypt_field
from shared.exceptions import (
    BusinessRuleViolationError,
    ResourceNotFoundError,
)
from shared.webhook import test_fire_tenant_webhook

from . import repository as repo
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


def get_tenant_config(tenant_id: str) -> dict[str, Any]:
    """Return tenant config as a flat dict keyed by config_key.

    The webhook_config.secret is masked to '****' — use the rotate-secret
    endpoint to retrieve a new secret in plaintext. paystack_config.
    secret_key_encrypted is stripped entirely — it is never returned to any
    client, encrypted or not (contrast with webhook secret rotation, which
    does show the plaintext once — a tenant's Paystack key isn't generated
    by ShipX, so there is no "show it once" moment to offer).
    """
    rows = repo.get_all_configs(tenant_id)
    config_map = {row["config_key"]: row["config_value"] for row in rows}
    return _mask_paystack_config(_mask_webhook_config(config_map))


def update_tenant_config(
    tenant_id: str,
    req: UpdateTenantConfigRequest,
    actor_id: str,
    ip_address: str | None = None,
) -> dict[str, Any]:
    if req.branding is not None:
        repo.upsert_config(tenant_id, "branding_config", req.branding, updated_by=actor_id)
        # Also update tenant.branding_config column
        repo.update_tenant(tenant_id, {"branding_config": json.dumps(req.branding)})
    if req.notification_preferences is not None:
        repo.upsert_config(tenant_id, "notification_preferences", req.notification_preferences, updated_by=actor_id)
        repo.update_tenant(tenant_id, {"notification_preferences": json.dumps(req.notification_preferences)})
    if req.webhook_config is not None:
        _update_webhook_config(tenant_id, req.webhook_config, actor_id, ip_address)
    if req.bank_transfer_config is not None:
        repo.upsert_config(tenant_id, "bank_transfer_config", req.bank_transfer_config.model_dump(), updated_by=actor_id)
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
        entity_id=f"{event_type}/{channel}",
        action="UPDATE" if existing else "CREATE",
        actor_id=actor_id,
        actor_role="tenant_admin",
        before_state=existing,
        after_state=row,
        ip_address=ip_address,
    )
    return row
