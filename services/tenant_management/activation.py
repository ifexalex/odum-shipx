"""Account activation and the audit record for access emails.

Account activation for operator-provisioned staff and admins, who set their own password from a one-time link, and
the audit record for every email that gives someone a way into their account (SEC-07).

Split out of ``service.py`` (audit BE-13); ``service`` re-exports every public function, so callers are unchanged.
"""

import logging
from typing import TYPE_CHECKING, Any

from shared.app_urls import MissingBaseUrlError, activation_url
from shared.audit import log_audit
from shared.exceptions import (
    BusinessRuleViolationError,
    ResourceNotFoundError,
)
from shared.providers import get_identity_provider

from . import repository as repo

if TYPE_CHECKING:
    pass


logger = logging.getLogger(__name__)


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
    if user.get("status", "active") != "active":
        raise BusinessRuleViolationError(
            "Cannot resend activation for a deactivated user",
            rule_id="USER_NOT_ACTIVE",
        )
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
    tenant_id = str(row["tenant_id"])
    tenant = repo.get_tenant_by_id(tenant_id)
    if tenant is not None and tenant.get("status") != "active":
        raise ResourceNotFoundError("activation", "token")
    user = repo.get_user_by_id(tenant_id, str(row["user_id"]))
    if not user or user.get("status", "active") != "active":
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
    tenant = repo.get_tenant_by_id(tenant_id)
    if tenant is not None and tenant.get("status") != "active":
        raise ResourceNotFoundError("activation", "token")
    user = repo.get_user_by_id(tenant_id, str(row["user_id"]))
    if not user or user.get("status", "active") != "active":
        raise ResourceNotFoundError("activation", "token")

    # Atomically claim the single-use token BEFORE mutating the IdP password so
    # concurrent submissions cannot both succeed with different passwords.
    consumed = activation.consume_activation(tenant_id, str(row["id"]))
    if consumed is None:
        raise ResourceNotFoundError("activation", "token")

    cognito = get_identity_provider()
    cognito.set_password(user["email"], password, force_change=False)
    logger.info("Account activated: tenant_id=%s user_id=%s", tenant_id, user["id"])
    return {"email": user["email"]}


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
