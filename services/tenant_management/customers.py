"""Customers, their accounts, and their personal data.

The tenant's customer records, GDPR erasure and export, public self-registration, and account-creation invites.

Split out of ``service.py`` (audit BE-13); ``service`` re-exports every public function, so callers are unchanged.
"""

import logging
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from shared.app_urls import MissingBaseUrlError, invite_url, login_url
from shared.audit import log_audit
from shared.auth import evict_identity_cache
from shared.db import tenant_transaction
from shared.exceptions import (
    BusinessRuleViolationError,
    DuplicateResourceError,
    ResourceNotFoundError,
)
from shared.providers import get_identity_provider

from . import repository as repo
from .models import (
    AcceptCustomerInviteRequest,
    CustomerRegistrationRequest,
)

if TYPE_CHECKING:
    pass
from .users import _revoke_login

logger = logging.getLogger(__name__)


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
    actor_role: str = "staff",
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
        actor_role=actor_role,
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
    actor_role: str = "tenant_admin",
) -> dict[str, Any] | None:
    """Erase a customer's personal data (GDPR Art. 17 — right to erasure).

    Anonymises the record in-place to preserve FK integrity.
    """
    customer = repo.get_customer_by_id(tenant_id, customer_id)
    if not customer:
        raise ResourceNotFoundError("customer", customer_id)
    if customer.get("anonymised_at"):
        raise BusinessRuleViolationError(
            "Customer record has already been anonymised",
            rule_id="ALREADY_ANONYMISED",
        )
    if actor_role == "customer" and repo.customer_has_unpaid_balance(tenant_id, customer_id):
        raise BusinessRuleViolationError(
            "Account cannot be erased while invoices or carryovers have an unpaid balance",
            rule_id="CUSTOMER_HAS_UNPAID_BALANCE",
        )
    _pii_fields = {"name", "email", "phone", "whatsapp", "address", "delivery_address", "contract_details"}
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
            actor_role=actor_role,
            before_state={"status": "active"},
            after_state={"status": "deactivated", "reason": "customer_erasure"},
            ip_address=ip_address,
        )
    if login is not None and not str(login["email"]).endswith(_ERASED_EMAIL_DOMAIN):
        _erase_login_identity(tenant_id, login)

    repo.delete_unconsumed_invites_for_customer(tenant_id, customer_id)
    repo.anonymise_customer_record(tenant_id, customer_id)
    log_audit(
        tenant_id=tenant_id,
        entity_type="customer",
        entity_id=customer_id,
        action="DELETE",
        actor_id=actor_id,
        actor_role=actor_role,
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
        actor_id=requesting_user_id or None,
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
    actor_role: str = "staff",
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
        actor_role=actor_role,
        before_state=existing,
        after_state=updated,
        ip_address=ip_address,
    )
    return updated


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


SELF_REGISTRATION_CONFIG_KEY = "self_registration"


def _self_registration_enabled(tenant_id: str) -> bool:
    """Whether this tenant currently accepts public self-registration."""
    import json

    rows = repo.get_all_configs(tenant_id)
    row = next((r for r in rows if r["config_key"] == SELF_REGISTRATION_CONFIG_KEY), None)
    value = row["config_value"] if row else {}
    if isinstance(value, str):
        value = json.loads(value)
    return bool(value.get("enabled", True))


def get_self_registration_setting(tenant_id: str) -> dict[str, Any]:
    """Return whether customer self-signup is enabled for this tenant, plus its slug."""
    rows = repo.get_all_configs(tenant_id)
    row = next((r for r in rows if r["config_key"] == SELF_REGISTRATION_CONFIG_KEY), None)
    tenant = repo.get_tenant_by_id(tenant_id)
    return {
        "enabled": _self_registration_enabled(tenant_id),
        "slug": (tenant or {}).get("slug"),
        "updated_at": (row or {}).get("updated_at"),
    }


def set_self_registration_enabled(
    tenant_id: str,
    enabled: bool,
    actor_id: str | None = None,
    actor_role: str = "",
    ip_address: str | None = None,
) -> dict[str, Any]:
    """Turn customer self-signup on or off for this tenant (audited)."""
    before = get_self_registration_setting(tenant_id)
    repo.upsert_config(tenant_id, SELF_REGISTRATION_CONFIG_KEY, {"enabled": enabled}, updated_by=actor_id)
    after = get_self_registration_setting(tenant_id)

    log_audit(
        tenant_id=tenant_id,
        entity_type="tenant_config",
        entity_id=SELF_REGISTRATION_CONFIG_KEY,
        action="UPDATE_SELF_REGISTRATION",
        actor_id=actor_id,
        actor_role=actor_role,
        before_state={"enabled": before["enabled"]},
        after_state={"enabled": after["enabled"]},
        ip_address=ip_address,
    )
    return after


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

    if not _self_registration_enabled(str(tenant["id"])):
        raise BusinessRuleViolationError(
            "This tenant is not accepting new registrations",
            rule_id="SELF_REGISTRATION_DISABLED",
        )

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

    if repo.find_user_across_tenants(email=req.email):
        _notify_account_exists(tenant_id, req.email, None, request_id)
        return

    dial_code = dial_code_for_country(tenant.get("destination_country"))
    phone = normalize_phone(req.phone, dial_code)
    whatsapp = normalize_phone(req.whatsapp, dial_code) if req.whatsapp else None

    if phone and repo.get_customer_by_phone(tenant_id, phone):
        raise DuplicateResourceError("customer", req.phone)

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
    if repo.find_user_across_tenants(user_id=cognito_sub):
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
    repo.ensure_primary_user_role(tenant_id, str(portal_user["id"]), "customer")

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
    if customer.get("anonymised_at"):
        raise BusinessRuleViolationError("Cannot invite an anonymised customer", rule_id="CUSTOMER_ANONYMISED")
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
        actor_id=actor_id or None,
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
    if not customer or not tenant or tenant.get("status") != "active" or customer.get("anonymised_at") or customer.get("user_id"):
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
    customer can retry the same link) and a lost concurrent race cleans up
    the created IdP account without linking a second login.

    Raises:
        ResourceNotFoundError: if the token is unknown, expired, or consumed.
        DuplicateResourceError: if the chosen email is already registered.
    """
    from shared.invites import consume_invite, get_invite_by_token, is_invite_valid

    invite = get_invite_by_token(token)
    if not is_invite_valid(invite):
        raise ResourceNotFoundError("customer_invite", token)
    assert invite is not None

    tenant_id = str(invite["tenant_id"])
    customer_id = str(invite["customer_id"])
    tenant = repo.get_tenant_by_id(tenant_id)
    if tenant is not None and tenant.get("status") != "active":
        raise ResourceNotFoundError("customer_invite", token)
    customer = repo.get_customer_by_id(tenant_id, customer_id)
    if not customer:
        raise ResourceNotFoundError("customer", customer_id)
    if customer.get("anonymised_at"):
        raise ResourceNotFoundError("customer_invite", token)
    if customer.get("user_id"):
        raise BusinessRuleViolationError("Customer already has an account", rule_id="CUSTOMER_ALREADY_HAS_ACCOUNT")
    if repo.get_customer_by_email(tenant_id, req.email):
        raise DuplicateResourceError("customer", req.email)
    if repo.find_user_across_tenants(email=req.email):
        raise DuplicateResourceError("customer", req.email)

    cognito = get_identity_provider()
    cognito_sub = cognito.create_user_with_password(
        email=req.email,
        full_name=str(customer.get("name") or ""),
        tenant_id=tenant_id,
        role="customer",
        password=req.password,
    )
    if repo.find_user_across_tenants(user_id=cognito_sub):
        raise DuplicateResourceError("customer", req.email)
    group_name = f"{tenant_id}:customer"
    cognito.create_group_if_not_exists(group_name)
    cognito.add_user_to_group(req.email, group_name)

    try:
        with tenant_transaction(tenant_id):
            consumed = consume_invite(tenant_id, str(invite["id"]))
            if consumed is None:
                raise ResourceNotFoundError("customer_invite", token)

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
            repo.ensure_primary_user_role(tenant_id, str(portal_user["id"]), "customer")

            updated_customer = repo.update_customer(
                tenant_id, customer_id, {"email": req.email, "user_id": str(portal_user["id"])}
            )
            if updated_customer is None:
                raise RuntimeError("update_customer returned None unexpectedly")
    except ResourceNotFoundError:
        logger.warning("Invite %s was already consumed by a concurrent request", invite["id"])
        try:
            cognito.delete_user(req.email)
        except Exception as cleanup_exc:
            logger.warning("Could not clean up IdP user after lost invite race: %s", cleanup_exc)
        raise

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
