"""Business logic layer for the Tenant Management service.

Coordinates between the repository (SQL), Cognito client, shared audit,
events, and metering utilities. Raises typed exceptions from shared.exceptions
— never raw Python exceptions.
"""

import json
import logging
from datetime import UTC, datetime
from typing import Any

from shared.audit import log_audit
from shared.events import publish_event
from shared.exceptions import (
    BusinessRuleViolationError,
    DuplicateResourceError,
    ResourceNotFoundError,
    TenantOffboardedError,
    UsageLimitExceededError,
)
from shared.metering import record_usage
from shared.tenant_context import PLATFORM_TENANT_ID

from . import repository as repo
from .cognito_client import get_cognito_client
from .models import (
    CreateTenantRequest,
    CreateTenantUserRequest,
    UpdateDollarRateRequest,
    UpdateTenantConfigRequest,
    UpdateTenantRequest,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

DEFAULT_CONFIGS: dict[str, Any] = {
    "dollar_rate": {
        "rate": 1550.00,
        "currency_pair": "USD_NGN",
        "effective_from": "",
    },
    "cbm_rate_per_unit": {"rate_usd": 45.00},
    "storage_fee": {
        "enabled": True,
        "grace_period_days": 14,
        "daily_fee_per_carton_ngn": 500,
    },
    "warehouse_address": {"address": "", "city": "Lagos", "state": "Lagos"},
    "refund_threshold_usd": {"staff_limit": 50, "requires_manager_above": 50},
    "dispute_escalation": {"enabled": True, "auto_escalate_days": 5},
    "reminder_days": {"storage_first_reminder": 7, "storage_final_reminder": 13},
}

TIER_USER_LIMITS: dict[str, int] = {
    "starter": 10,
    "business": 50,
    "enterprise": 500,
}


# ---------------------------------------------------------------------------
# Tenant CRUD
# ---------------------------------------------------------------------------


def create_tenant(
    req: CreateTenantRequest,
    actor_id: str,
    request_id: str = "",
    ip_address: str | None = None,
) -> dict[str, Any]:
    """Create a new tenant with initial admin user and default config.

    Steps:
      1. Insert tenant row
      2. Create Cognito user + group for initial admin
      3. Insert tenant_user row
      4. Upsert all default tenant_config rows
      5. Publish TenantOnboarded event
      6. Log to platform_audit_log
    """
    cognito = get_cognito_client()

    # 1. Create tenant
    tenant = repo.create_tenant(
        {
            "company_name": req.company_name,
            "primary_contact_email": req.primary_contact_email,
            "primary_contact_phone": req.primary_contact_phone,
            "origin_country": req.origin_country,
            "destination_country": req.destination_country,
            "subscription_tier": req.subscription_tier.value,
        }
    )
    if tenant is None:
        raise RuntimeError("create_tenant returned None unexpectedly")
    tenant_id = str(tenant["id"])

    # 2. Provision Cognito user and group
    group_name = f"{tenant_id}:tenant_admin"
    cognito_sub = cognito.create_user(
        email=req.initial_admin.email,
        full_name=req.initial_admin.full_name,
        tenant_id=tenant_id,
        role="tenant_admin",
    )
    cognito.create_group_if_not_exists(group_name)
    cognito.add_user_to_group(req.initial_admin.email, group_name)

    # 3. Insert tenant_user record
    admin_user = repo.create_tenant_user(
        tenant_id,
        {
            "tenant_id": tenant_id,
            "cognito_sub": cognito_sub,
            "email": req.initial_admin.email,
            "full_name": req.initial_admin.full_name,
            "role": "tenant_admin",
            "created_by": None,
        },
    )
    if admin_user is None:
        raise RuntimeError("create_tenant_user returned None unexpectedly")

    # 4. Upsert default configs
    today = datetime.now(UTC).isoformat()
    default_dollar_rate = {**DEFAULT_CONFIGS["dollar_rate"], "effective_from": today}
    configs_to_insert = {**DEFAULT_CONFIGS, "dollar_rate": default_dollar_rate}
    for key, value in configs_to_insert.items():
        repo.upsert_config(tenant_id, key, value, updated_by=str(admin_user["id"]))

    # 5. Publish event
    try:
        publish_event(
            source="logistics.tenant_management",
            detail_type="TenantOnboarded",
            tenant_id=PLATFORM_TENANT_ID,
            payload={
                "tenant_id": tenant_id,
                "company_name": req.company_name,
                "subscription_tier": req.subscription_tier.value,
                "admin_email": req.initial_admin.email,
            },
            request_id=request_id,
        )
    except Exception as exc:
        logger.warning("TenantOnboarded event publish failed: %s", exc)

    # 6. Platform audit
    try:
        repo.insert_platform_audit(
            action="TENANT_CREATED",
            actor_id=actor_id,
            target_tenant_id=tenant_id,
            details={"company_name": req.company_name, "tier": req.subscription_tier.value},
            ip_address=ip_address,
        )
    except Exception as exc:
        logger.warning("Platform audit insert failed: %s", exc)

    return {"tenant": tenant, "admin_user": admin_user}


def list_tenants(limit: int = 50, cursor: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    return repo.list_tenants(limit=limit, cursor=cursor)


def get_tenant(tenant_id: str) -> dict[str, Any]:
    tenant = repo.get_tenant_by_id(tenant_id)
    if not tenant:
        raise ResourceNotFoundError("tenant", tenant_id)
    return tenant


def update_tenant(
    tenant_id: str,
    req: UpdateTenantRequest,
    actor_id: str,
    ip_address: str | None = None,
) -> dict[str, Any]:
    existing = get_tenant(tenant_id)
    if existing["status"] == "offboarded":
        raise TenantOffboardedError(tenant_id)
    updates = req.model_dump(exclude_none=True)
    if not updates:
        return existing
    updated = repo.update_tenant(tenant_id, updates)
    if updated is None:
        raise RuntimeError("update_tenant returned None unexpectedly")
    try:
        repo.insert_platform_audit(
            action="TENANT_UPDATED",
            actor_id=actor_id,
            target_tenant_id=tenant_id,
            details=updates,
            ip_address=ip_address,
        )
    except Exception as exc:
        logger.warning("Platform audit insert failed: %s", exc)
    return updated


def offboard_tenant(
    tenant_id: str,
    actor_id: str,
    ip_address: str | None = None,
) -> dict[str, Any]:
    existing = get_tenant(tenant_id)
    if existing["status"] == "offboarded":
        raise BusinessRuleViolationError("Tenant is already offboarded")
    updated = repo.set_tenant_status(tenant_id, "offboarded")
    if updated is None:
        raise RuntimeError("set_tenant_status returned None unexpectedly")

    # Art. 32 — immediately block further requests: evict the cached 'active'
    # status so _check_tenant_active() hits the DB on the very next request
    # rather than serving the stale cache for up to the TTL window.
    try:
        from shared.auth import _tenant_status_cache

        _tenant_status_cache.delete(tenant_id)
    except Exception as exc:
        logger.warning("Cache eviction failed for tenant %s: %s", tenant_id, exc)

    # Art. 32 — revoke all active Cognito sessions so existing access tokens
    # and refresh tokens cannot be used to obtain new tokens after offboarding.
    # Best-effort: a Cognito outage must not roll back the offboarding itself.
    try:
        from services.tenant_management.cognito_client import get_cognito_client

        cognito = get_cognito_client()
        for user in repo.list_users(tenant_id):
            email: str = user.get("email", "")
            if email:
                cognito.global_sign_out(email)
    except Exception as exc:
        logger.warning("Cognito session revocation failed for tenant %s: %s", tenant_id, exc)

    try:
        repo.insert_platform_audit(
            action="TENANT_OFFBOARDED",
            actor_id=actor_id,
            target_tenant_id=tenant_id,
            ip_address=ip_address,
        )
    except Exception as exc:
        logger.warning("Platform audit insert failed: %s", exc)
    return updated


def suspend_tenant(
    tenant_id: str,
    reason: str,
    actor_id: str,
    ip_address: str | None = None,
) -> dict[str, Any]:
    existing = get_tenant(tenant_id)
    if existing["status"] != "active":
        raise BusinessRuleViolationError(f"Cannot suspend tenant with status '{existing['status']}'")
    updated = repo.set_tenant_status(tenant_id, "suspended")
    if updated is None:
        raise RuntimeError("set_tenant_status returned None unexpectedly")

    # Immediately evict the cached status so auth blocks requests right away
    try:
        from shared.auth import _tenant_status_cache

        _tenant_status_cache.delete(tenant_id)
    except Exception as exc:
        logger.warning("Cache eviction failed for tenant %s: %s", tenant_id, exc)

    try:
        publish_event(
            source="logistics.tenant_management",
            detail_type="TenantSuspended",
            tenant_id=PLATFORM_TENANT_ID,
            payload={"tenant_id": tenant_id, "reason": reason},
        )
    except Exception as exc:
        logger.warning("TenantSuspended event publish failed: %s", exc)

    try:
        repo.insert_platform_audit(
            action="TENANT_SUSPENDED",
            actor_id=actor_id,
            target_tenant_id=tenant_id,
            details={"reason": reason},
            ip_address=ip_address,
        )
    except Exception as exc:
        logger.warning("Platform audit insert failed: %s", exc)

    return updated


def activate_tenant(
    tenant_id: str,
    actor_id: str,
    ip_address: str | None = None,
) -> dict[str, Any]:
    existing = get_tenant(tenant_id)
    if existing["status"] == "active":
        raise BusinessRuleViolationError("Tenant is already active")
    if existing["status"] == "offboarded":
        raise BusinessRuleViolationError("Cannot reactivate an offboarded tenant")
    updated = repo.set_tenant_status(tenant_id, "active")
    if updated is None:
        raise RuntimeError("set_tenant_status returned None unexpectedly")

    try:
        from shared.auth import _tenant_status_cache

        _tenant_status_cache.delete(tenant_id)
    except Exception as exc:
        logger.warning("Cache eviction failed for tenant %s: %s", tenant_id, exc)

    try:
        repo.insert_platform_audit(
            action="TENANT_ACTIVATED",
            actor_id=actor_id,
            target_tenant_id=tenant_id,
            ip_address=ip_address,
        )
    except Exception as exc:
        logger.warning("Platform audit insert failed: %s", exc)

    return updated


def reactivate_tenant(
    tenant_id: str,
    actor_id: str,
    ip_address: str | None = None,
) -> dict[str, Any]:
    """Re-onboard an offboarded tenant under a new agreement.

    Distinct from activate_tenant (suspended→active). Only valid from
    offboarded state. Returns GDPR notices the platform admin must relay
    to the tenant before processing resumes.
    """
    existing = get_tenant(tenant_id)
    if existing["status"] != "offboarded":
        raise BusinessRuleViolationError(f"Only offboarded tenants can be reactivated. Current status: '{existing['status']}'")

    updated = repo.reactivate_tenant(tenant_id)
    if updated is None:
        raise RuntimeError("reactivate_tenant returned None unexpectedly")

    # Evict cached status so requests are unblocked immediately
    try:
        from shared.auth import _tenant_status_cache

        _tenant_status_cache.delete(tenant_id)
    except Exception as exc:
        logger.warning("Cache eviction failed for tenant %s: %s", tenant_id, exc)

    try:
        publish_event(
            source="logistics.tenant_management",
            detail_type="TenantReactivated",
            tenant_id=PLATFORM_TENANT_ID,
            payload={"tenant_id": tenant_id, "reactivated_by": actor_id},
        )
    except Exception as exc:
        logger.warning("TenantReactivated event publish failed: %s", exc)

    try:
        repo.insert_platform_audit(
            action="TENANT_REACTIVATED",
            actor_id=actor_id,
            target_tenant_id=tenant_id,
            ip_address=ip_address,
        )
    except Exception as exc:
        logger.warning("Platform audit insert failed: %s", exc)

    return {
        "tenant": updated,
        "notices": [
            "CONSENT_REVERIFICATION_REQUIRED: Tenant admin must re-verify consent from all users under the new agreement.",
            "ANONYMISED_DATA_IRRECOVERABLE: Customer records anonymised during the offboarding period cannot be restored.",
        ],
    }


def get_platform_dashboard() -> dict[str, Any]:
    return repo.get_dashboard_stats()


def list_platform_audit_log(
    limit: int = 50,
    cursor: dict[str, Any] | None = None,
    target_tenant_id: str | None = None,
    action: str | None = None,
) -> tuple[list[dict[str, Any]], str | None, bool]:
    return repo.list_platform_audit_log(
        limit=limit,
        cursor=cursor,
        target_tenant_id=target_tenant_id,
        action=action,
    )


# ---------------------------------------------------------------------------
# Tenant config
# ---------------------------------------------------------------------------


def get_tenant_config(tenant_id: str) -> dict[str, Any]:
    """Return tenant config as a flat dict keyed by config_key."""
    rows = repo.get_all_configs(tenant_id)
    return {row["config_key"]: row["config_value"] for row in rows}


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
    return get_tenant_config(tenant_id)


# ---------------------------------------------------------------------------
# Dollar rate
# ---------------------------------------------------------------------------


def get_dollar_rate(tenant_id: str) -> dict[str, Any]:
    rows = repo.get_all_configs(tenant_id)
    config_map = {r["config_key"]: r["config_value"] for r in rows}
    rate_cfg = config_map.get("dollar_rate", {})
    return {
        "rate": rate_cfg.get("rate", 0),
        "currency_pair": rate_cfg.get("currency_pair", "USD_NGN"),
        "effective_from": rate_cfg.get("effective_from", ""),
    }


def update_dollar_rate(
    tenant_id: str,
    req: UpdateDollarRateRequest,
    actor_id: str,
    ip_address: str | None = None,
) -> dict[str, Any]:
    current = get_dollar_rate(tenant_id)
    previous_rate = current.get("rate")

    new_value = {
        "rate": float(req.rate),
        "currency_pair": req.currency_pair,
        "effective_from": datetime.now(UTC).isoformat(),
    }
    repo.upsert_config(tenant_id, "dollar_rate", new_value, updated_by=actor_id)

    log_audit(
        tenant_id=tenant_id,
        entity_type="tenant_config",
        entity_id=tenant_id,
        action="UPDATE",
        actor_id=actor_id,
        actor_role="tenant_admin",
        before_state={"dollar_rate": current},
        after_state={"dollar_rate": new_value},
        ip_address=ip_address,
    )
    return {**new_value, "previous_rate": previous_rate}


# ---------------------------------------------------------------------------
# User management
# ---------------------------------------------------------------------------


def create_user(
    tenant_id: str,
    req: CreateTenantUserRequest,
    actor_id: str,
    request_id: str = "",
    ip_address: str | None = None,
) -> dict[str, Any]:
    # Check tier limits
    tenant = get_tenant(tenant_id)
    tier = tenant["subscription_tier"]
    limit = TIER_USER_LIMITS.get(tier, 10)
    current_count = repo.count_active_users(tenant_id)
    if current_count >= limit:
        raise UsageLimitExceededError("users", current_count, limit)

    # Check duplicate email
    if repo.get_user_by_email(tenant_id, req.email):
        raise DuplicateResourceError("user", req.email)

    # Provision Cognito
    cognito = get_cognito_client()
    cognito_sub = cognito.create_user(
        email=req.email,
        full_name=req.full_name,
        tenant_id=tenant_id,
        role=req.role.value,
    )
    group_name = f"{tenant_id}:{req.role.value}"
    cognito.create_group_if_not_exists(group_name)
    cognito.add_user_to_group(req.email, group_name)

    # Insert tenant_user
    user = repo.create_tenant_user(
        tenant_id,
        {
            "tenant_id": tenant_id,
            "cognito_sub": cognito_sub,
            "email": req.email,
            "full_name": req.full_name,
            "role": req.role.value,
            "created_by": actor_id,
        },
    )
    if user is None:
        raise RuntimeError("create_tenant_user returned None unexpectedly")
    user_id = str(user["id"])

    # Link customer record if role is customer
    if req.role.value == "customer":
        try:
            repo.link_customer_user(tenant_id, req.email, user_id)
        except Exception as exc:
            logger.warning("Customer link failed: %s", exc)

    log_audit(
        tenant_id=tenant_id,
        entity_type="tenant_user",
        entity_id=user_id,
        action="CREATE",
        actor_id=actor_id,
        actor_role="tenant_admin",
        after_state=user,
        ip_address=ip_address,
    )
    try:
        record_usage(tenant_id, "users_active", 1.0, request_id=request_id)
    except Exception as exc:
        logger.warning("Metering record failed: %s", exc)

    return user


def list_users(tenant_id: str) -> list[dict[str, Any]]:
    return repo.list_users(tenant_id)


def get_user(tenant_id: str, user_id: str) -> dict[str, Any]:
    user = repo.get_user_by_id(tenant_id, user_id)
    if not user:
        raise ResourceNotFoundError("user", user_id)
    return user


def update_user(
    tenant_id: str,
    user_id: str,
    updates: dict[str, Any],
    actor_id: str,
    ip_address: str | None = None,
) -> dict[str, Any]:
    existing = get_user(tenant_id, user_id)
    if not updates:
        return existing
    updated = repo.update_user(tenant_id, user_id, updates)
    if updated is None:
        raise RuntimeError("update_user returned None unexpectedly")
    # Sync mutable Cognito attributes (name, role) — username/email is immutable
    cognito_updates = {k: updates[k] for k in ("full_name", "role") if k in updates}
    if cognito_updates:
        cognito = get_cognito_client()
        cognito.update_user_attributes(
            username=existing["email"],
            full_name=cognito_updates.get("full_name"),
            role=cognito_updates.get("role"),
        )
    log_audit(
        tenant_id=tenant_id,
        entity_type="tenant_user",
        entity_id=user_id,
        action="UPDATE",
        actor_id=actor_id,
        actor_role="tenant_admin",
        before_state=existing,
        after_state=updated,
        ip_address=ip_address,
    )
    return updated


def deactivate_user(
    tenant_id: str,
    user_id: str,
    actor_id: str,
    ip_address: str | None = None,
) -> dict[str, Any]:
    existing = get_user(tenant_id, user_id)
    if existing["status"] == "deactivated":
        raise BusinessRuleViolationError("User is already deactivated")

    cognito = get_cognito_client()
    if existing.get("email"):
        cognito.disable_user(existing["email"])

    updated = repo.set_user_status(tenant_id, user_id, "deactivated")
    if updated is None:
        raise RuntimeError("set_user_status returned None unexpectedly")
    log_audit(
        tenant_id=tenant_id,
        entity_type="tenant_user",
        entity_id=user_id,
        action="STATUS_CHANGE",
        actor_id=actor_id,
        actor_role="tenant_admin",
        before_state={"status": "active"},
        after_state={"status": "deactivated"},
        ip_address=ip_address,
    )
    return updated


# ---------------------------------------------------------------------------
# Customer management
# ---------------------------------------------------------------------------


def create_customer(
    tenant_id: str,
    data: dict[str, Any],
    actor_id: str,
    request_id: str = "",
    ip_address: str | None = None,
) -> dict[str, Any]:
    # Accept both "full_name" and "name" — normalise to "name" for storage
    if "full_name" in data and "name" not in data:
        data = {**data, "name": data["full_name"]}
    customer = repo.create_customer(tenant_id, data)
    if customer is None:
        raise RuntimeError("create_customer returned None unexpectedly")
    log_audit(
        tenant_id=tenant_id,
        entity_type="customer",
        entity_id=str(customer["id"]),
        action="CREATE",
        actor_id=actor_id,
        actor_role="staff",
        after_state=customer,
        ip_address=ip_address,
    )
    return customer


def list_customers(
    tenant_id: str,
    q: str | None = None,
    limit: int = 50,
    cursor: dict[str, Any] | None = None,
) -> tuple[list[dict[str, Any]], str | None, bool]:
    return repo.list_customers(tenant_id, q=q, limit=limit, cursor=cursor)


def get_customer(
    tenant_id: str,
    customer_id: str,
    requesting_user_id: str | None = None,
    is_customer_role: bool = False,
) -> dict[str, Any]:
    customer = repo.get_customer_by_id(tenant_id, customer_id)
    if not customer:
        raise ResourceNotFoundError("customer", customer_id)
    # Customer role users may only access their own record
    if is_customer_role and requesting_user_id and str(customer.get("user_id")) != requesting_user_id:
        raise ResourceNotFoundError("customer", customer_id)
    return customer


def anonymise_customer(
    tenant_id: str,
    customer_id: str,
    actor_id: str,
    ip_address: str | None = None,
) -> dict[str, Any] | None:
    """Erase a customer's personal data (GDPR Art. 17 — right to erasure).

    Anonymises the record in-place to preserve FK integrity.
    Only TENANT_ADMIN may invoke this — enforced at the handler level.
    """
    customer = repo.get_customer_by_id(tenant_id, customer_id)
    if not customer:
        raise ResourceNotFoundError("customer", customer_id)
    if customer.get("anonymised_at"):
        raise BusinessRuleViolationError(
            "Customer record has already been anonymised",
            rule_id="ALREADY_ANONYMISED",
        )
    _pii_fields = {"name", "email", "phone", "whatsapp", "address", "contract_details"}
    before_masked = {k: ("***" if k in _pii_fields else v) for k, v in customer.items()}
    repo.anonymise_customer_record(tenant_id, customer_id)
    log_audit(
        tenant_id=tenant_id,
        entity_type="customer",
        entity_id=customer_id,
        action="DELETE",
        actor_id=actor_id,
        actor_role="tenant_admin",
        before_state=before_masked,
        after_state={"anonymised": True},
        ip_address=ip_address,
    )
    return repo.get_customer_by_id(tenant_id, customer_id)


def export_customer_data(
    tenant_id: str,
    customer_id: str,
    requesting_user_id: str | None = None,
    is_customer_role: bool = False,
) -> dict[str, Any]:
    """Return all data held for a customer (GDPR Art. 20 — right to portability).

    Audit-logs every export so there is an accountable record of who accessed
    personal data and when (GDPR Art. 5(2) — accountability principle).
    """
    from datetime import datetime

    customer = repo.get_customer_by_id(tenant_id, customer_id)
    if not customer:
        raise ResourceNotFoundError("customer", customer_id)
    if is_customer_role and requesting_user_id and str(customer.get("user_id")) != requesting_user_id:
        raise ResourceNotFoundError("customer", customer_id)
    data = repo.get_customer_full_export_data(tenant_id, customer_id)
    exported_at = datetime.now(UTC).isoformat()
    data["exported_at"] = exported_at

    # Audit trail — required by GDPR Art. 5(2) accountability principle.
    # Records who exported the data and when, without logging PII fields.
    actor_role = "customer" if is_customer_role else "tenant_admin"
    log_audit(
        tenant_id=tenant_id,
        entity_type="customer",
        entity_id=customer_id,
        action="EXPORT",
        actor_id=requesting_user_id or "",
        actor_role=actor_role,
        after_state={"exported_at": exported_at, "record_count": len(data.get("shipments", []))},
    )
    return data


def update_customer(
    tenant_id: str,
    customer_id: str,
    updates: dict[str, Any],
    actor_id: str,
    ip_address: str | None = None,
) -> dict[str, Any]:
    existing = get_customer(tenant_id, customer_id)
    if not updates:
        return existing
    updated = repo.update_customer(tenant_id, customer_id, updates)
    if updated is None:
        raise RuntimeError("update_customer returned None unexpectedly")
    log_audit(
        tenant_id=tenant_id,
        entity_type="customer",
        entity_id=customer_id,
        action="UPDATE",
        actor_id=actor_id,
        actor_role="staff",
        before_state=existing,
        after_state=updated,
        ip_address=ip_address,
    )
    return updated


# ---------------------------------------------------------------------------
# Charge types
# ---------------------------------------------------------------------------


def create_charge_type(
    tenant_id: str,
    data: dict[str, Any],
    actor_id: str,
    ip_address: str | None = None,
) -> dict[str, Any]:
    charge_type = repo.create_charge_type(tenant_id, {**data, "created_by": actor_id})
    if charge_type is None:
        raise RuntimeError("create_charge_type returned None unexpectedly")
    log_audit(
        tenant_id=tenant_id,
        entity_type="charge_type",
        entity_id=str(charge_type["id"]),
        action="CREATE",
        actor_id=actor_id,
        actor_role="tenant_admin",
        after_state=charge_type,
        ip_address=ip_address,
    )
    return charge_type


def list_charge_types(tenant_id: str) -> list[dict[str, Any]]:
    return repo.list_charge_types(tenant_id)


def update_charge_type(
    tenant_id: str,
    charge_type_id: str,
    updates: dict[str, Any],
    actor_id: str,
    ip_address: str | None = None,
) -> dict[str, Any]:
    existing = repo.get_charge_type_by_id(tenant_id, charge_type_id)
    if not existing:
        raise ResourceNotFoundError("charge_type", charge_type_id)
    updated = repo.update_charge_type(tenant_id, charge_type_id, updates)
    if updated is None:
        raise RuntimeError("update_charge_type returned None unexpectedly")
    log_audit(
        tenant_id=tenant_id,
        entity_type="charge_type",
        entity_id=charge_type_id,
        action="UPDATE",
        actor_id=actor_id,
        actor_role="tenant_admin",
        before_state=existing,
        after_state=updated,
        ip_address=ip_address,
    )
    return updated


def deactivate_charge_type(
    tenant_id: str,
    charge_type_id: str,
    actor_id: str,
    ip_address: str | None = None,
) -> dict[str, Any]:
    existing = repo.get_charge_type_by_id(tenant_id, charge_type_id)
    if not existing:
        raise ResourceNotFoundError("charge_type", charge_type_id)
    result = repo.update_charge_type(tenant_id, charge_type_id, {"is_active": False})
    if result is None:
        raise RuntimeError("update_charge_type returned None unexpectedly")
    return result


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
# Tenant reports (tenant_admin)
# ---------------------------------------------------------------------------


def get_tenant_report(tenant_id: str) -> dict[str, Any]:
    """Return aggregated analytics for the tenant's current calendar month."""
    from datetime import date

    period = date.today().strftime("%Y-%m")
    return repo.get_tenant_report_data(tenant_id, period)
