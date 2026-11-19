"""Platform-admin settings.

Platform settings, plans and per-tenant quota overrides, a tenant's own quota read, and the notification provider
gateways.

Split out of ``service.py`` (audit BE-13); ``service`` re-exports every public function, so callers are unchanged.
"""

import logging
from typing import TYPE_CHECKING, Any

from shared.exceptions import (
    BusinessRuleViolationError,
    ResourceNotFoundError,
)

from . import repository as repo

if TYPE_CHECKING:
    pass


logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Platform settings (platform_admin)
# ---------------------------------------------------------------------------


def get_platform_settings() -> dict[str, Any]:
    """Return all platform settings as a flat dict."""
    return repo.get_platform_settings()


def update_platform_settings(settings: dict[str, Any], actor_id: str) -> dict[str, Any]:
    """Upsert each key in the provided settings dict."""
    for key, value in settings.items():
        repo.upsert_platform_setting(key, value, actor_id)
    return repo.get_platform_settings()


# ---------------------------------------------------------------------------
# Tenant quota — GET /v1/tenants/me/quota
# ---------------------------------------------------------------------------


def get_tenant_quota(tenant_id: str) -> dict[str, Any]:
    """Return real-time quota usage for the caller's own tenant.

    Response shape mirrors GET /v1/platform/tenants/{id}/usage so the same
    frontend TenantQuota type covers both.
    """
    from calendar import monthrange
    from datetime import date

    from shared.tier_limits import get_effective_limits

    tier = repo.get_subscription_tier(tenant_id)
    limits = get_effective_limits(tier, tenant_id)

    users_used = repo.count_active_users(tenant_id)
    containers_used = repo.count_containers_this_month(tenant_id)

    today = date.today()
    last_day = monthrange(today.year, today.month)[1]
    period_start = date(today.year, today.month, 1)
    period_end = date(today.year, today.month, last_day)

    from shared.db import execute_with_tenant

    usage_rows = execute_with_tenant(
        tenant_id,
        """
        SELECT metric_type, SUM(value) AS total_value
        FROM usage_record
        WHERE tenant_id   = %s
          AND period_start >= %s
          AND period_end   <= %s
        GROUP BY metric_type
        """,
        (tenant_id, period_start, period_end),
    )
    metrics: dict[str, float] = {r["metric_type"]: float(r["total_value"]) for r in usage_rows}

    storage_rows = execute_with_tenant(
        tenant_id,
        """
        SELECT value FROM usage_record
        WHERE tenant_id = %s AND metric_type = 'storage_bytes'
        ORDER BY recorded_at DESC LIMIT 1
        """,
        (tenant_id,),
    )
    storage_bytes = float(storage_rows[0]["value"]) if storage_rows else 0.0
    storage_gb = round(storage_bytes / (1024**3), 2)

    return {
        "tenant_id": tenant_id,
        "period": f"{today.year:04d}-{today.month:02d}",
        "subscription_tier": tier,
        "limits": {
            "users": {"used": users_used, "max": limits["users"]},
            "containers_per_month": {"used": containers_used, "max": limits["containers_per_month"]},
            "storage_gb": {"used": storage_gb, "max": limits["storage_gb"]},
        },
        "api_calls": int(metrics.get("api_calls", 0)),
        "notifications": {
            "sms_sent": int(metrics.get("sms_sent", 0)),
            "whatsapp_sent": int(metrics.get("whatsapp_sent", 0)),
            "emails_sent": int(metrics.get("emails_sent", 0)),
        },
    }


# ---------------------------------------------------------------------------
# Platform plans + quota overrides (B-2 / B-3)
# ---------------------------------------------------------------------------


def get_plans() -> dict[str, Any]:
    """All subscription tiers with plan-level overrides applied."""
    from shared.tier_limits import get_all_plan_limits

    return {"plans": get_all_plan_limits()}


def update_plan(tier: str, body: dict[str, Any], actor_id: str, ip_address: str | None = None) -> dict[str, Any]:
    """Override a tier's default limits platform-wide.

    Only the dimensions present in the body are overridden; the rest keep
    their static defaults. Stored in platform_settings under 'plan_limits'.
    """
    from shared.tier_limits import LIMIT_DIMENSIONS, PLAN_LIMITS_SETTING_KEY, TIER_LIMITS

    if tier not in TIER_LIMITS:
        raise ResourceNotFoundError("plan", tier)

    override = {k: v for k, v in body.items() if k in LIMIT_DIMENSIONS and isinstance(v, int | float) and v >= 0}
    if not override:
        raise BusinessRuleViolationError(
            f"No valid limit dimensions in body. Allowed: {', '.join(sorted(LIMIT_DIMENSIONS))}",
            rule_id="INVALID_PLAN_LIMITS",
        )

    settings = repo.get_platform_settings()
    plan_limits = settings.get(PLAN_LIMITS_SETTING_KEY) or {}
    if not isinstance(plan_limits, dict):
        plan_limits = {}
    plan_limits[tier] = {**(plan_limits.get(tier) or {}), **override}
    repo.upsert_platform_setting(PLAN_LIMITS_SETTING_KEY, plan_limits, actor_id)

    try:
        repo.insert_platform_audit(
            action="PLAN_LIMITS_UPDATED",
            actor_id=actor_id,
            target_tenant_id=None,
            details={"tier": tier, "override": override},
            ip_address=ip_address,
        )
    except Exception as exc:
        logger.warning("Platform audit insert failed: %s", exc)

    return get_plans()


def set_quota_override(
    tenant_id: str,
    body: dict[str, Any],
    actor_id: str,
    ip_address: str | None = None,
) -> dict[str, Any]:
    """Set (or clear, with an empty body) a per-tenant quota override.

    Overrides win over both the tier default and any plan-level override —
    see shared/tier_limits.get_effective_limits.
    """
    from shared.tier_limits import LIMIT_DIMENSIONS, QUOTA_OVERRIDE_KEY_PREFIX, get_effective_limits

    tenant = repo.get_tenant_by_id(tenant_id)
    if not tenant:
        raise ResourceNotFoundError("tenant", tenant_id)

    override = {k: v for k, v in body.items() if k in LIMIT_DIMENSIONS and isinstance(v, int | float) and v >= 0}
    key = f"{QUOTA_OVERRIDE_KEY_PREFIX}{tenant_id}"
    repo.upsert_platform_setting(key, override, actor_id)

    try:
        repo.insert_platform_audit(
            action="QUOTA_OVERRIDE_SET" if override else "QUOTA_OVERRIDE_CLEARED",
            actor_id=actor_id,
            target_tenant_id=tenant_id,
            details={"override": override},
            ip_address=ip_address,
        )
    except Exception as exc:
        logger.warning("Platform audit insert failed: %s", exc)

    tier = tenant.get("subscription_tier") or "starter"
    return {
        "tenant_id": tenant_id,
        "override": override,
        "effective_limits": get_effective_limits(tier, tenant_id),
    }


# ---------------------------------------------------------------------------
# Notification provider gateway settings (B-1)
# ---------------------------------------------------------------------------

# Per-provider config contract. Secret fields are masked on every read.
_GATEWAY_KINDS: dict[str, dict[str, Any]] = {
    "sms": {  # Termii
        "setting_key": "sms_gateway",
        "required": ("api_key", "sender_id"),
        "secret_fields": ("api_key",),
    },
    "whatsapp": {  # Meta Cloud API
        "setting_key": "whatsapp_gateway",
        "required": ("access_token", "phone_number_id"),
        "secret_fields": ("access_token",),
    },
    "email": {  # Postmark
        "setting_key": "email_gateway",
        "required": ("server_token", "from_email"),
        "secret_fields": ("server_token",),
    },
}


def _mask_gateway(cfg: dict[str, Any], secret_fields: tuple[str, ...]) -> dict[str, Any]:
    masked = dict(cfg)
    for field in secret_fields:
        if masked.get(field):
            masked[field] = "****"
    return masked


def get_gateway_settings() -> dict[str, Any]:
    """All three provider configs, secrets masked."""
    settings = repo.get_platform_settings()
    out: dict[str, Any] = {}
    for kind, spec in _GATEWAY_KINDS.items():
        cfg = settings.get(spec["setting_key"]) or {}
        out[kind] = _mask_gateway(cfg, spec["secret_fields"]) if isinstance(cfg, dict) else {}
    return out


def update_gateway_settings(
    kind: str,
    body: dict[str, Any],
    actor_id: str,
    ip_address: str | None = None,
) -> dict[str, Any]:
    """Update one provider's gateway config.

    A masked secret value ('****') in the body means "keep the stored value" —
    so the UI can round-trip the masked GET response without wiping secrets.
    """
    spec = _GATEWAY_KINDS.get(kind)
    if not spec:
        raise ResourceNotFoundError("gateway", kind)

    settings = repo.get_platform_settings()
    existing = settings.get(spec["setting_key"]) or {}
    if not isinstance(existing, dict):
        existing = {}

    merged = {**existing}
    for k, v in body.items():
        if k in spec["secret_fields"] and v == "****":
            continue  # masked round-trip — keep stored secret
        merged[k] = v

    repo.upsert_platform_setting(spec["setting_key"], merged, actor_id)

    try:
        repo.insert_platform_audit(
            action="GATEWAY_SETTINGS_UPDATED",
            actor_id=actor_id,
            target_tenant_id=None,
            details={"gateway": kind, "fields": sorted(body.keys())},  # never log values
            ip_address=ip_address,
        )
    except Exception as exc:
        logger.warning("Platform audit insert failed: %s", exc)

    return {kind: _mask_gateway(merged, spec["secret_fields"])}


def test_gateway(kind: str) -> dict[str, Any]:
    """Configuration test for a provider gateway.

    Validates that all required fields are present and non-empty. This is a
    config-shape check, not a live provider call — actual deliverability is
    proven by the notification pipeline (services/notification), which reads
    the same settings.
    """
    spec = _GATEWAY_KINDS.get(kind)
    if not spec:
        raise ResourceNotFoundError("gateway", kind)

    settings = repo.get_platform_settings()
    cfg = settings.get(spec["setting_key"]) or {}
    if not isinstance(cfg, dict):
        cfg = {}

    missing = [f for f in spec["required"] if not cfg.get(f)]
    if missing:
        return {"success": False, "error": f"Missing required fields: {', '.join(missing)}"}
    return {"success": True, "error": None}
