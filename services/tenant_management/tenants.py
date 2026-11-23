"""Tenants and their lifecycle.

Creation, the platform's tenant list and lifecycle (suspend, activate, offboard, reactivate), company onboarding
leads, and the platform dashboard and activity reads.

Split out of ``service.py`` (audit BE-13); ``service`` re-exports every public function, so callers are unchanged.
"""

import logging
import re
import uuid
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from shared import tenant_export
from shared.db import tenant_transaction
from shared.events import publish_event
from shared.exceptions import (
    BusinessRuleViolationError,
    DuplicateResourceError,
    ResourceNotFoundError,
    TenantOffboardedError,
)
from shared.providers import get_identity_provider
from shared.tenant_context import PLATFORM_TENANT_ID

from . import repository as repo
from .models import (
    CreateOnboardingRequest,
    CreateTenantRequest,
    OnboardingRequestStatusUpdate,
    UpdateTenantRequest,
)

if TYPE_CHECKING:
    pass
from .activation import issue_activation

logger = logging.getLogger(__name__)


def _generate_slug(company_name: str) -> str:
    """Derive a URL-safe slug from company_name.

    Lowercases, replaces non-alphanumeric runs with hyphens, strips leading/trailing
    hyphens. Appends a 6-char UUID segment when slug would be empty.
    """
    slug = re.sub(r"[^a-z0-9]+", "-", company_name.lower()).strip("-")
    return slug or uuid.uuid4().hex[:6]


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

DEFAULT_CONFIGS: dict[str, Any] = {
    # Superseded by shared/fx_rate.py: the base USD/NGN rate is now fetched
    # live from Bybit's P2P order book, not a value stored per tenant. Only
    # the markup a tenant layers on top of that base lives here now.
    # markup_value 0 means "pass Bybit's rate through unchanged" — the
    # safest default so no tenant's pricing silently jumps on rollout.
    "dollar_rate_markup": {
        "markup_type": "percentage",
        "markup_value": 0,
    },
    # "flat" is just carton_rate == bag_rate == bale_rate — new tenants are
    # seeded directly in this shape; the pre-2026-09-20 {"rate_usd": ...}
    # shape is only ever produced by tenants provisioned before this
    # feature, and shared/cbm_rate.py normalizes it at read time.
    "cbm_rate_per_unit": {
        "currency": "usd",
        "rate_mode": "flat",
        "carton_rate": 45.00,
        "bag_rate": 45.00,
        "bale_rate": 45.00,
    },
    "storage_fee": {
        "enabled": True,
        "grace_period_days": 14,
        "daily_fee_per_carton_ngn": 500,
    },
    "warehouse_address": {"address": "", "city": "Lagos", "state": "Lagos"},
    "refund_threshold_usd": {"staff_limit": 50, "requires_manager_above": 50},
    "dispute_escalation": {"enabled": True, "auto_escalate_days": 5},
    "reminder_days": {"storage_first_reminder": 7, "storage_final_reminder": 13},
    "webhook_config": {
        "enabled": False,
        "url": "",
        "secret": "",
        "events": ["container.status_updated"],
    },
    "paystack_config": {
        "enabled": False,
        "secret_key_encrypted": None,
        "last4": None,
        "environment": None,
        "configured_by": None,
        "configured_at": None,
    },
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
    cognito = get_identity_provider()

    # 0. Idempotency guard for lead-driven provisioning: if this onboarding
    # request was already provisioned, do not create a second tenant (the
    # provision button can be clicked again, or a transient 500 can leave the
    # client unsure). Return a conflict so the caller refreshes rather than
    # duplicating the tenant.
    if req.onboarding_request_id:
        existing_request = repo.get_onboarding_request(req.onboarding_request_id)
        if existing_request and (existing_request.get("status") == "provisioned" or existing_request.get("tenant_id")):
            raise DuplicateResourceError("onboarding_request", req.onboarding_request_id)

    # 0b. The initial admin's email must not already belong to a ShipX user.
    # `tenant_user.id` IS the IdP subject (oid), so one identity belongs to exactly
    # one tenant — reusing an email that already has a row violates tenant_user_pkey
    # mid-create, *after* the tenant row is committed (leaving an orphan tenant).
    # Fail fast, before anything is created.
    if repo.find_user_across_tenants(email=req.initial_admin.email):
        raise DuplicateResourceError("tenant_user", req.initial_admin.email)

    # 1. Create tenant — slug derived from company_name; unique constraint handled at DB level
    base_slug = _generate_slug(req.company_name)
    slug = base_slug
    # Retry with a suffix on collision (race-condition safe via DB UNIQUE constraint)
    for attempt in range(5):
        try:
            tenant = repo.create_tenant(
                {
                    "company_name": req.company_name,
                    "primary_contact_email": req.primary_contact_email,
                    "primary_contact_phone": req.primary_contact_phone,
                    "origin_country": req.origin_country,
                    "destination_country": req.destination_country,
                    "subscription_tier": req.subscription_tier.value,
                    "slug": slug,
                }
            )
            break
        except Exception as exc:
            if attempt < 4 and "tenant_slug_unique" in str(exc):
                slug = f"{base_slug}-{uuid.uuid4().hex[:4]}"
                continue
            raise
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
    # The IdP may have resolved to a pre-existing directory account (same person
    # under a different email spelling). If that subject already has a tenant_user
    # row, it belongs to another tenant — fail with a clear conflict rather than a
    # tenant_user_pkey violation.
    if repo.find_user_across_tenants(user_id=cognito_sub):
        raise DuplicateResourceError("tenant_user", req.initial_admin.email)

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

    # 3b. Send the initial admin a ShipX activation link to set their password
    # (created with a random IdP password + no login). This is their first-login
    # path. Best-effort — the tenant + admin are already committed and the link
    # can be resent; a failure here must not fail provisioning.
    try:
        issue_activation(
            tenant_id,
            str(admin_user["id"]),
            req.initial_admin.email,
            req.initial_admin.full_name,
            created_by=None,
            request_id=request_id,
        )
    except Exception as exc:
        logger.warning("Activation link issuance failed for admin of tenant %s: %s", tenant_id, exc)

    # 4. Upsert default configs
    today = datetime.now(UTC).isoformat()
    default_markup = {**DEFAULT_CONFIGS["dollar_rate_markup"], "updated_at": today}
    configs_to_insert = {**DEFAULT_CONFIGS, "dollar_rate_markup": default_markup}
    for key, value in configs_to_insert.items():
        repo.upsert_config(tenant_id, key, value, updated_by=str(admin_user["id"]))

    # 4b. Default warehouse. Ground-truth gap found live, reported by the
    # user against a real paper "Goods Release Note": every generated
    # release note tries to resolve a warehouse (falls back to
    # get_default_warehouse when the caller doesn't pick one explicitly).
    # Migration 041 backfilled exactly one "Main Warehouse" per tenant that
    # *already existed* at migration time — a one-time SQL statement that
    # can never reach a tenant onboarded afterwards. Without this step,
    # every tenant created from here on has zero warehouse rows and every
    # release note they ever generate prints with no warehouse address at
    # all. Best-effort, same reasoning as the notification below: an outage
    # here must not fail tenant creation, which has already committed.
    try:
        from services.payment_release import repository as release_repo

        release_repo.create_warehouse(
            tenant_id,
            {"tenant_id": tenant_id, "name": "Main Warehouse", "is_default": True, "created_by": str(admin_user["id"])},
        )
    except Exception as exc:
        logger.warning("Default warehouse creation failed for tenant %s: %s", tenant_id, exc)

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

    # Ground-truth gap found live, reported by the user while investigating a
    # separate missing notification on payment-claim rejection — asked to
    # check every notification in the app: `tenant_onboarded` had a full
    # SMS/WhatsApp/email template defined but no call site ever used it.
    # Best-effort — never raises: a notification outage must not fail
    # tenant creation itself, which has already committed by this point.
    try:
        from shared.notifications import enqueue_notifications

        enqueue_notifications(
            tenant_id=tenant_id,
            event_type="tenant_onboarded",
            recipient={
                "phone": req.primary_contact_phone or "",
                "email": req.primary_contact_email,
                "whatsapp": "",
                "name": req.company_name,
            },
            template_data={"company_name": req.company_name},
            request_id=request_id,
        )
    except Exception as exc:
        logger.warning("tenant_onboarded notification failed for tenant %s: %s", tenant_id, exc)

    # When provisioned from a company onboarding lead: link the tenant back and
    # close the lead. Best-effort — the tenant already exists; a bookkeeping
    # failure here must not fail the create (the admin can re-mark it).
    if req.onboarding_request_id:
        try:
            repo.update_onboarding_request(
                req.onboarding_request_id,
                {
                    "status": "provisioned",
                    "tenant_id": tenant_id,
                    "reviewed_by": actor_id,
                    "reviewed_at": datetime.now(UTC),
                },
            )
        except Exception as exc:
            logger.warning(
                "Could not link onboarding request %s to tenant %s: %s",
                req.onboarding_request_id,
                tenant_id,
                exc,
            )

    return {"tenant": tenant, "admin_user": admin_user}


# ---------------------------------------------------------------------------
# Company onboarding (shipping-company leads — distinct from customer sign-up)
# ---------------------------------------------------------------------------


def create_onboarding_request(
    req: CreateOnboardingRequest, request_id: str = "", ip_address: str | None = None
) -> dict[str, Any]:
    """Record a shipping-company onboarding lead (public). Creates NO account and
    NO tenant — a platform admin reviews and provisions via create_tenant."""
    row = repo.insert_onboarding_request(
        {
            "company_name": req.company_name,
            "contact_name": req.contact_name,
            "contact_email": req.contact_email,
            "contact_phone": req.contact_phone,
            "origin_country": req.origin_country,
            "destination_country": req.destination_country,
            "monthly_volume": req.monthly_volume,
            "notes": req.notes,
        }
    )
    # Notify platform ops (best-effort) — a lead, never a customer notification.
    try:
        publish_event(
            source="logistics.tenant_management",
            detail_type="OnboardingRequested",
            tenant_id=PLATFORM_TENANT_ID,
            payload={"request_id": str(row["id"]), "company_name": req.company_name},
            request_id=request_id,
        )
    except Exception as exc:
        logger.warning("OnboardingRequested event publish failed: %s", exc)
    # Return only non-sensitive confirmation — the public caller gets an id + status.
    return {"id": str(row["id"]), "status": row["status"]}


def list_onboarding_requests(status: str | None = None) -> list[dict[str, Any]]:
    return repo.list_onboarding_requests(status=status)


def get_onboarding_request(request_id: str) -> dict[str, Any]:
    row = repo.get_onboarding_request(request_id)
    if not row:
        raise ResourceNotFoundError("onboarding_request", request_id)
    return row


def update_onboarding_request_status(
    request_id: str,
    req: OnboardingRequestStatusUpdate,
    actor_id: str,
    ip_address: str | None = None,
) -> dict[str, Any]:
    """Platform-admin status transition (contacted/rejected/approved). Provisioning
    to 'provisioned' happens via create_tenant, not here."""
    existing = repo.get_onboarding_request(request_id)
    if not existing:
        raise ResourceNotFoundError("onboarding_request", request_id)
    updated = repo.update_onboarding_request(
        request_id,
        {
            "status": req.status.value,
            "rejection_reason": req.rejection_reason,
            "reviewed_by": actor_id,
            "reviewed_at": datetime.now(UTC),
        },
    )
    try:
        repo.insert_platform_audit(
            action="ONBOARDING_REQUEST_UPDATED",
            actor_id=actor_id,
            target_tenant_id=None,
            details={"request_id": request_id, "status": req.status.value},
            ip_address=ip_address,
        )
    except Exception as exc:
        logger.warning("Platform audit insert failed: %s", exc)
    return updated if updated else existing


def list_tenants(limit: int = 50, cursor: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    from shared.tier_limits import get_effective_limits

    tenants = repo.list_tenants(limit=limit, cursor=cursor)
    # Effective (tier ⊕ plan-override ⊕ tenant-override) users limit per row,
    # so the platform list can render "users x/limit" honestly (audit gap B2).
    for t in tenants:
        try:
            t["users_limit"] = get_effective_limits(t.get("subscription_tier", ""), str(t["id"]))["users"]
        except Exception:  # limits are decorative here — never fail the list for them
            logger.warning("Could not resolve effective limits for tenant %s", t.get("id"))
            t["users_limit"] = None
    return tenants


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
    # The tenant's data export (FR-TN-004, audit BE-10) is queued with the status change, so there is never an
    # offboarded tenant with nothing queued. The hourly job writes it; the cleanup will not delete without it.
    with tenant_transaction(PLATFORM_TENANT_ID):
        updated = repo.set_tenant_status(tenant_id, "offboarded")
        if updated is None:
            raise RuntimeError("set_tenant_status returned None unexpectedly")
        queued = tenant_export.queue_export(tenant_id, requested_by=actor_id)

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
        from shared.providers import get_identity_provider

        cognito = get_identity_provider()
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
            details={"export_id": str(queued["id"])} if queued else None,
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

    # Ground-truth gap found live, reported by the user while investigating a
    # separate missing notification on payment-claim rejection — asked to
    # check every notification in the app: `tenant_suspended` had a full
    # SMS/WhatsApp/email template defined but no call site ever used it.
    # Best-effort — never raises: a notification outage must not fail the
    # suspend action itself.
    try:
        from shared.notifications import enqueue_notifications

        if existing.get("primary_contact_email") or existing.get("primary_contact_phone"):
            enqueue_notifications(
                tenant_id=tenant_id,
                event_type="tenant_suspended",
                recipient={
                    "phone": existing.get("primary_contact_phone") or "",
                    "email": existing.get("primary_contact_email") or "",
                    "whatsapp": "",
                    "name": existing.get("company_name") or "",
                },
                template_data={"reason": reason},
            )
    except Exception as exc:
        logger.warning("tenant_suspended notification failed for tenant %s: %s", tenant_id, exc)

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

    # An export not yet written is for an offboarding that no longer applies; dropping it lets a later offboarding
    # queue its own (one open export per tenant).
    with tenant_transaction(PLATFORM_TENANT_ID):
        updated = repo.reactivate_tenant(tenant_id)
        if updated is None:
            raise RuntimeError("reactivate_tenant returned None unexpectedly")
        tenant_export.cancel_open_exports(tenant_id)

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


def list_tenant_activity(
    tenant_id: str,
    limit: int = 20,
    cursor: dict[str, Any] | None = None,
    actor_id: str | None = None,
    entity_type: str | list[str] | None = None,
    action: str | None = None,
    q: str | None = None,
    created_after: str | None = None,
    created_before: str | None = None,
    sort_direction: str = "desc",
) -> tuple[list[dict[str, Any]], str | None, bool]:
    """Tenant-scoped activity feed (audit gap B6) — see
    repository.list_tenant_activity's docstring for the full filter set
    (actor, entity type(s), action, free-text search, date range, sort)."""
    return repo.list_tenant_activity(
        tenant_id,
        limit=limit,
        cursor=cursor,
        actor_id=actor_id,
        entity_type=entity_type,
        action=action,
        q=q,
        created_after=created_after,
        created_before=created_before,
        sort_direction=sort_direction,
    )
