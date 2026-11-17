"""Business logic layer for the Tenant Management service.

Coordinates between the repository (SQL), Cognito client, shared audit,
events, and metering utilities. Raises typed exceptions from shared.exceptions
— never raw Python exceptions.
"""

import json
import logging
import re
import uuid
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any

from shared import tenant_export
from shared.app_urls import MissingBaseUrlError, activation_url, invite_url, login_url
from shared.audit import log_audit
from shared.auth import evict_identity_cache
from shared.cbm_rate import get_cbm_rate_config, get_min_cbm_per_item
from shared.db import tenant_transaction
from shared.encryption import decrypt_field, encrypt_field
from shared.events import publish_event
from shared.exceptions import (
    BusinessRuleViolationError,
    DuplicateResourceError,
    ResourceNotFoundError,
    TenantOffboardedError,
    UsageLimitExceededError,
    ValidationError,
)
from shared.fx_rate import get_effective_dollar_rate
from shared.metering import record_usage
from shared.providers import get_identity_provider, get_storage_provider
from shared.tenant_context import PLATFORM_TENANT_ID
from shared.webhook import test_fire_tenant_webhook

from . import repository as repo
from .models import (
    AcceptCustomerInviteRequest,
    CreateOnboardingRequest,
    CreateTenantRequest,
    CreateTenantUserRequest,
    CustomerRegistrationRequest,
    OnboardingRequestStatusUpdate,
    PaystackConfigRequest,
    UpdateDollarRateMarkupRequest,
    UpdateTenantConfigRequest,
    UpdateTenantRequest,
    UpsertNotificationTemplateRequest,
    WebhookConfigRequest,
)

if TYPE_CHECKING:
    from .models import UpdateCbmRateRequest

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


# ---------------------------------------------------------------------------
# Offboarding data export (audit BE-10)
# ---------------------------------------------------------------------------

#: How long a download link for an offboarding archive works.
EXPORT_LINK_SECONDS = 300

_FILENAME_UNSAFE = re.compile(r"[^a-z0-9-]+")


def _current_export(tenant: dict[str, Any]) -> dict[str, Any] | None:
    """The latest export for the tenant's latest offboarding; one from an earlier offboarding does not count."""
    if tenant["status"] != "offboarded":
        return None
    export = tenant_export.latest_export(str(tenant["id"]))
    offboarded_at = tenant.get("offboarded_at")
    if export is None or (offboarded_at is not None and export["requested_at"] < offboarded_at):
        return None
    return export


def get_offboarding_export(tenant_id: str) -> dict[str, Any]:
    """Where the tenant's offboarding export stands, for the platform tenant page.

    Returns:
        ``status`` (``none`` when nothing is queued for the current offboarding, else the export's status), the
        export's id, times, size, checksum and row count, how many attempts it has had, whether it is still being
        retried, whether a platform admin may queue one now, and when the tenant's data is due to be deleted.
    """
    tenant = get_tenant(tenant_id)
    export = _current_export(tenant)
    row_counts = (export or {}).get("row_counts") or {}
    status = export["status"] if export else "none"
    attempts = int(export["attempts"]) if export else 0
    return {
        "tenant_status": tenant["status"],
        "status": status,
        "export_id": str(export["id"]) if export else None,
        "requested_at": export["requested_at"] if export else None,
        "completed_at": export.get("completed_at") if export else None,
        "size_bytes": export.get("size_bytes") if export else None,
        "sha256": export.get("sha256") if export else None,
        "row_count": sum(int(n) for n in row_counts.values()) if export else None,
        "attempts": attempts,
        "max_attempts": tenant_export.MAX_ATTEMPTS,
        "retrying": status == "failed" and attempts < tenant_export.MAX_ATTEMPTS,
        "can_queue": tenant["status"] == "offboarded"
        and (status in {"none", "cancelled"} or (status == "failed" and attempts >= tenant_export.MAX_ATTEMPTS)),
        "deletion_scheduled_at": tenant.get("deletion_scheduled_at"),
    }


def queue_offboarding_export(tenant_id: str, actor_id: str, ip_address: str | None = None) -> dict[str, Any]:
    """Queue an export for an offboarded tenant that has none, or whose export gave up.

    For tenants offboarded before exports existed, and for an export that failed every attempt.

    Raises:
        BusinessRuleViolationError: The tenant is not offboarded, or an export is already queued, running, retrying
            or done.
    """
    tenant = get_tenant(tenant_id)
    if tenant["status"] != "offboarded":
        raise BusinessRuleViolationError(
            "Only an offboarded tenant has an offboarding export.", rule_id="OFFBOARDING_EXPORT_NOT_OFFBOARDED"
        )
    current = get_offboarding_export(tenant_id)
    if not current["can_queue"]:
        raise BusinessRuleViolationError(
            f"This tenant's export is already {current['status']}.", rule_id="OFFBOARDING_EXPORT_IN_PROGRESS"
        )
    if current["status"] == "failed":
        tenant_export.mark_cancelled(current["export_id"])
    queued = tenant_export.queue_export(tenant_id, requested_by=actor_id)
    if queued is None:
        raise BusinessRuleViolationError("An export was queued by another request.", rule_id="OFFBOARDING_EXPORT_IN_PROGRESS")
    try:
        repo.insert_platform_audit(
            action="TENANT_EXPORT_QUEUED",
            actor_id=actor_id,
            target_tenant_id=tenant_id,
            details={"export_id": str(queued["id"])},
            ip_address=ip_address,
        )
    except Exception as exc:
        logger.warning("Platform audit insert failed: %s", exc)
    return get_offboarding_export(tenant_id)


def create_offboarding_export_link(tenant_id: str, actor_id: str, ip_address: str | None = None) -> dict[str, Any]:
    """A five-minute download link to the tenant's completed offboarding archive. Every link is audited.

    Raises:
        BusinessRuleViolationError: No export of the current offboarding has completed.
    """
    tenant = get_tenant(tenant_id)
    export = _current_export(tenant)
    if export is None or export["status"] != "completed":
        raise BusinessRuleViolationError("The export is not ready yet.", rule_id="OFFBOARDING_EXPORT_NOT_READY")
    key = str(export["object_key"])
    # The key comes from our own record, but it is still checked to sit in this tenant's export folder before a
    # link to it is signed.
    if not key.startswith(tenant_export.export_prefix(tenant_id)) or ".." in key:
        logger.error("Offboarding export %s has a key outside its tenant's export folder", export["id"])
        raise BusinessRuleViolationError("The export is not available.", rule_id="OFFBOARDING_EXPORT_NOT_READY")

    slug = _FILENAME_UNSAFE.sub("-", str(tenant.get("slug") or "tenant").lower()).strip("-") or "tenant"
    completed = export.get("completed_at") or datetime.now(UTC)
    filename = f"shipx-export-{slug}-{completed:%Y%m%d}.zip"
    url = get_storage_provider().presigned_get_url(
        key, expires_in=EXPORT_LINK_SECONDS, response_content_disposition=f'attachment; filename="{filename}"'
    )
    try:
        repo.insert_platform_audit(
            action="TENANT_EXPORT_LINK_ISSUED",
            actor_id=actor_id,
            target_tenant_id=tenant_id,
            details={"export_id": str(export["id"])},
            ip_address=ip_address,
        )
    except Exception as exc:
        # The link is a download of every customer's personal data: no record, no link.
        logger.warning("Platform audit insert failed; refusing the export link: %s", exc)
        raise
    return {
        "download_url": url,
        "expires_at": datetime.now(UTC) + timedelta(seconds=EXPORT_LINK_SECONDS),
        "filename": filename,
        "size_bytes": export.get("size_bytes"),
        "sha256": export.get("sha256"),
    }


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
# Dollar rate
# ---------------------------------------------------------------------------


def get_dollar_rate(tenant_id: str) -> dict[str, Any]:
    """The effective USD/NGN rate: Bybit's live P2P base rate plus this
    tenant's markup (shared/fx_rate.py). `effective_from` is the markup's
    own last-changed timestamp (the stable, admin-controlled part);
    `fetched_at` separately reports how fresh the underlying market data is.
    """
    effective = get_effective_dollar_rate(tenant_id)
    return {
        "rate": effective["rate"],
        "base_rate": effective["base_rate"],
        "markup_type": effective["markup_type"],
        "markup_value": effective["markup_value"],
        "source": effective["source"],
        "rate_source": effective["rate_source"],
        "fetched_at": effective["fetched_at"],
        "currency_pair": "USD_NGN",
        "effective_from": effective["markup_updated_at"] or "",
    }


def update_dollar_rate(
    tenant_id: str,
    req: UpdateDollarRateMarkupRequest,
    actor_id: str,
    ip_address: str | None = None,
) -> dict[str, Any]:
    """Update this tenant's markup on the Bybit-sourced base rate (the rate
    itself is no longer set directly — see get_dollar_rate)."""
    current = get_dollar_rate(tenant_id)

    new_markup = {
        "markup_type": req.markup_type.value,
        "markup_value": float(req.markup_value),
        "updated_at": datetime.now(UTC).isoformat(),
    }
    repo.upsert_config(tenant_id, "dollar_rate_markup", new_markup, updated_by=actor_id)

    # Effective rate *after* the markup change — this, not the raw markup
    # value, is what rate_history/RateHistoryTable charts (unchanged
    # frontend component; it just reads rate_value.rate as a plain number).
    # Cast every Decimal to float here — get_dollar_rate/get_effective_dollar_rate
    # return Decimal, but repo.append_rate_history's json.dumps() has no
    # `default=str` (unlike log_audit's) and raises on a raw Decimal; found
    # live (rate_history silently stopped recording anything after this
    # feature shipped, swallowed by this function's own try/except below).
    updated = get_dollar_rate(tenant_id)
    new_value = {
        "rate": float(updated["rate"]),
        "base_rate": float(updated["base_rate"]),
        "markup_type": updated["markup_type"],
        "markup_value": float(updated["markup_value"]),
    }

    try:
        repo.append_rate_history(
            tenant_id=tenant_id,
            rate_type="dollar_rate",
            rate_value=new_value,
            previous_value={
                "rate": float(current["rate"]),
                "markup_type": current["markup_type"],
                "markup_value": float(current["markup_value"]),
            },
            changed_by=actor_id,
        )
    except Exception as exc:
        logger.warning("rate_history append failed: %s", exc)

    log_audit(
        tenant_id=tenant_id,
        entity_type="tenant_config",
        entity_id=tenant_id,
        action="UPDATE",
        actor_id=actor_id,
        actor_role="tenant_admin",
        before_state={"dollar_rate_markup": {"markup_type": current["markup_type"], "markup_value": current["markup_value"]}},
        after_state={"dollar_rate_markup": new_markup},
        ip_address=ip_address,
    )
    return {**updated, "previous_rate": current["rate"]}


def list_rate_history(
    tenant_id: str,
    rate_type: str | None = None,
    limit: int = 50,
    cursor: dict[str, Any] | None = None,
) -> tuple[list[dict[str, Any]], str | None, bool]:
    """Return paginated rate history for a tenant."""
    return repo.list_rate_history(tenant_id, rate_type=rate_type, limit=limit, cursor=cursor)


def get_cbm_rate(tenant_id: str) -> dict[str, Any]:
    """This tenant's CBM rate config: currency + carton/bag/bale rates.

    "flat" (the common case) is just carton_rate == bag_rate == bale_rate —
    see shared/cbm_rate.py for the backward-compat normalization of the
    pre-2026-09-20 single-rate shape.

    Rates are cast to float here, for this API response only — the shared
    config resolver itself must keep returning Decimal (services/billing
    does real money arithmetic with it), but this repository's `success()`
    response helper (shared/responses.py) serializes anything it doesn't
    recognize via `json.dumps(..., default=str)`, which would otherwise
    turn every rate into a JSON string here — inconsistent with
    update_cbm_rate's response (already float-cast) and, found live, a
    frontend crash (`config.carton_rate.toFixed is not a function`) since
    the frontend types these fields as `number`.
    """
    config = get_cbm_rate_config(tenant_id)
    return {
        **config,
        "carton_rate": float(config["carton_rate"]),
        "bag_rate": float(config["bag_rate"]),
        "bale_rate": float(config["bale_rate"]),
        "min_cbm_per_item": float(get_min_cbm_per_item(tenant_id)),
    }


def update_cbm_rate(
    tenant_id: str,
    req: "UpdateCbmRateRequest",
    actor_id: str,
    ip_address: str | None = None,
) -> dict[str, Any]:
    current = get_cbm_rate(tenant_id)
    # bag_rate/bale_rate are always set by this point — the request's own
    # model_validator (_resolve_per_type_rates) guarantees it — but narrowed
    # explicitly here since the field type itself is still `Decimal | None`.
    bag_rate = req.bag_rate if req.bag_rate is not None else req.carton_rate
    bale_rate = req.bale_rate if req.bale_rate is not None else req.carton_rate
    new_value = {
        "currency": req.currency.value,
        "rate_mode": req.rate_mode.value,
        "carton_rate": float(req.carton_rate),
        "bag_rate": float(bag_rate),
        "bale_rate": float(bale_rate),
        "effective_from": datetime.now(UTC).isoformat(),
    }
    repo.upsert_config(tenant_id, "cbm_rate_per_unit", new_value, updated_by=actor_id)

    # Minimum billable CBM floor — its own config key, updated only when supplied.
    if req.min_cbm_per_item is not None:
        repo.upsert_config(
            tenant_id,
            "min_cbm_per_item",
            {"value": float(req.min_cbm_per_item)},
            updated_by=actor_id,
        )

    try:
        repo.append_rate_history(
            tenant_id=tenant_id,
            rate_type="cbm_rate",
            rate_value=new_value,
            previous_value={
                "currency": current["currency"],
                "rate_mode": current["rate_mode"],
                "carton_rate": float(current["carton_rate"]),
                "bag_rate": float(current["bag_rate"]),
                "bale_rate": float(current["bale_rate"]),
            },
            changed_by=actor_id,
        )
    except Exception as exc:
        logger.warning("rate_history append failed: %s", exc)

    log_audit(
        tenant_id=tenant_id,
        entity_type="tenant_config",
        entity_id=tenant_id,
        action="UPDATE",
        actor_id=actor_id,
        actor_role="tenant_admin",
        before_state={"cbm_rate_per_unit": current},
        after_state={"cbm_rate_per_unit": new_value},
        ip_address=ip_address,
    )
    return {**new_value, "min_cbm_per_item": float(get_min_cbm_per_item(tenant_id))}


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

    role_values = [r.value for r in req.roles]
    primary_role_value = req.primary_role.value if req.primary_role is not None else role_values[0]

    # Provision Cognito
    cognito = get_identity_provider()
    cognito_sub = cognito.create_user(
        email=req.email,
        full_name=req.full_name,
        tenant_id=tenant_id,
        role=primary_role_value,
    )

    # `tenant_user.id` IS the IdP subject, so one identity belongs to exactly one
    # tenant. If the IdP resolved to an account already attached to a tenant_user
    # row, conflict clearly instead of violating tenant_user_pkey.
    if repo.find_user_across_tenants(user_id=cognito_sub):
        raise DuplicateResourceError("user", req.email)

    # Insert tenant_user (primary role only — tenant_user.role is the
    # single-role-shaped source of truth every existing query reads directly)
    user = repo.create_tenant_user(
        tenant_id,
        {
            "tenant_id": tenant_id,
            "cognito_sub": cognito_sub,
            "email": req.email,
            "full_name": req.full_name,
            "role": primary_role_value,
            "created_by": actor_id,
        },
    )
    if user is None:
        raise RuntimeError("create_tenant_user returned None unexpectedly")
    user_id = str(user["id"])

    # Populate tenant_user_role with the full assigned role set (N=1 for a
    # single-role invite) and reconcile Cognito group membership to match —
    # sync_user_groups replaces the old single create_group/add_user_to_group
    # pair and is the same "diff and reconcile" operation used by update_user.
    user = repo.set_user_roles(tenant_id, user_id, role_values, primary_role_value, assigned_by=actor_id) or user
    cognito.sync_user_groups(req.email, tenant_id, set(role_values))

    # Link customer record if customer is one of the assigned roles
    if "customer" in role_values:
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

    # Operator-provisioned users have a random IdP password and no login — send
    # the ShipX activation link so they set their own password (all roles).
    # Best-effort: the user is committed and the link can be resent.
    try:
        issue_activation(tenant_id, user_id, req.email, req.full_name, created_by=actor_id, request_id=request_id)
    except Exception as exc:
        logger.warning("Activation link issuance failed for user %s: %s", user_id, exc)

    return user


# ---------------------------------------------------------------------------
# Account activation (operator-provisioned staff/admins set their own password)
# ---------------------------------------------------------------------------


def _mask_email(email: str) -> str:
    local, _, domain = email.partition("@")
    return f"{local[:1]}***@{domain}" if domain else "***"


def issue_activation(
    tenant_id: str,
    user_id: str,
    email: str,
    full_name: str,
    created_by: str | None = None,
    request_id: str = "",
) -> str:
    """Mint a single-use activation link and email a ShipX welcome with a
    "set your password" link. Best-effort email; the token row is the record.
    Returns the raw token (for tests / resend). Never raises on email failure."""
    from shared import activation
    from shared.notifications import enqueue_notifications

    activation.delete_unconsumed(tenant_id, user_id)
    token = activation.mint_token()
    activation.create_activation(
        tenant_id,
        user_id,
        activation.hash_token(token),
        sent_channel="email",
        sent_to_masked=_mask_email(email),
        created_by=created_by,
    )
    try:
        link = activation_url(token)
    except MissingBaseUrlError as exc:
        # The token row is already written and is the record, so activation can
        # still be completed by a resend once the base URL is configured. What
        # must not happen is emailing a link to nowhere and reporting success.
        logger.error(
            "account_activation link could not be built for user %s — no email sent: %s",
            user_id,
            exc,
        )
        return token
    try:
        enqueue_notifications(
            tenant_id=tenant_id,
            event_type="account_activation",
            recipient={"email": email, "phone": "", "whatsapp": "", "name": full_name or email},
            template_data={"name": full_name or "", "activation_link": link},
            request_id=request_id,
        )
    except Exception as exc:
        logger.warning("account_activation notification failed for user %s: %s", user_id, exc)
    return token


def resend_activation(
    tenant_id: str,
    user_id: str,
    actor_id: str | None = None,
    request_id: str = "",
    actor_role: str = "tenant_admin",
    ip_address: str | None = None,
) -> dict[str, Any]:
    """Re-issue a user's activation link (staff action). Mints a fresh token —
    invalidating any prior unconsumed one — and re-sends the welcome email. Used
    for users provisioned before activation existed, or whose link expired."""
    user = repo.get_user_by_id(tenant_id, user_id)
    if not user:
        raise ResourceNotFoundError("user", user_id)
    issue_activation(tenant_id, user_id, user["email"], user.get("full_name") or "", created_by=actor_id, request_id=request_id)
    _audit_access_email(tenant_id, user_id, "ACTIVATION_RESENT", actor_id, actor_role, ip_address)
    return {"message": "Activation link sent", "email": _mask_email(user["email"])}


def get_activation_preview(token: str) -> dict[str, Any]:
    """Public preview for GET /v1/activate/{token} — the email being activated."""
    from shared import activation

    row = activation.get_activation_by_token(token)
    if not activation.is_activation_valid(row):
        raise ResourceNotFoundError("activation", "token")
    assert row is not None
    user = repo.get_user_by_id(str(row["tenant_id"]), str(row["user_id"]))
    if not user:
        raise ResourceNotFoundError("activation", "token")
    return {"email": user["email"], "full_name": user.get("full_name")}


def activate_account(token: str, password: str) -> dict[str, Any]:
    """Public POST /v1/activate/{token} — set the user's chosen password in the IdP
    and consume the single-use token. The account is then a normal login."""
    from shared import activation

    row = activation.get_activation_by_token(token)
    if not activation.is_activation_valid(row):
        raise ResourceNotFoundError("activation", "token")
    assert row is not None
    tenant_id = str(row["tenant_id"])
    user = repo.get_user_by_id(tenant_id, str(row["user_id"]))
    if not user:
        raise ResourceNotFoundError("activation", "token")

    cognito = get_identity_provider()
    cognito.set_password(user["email"], password, force_change=False)
    # Burn the token (single-use). set_password already succeeded, so a lost race
    # here only means the link can't be reused — the password is set either way.
    activation.consume_activation(tenant_id, str(row["id"]))
    logger.info("Account activated: tenant_id=%s user_id=%s", tenant_id, user["id"])
    return {"email": user["email"]}


def list_users(tenant_id: str) -> list[dict[str, Any]]:
    return repo.list_users(tenant_id)


def get_user(tenant_id: str, user_id: str) -> dict[str, Any]:
    user = repo.get_user_by_id(tenant_id, user_id)
    if not user:
        raise ResourceNotFoundError("user", user_id)
    return user


def get_user_by_cognito_sub(tenant_id: str, cognito_sub: str) -> dict[str, Any]:
    """Return tenant_user by Cognito sub (used for self-service profile updates)."""
    user = repo.get_user_by_cognito_sub(tenant_id, cognito_sub)
    if user is None:
        raise ResourceNotFoundError("tenant_user", cognito_sub)
    return user


def update_user(
    tenant_id: str,
    user_id: str,
    updates: dict[str, Any],
    actor_id: str,
    ip_address: str | None = None,
) -> dict[str, Any]:
    from services.tenant_management.repository import _SUPPORTED_LOCALES

    if "locale" in updates and updates["locale"] not in _SUPPORTED_LOCALES:
        raise BusinessRuleViolationError(
            f"Unsupported locale '{updates['locale']}' — must be one of: {sorted(_SUPPORTED_LOCALES)}",
            rule_id="UNSUPPORTED_LOCALE",
        )
    existing = get_user(tenant_id, user_id)
    if not updates:
        return existing

    # roles/primary_role touch tenant_user_role + Cognito group membership,
    # not a plain tenant_user column — handled separately from the generic
    # SET-clause update below (replaces the old dead-end
    # cognito.update_user_attributes(role=...)-only path that never actually
    # synced Cognito groups).
    roles = updates.pop("roles", None)
    primary_role = updates.pop("primary_role", None)
    new_primary: str | None = primary_role or (roles[0] if roles else None)

    updated = existing
    if updates:
        result = repo.update_user(tenant_id, user_id, updates)
        if result is None:
            raise RuntimeError("update_user returned None unexpectedly")
        updated = result

    cognito = get_identity_provider()

    # Sync mutable Cognito attributes (name, primary role) — username/email is immutable
    if "full_name" in updates or new_primary is not None:
        cognito.update_user_attributes(
            username=existing["email"],
            full_name=updates.get("full_name"),
            role=new_primary,
        )

    if roles is not None and new_primary is not None:
        updated = repo.set_user_roles(tenant_id, user_id, roles, new_primary, assigned_by=actor_id) or updated
        # Reconcile Cognito group membership to match the new role set — the
        # actual fix for the bug where role changes never touched groups.
        cognito.sync_user_groups(existing["email"], tenant_id, set(roles))
        # Invalidate existing sessions so the new group membership / primary
        # role claim takes effect immediately rather than after JWT expiry.
        if existing.get("email"):
            try:
                cognito.global_sign_out(existing["email"])
            except Exception as exc:
                logger.warning("Session invalidation failed for user %s: %s", user_id, exc)
        # The identity cache holds the role for tokens that carry none.
        evict_identity_cache(user_id)

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


def _revoke_login(tenant_id: str, user: dict[str, Any]) -> dict[str, Any]:
    """Cut a user's access off now and return their updated `tenant_user` row.

    Disables the identity-provider account, marks the row `deactivated`, ends their sessions
    and drops the cached identity. The row status is what denies a token that was already
    issued (`shared.auth._check_user_active` reads it on every request); the sign-out also
    revokes the refresh token so the session cannot be renewed, and is best effort because
    the status check does not depend on it.
    """
    user_id = str(user["id"])
    email = user.get("email")
    cognito = get_identity_provider()
    if email:
        cognito.disable_user(email)

    updated = repo.set_user_status(tenant_id, user_id, "deactivated")
    if updated is None:
        raise RuntimeError("set_user_status returned None unexpectedly")

    if email:
        try:
            cognito.global_sign_out(email)
        except Exception as exc:
            logger.warning("Session invalidation failed for user %s: %s", user_id, exc)
    # After the commit above, so the next request reads the new status instead of the old one.
    evict_identity_cache(user_id)
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

    updated = _revoke_login(tenant_id, existing)
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


def _audit_access_email(
    tenant_id: str, user_id: str, action: str, actor_id: str | None, actor_role: str, ip_address: str | None
) -> None:
    """Record that a staff member sent another user a way into their account (audit SEC-07).

    Only IDs are recorded: the email itself is PII and is already on the user's row.
    """
    log_audit(
        tenant_id=tenant_id,
        entity_type="tenant_user",
        entity_id=user_id,
        action=action,
        actor_id=actor_id,
        actor_role=actor_role,
        after_state={"user_id": user_id},
        ip_address=ip_address,
    )


def resend_user_invite(
    tenant_id: str,
    user_id: str,
    actor_id: str | None = None,
    actor_role: str = "tenant_admin",
    ip_address: str | None = None,
) -> None:
    """Resend the identity provider's temporary-password email for an existing staff user, and audit it."""
    user = get_user(tenant_id, user_id)
    get_identity_provider().resend_invite(user["email"])
    _audit_access_email(tenant_id, user_id, "INVITE_RESENT", actor_id, actor_role, ip_address)


def reset_user_password(
    tenant_id: str,
    user_id: str,
    actor_id: str | None = None,
    actor_role: str = "tenant_admin",
    ip_address: str | None = None,
) -> None:
    """Trigger the identity provider's password-reset email for a staff user, and audit it."""
    user = get_user(tenant_id, user_id)
    get_identity_provider().reset_password(user["email"])
    _audit_access_email(tenant_id, user_id, "PASSWORD_RESET_SENT", actor_id, actor_role, ip_address)


# ---------------------------------------------------------------------------
# Customer management
# ---------------------------------------------------------------------------


def _normalize_customer_phones(tenant_id: str, data: dict[str, Any]) -> dict[str, Any]:
    """Canonicalise `phone`/`whatsapp` to E.164 before a customer write.

    Applied on every customer write path (staff create/update here; import
    and self-registration normalise inline where they resolve the tenant's
    dial code themselves) so imported, self-registered, and admin-created
    rows for the same person converge on one phone value instead of
    duplicating under `08012345678` vs `+2348012345678`.
    """
    from shared.phone import dial_code_for_country, normalize_phone

    if "phone" not in data and "whatsapp" not in data:
        return data
    tenant = repo.get_tenant_by_id(tenant_id)
    dial_code = dial_code_for_country(tenant.get("destination_country") if tenant else None)
    normalized = dict(data)
    if "phone" in data:
        normalized["phone"] = normalize_phone(data["phone"], dial_code)
    if "whatsapp" in data:
        normalized["whatsapp"] = normalize_phone(data["whatsapp"], dial_code)
    return normalized


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
    data = _normalize_customer_phones(tenant_id, data)
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


def get_customer_stats(tenant_id: str) -> dict[str, int]:
    """Tenant-wide customer aggregates for the list stats row (SQL-computed)."""
    return repo.get_customer_stats(tenant_id)


def list_customers(
    tenant_id: str,
    q: str | None = None,
    limit: int = 50,
    cursor: dict[str, Any] | None = None,
) -> tuple[list[dict[str, Any]], str | None, bool]:
    return repo.list_customers(tenant_id, q=q, limit=limit, cursor=cursor)


def get_customer_for_user(tenant_id: str, user_id: str) -> dict[str, Any] | None:
    """Return the customer record linked to a portal user's Cognito sub, or None."""
    return repo.get_customer_by_user_id(tenant_id, user_id)


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


_ERASED_EMAIL_DOMAIN = "@erased.invalid"


def _erase_login_identity(tenant_id: str, login: dict[str, Any]) -> None:
    """Erase the personal data a portal login still holds: the identity provider's account, then our row.

    The provider's copy goes first, and strictly: it is keyed by the email the row is about to lose, and a
    failure here must leave the customer unerased so the whole erasure can be retried.
    """
    if login.get("email"):
        get_identity_provider().delete_user(login["email"])
    if repo.anonymise_tenant_user(tenant_id, str(login["id"])) is None:
        raise RuntimeError("anonymise_tenant_user returned None unexpectedly")
    evict_identity_cache(str(login["id"]))


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

    # The erased person must not keep a working login: the tenant_user row and the identity-provider
    # account are where their identity still lives. The record's link to it is cleared by the erasure,
    # so read it first, and cut access before erasing so a failure leaves a customer that can be retried.
    login = repo.get_user_by_id(tenant_id, str(customer["user_id"])) if customer.get("user_id") else None
    if login is not None and login["status"] != "deactivated":
        _revoke_login(tenant_id, login)
        log_audit(
            tenant_id=tenant_id,
            entity_type="tenant_user",
            entity_id=str(login["id"]),
            action="STATUS_CHANGE",
            actor_id=actor_id,
            actor_role="tenant_admin",
            before_state={"status": "active"},
            after_state={"status": "deactivated", "reason": "customer_erasure"},
            ip_address=ip_address,
        )
    if login is not None and not str(login["email"]).endswith(_ERASED_EMAIL_DOMAIN):
        _erase_login_identity(tenant_id, login)

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
    from services.tenant_management.repository import _SUPPORTED_LOCALES

    if "locale" in updates and updates["locale"] not in _SUPPORTED_LOCALES:
        raise BusinessRuleViolationError(
            f"Unsupported locale '{updates['locale']}' — must be one of: {sorted(_SUPPORTED_LOCALES)}",
            rule_id="UNSUPPORTED_LOCALE",
        )
    existing = get_customer(tenant_id, customer_id)
    if not updates:
        return existing
    updates = _normalize_customer_phones(tenant_id, updates)
    # Saving notification preferences is what records a choice (shared/notification_consent.py): a customer
    # with no choice on record is messaged on every channel, one with a choice is held to it. Stamped here
    # so it is true however the preferences arrive: the Account page, or staff recording what a customer said.
    if "notification_consent" in updates and "consent_given_at" not in updates:
        updates = {**updates, "consent_given_at": datetime.now(UTC).isoformat()}
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


def _serialize_charge_type(row: dict[str, Any]) -> dict[str, Any]:
    """Map a charge_type DB row to the wire shape.

    The column is `default_amount_ngn`; the wire (frontend) contract is
    `amount_ngn`. `usage_count` is present only on list rows (correlated
    count) — default to 0 for single-row create/update responses.
    """
    return {
        "id": row["id"],
        "name": row["name"],
        "description": row.get("description"),
        "amount_ngn": row.get("default_amount_ngn"),
        "is_active": row.get("is_active", True),
        "usage_count": int(row.get("usage_count") or 0),
        "created_at": row.get("created_at"),
    }


def _charge_type_write_fields(data: dict[str, Any]) -> dict[str, Any]:
    """Translate inbound wire fields to DB column names (amount_ngn -> default_amount_ngn)."""
    mapped = {k: v for k, v in data.items() if k in ("name", "description", "is_active")}
    if "amount_ngn" in data:
        mapped["default_amount_ngn"] = data["amount_ngn"]
    return mapped


def create_charge_type(
    tenant_id: str,
    data: dict[str, Any],
    actor_id: str,
    ip_address: str | None = None,
) -> dict[str, Any]:
    charge_type = repo.create_charge_type(tenant_id, {**_charge_type_write_fields(data), "created_by": actor_id})
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
    return _serialize_charge_type(charge_type)


def list_charge_types(tenant_id: str) -> list[dict[str, Any]]:
    return [_serialize_charge_type(row) for row in repo.list_charge_types(tenant_id)]


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
    updated = repo.update_charge_type(tenant_id, charge_type_id, _charge_type_write_fields(updates))
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
    return _serialize_charge_type(updated)


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

    # Ground-truth gap found while auditing log coverage: create/update both
    # log this; deactivate was the one silently missing.
    log_audit(
        tenant_id=tenant_id,
        entity_type="charge_type",
        entity_id=charge_type_id,
        action="UPDATE",
        actor_id=actor_id,
        actor_role="tenant_admin",
        before_state={"is_active": existing.get("is_active")},
        after_state={"is_active": False},
        ip_address=ip_address,
    )
    return _serialize_charge_type(result)


# ---------------------------------------------------------------------------
# Container capacity presets
#
# Ten well-known shipping-container capacities ship as read-only defaults
# (internal usable volumes; recommended load ≈ 92% of capacity, the practical
# fill target). Tenants add their own custom presets on top via the admin
# config page — those persist in container_capacity. The list endpoint merges
# defaults + custom so the create-container picker shows everything.
# ---------------------------------------------------------------------------

DEFAULT_CONTAINER_CAPACITIES: list[dict[str, Any]] = [
    {"name": "45' High Cube (HC)", "capacity_cbm": 86.0, "recommended_cbm": 79.0},
    {"name": "40' High Cube (HC)", "capacity_cbm": 76.0, "recommended_cbm": 70.0},
    {"name": "40' Standard (GP)", "capacity_cbm": 67.0, "recommended_cbm": 62.0},
    {"name": "40' Open Top", "capacity_cbm": 66.0, "recommended_cbm": 60.0},
    {"name": "40' Reefer (HC)", "capacity_cbm": 67.0, "recommended_cbm": 60.0},
    {"name": "20' High Cube (HC)", "capacity_cbm": 37.0, "recommended_cbm": 34.0},
    {"name": "20' Standard (GP)", "capacity_cbm": 33.0, "recommended_cbm": 30.0},
    {"name": "20' Open Top", "capacity_cbm": 32.0, "recommended_cbm": 29.0},
    {"name": "20' Reefer", "capacity_cbm": 28.0, "recommended_cbm": 25.0},
    {"name": "10' Standard", "capacity_cbm": 16.0, "recommended_cbm": 14.0},
]

_CAPACITY_NAME_MAX = 100


def _serialize_container_capacity(row: dict[str, Any], *, is_custom: bool) -> dict[str, Any]:
    """Map a capacity (default dict or DB row) to the wire shape, CBM as floats
    so the frontend can call toFixed without the Decimal-as-string trap."""
    rec = row.get("recommended_cbm")
    return {
        "id": str(row["id"]) if is_custom else f"default:{row['name']}",
        "name": row["name"],
        "capacity_cbm": float(row["capacity_cbm"]),
        "recommended_cbm": float(rec) if rec is not None else None,
        "is_custom": is_custom,
    }


_CAPACITY_OVERRIDES_KEY = "container_capacity_overrides"


def _default_recommended_overrides(tenant_id: str) -> dict[str, float]:
    """Per-tenant admin overrides of the built-in defaults' recommended load,
    stored in tenant_config (no table needed) as {default name: recommended}."""
    for row in repo.get_all_configs(tenant_id):
        if row["config_key"] == _CAPACITY_OVERRIDES_KEY:
            raw = row.get("config_value") or {}
            return {k: float(v) for k, v in raw.items() if v is not None}
    return {}


def list_container_capacities(tenant_id: str) -> list[dict[str, Any]]:
    custom = [_serialize_container_capacity(row, is_custom=True) for row in repo.list_container_capacities(tenant_id)]
    overrides = _default_recommended_overrides(tenant_id)
    defaults = []
    for row in DEFAULT_CONTAINER_CAPACITIES:
        item = _serialize_container_capacity(row, is_custom=False)
        if row["name"] in overrides:
            item["recommended_cbm"] = overrides[row["name"]]
        defaults.append(item)
    # Largest first, so the create-container picker leads with 40'/45' HC.
    return sorted(custom + defaults, key=lambda c: c["capacity_cbm"], reverse=True)


def update_container_capacity(
    tenant_id: str,
    capacity_id: str,
    data: dict[str, Any],
    actor_id: str,
    ip_address: str | None = None,
) -> dict[str, Any]:
    rec_raw = data.get("recommended_cbm")
    rec_cleared = rec_raw in (None, "")
    recommended = None if rec_cleared else _positive_cbm(rec_raw, "recommended_cbm")

    # --- Default preset: only recommended_cbm is tunable (capacity/name are
    # physical constants). Persisted as an override in tenant_config. ---
    if capacity_id.startswith("default:"):
        name = capacity_id[len("default:") :]
        default = next((d for d in DEFAULT_CONTAINER_CAPACITIES if d["name"] == name), None)
        if default is None:
            raise ResourceNotFoundError("container_capacity", capacity_id)
        if recommended is not None and recommended > float(default["capacity_cbm"]):
            raise ValidationError("recommended_cbm cannot exceed capacity_cbm")
        overrides = _default_recommended_overrides(tenant_id)
        if rec_cleared:
            overrides.pop(name, None)  # revert to the built-in recommended
        else:
            overrides[name] = recommended  # type: ignore[assignment]
        repo.upsert_config(tenant_id, _CAPACITY_OVERRIDES_KEY, overrides, updated_by=actor_id)
        log_audit(
            tenant_id=tenant_id,
            entity_type="container_capacity",
            entity_id=capacity_id,
            action="UPDATE",
            actor_id=actor_id,
            actor_role="tenant_admin",
            after_state={"recommended_cbm": recommended},
            ip_address=ip_address,
        )
        item = _serialize_container_capacity(default, is_custom=False)
        item["recommended_cbm"] = (
            recommended
            if recommended is not None
            else (float(default["recommended_cbm"]) if default["recommended_cbm"] else None)
        )
        return item

    # --- Custom preset: name / capacity / recommended all editable. ---
    existing = repo.get_container_capacity_by_id(tenant_id, capacity_id)
    if not existing:
        raise ResourceNotFoundError("container_capacity", capacity_id)
    updates: dict[str, Any] = {}
    if "name" in data:
        name = (data.get("name") or "").strip()
        if not name:
            raise ValidationError("name is required")
        if len(name) > _CAPACITY_NAME_MAX:
            raise ValidationError(f"name must be at most {_CAPACITY_NAME_MAX} characters")
        updates["name"] = name
    if data.get("capacity_cbm") not in (None, ""):
        updates["capacity_cbm"] = _positive_cbm(data.get("capacity_cbm"), "capacity_cbm")
    if "recommended_cbm" in data:
        updates["recommended_cbm"] = recommended
    effective_capacity = updates.get("capacity_cbm", float(existing["capacity_cbm"]))
    if updates.get("recommended_cbm") is not None and updates["recommended_cbm"] > effective_capacity:
        raise ValidationError("recommended_cbm cannot exceed capacity_cbm")

    try:
        row = repo.update_container_capacity(tenant_id, capacity_id, updates)
    except Exception as exc:  # UNIQUE (tenant_id, name)
        if "container_capacity" in str(exc) and ("unique" in str(exc).lower() or "duplicate" in str(exc).lower()):
            raise DuplicateResourceError("container_capacity", updates.get("name", "")) from exc
        raise
    if row is None:
        raise ResourceNotFoundError("container_capacity", capacity_id)
    log_audit(
        tenant_id=tenant_id,
        entity_type="container_capacity",
        entity_id=capacity_id,
        action="UPDATE",
        actor_id=actor_id,
        actor_role="tenant_admin",
        after_state=updates,
        ip_address=ip_address,
    )
    return _serialize_container_capacity(row, is_custom=True)


def create_container_capacity(
    tenant_id: str,
    data: dict[str, Any],
    actor_id: str,
    ip_address: str | None = None,
) -> dict[str, Any]:
    name = (data.get("name") or "").strip()
    if not name:
        raise ValidationError("name is required")
    if len(name) > _CAPACITY_NAME_MAX:
        raise ValidationError(f"name must be at most {_CAPACITY_NAME_MAX} characters")
    capacity_cbm = _positive_cbm(data.get("capacity_cbm"), "capacity_cbm")
    recommended = data.get("recommended_cbm")
    recommended_cbm = _positive_cbm(recommended, "recommended_cbm") if recommended not in (None, "") else None
    if recommended_cbm is not None and recommended_cbm > capacity_cbm:
        raise ValidationError("recommended_cbm cannot exceed capacity_cbm")

    try:
        row = repo.create_container_capacity(
            tenant_id,
            {"name": name, "capacity_cbm": capacity_cbm, "recommended_cbm": recommended_cbm, "created_by": actor_id},
        )
    except Exception as exc:  # UNIQUE (tenant_id, name)
        if "container_capacity" in str(exc) and ("unique" in str(exc).lower() or "duplicate" in str(exc).lower()):
            raise DuplicateResourceError("container_capacity", name) from exc
        raise
    if row is None:
        raise RuntimeError("create_container_capacity returned None unexpectedly")
    log_audit(
        tenant_id=tenant_id,
        entity_type="container_capacity",
        entity_id=str(row["id"]),
        action="CREATE",
        actor_id=actor_id,
        actor_role="tenant_admin",
        after_state={"name": name, "capacity_cbm": capacity_cbm, "recommended_cbm": recommended_cbm},
        ip_address=ip_address,
    )
    return _serialize_container_capacity(row, is_custom=True)


def delete_container_capacity(
    tenant_id: str,
    capacity_id: str,
    actor_id: str,
    ip_address: str | None = None,
) -> None:
    # Only custom presets are deletable; defaults are code constants with a
    # synthetic "default:" id that never reaches a DB row.
    if capacity_id.startswith("default:"):
        raise BusinessRuleViolationError("Default container capacities cannot be deleted", rule_id="CAPACITY_DEFAULT_IMMUTABLE")
    deleted = repo.delete_container_capacity(tenant_id, capacity_id)
    if deleted is None:
        raise ResourceNotFoundError("container_capacity", capacity_id)
    log_audit(
        tenant_id=tenant_id,
        entity_type="container_capacity",
        entity_id=capacity_id,
        action="DELETE",
        actor_id=actor_id,
        actor_role="tenant_admin",
        ip_address=ip_address,
    )


def _positive_cbm(value: Any, field: str) -> float:
    try:
        num = float(value)
    except (TypeError, ValueError) as exc:
        raise ValidationError(f"{field} must be a number") from exc
    if num <= 0:
        raise ValidationError(f"{field} must be greater than 0")
    if num > 1000:
        raise ValidationError(f"{field} is unrealistically large")
    return num


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


# ---------------------------------------------------------------------------
# Customer self-registration (public — no JWT)
# ---------------------------------------------------------------------------


def _notify_account_exists(tenant_id: str, email: str, name: str | None, request_id: str) -> None:
    """Tell the owner of an address that someone tried to register with it.

    Best effort: the sign-up answer must not depend on whether this succeeds or how long it takes.
    `name` is the existing account's, never what the registrant typed, which is attacker-controlled.
    """
    from shared.notifications import enqueue_notifications

    try:
        enqueue_notifications(
            tenant_id=tenant_id,
            event_type="registration_existing_account",
            recipient={"email": email, "phone": "", "whatsapp": "", "name": name or ""},
            template_data={"name": name or "", "login_link": login_url()},
            request_id=request_id,
        )
    except MissingBaseUrlError as exc:
        logger.error("registration_existing_account link could not be built — no email sent: %s", exc)
    except Exception as exc:
        logger.warning("registration_existing_account notification failed: %s", exc)


def self_register_customer(
    req: CustomerRegistrationRequest,
    slug: str | None = None,
    host: str = "",
    request_id: str = "",
    ip_address: str | None = None,
) -> None:
    """Register a customer against a tenant, provisioning both Cognito and the
    tenant_user row that Cognito login requires.

    Returns nothing, and returns the same way whether the email was new or already had an account:
    the endpoint is public, so any difference in the answer lets anyone test whether a person is a
    customer of a given shipping company, or has an account anywhere on the platform (the identity
    provider is shared by every tenant). An existing account's owner is told by email instead
    (`_notify_account_exists`). Residual: a new registration does more work than an existing one, so
    response time still differs slightly; rate limiting is what bounds probing through it.

    Tenant resolution order (first match wins):
      1. Explicit `slug` — the path param from POST /v1/register/{slug},
         the supported route going forward.
      2. `req.slug` — the body field, for callers still posting to the bare
         POST /v1/register endpoint.
      3. Host header (legacy fallback only — kept for any caller relying on
         the old behaviour, but never reachable in practice since the
         frontend calls a shared VITE_API_BASE_URL, so API Gateway's own
         host is all `host` ever carries here).

    Guards:
      - Tenant must be active
      - An email that already has an account (in this tenant's customer table, or in the identity
        provider) creates nothing and is answered like a new one

    Ground-truth fix: this previously wrote the Cognito sub directly into
    `customer.user_id`, a column with FOREIGN KEY REFERENCES tenant_user(id)
    — that write could never succeed against the real schema, so
    self-registration never actually worked. Fixed by creating the missing
    tenant_user row (role='customer') and linking *its* id.
    """
    from shared.notifications import enqueue_notifications
    from shared.phone import dial_code_for_country, normalize_phone

    resolved_slug = slug or req.slug
    if resolved_slug:
        tenant = repo.get_tenant_by_slug(resolved_slug)
    else:
        hostname = host.split(":")[0].lower()
        tenant = repo.get_tenant_by_custom_domain(hostname)
        if not tenant:
            parts = hostname.split(".")
            fallback_slug = parts[0] if len(parts) >= 3 else hostname
            tenant = repo.get_tenant_by_slug(fallback_slug)
    if not tenant:
        raise ResourceNotFoundError("tenant", resolved_slug or host)

    if tenant["status"] != "active":
        raise BusinessRuleViolationError(
            "This tenant is not accepting new registrations",
            rule_id="TENANT_NOT_ACTIVE",
        )

    tenant_id = str(tenant["id"])

    existing = repo.get_customer_by_email(tenant_id, req.email)
    if existing:
        _notify_account_exists(tenant_id, req.email, existing.get("name"), request_id)
        return

    dial_code = dial_code_for_country(tenant.get("destination_country"))
    phone = normalize_phone(req.phone, dial_code)
    whatsapp = normalize_phone(req.whatsapp, dial_code) if req.whatsapp else None

    # Provision Cognito user (sends temp-password email via Cognito)
    cognito = get_identity_provider()
    try:
        cognito_sub = cognito.create_user(
            email=req.email,
            full_name=req.name,
            tenant_id=tenant_id,
            role="customer",
        )
    except DuplicateResourceError:
        # The address has an account elsewhere on the platform: one identity belongs to exactly one
        # tenant. Nothing was created, and the caller is told nothing about it.
        _notify_account_exists(tenant_id, req.email, None, request_id)
        return
    group_name = f"{tenant_id}:customer"
    cognito.create_group_if_not_exists(group_name)
    cognito.add_user_to_group(req.email, group_name)

    # Create the tenant_user row Cognito login actually requires — this is
    # the FK the old code silently skipped. id is set to cognito_sub by
    # repo.create_tenant_user, matching every other created-by/user chain.
    portal_user = repo.create_tenant_user(
        tenant_id,
        {
            "tenant_id": tenant_id,
            "cognito_sub": cognito_sub,
            "email": req.email,
            "full_name": req.name,
            "role": "customer",
            "created_by": None,
        },
    )
    if portal_user is None:
        raise RuntimeError("create_tenant_user returned None unexpectedly")

    # Create customer row, linked to the tenant_user we just created —
    # customer.user_id's FK is tenant_user(id), never a bare Cognito sub.
    customer = repo.create_customer(
        tenant_id,
        {
            "name": req.name,
            "email": req.email,
            "phone": phone,
            "whatsapp": whatsapp,
            # An empty list is the registrant choosing nothing, not leaving it blank: only an omitted field
            # gets the default.
            "notification_consent": ["email"] if req.notification_consent is None else req.notification_consent,
            "consent_given_at": datetime.now(UTC).isoformat(),
            "user_id": str(portal_user["id"]),
        },
    )
    if customer is None:
        raise RuntimeError("create_customer returned None unexpectedly")

    # Welcome notification (best-effort)
    try:
        enqueue_notifications(
            tenant_id=tenant_id,
            event_type="customer_registered",
            recipient={
                "phone": phone or "",
                "email": req.email,
                "whatsapp": whatsapp or "",
                "name": req.name,
            },
            template_data={"name": req.name},
            request_id=request_id,
        )
    except Exception as exc:
        logger.warning("Welcome notification failed for new customer: %s", exc)

    log_audit(
        tenant_id=tenant_id,
        entity_type="customer",
        entity_id=str(customer["id"]),
        action="SELF_REGISTER",
        actor_id=cognito_sub,
        actor_role="customer",
        after_state={"id": str(customer["id"])},
        ip_address=ip_address,
    )


# ---------------------------------------------------------------------------
# Customer account-creation invites
# ---------------------------------------------------------------------------


def issue_customer_invite(
    tenant_id: str,
    customer_id: str,
    actor_id: str | None = None,
    request_id: str = "",
) -> dict[str, Any]:
    """Issue (or resend) an account-creation invite for a customer with no login.

    Deletes any prior unconsumed invite first — a resend invalidates the old
    link. Never returns the raw token to staff; it is delivered to the
    customer by SMS/WhatsApp (the only contact a manifest import gives us).

    Raises:
        ResourceNotFoundError: if the customer does not exist.
        BusinessRuleViolationError: if the customer already has a portal login.
    """
    from shared.invites import (
        create_invite,
        delete_unconsumed_invites,
        hash_token,
        mint_token,
    )
    from shared.notifications import enqueue_notifications, is_recipient_allowed, primary_channel
    from shared.phone import mask_phone

    customer = repo.get_customer_by_id(tenant_id, customer_id)
    if not customer:
        raise ResourceNotFoundError("customer", customer_id)
    if customer.get("user_id"):
        raise BusinessRuleViolationError("Customer already has an account", rule_id="CUSTOMER_ALREADY_HAS_ACCOUNT")

    delete_unconsumed_invites(tenant_id, customer_id)

    token = mint_token()
    token_hash = hash_token(token)
    # Ask the notification layer which channel it will actually use. This was
    # hardcoded to "sms", so after the switch to WhatsApp-first every invite was
    # reported to staff as sent by SMS while the message went out over WhatsApp.
    channel = primary_channel(tenant_id, "customer_invite", {"phone": customer.get("phone")})
    # Report what actually happened. Outside production the recipient guard
    # (shared/notifications.py) suppresses contacts that are not allowlisted,
    # and tenant preferences can mute a channel in production — in either case
    # telling staff the invite was "sent by sms" would be a lie, and they would
    # not know to deliver the link another way.
    recipient = {
        "phone": customer.get("phone"),
        "email": customer.get("email"),
        "name": customer.get("name"),
    }
    delivered = is_recipient_allowed(recipient)
    sent_to = customer.get("phone") or customer.get("email")

    # Built before the row is written, so `sent_channel` can record that nothing
    # was sent. Was f"{os.environ.get('CUSTOMER_PORTAL_BASE_URL', '')}/invite/{token}"
    # — and that variable is set in no environment, so every invite went out as
    # the relative path "/invite/<token>", which no mail or messaging client can
    # open. See shared/app_urls.py.
    invite_link = ""
    try:
        invite_link = invite_url(token)
    except MissingBaseUrlError as exc:
        # Two things must not happen: sending a dead link, and telling staff the
        # customer was invited when they were not. The row is still written —
        # it is the record a resend works from once the base URL is configured —
        # but with no channel, because nothing left the building.
        logger.error(
            "customer_invite link could not be built for customer %s — nothing sent: %s",
            customer_id,
            exc,
        )
        delivered = False

    invite = create_invite(
        tenant_id,
        customer_id,
        token_hash,
        sent_channel=channel if delivered else None,
        sent_to_masked=(mask_phone(sent_to) if channel in ("sms", "whatsapp") else sent_to) if delivered else None,
        created_by=actor_id,
    )
    if invite is None:
        raise RuntimeError("create_invite returned None unexpectedly")

    if invite_link:
        try:
            enqueue_notifications(
                tenant_id=tenant_id,
                event_type="customer_invite",
                recipient={
                    "phone": customer.get("phone") or "",
                    "email": customer.get("email") or "",
                    "whatsapp": customer.get("whatsapp") or "",
                    "name": customer.get("name") or "",
                },
                template_data={"name": customer.get("name") or "", "invite_link": invite_link},
                request_id=request_id,
                customer_id=customer_id,
            )
        except Exception as exc:
            logger.warning("Customer invite notification failed for customer_id=%s: %s", customer_id, exc)

    log_audit(
        tenant_id=tenant_id,
        entity_type="customer_invite",
        entity_id=str(invite["id"]),
        action="CREATE",
        actor_id=actor_id or "",
        actor_role="staff" if actor_id else "system",
        after_state={
            "customer_id": customer_id,
            "expires_at": str(invite["expires_at"]),
            "sent_channel": channel if delivered else None,
        },
    )
    return {
        "id": str(invite["id"]),
        "customer_id": customer_id,
        "expires_at": invite["expires_at"],
        "sent_channel": channel if delivered else None,
        "delivery_suppressed": not delivered,
        "sent_to_masked": invite["sent_to_masked"],
    }


def get_customer_invite_public(token: str) -> dict[str, Any]:
    """Return the public, no-auth preview for GET /v1/invites/{token}.

    Only ever exposes company name, customer name, and expiry — never any
    other customer PII, since this endpoint requires no authentication.

    Raises ResourceNotFoundError if the token is unknown, expired, or consumed.
    """
    from shared.invites import get_invite_by_token, is_invite_valid

    invite = get_invite_by_token(token)
    if not is_invite_valid(invite):
        raise ResourceNotFoundError("customer_invite", token)
    assert invite is not None  # is_invite_valid(None) is False, so invite is set here

    tenant_id = str(invite["tenant_id"])
    customer = repo.get_customer_by_id(tenant_id, str(invite["customer_id"]))
    tenant = repo.get_tenant_by_id(tenant_id)
    if not customer or not tenant:
        raise ResourceNotFoundError("customer_invite", token)

    return {
        "company_name": tenant.get("company_name"),
        "customer_name": customer.get("name"),
        "expires_at": invite["expires_at"],
    }


def accept_customer_invite(
    token: str,
    req: AcceptCustomerInviteRequest,
    ip_address: str | None = None,
) -> dict[str, Any]:
    """Claim an invite: create the Cognito login + tenant_user row, link the
    customer, and stamp the invite consumed.

    Wrapped so a failed Cognito call leaves the invite unconsumed (the
    customer can retry the same link) — the invite is only stamped consumed
    after the Cognito user and tenant_user row both exist.

    Raises:
        ResourceNotFoundError: if the token is unknown, expired, or consumed.
        DuplicateResourceError: if the chosen email is already registered
            for this tenant.
    """
    from shared.invites import consume_invite, get_invite_by_token, is_invite_valid

    invite = get_invite_by_token(token)
    if not is_invite_valid(invite):
        raise ResourceNotFoundError("customer_invite", token)
    assert invite is not None

    tenant_id = str(invite["tenant_id"])
    customer_id = str(invite["customer_id"])
    customer = repo.get_customer_by_id(tenant_id, customer_id)
    if not customer:
        raise ResourceNotFoundError("customer", customer_id)
    if customer.get("user_id"):
        raise BusinessRuleViolationError("Customer already has an account", rule_id="CUSTOMER_ALREADY_HAS_ACCOUNT")
    if repo.get_customer_by_email(tenant_id, req.email):
        raise DuplicateResourceError("customer", req.email)

    cognito = get_identity_provider()
    cognito_sub = cognito.create_user_with_password(
        email=req.email,
        full_name=str(customer.get("name") or ""),
        tenant_id=tenant_id,
        role="customer",
        password=req.password,
    )
    group_name = f"{tenant_id}:customer"
    cognito.create_group_if_not_exists(group_name)
    cognito.add_user_to_group(req.email, group_name)

    portal_user = repo.create_tenant_user(
        tenant_id,
        {
            "tenant_id": tenant_id,
            "cognito_sub": cognito_sub,
            "email": req.email,
            "full_name": str(customer.get("name") or ""),
            "role": "customer",
            "created_by": None,
        },
    )
    if portal_user is None:
        raise RuntimeError("create_tenant_user returned None unexpectedly")

    updated_customer = repo.update_customer(tenant_id, customer_id, {"email": req.email, "user_id": str(portal_user["id"])})
    if updated_customer is None:
        raise RuntimeError("update_customer returned None unexpectedly")

    consumed = consume_invite(tenant_id, str(invite["id"]))
    if consumed is None:
        # Lost a race with a concurrent claim of the same token — the
        # Cognito user/tenant_user rows above are already created and safe
        # to leave in place; the invite itself just can't be re-consumed.
        logger.warning("Invite %s was already consumed by a concurrent request", invite["id"])

    log_audit(
        tenant_id=tenant_id,
        entity_type="customer",
        entity_id=customer_id,
        action="INVITE_ACCEPTED",
        actor_id=cognito_sub,
        actor_role="customer",
        after_state={"id": customer_id, "user_id": str(portal_user["id"])},
        ip_address=ip_address,
    )
    return updated_customer


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
