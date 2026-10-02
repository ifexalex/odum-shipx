"""Subscription tier limits — single source of truth.

Imported by services/metering and services/tenant_management so both use
identical limits without duplicating the constant or coupling service modules.

Resolution order for a tenant's effective limits:
  1. Static TIER_LIMITS default for the tenant's tier (below)
  2. Platform-wide per-plan overrides   — platform_settings key 'plan_limits'
     (shape: {"starter": {"users": 15, ...}, "business": {...}, ...})
  3. Per-tenant quota override          — platform_settings key
     'quota_override:{tenant_id}' (shape: {"users": 20, ...})

Overrides are partial — only the dimensions present are replaced.
Reads fail-open to the static defaults: quota enforcement is a soft
commercial limit, not a security boundary, so an infra failure must not
block tenant operations (unlike auth checks, which fail closed).
"""

import logging
from typing import Any

logger = logging.getLogger(__name__)

TIER_LIMITS: dict[str, dict[str, Any]] = {
    "starter": {"users": 10, "containers_per_month": 5, "storage_gb": 5.0},
    "business": {"users": 50, "containers_per_month": 25, "storage_gb": 25.0},
    "enterprise": {"users": 999999, "containers_per_month": 999999, "storage_gb": 999999.0},
}

DEFAULT_TIER = "starter"

# Dimensions a plan/tenant override may set — anything else is dropped.
LIMIT_DIMENSIONS = frozenset({"users", "containers_per_month", "storage_gb"})

PLAN_LIMITS_SETTING_KEY = "plan_limits"
QUOTA_OVERRIDE_KEY_PREFIX = "quota_override:"


def _read_setting(key: str) -> Any | None:
    """Read a single platform_settings value (PLATFORM scope); None on any failure."""
    try:
        from shared.db import execute_with_tenant
        from shared.tenant_context import PLATFORM_TENANT_ID

        rows = execute_with_tenant(
            PLATFORM_TENANT_ID,
            "SELECT value FROM platform_settings WHERE key = %s LIMIT 1",
            (key,),
        )
        return rows[0]["value"] if rows else None
    except Exception as exc:
        logger.warning("tier_limits: could not read platform setting %s: %s", key, exc)
        return None


def _sanitize(override: Any) -> dict[str, Any]:
    if not isinstance(override, dict):
        return {}
    return {k: v for k, v in override.items() if k in LIMIT_DIMENSIONS and isinstance(v, int | float)}


def get_effective_limits(tier: str, tenant_id: str | None = None) -> dict[str, Any]:
    """Merge static tier defaults ⊕ plan overrides ⊕ per-tenant override."""
    limits = dict(TIER_LIMITS.get(tier, TIER_LIMITS[DEFAULT_TIER]))

    plan_overrides = _read_setting(PLAN_LIMITS_SETTING_KEY)
    if isinstance(plan_overrides, dict):
        limits.update(_sanitize(plan_overrides.get(tier)))

    if tenant_id:
        tenant_override = _read_setting(f"{QUOTA_OVERRIDE_KEY_PREFIX}{tenant_id}")
        limits.update(_sanitize(tenant_override))

    return limits


def get_all_plan_limits() -> dict[str, dict[str, Any]]:
    """All tiers with plan-level overrides applied (no per-tenant overrides)."""
    plan_overrides = _read_setting(PLAN_LIMITS_SETTING_KEY)
    result: dict[str, dict[str, Any]] = {}
    for tier, defaults in TIER_LIMITS.items():
        merged = dict(defaults)
        if isinstance(plan_overrides, dict):
            merged.update(_sanitize(plan_overrides.get(tier)))
        result[tier] = merged
    return result
