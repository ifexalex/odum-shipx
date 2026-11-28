"""Two-person approval for irreversible or platform-wide platform actions (platform audit C-30, decision D4).

The protected actions are offboarding a tenant, changing a provider gateway's secret, and turning maintenance mode on
(plan price changes, a manual ``data_cleanup`` re-run and a tenant admin transfer join them when their routes land in
Phases 2–4; the actions are already in the schema).

When another admin can approve, a request waits for them:

    request ──► pending ──approve (a different admin)──► approved ──► executed | failed
                   │
                   ├──reject──► rejected      ├──cancel──► cancelled      └──24 h──► expired

When the requester is the only admin who could approve (decision D4's fallback), they must also type the target's
name, every active owner is emailed, and then: an offboarding is ``scheduled`` to run 24 hours later unless cancelled;
the other actions run at once. The step-up re-authentication is required either way (enforced by the routes).

A request's payload is hashed when it is made and checked before it runs, so the action executed is the one that was
approved. Secret values (a gateway key) are held encrypted and never shown; the payload approvers see has them masked.
"""

import hashlib
import json
import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from typing import Any

from shared.app_urls import MissingBaseUrlError, app_base_url
from shared.encryption import decrypt_field, encrypt_field
from shared.exceptions import (
    BusinessRuleViolationError,
    DuplicateResourceError,
    InsufficientPermissionsError,
    ResourceNotFoundError,
    SelfApprovalForbiddenError,
    ValidationError,
)
from shared.platform_audit import PlatformAuditAction, insert_platform_audit
from shared.platform_mail import send_platform_email
from shared.platform_roles import APPROVER_ROLES, PlatformPermission, PlatformRole
from shared.tenant_context import TenantContext

from . import platform_repository as prepo

logger = logging.getLogger(__name__)

APPROVAL_TTL = timedelta(hours=24)
SOLE_ADMIN_OFFBOARD_DELAY = timedelta(hours=24)


class ApprovalAction(StrEnum):
    """Actions that need a second admin (decision D4). Values match the CHECK in migration 076."""

    OFFBOARD_TENANT = "offboard_tenant"
    GATEWAY_SECRET_CHANGE = "gateway_secret_change"  # noqa: S105 - an action name, not a secret
    MAINTENANCE_ON = "maintenance_on"
    PLAN_PRICE_CHANGE = "plan_price_change"
    DATA_CLEANUP_RERUN = "data_cleanup_rerun"
    ADMIN_TRANSFER = "admin_transfer"


@dataclass(frozen=True)
class ProtectedAction:
    """One request for a protected action, as a route builds it.

    Attributes:
        action: Which protected action.
        target_label: What it acts on (a tenant id, a gateway kind); one open request per action and label.
        summary: One line for approvers and owners, e.g. ``Offboard Acme Freight``.
        confirm_text: What the sole admin must type to confirm (a slug, a gateway kind).
        payload: Everything the executor needs except secrets; shown to approvers.
        secret: Secret values the executor needs; encrypted at rest, never shown.
        target_tenant_id: The tenant affected, if any.
        reason: The requester's reason, if the action takes one.
    """

    action: ApprovalAction
    target_label: str
    summary: str
    confirm_text: str
    payload: dict[str, Any] = field(default_factory=dict)
    secret: dict[str, Any] | None = None
    target_tenant_id: str | None = None
    reason: str | None = None


# ---------------------------------------------------------------------------
# Executors — what each action does once approved
# ---------------------------------------------------------------------------


def _offboard(payload: dict[str, Any], _secret: dict[str, Any] | None, actor_id: str, ip: str | None) -> dict[str, Any]:
    from .tenants import offboard_tenant

    return offboard_tenant(payload["tenant_id"], actor_id=actor_id, reason=payload["reason"], ip_address=ip)


def _gateway(payload: dict[str, Any], secret: dict[str, Any] | None, actor_id: str, ip: str | None) -> dict[str, Any]:
    from .platform import update_gateway_settings

    body = {**payload["body"], **(secret or {})}
    return update_gateway_settings(payload["kind"], body, actor_id=actor_id, ip_address=ip)


def _maintenance_on(_payload: dict[str, Any], _secret: dict[str, Any] | None, actor_id: str, ip: str | None) -> dict[str, Any]:
    from .platform import update_platform_settings

    return update_platform_settings({"maintenance_mode": True}, actor_id=actor_id, ip_address=ip)


_Executor = Callable[[dict[str, Any], dict[str, Any] | None, str, str | None], dict[str, Any]]
_EXECUTORS: dict[str, _Executor] = {
    ApprovalAction.OFFBOARD_TENANT: _offboard,
    ApprovalAction.GATEWAY_SECRET_CHANGE: _gateway,
    ApprovalAction.MAINTENANCE_ON: _maintenance_on,
}


# ---------------------------------------------------------------------------
# Requesting
# ---------------------------------------------------------------------------


def request_protected_action(
    ctx: TenantContext,
    protected: ProtectedAction,
    *,
    confirm: str | None,
    ip_address: str | None = None,
) -> dict[str, Any]:
    """Ask for a protected action; return ``{"outcome", "approval", "result"?}``.

    ``outcome`` is ``pending_approval`` (another admin must approve), ``scheduled`` (sole-admin offboarding, runs in
    24 hours) or ``executed`` (sole-admin, ran now; ``result`` is the action's own response).

    Raises:
        DuplicateResourceError: The same action on the same target is already awaiting a decision.
        ValidationError: Sole admin, and ``confirm`` does not match the target.
    """
    if not ctx.platform_user_id:
        raise InsufficientPermissionsError("Only platform admins in the directory can request this.")
    if protected.action not in _EXECUTORS:
        raise BusinessRuleViolationError(f"{protected.action} cannot be requested yet", rule_id="APPROVAL_ACTION_UNAVAILABLE")
    if prepo.find_open_approval(protected.action, protected.target_label):
        raise DuplicateResourceError("approval request", protected.summary)

    approvers = [
        a
        for a in prepo.list_active_users_with_roles(sorted(r.value for r in APPROVER_ROLES))
        if str(a["id"]) != ctx.platform_user_id
    ]
    now = datetime.now(UTC)
    values = _row_values(ctx, protected, now)

    if approvers:
        approval = prepo.insert_approval({**values, "status": "pending", "execute_after": None})
        _audit(PlatformAuditAction.APPROVAL_REQUESTED, ctx.user_id, approval, ip_address)
        _email(
            approvers,
            f"Approval needed: {protected.summary}",
            f"{approval['requested_by_name']} asked to: {protected.summary}.\n"
            f"Reason: {protected.reason or 'none given'}\n\n"
            f"A second platform admin must approve it before it runs. It expires in 24 hours.\n"
            f"Review it: {_console_url()}\n",
        )
        return {"outcome": "pending_approval", "approval": approval}

    _check_confirmation(protected, confirm)
    owners = prepo.list_active_users_with_roles([PlatformRole.OWNER.value])

    if protected.action == ApprovalAction.OFFBOARD_TENANT:
        values["execute_after"] = now + SOLE_ADMIN_OFFBOARD_DELAY
        approval = prepo.insert_approval({**values, "status": "scheduled"})
        _audit(PlatformAuditAction.APPROVAL_SCHEDULED, ctx.user_id, approval, ip_address)
        _email(
            owners,
            f"Scheduled: {protected.summary}",
            f"{approval['requested_by_name']} scheduled: {protected.summary}.\nReason: {protected.reason or 'none given'}\n\n"
            f"No other platform admin could approve it, so it runs in 24 hours unless cancelled.\n"
            f"Cancel it: {_console_url()}\n",
        )
        return {"outcome": "scheduled", "approval": approval}

    approval = prepo.insert_approval({**values, "status": "pending", "execute_after": None})
    _audit(PlatformAuditAction.APPROVAL_REQUESTED, ctx.user_id, approval, ip_address)
    claimed = prepo.transition_approval(
        str(approval["id"]), ["pending"], "approved", decision_note="Sole platform admin: confirmed by typing the target"
    )
    if claimed is None:
        raise BusinessRuleViolationError("This request was already decided", rule_id="APPROVAL_ALREADY_DECIDED")
    _email(
        owners,
        f"Done by the sole admin: {protected.summary}",
        f"{approval['requested_by_name']} did: {protected.summary}, with no second approver available.\n"
        f"See the approvals log: {_console_url()}\n",
    )
    outcome = _execute(claimed, actor_id=ctx.user_id, ip_address=ip_address)
    return {"outcome": "executed", **outcome}


def _row_values(ctx: TenantContext, protected: ProtectedAction, now: datetime) -> dict[str, Any]:
    secret_blob = json.dumps(protected.secret, sort_keys=True) if protected.secret else None
    return {
        "action": protected.action.value,
        "target_tenant_id": protected.target_tenant_id,
        "target_label": protected.target_label,
        "payload": json.dumps({**protected.payload, "summary": protected.summary}, default=str),
        "secret_payload": encrypt_field(secret_blob) if secret_blob else None,
        "payload_hash": _payload_hash(protected.action.value, protected.target_label, protected.payload, protected.secret),
        "reason": protected.reason,
        "requested_by": ctx.platform_user_id,
        "expires_at": now + APPROVAL_TTL,
    }


def _payload_hash(action: str, target_label: str, payload: dict[str, Any], secret: dict[str, Any] | None) -> str:
    canonical = json.dumps(
        {"action": action, "target": target_label, "payload": payload, "secret": secret or {}},
        sort_keys=True,
        default=str,
        separators=(",", ":"),
    )
    return hashlib.sha256(canonical.encode()).hexdigest()


def _check_confirmation(protected: ProtectedAction, confirm: str | None) -> None:
    if (confirm or "").strip().lower() != protected.confirm_text.strip().lower():
        raise ValidationError(
            f'No other platform admin can approve this. Type "{protected.confirm_text}" to confirm.',
            field_errors={"confirm": f"Type {protected.confirm_text} to confirm"},
        )


# ---------------------------------------------------------------------------
# Deciding
# ---------------------------------------------------------------------------


def list_approvals(status: str | None, limit: int) -> list[dict[str, Any]]:
    """Approvals for the console, newest first, payload hash left out."""
    return [_public(row) for row in prepo.list_approvals(status, limit)]


def get_approval(approval_id: str) -> dict[str, Any]:
    """One approval for the console."""
    row = prepo.get_approval(approval_id)
    if row is None:
        raise ResourceNotFoundError("approval", approval_id)
    return _public(row)


def approve(ctx: TenantContext, approval_id: str, note: str | None, ip_address: str | None = None) -> dict[str, Any]:
    """A second admin approves; the action runs now. Returns ``{"approval", "result"?}``.

    Raises:
        SelfApprovalForbiddenError: The caller made the request.
        BusinessRuleViolationError: It is no longer pending, or it expired.
    """
    approval = _load_pending(approval_id)
    if str(approval["requested_by"]) == ctx.platform_user_id:
        raise SelfApprovalForbiddenError()
    claimed = prepo.transition_approval(
        approval_id, ["pending"], "approved", decided_by=ctx.platform_user_id, decision_note=note, decided=True
    )
    if claimed is None:
        raise BusinessRuleViolationError("This request was already decided", rule_id="APPROVAL_ALREADY_DECIDED")
    _audit(PlatformAuditAction.APPROVAL_APPROVED, ctx.user_id, claimed, ip_address)
    requester = prepo.get_platform_user(str(claimed["requested_by"])) or {}
    # The action runs as the requester: they asked for it; the approval row and its audit name who agreed.
    return _execute(claimed, actor_id=str(requester.get("subject") or ctx.user_id), ip_address=ip_address)


def reject(ctx: TenantContext, approval_id: str, note: str | None, ip_address: str | None = None) -> dict[str, Any]:
    """A second admin turns the request down."""
    approval = _load_pending(approval_id)
    if str(approval["requested_by"]) == ctx.platform_user_id:
        raise BusinessRuleViolationError("Cancel your own request instead of rejecting it", rule_id="APPROVAL_SELF_REJECT")
    rejected = prepo.transition_approval(
        approval_id, ["pending"], "rejected", decided_by=ctx.platform_user_id, decision_note=note, decided=True
    )
    if rejected is None:
        raise BusinessRuleViolationError("This request was already decided", rule_id="APPROVAL_ALREADY_DECIDED")
    _audit(PlatformAuditAction.APPROVAL_REJECTED, ctx.user_id, rejected, ip_address)
    return {"approval": _public(rejected)}


def cancel(ctx: TenantContext, approval_id: str, note: str | None, ip_address: str | None = None) -> dict[str, Any]:
    """The requester, or an owner, withdraws a pending or scheduled request."""
    approval = prepo.get_approval(approval_id)
    if approval is None:
        raise ResourceNotFoundError("approval", approval_id)
    is_requester = str(approval["requested_by"]) == ctx.platform_user_id
    if not is_requester and not ctx.has_platform_permission(PlatformPermission.ADMINS):
        raise InsufficientPermissionsError("Only the requester or an owner can cancel this request.")
    cancelled = prepo.transition_approval(
        approval_id,
        ["pending", "scheduled"],
        "cancelled",
        decided_by=None if is_requester else ctx.platform_user_id,
        decision_note=note,
        decided=True,
    )
    if cancelled is None:
        raise BusinessRuleViolationError("This request is no longer open", rule_id="APPROVAL_NOT_OPEN")
    _audit(PlatformAuditAction.APPROVAL_CANCELLED, ctx.user_id, cancelled, ip_address)
    return {"approval": _public(cancelled)}


def _load_pending(approval_id: str) -> dict[str, Any]:
    approval = prepo.get_approval(approval_id)
    if approval is None:
        raise ResourceNotFoundError("approval", approval_id)
    if approval["status"] != "pending":
        raise BusinessRuleViolationError(f"This request is {approval['status']}", rule_id="APPROVAL_NOT_PENDING")
    if approval["expires_at"] <= datetime.now(UTC):
        expired = prepo.transition_approval(approval_id, ["pending"], "expired")
        if expired:
            _audit(PlatformAuditAction.APPROVAL_EXPIRED, None, expired, None)
        raise BusinessRuleViolationError("This request expired", rule_id="APPROVAL_EXPIRED")
    return approval


# ---------------------------------------------------------------------------
# Running
# ---------------------------------------------------------------------------


def _execute(claimed: dict[str, Any], *, actor_id: str, ip_address: str | None) -> dict[str, Any]:
    """Run an ``approved`` (or due ``scheduled``) request and record how it ended."""
    approval_id = str(claimed["id"])
    full = prepo.get_approval(approval_id, with_secret=True)
    if full is None:
        raise ResourceNotFoundError("approval", approval_id)
    payload = {k: v for k, v in (full["payload"] or {}).items() if k != "summary"}
    secret = json.loads(decrypt_field(full["secret_payload"]) or "null") if full.get("secret_payload") else None
    if _payload_hash(full["action"], full["target_label"], payload, secret) != full["payload_hash"]:
        failed = prepo.transition_approval(
            approval_id, ["approved", "scheduled"], "failed", error="Payload changed after the request"
        )
        _audit(PlatformAuditAction.APPROVAL_FAILED, actor_id, failed or full, ip_address)
        raise BusinessRuleViolationError("The request changed after it was made; it was not run", rule_id="APPROVAL_TAMPERED")

    try:
        result = _EXECUTORS[full["action"]](payload, secret, actor_id, ip_address)
    except Exception as exc:
        message = getattr(exc, "message", None) or type(exc).__name__
        failed = prepo.transition_approval(approval_id, ["approved", "scheduled"], "failed", error=str(message)[:500])
        _audit(PlatformAuditAction.APPROVAL_FAILED, actor_id, failed or full, ip_address)
        raise
    executed = prepo.transition_approval(approval_id, ["approved", "scheduled"], "executed", executed=True)
    _audit(PlatformAuditAction.APPROVAL_EXECUTED, actor_id, executed or full, ip_address)
    return {"approval": _public(executed or full), "result": result}


def run_due() -> dict[str, int]:
    """Scheduled job: run sole-admin offboardings whose 24 hours are up, and expire undecided requests."""
    executed = failed = expired = 0
    for approval in prepo.list_due_scheduled_approvals():
        requester = prepo.get_platform_user(str(approval["requested_by"])) or {}
        try:
            _execute(approval, actor_id=str(requester.get("subject") or ""), ip_address=None)
            executed += 1
        except Exception:
            logger.exception("Scheduled platform approval %s failed", approval["id"])
            failed += 1
    for approval in prepo.list_expired_pending_approvals():
        moved = prepo.transition_approval(str(approval["id"]), ["pending"], "expired")
        if moved:
            _audit(PlatformAuditAction.APPROVAL_EXPIRED, None, moved, None)
            expired += 1
    return {"executed": executed, "failed": failed, "expired": expired}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _public(row: dict[str, Any]) -> dict[str, Any]:
    hidden = {"payload_hash", "secret_payload"}
    return {k: v for k, v in row.items() if k not in hidden}


def _console_url() -> str:
    """Link to the console's approvals page; plain words when no base URL is configured (an email never blocks)."""
    try:
        return f"{app_base_url()}/platform/approvals"
    except MissingBaseUrlError:
        return "the Approvals page of the ShipX platform console"


def _email(recipients: list[dict[str, Any]], subject: str, body: str) -> None:
    for person in recipients:
        if person.get("email"):
            send_platform_email(str(person["email"]), subject, body)


def _audit(action: PlatformAuditAction, actor_id: str | None, approval: dict[str, Any], ip_address: str | None) -> None:
    try:
        insert_platform_audit(
            action=action,
            actor_id=actor_id,
            target_tenant_id=str(approval["target_tenant_id"]) if approval.get("target_tenant_id") else None,
            details={
                "approval_id": str(approval["id"]),
                "approval_action": approval["action"],
                "target": approval["target_label"],
                "status": approval["status"],
            },
            ip_address=ip_address,
        )
    except Exception as exc:
        logger.warning("Platform audit insert failed for %s: %s", action, exc)
