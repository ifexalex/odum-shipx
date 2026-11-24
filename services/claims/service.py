"""Business logic for the Claims service.

Handles damage claim lifecycle, S3 presigned upload URL generation,
claim resolution with approval threshold enforcement, and logging of
missing/seized items.
"""

import logging
import re
from datetime import UTC, date, datetime
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

from services.refunds import repository as refund_repo
from shared import uploads
from shared.audit import log_audit
from shared.billing_money import adjust_billing_and_refund_overpayment
from shared.db import tenant_transaction
from shared.events import publish_event
from shared.exceptions import (
    ApprovalThresholdExceededError,
    BusinessRuleViolationError,
    IllegalTransitionError,
    InsufficientPermissionsError,
    ResourceNotFoundError,
    ServiceUnavailableError,
)
from shared.fx_rate import get_effective_dollar_rate
from shared.notifications import enqueue_notifications
from shared.providers import get_storage_provider
from shared.staff_notifications import notify_staff
from shared.tenant_context import UserRole

from . import repository as repo
from .models import MissingItemStatus, SeizedItemStatus

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# S3 configuration
# ---------------------------------------------------------------------------

_URL_EXPIRY = 3600  # 1 hour
_MAX_EVIDENCE_FILES_PER_CLAIM = 20
_SAFE_DISPOSITION_RE = re.compile(r"[^A-Za-z0-9._-]+")

# ---------------------------------------------------------------------------
# Damage claim state machine
# ---------------------------------------------------------------------------

# Valid source states for resolve_claim
_RESOLVABLE_STATES = {"under_inspection", "inspection_complete", "pending_resolution"}

# Container statuses where filing a damage claim is disallowed: before cargo
# reaches Nigeria, or when the container was cancelled.
_PRE_ARRIVAL_STATUSES = {"loading", "sealed", "in_transit", "cancelled"}

# Claim statuses where uploading/confirming new evidence is no longer permitted.
_CLOSED_CLAIM_STATUSES = {"resolved", "closed"}


def _check_staff_threshold(tenant_id: str, amount_ngn: Decimal, ctx: Any) -> str:
    """Enforce staff USD approval limit (fail-closed) and return approval_level."""
    try:
        threshold_cfg = repo.get_tenant_config_value(tenant_id, "refund_threshold_usd") or {}
        staff_limit_usd = Decimal(str(threshold_cfg.get("staff_limit", 50)))
        dollar_rate = Decimal(str(get_effective_dollar_rate(tenant_id)["rate"]))
    except Exception as exc:
        logger.error("Could not load claim approval threshold for tenant %s: %s", tenant_id, exc)
        raise ServiceUnavailableError("Unable to verify staff approval limit — please retry") from exc

    if (
        not staff_limit_usd.is_finite()
        or staff_limit_usd < Decimal("0")
        or not dollar_rate.is_finite()
        or dollar_rate <= Decimal("0")
    ):
        raise ServiceUnavailableError("Invalid approval threshold configuration")

    amount_usd = amount_ngn / dollar_rate
    if amount_usd > staff_limit_usd:
        if not ctx.has_role(UserRole.TENANT_ADMIN):
            raise ApprovalThresholdExceededError(
                f"Amount of \u20a6{amount_ngn} (~${amount_usd:.2f}) exceeds staff limit of "
                f"${staff_limit_usd}; tenant_admin approval required",
                staff_limit_usd=float(staff_limit_usd),
                staff_limit_ngn=float(staff_limit_usd * dollar_rate),
                dollar_rate=float(dollar_rate),
                amount_ngn=float(amount_ngn),
            )
        return "tenant_admin"
    return "nigeria_staff"


# ---------------------------------------------------------------------------
# Damage claim operations
# ---------------------------------------------------------------------------


def file_claim(
    tenant_id: str,
    req: Any,
    actor_id: str,
    ctx: Any,
    customer_id_override: str | None = None,
    request_id: str = "",
    ip_address: str | None = None,
) -> dict[str, Any]:
    """File a new damage claim.

    For CUSTOMER role: customer_id is derived from ctx.user_id.
    For staff roles: customer_id_override (from request body) is used.
    """
    is_customer = ctx.is_customer_only
    if is_customer:
        customer = repo.get_customer_by_user_id(tenant_id, ctx.user_id)
        if not customer:
            raise ResourceNotFoundError("customer", ctx.user_id)
        customer_id = str(customer["id"])
    else:
        if not customer_id_override:
            raise BusinessRuleViolationError(
                "customer_id is required when filing a claim on behalf of a customer",
                rule_id="MISSING_CUSTOMER_ID",
            )
        customer_id = customer_id_override

    cartons_affected = [str(t) for t in req.cartons_affected] if isinstance(req.cartons_affected, list) else []

    container_id = repo.resolve_container_id(tenant_id, req.container_id)
    if not container_id:
        raise ResourceNotFoundError("container", req.container_id)
    if is_customer and not repo.customer_has_cargo_in_container(tenant_id, customer_id, container_id):
        # Without this, a customer could file a claim against any container
        # in the tenant by guessing/enumerating numbers, not only their own.
        raise ResourceNotFoundError("container", req.container_id)

    container_status = repo.get_container_status(tenant_id, container_id)
    if container_status in _PRE_ARRIVAL_STATUSES:
        raise BusinessRuleViolationError(
            "A claim can't be filed for a container that has not arrived or has been cancelled.",
            rule_id="CONTAINER_NOT_ARRIVED",
        )

    reference = repo.get_next_claim_reference(tenant_id)
    claim = repo.create_damage_claim(
        tenant_id,
        {
            "tenant_id": tenant_id,
            "customer_id": customer_id,
            "container_id": container_id,
            "cartons_affected": cartons_affected,
            "description": req.description,
            "status": "filed",
            "submitted_by": actor_id,
            "reference": reference,
        },
    )
    if claim is None:
        raise RuntimeError("create_damage_claim returned None unexpectedly")

    log_audit(
        tenant_id=tenant_id,
        entity_type="damage_claim",
        entity_id=str(claim["id"]),
        action="CREATE",
        actor_id=actor_id,
        actor_role=str(ctx.role),
        after_state={"status": "filed", "container_id": container_id},
        ip_address=ip_address,
    )

    publish_event(
        source="logistics.claims",
        detail_type="DamageClaimFiled",
        tenant_id=tenant_id,
        payload={
            "claim_id": str(claim["id"]),
            "customer_id": customer_id,
            "container_id": container_id,
        },
        request_id=request_id,
    )

    if is_customer:
        for role in ("nigeria_office_staff", "tenant_admin"):
            notify_staff(
                tenant_id=tenant_id,
                event_type="damage_claim_filed",
                entity_type="damage_claim",
                entity_id=str(claim["id"]),
                title="New damage claim filed",
                body=f"Claim {reference} was filed and needs inspection.",
                target_role=role,
            )

    return _fmt_claim(claim)


def get_claim_stats(tenant_id: str) -> dict[str, int]:
    """Tenant-wide claim aggregates for the list stats row + status chips."""
    return repo.get_claim_stats(tenant_id)


def list_claims(
    tenant_id: str,
    ctx: Any,
    filters: dict[str, Any],
    limit: int,
    cursor: dict[str, Any] | None,
    sort_field: str = "created_at",
    sort_direction: str = "DESC",
) -> tuple[list[dict[str, Any]], str | None, bool]:
    if ctx.is_customer_only:
        customer = repo.get_customer_by_user_id(tenant_id, ctx.user_id)
        if not customer:
            return [], None, False
        filters = {**filters, "customer_id": str(customer["id"])}

    rows, next_cursor, has_more = repo.list_damage_claims(
        tenant_id, filters, limit, cursor, sort_field=sort_field, sort_direction=sort_direction
    )
    return [_fmt_claim(r) for r in rows], next_cursor, has_more


_EVIDENCE_LINK_EXPIRY = 300  # seconds


def _claim_for_actor(tenant_id: str, claim_id: str, ctx: Any) -> dict[str, Any]:
    """The claim, if the caller may see it: staff see the tenant's claims, a customer only their own.

    Another customer's claim is a 404, the same as one that does not exist: a 403 would confirm that the id is real.

    Raises:
        ResourceNotFoundError: No such claim in the tenant, or a customer's claim that is not theirs.
    """
    claim = repo.get_damage_claim_by_id(tenant_id, claim_id)
    if not claim:
        raise ResourceNotFoundError("damage_claim", claim_id)
    if ctx.is_customer_only:
        customer = repo.get_customer_by_user_id(tenant_id, ctx.user_id)
        if not customer or str(customer["id"]) != str(claim["customer_id"]):
            raise ResourceNotFoundError("damage_claim", claim_id)
    return claim


def get_claim(tenant_id: str, claim_id: str, ctx: Any) -> dict[str, Any]:
    """One claim, with its evidence, the outcome and the refund it produced (audit UX-07).

    A customer reads only their own. Another customer's claim is a 404, the same as one that does not exist: a 403
    would confirm that the id is real.
    """
    claim = _claim_for_actor(tenant_id, claim_id, ctx)
    canonical_id = str(claim["id"])
    return {
        **_fmt_claim(claim),
        "evidence": _evidence_links(tenant_id, canonical_id),
        **_fmt_outcome(repo.get_claim_outcome(tenant_id, canonical_id), for_customer=ctx.is_customer_only),
    }


def _evidence_links(tenant_id: str, claim_id: str) -> list[dict[str, Any]]:
    """The claim's evidence files, each with a short-lived download link.

    A link is made only for a key that is exactly this claim's prefix plus one filename (that is what an upload
    produces), so a bad row, even one that starts with the right prefix and then climbs out of it with `..`, can never
    turn into a link to another tenant's or another claim's file. A file whose link cannot be made is still listed,
    without one.
    """
    prefix = f"{tenant_id}/claims/{claim_id}/"
    storage = get_storage_provider()
    files: list[dict[str, Any]] = []
    for row in repo.list_claim_evidence(claim_id):
        key = str(row["file_key"])
        name = key[len(prefix) :]
        if not key.startswith(prefix) or not name or "/" in name or name in {".", ".."}:
            logger.warning("Claim evidence key outside the claim's prefix, skipped (claim_id=%s)", claim_id)
            continue
        url: str | None = None
        safe_file_name = _SAFE_DISPOSITION_RE.sub("_", str(row.get("file_name") or "evidence"))[:120] or "evidence"
        try:
            url = storage.presigned_get_url(
                key,
                expires_in=_EVIDENCE_LINK_EXPIRY,
                response_content_disposition=f'attachment; filename="{safe_file_name}"',
            )
        except Exception:
            logger.warning("Could not presign a claim evidence download (claim_id=%s)", claim_id, exc_info=True)
        files.append(
            {
                "id": str(row["id"]),
                "file_name": row["file_name"],
                "file_type": row["file_type"],
                "file_size_bytes": row.get("file_size_bytes"),
                "uploaded_at": row.get("created_at"),
                "download_url": url,
            }
        )
    return files


# Decisions that go against the customer. They are told why (owner decision, 2026-11-17); when the decision is in
# their favour the reason staff typed stays internal.
_UNFAVOURABLE_RESOLUTIONS = frozenset({"no_action"})


def _fmt_outcome(row: dict[str, Any] | None, *, for_customer: bool) -> dict[str, Any]:
    """What was decided and the refund's status. Never the approver or the approval level.

    `reason` is the explanation staff typed. Staff always see it. A customer sees it only when the decision went
    against them (the claim was closed without a payout); otherwise it is None.
    """
    if row is None:
        return {"resolution": None, "refund": None}
    show_reason = not for_customer or row["resolution_type"] in _UNFAVOURABLE_RESOLUTIONS
    resolution = {
        "resolution_type": row["resolution_type"],
        "amount_ngn": row.get("resolution_amount_ngn"),
        "discount_percentage": row.get("discount_percentage"),
        "resolved_at": row.get("resolved_at"),
        "reason": (row.get("reason") or None) if show_reason else None,
    }
    refund = (
        {"id": str(row["refund_id"]), "status": row["refund_status"], "amount_ngn": row.get("refund_amount_ngn")}
        if row.get("refund_id")
        else None
    )
    return {"resolution": resolution, "refund": refund}


def start_inspection(
    tenant_id: str,
    claim_id: str,
    req: Any,
    actor_id: str,
    ip_address: str | None = None,
    actor_role: str = str(UserRole.NIGERIA_OFFICE_STAFF),
) -> dict[str, Any]:
    claim = repo.get_damage_claim_by_id(tenant_id, claim_id)
    if not claim:
        raise ResourceNotFoundError("damage_claim", claim_id)

    if claim["status"] != "filed":
        raise IllegalTransitionError(
            entity="damage_claim",
            current_state=claim["status"],
            requested_state="under_inspection",
            allowed=["filed"],
        )

    inspection_method = req.inspection_method.value if hasattr(req.inspection_method, "value") else str(req.inspection_method)
    updated = repo.update_claim_status(
        tenant_id,
        claim_id,
        "under_inspection",
        extra={
            "inspection_method": inspection_method,
            "reviewed_by": actor_id,
        },
        allowed_from=["filed"],
    )
    if updated is None:
        raise IllegalTransitionError(
            entity="damage_claim",
            current_state="changed by another request",
            requested_state="under_inspection",
            allowed=["filed"],
        )

    log_audit(
        tenant_id=tenant_id,
        entity_type="damage_claim",
        entity_id=claim_id,
        action="STATUS_CHANGE",
        actor_id=actor_id,
        actor_role=actor_role,
        before_state={"status": "filed"},
        after_state={"status": "under_inspection"},
        ip_address=ip_address,
    )
    _notify_customer_claim_update(tenant_id, updated, "under_inspection")
    return _fmt_claim(updated)


def resolve_claim(
    tenant_id: str,
    claim_id: str,
    req: Any,
    actor_id: str,
    ctx: Any,
    request_id: str = "",
    ip_address: str | None = None,
) -> dict[str, Any]:
    claim = repo.get_damage_claim_by_id(tenant_id, claim_id)
    if not claim:
        raise ResourceNotFoundError("damage_claim", claim_id)

    if claim["status"] not in _RESOLVABLE_STATES:
        raise IllegalTransitionError(
            entity="damage_claim",
            current_state=claim["status"],
            requested_state="resolved",
            allowed=list(_RESOLVABLE_STATES),
        )

    resolution_type = req.resolution_type.value if hasattr(req.resolution_type, "value") else str(req.resolution_type)
    settlement_usd = getattr(req, "settlement_amount_usd", None)
    raw_amount_ngn = getattr(req, "amount_ngn", None)
    raw_amount_usd = getattr(req, "amount_usd", None)
    raw_discount_pct = getattr(req, "discount_percentage", None)
    reason_text = (getattr(req, "reason", None) or getattr(req, "notes", None) or "").strip()

    # Resolve the effective monetary amount in NGN across both old and new request shapes.
    resolved_amount_ngn: Decimal | None = None
    if isinstance(settlement_usd, Decimal):
        if settlement_usd <= Decimal("0"):
            raise BusinessRuleViolationError("Settlement amount must be greater than 0", rule_id="POSITIVE_AMOUNT_REQUIRED")
        dollar_rate = Decimal(str(get_effective_dollar_rate(tenant_id)["rate"]))
        if not dollar_rate.is_finite() or dollar_rate <= Decimal("0"):
            raise ServiceUnavailableError("Unable to resolve exchange rate for claim settlement")
        resolved_amount_ngn = (settlement_usd * dollar_rate).quantize(Decimal("0.01"), ROUND_HALF_UP)
    elif isinstance(raw_amount_ngn, Decimal):
        resolved_amount_ngn = raw_amount_ngn
    elif isinstance(raw_amount_usd, Decimal) and raw_amount_usd > Decimal("0"):
        dollar_rate = Decimal(str(get_effective_dollar_rate(tenant_id)["rate"]))
        if not dollar_rate.is_finite() or dollar_rate <= Decimal("0"):
            raise ServiceUnavailableError("Unable to resolve exchange rate for claim settlement")
        resolved_amount_ngn = (raw_amount_usd * dollar_rate).quantize(Decimal("0.01"), ROUND_HALF_UP)

    discount_pct: Decimal | None = raw_discount_pct if isinstance(raw_discount_pct, Decimal) else None

    if resolution_type in ("refund", "compensation") and (resolved_amount_ngn is None or resolved_amount_ngn <= Decimal("0")):
        raise BusinessRuleViolationError(
            f"A positive settlement amount is required for resolution_type '{resolution_type}'",
            rule_id="POSITIVE_AMOUNT_REQUIRED",
        )

    # Resolve linked invoice (used for discount application and refund linkage).
    billing = None
    if claim.get("billing_id"):
        billing = repo.get_billing_by_id(tenant_id, str(claim["billing_id"]))
    elif resolution_type == "discount" and claim.get("container_id"):
        billing = repo.get_billing_for_claim(tenant_id, str(claim["customer_id"]), str(claim["container_id"]))
    billing_id = str(billing["id"]) if billing else None

    # For discount resolution, compute the exact NGN reduction so threshold and invoice adjustment agree.
    discount_ngn = Decimal("0")
    if resolution_type == "discount":
        if (discount_pct is None or discount_pct <= Decimal("0")) and (
            resolved_amount_ngn is None or resolved_amount_ngn <= Decimal("0")
        ):
            raise BusinessRuleViolationError(
                "A positive discount_percentage or amount_ngn is required for discount resolution",
                rule_id="POSITIVE_DISCOUNT_REQUIRED",
            )
        if resolved_amount_ngn is not None and resolved_amount_ngn > Decimal("0"):
            discount_ngn = resolved_amount_ngn
        elif billing is not None and discount_pct is not None:
            invoice_total = Decimal(str(billing.get("total_ngn") or 0))
            discount_ngn = (invoice_total * discount_pct / Decimal("100")).quantize(Decimal("0.01"), ROUND_HALF_UP)
            resolved_amount_ngn = discount_ngn
        if billing is None:
            raise BusinessRuleViolationError(
                "No active invoice found for this claim to apply a discount",
                rule_id="NO_BILLING_FOR_DISCOUNT",
            )
        if billing.get("status") in ("cancelled", "waived"):
            raise BusinessRuleViolationError(
                f"Cannot apply a claim discount to a {billing['status']} invoice",
                rule_id="INVALID_BILLING_STATUS",
            )

    # Enforce staff approval threshold on ALL financial resolutions (refund, compensation,
    # discount, and any settlement_amount_usd payout).
    approval_level = "nigeria_staff"
    financial_ngn = discount_ngn if resolution_type == "discount" else (resolved_amount_ngn or Decimal("0"))
    if resolution_type != "no_action" and financial_ngn > Decimal("0"):
        approval_level = _check_staff_threshold(tenant_id, financial_ngn, ctx)

    # Status change, refund request / invoice discount, and claim_resolution commit atomically.
    now = datetime.now(UTC)
    with tenant_transaction(tenant_id):
        updated = repo.update_claim_status(
            tenant_id,
            claim_id,
            "resolved",
            extra={"reviewed_by": actor_id, "reviewed_at": now},
            allowed_from=sorted(_RESOLVABLE_STATES),
        )
        if updated is None:
            raise IllegalTransitionError(
                entity="damage_claim",
                current_state="changed by another request",
                requested_state="resolved",
                allowed=sorted(_RESOLVABLE_STATES),
            )

        refund_request_id = None
        if resolution_type in ("refund", "compensation"):
            refund_row = repo.create_refund_request_for_claim(
                tenant_id,
                {
                    "tenant_id": tenant_id,
                    "customer_id": str(claim["customer_id"]),
                    "billing_id": billing_id,
                    "damage_claim_id": claim_id,
                    "amount_ngn": resolved_amount_ngn,
                    "reason": f"Damage claim resolution — {reason_text}",
                    "requested_by": actor_id,
                },
            )
            refund_request_id = str(refund_row["id"]) if refund_row else None
        elif resolution_type == "discount" and billing_id and discount_ngn > Decimal("0"):
            adjust_billing_and_refund_overpayment(
                tenant_id,
                billing_id,
                -discount_ngn,
                f"Damage claim {claim.get('reference') or claim_id} discount — {reason_text}",
                refund_type="overpayment",
            )

        resolution = repo.create_claim_resolution(
            tenant_id,
            {
                "tenant_id": tenant_id,
                "damage_claim_id": claim_id,
                "resolution_type": resolution_type,
                "resolution_amount_ngn": resolved_amount_ngn,
                "approval_level": approval_level,
                "approved_by": actor_id,
                "notes": reason_text,
                "refund_request_id": refund_request_id,
                "discount_percentage": discount_pct,
            },
        )
        if resolution is None:
            raise RuntimeError("create_claim_resolution returned None unexpectedly")

    publish_event(
        source="logistics.claims",
        detail_type="DamageClaimResolved",
        tenant_id=tenant_id,
        payload={
            "claim_id": claim_id,
            "resolution_type": resolution_type,
            "approval_level": approval_level,
        },
        request_id=request_id,
    )

    log_audit(
        tenant_id=tenant_id,
        entity_type="damage_claim",
        entity_id=claim_id,
        action="STATUS_CHANGE",
        actor_id=actor_id,
        actor_role=str(ctx.role),
        before_state={"status": claim["status"]},
        after_state={
            "status": "resolved",
            "resolution_type": resolution_type,
            "approval_level": approval_level,
            **({"amount_ngn": str(resolved_amount_ngn)} if resolved_amount_ngn is not None else {}),
        },
        ip_address=ip_address,
    )

    _notify_customer_claim_update(tenant_id, updated, "resolved", request_id)
    return {
        **_fmt_claim(updated),
        "resolution": _fmt_resolution(resolution),
        "resolution_type": resolution_type,
        "refund_request_id": refund_request_id,
    }


# ---------------------------------------------------------------------------
# Presigned URL generation
# ---------------------------------------------------------------------------


def generate_presigned_url(
    tenant_id: str,
    claim_id: str,
    filename: str,
    content_type: str,
    ctx: Any,
    size_bytes: object = None,
) -> dict[str, Any]:
    """Presign an evidence upload for a claim the caller may see, and record it unconfirmed.

    The row stays hidden until ``confirm_evidence``: the browser uploads, then confirms.

    Raises:
        ResourceNotFoundError: The claim is not the tenant's, or not this customer's.
        BusinessRuleViolationError: ``INVALID_CONTENT_TYPE``, ``FILE_TOO_LARGE``,
            ``CLAIM_CLOSED_FOR_EVIDENCE``, or ``EVIDENCE_LIMIT_REACHED``.
    """
    uploads.EVIDENCE.check(content_type, size_bytes)
    claim = _claim_for_actor(tenant_id, claim_id, ctx)
    if claim.get("status") in _CLOSED_CLAIM_STATUSES:
        raise BusinessRuleViolationError(
            f"Cannot upload evidence to a {claim['status']} claim",
            rule_id="CLAIM_CLOSED_FOR_EVIDENCE",
        )
    canonical_claim_id = str(claim["id"])
    if repo.count_claim_evidence(canonical_claim_id) >= _MAX_EVIDENCE_FILES_PER_CLAIM:
        raise BusinessRuleViolationError(
            f"Maximum of {_MAX_EVIDENCE_FILES_PER_CLAIM} evidence files per claim reached",
            rule_id="EVIDENCE_LIMIT_REACHED",
        )

    upload = uploads.presign_upload(
        uploads.EVIDENCE, tenant_id, ("claims", canonical_claim_id), filename, content_type, size_bytes
    )
    file_key = upload.key

    evidence = repo.create_claim_evidence(
        {
            "damage_claim_id": canonical_claim_id,
            "file_key": file_key,
            "file_name": upload.filename,
            "file_type": content_type,
            "file_size_bytes": None,
            "uploaded_by": ctx.user_id,
        }
    )

    return {
        **upload.as_response(),
        "evidence_id": str(evidence["id"]) if evidence else None,
        "file_key": file_key,
    }


def confirm_evidence(tenant_id: str, claim_id: str, evidence_id: str, ctx: Any, ip_address: str | None = None) -> dict[str, Any]:
    """Confirm an evidence upload landed: check its stored size, then list it on the claim.

    A file over the limit (possible on Azure, where the upload URL cannot bind the length) is deleted with its row.
    Confirming an already confirmed file returns it unchanged.

    Raises:
        ResourceNotFoundError: The claim or the evidence row is not the caller's to confirm.
        BusinessRuleViolationError: ``UPLOAD_NOT_FOUND``, ``FILE_TOO_LARGE``, or ``CLAIM_CLOSED_FOR_EVIDENCE``.
    """
    claim = _claim_for_actor(tenant_id, claim_id, ctx)
    if claim.get("status") in _CLOSED_CLAIM_STATUSES:
        raise BusinessRuleViolationError(
            f"Cannot confirm evidence on a {claim['status']} claim",
            rule_id="CLAIM_CLOSED_FOR_EVIDENCE",
        )
    canonical_claim_id = str(claim["id"])
    evidence = repo.get_claim_evidence(canonical_claim_id, evidence_id)
    if not evidence:
        raise ResourceNotFoundError("claim_evidence", evidence_id)
    if evidence.get("confirmed_at") is None:
        try:
            size = uploads.confirm_stored_upload(uploads.EVIDENCE, str(evidence["file_key"]))
        except BusinessRuleViolationError as exc:
            if exc.rule_id == "FILE_TOO_LARGE":
                logger.warning("Claim evidence over the size limit deleted at confirmation (claim_id=%s)", canonical_claim_id)
                repo.delete_unconfirmed_claim_evidence(canonical_claim_id, evidence_id)
            raise
        evidence = repo.confirm_claim_evidence(canonical_claim_id, evidence_id, size) or evidence
        log_audit(
            tenant_id=tenant_id,
            entity_type="claim_evidence",
            entity_id=evidence_id,
            action="CREATE",
            actor_id=ctx.user_id,
            actor_role=str(ctx.role),
            after_state={"damage_claim_id": canonical_claim_id, "file_type": evidence["file_type"], "file_size_bytes": size},
            ip_address=ip_address,
        )
    return {
        "id": str(evidence["id"]),
        "file_name": evidence["file_name"],
        "file_type": evidence["file_type"],
        "file_size_bytes": evidence.get("file_size_bytes"),
        "uploaded_at": evidence.get("created_at"),
    }


# ---------------------------------------------------------------------------
# Missing / seized item list operations
# ---------------------------------------------------------------------------


def list_missing_items(
    tenant_id: str,
    filters: dict[str, Any],
    limit: int,
    cursor: dict[str, Any] | None,
) -> tuple[list[dict[str, Any]], str | None, bool]:
    rows, next_cursor, has_more = repo.list_missing_items(tenant_id, filters, limit, cursor)
    return [dict(r) for r in rows], next_cursor, has_more


def get_missing_item(tenant_id: str, item_id: str) -> dict[str, Any]:
    item = repo.get_missing_item_by_id(tenant_id, item_id)
    if not item:
        raise ResourceNotFoundError("missing_item", item_id)
    return dict(item)


def list_seized_items(
    tenant_id: str,
    filters: dict[str, Any],
    limit: int,
    cursor: dict[str, Any] | None,
) -> tuple[list[dict[str, Any]], str | None, bool]:
    rows, next_cursor, has_more = repo.list_seized_items(tenant_id, filters, limit, cursor)
    return [dict(r) for r in rows], next_cursor, has_more


def get_seized_item(tenant_id: str, item_id: str) -> dict[str, Any]:
    item = repo.get_seized_item_by_id(tenant_id, item_id)
    if not item:
        raise ResourceNotFoundError("seized_item", item_id)
    return dict(item)


# ---------------------------------------------------------------------------
# Missing item operations
# ---------------------------------------------------------------------------


def log_missing_item(
    tenant_id: str,
    req: Any,
    actor_id: str,
    ctx: Any,
    ip_address: str | None = None,
) -> dict[str, Any]:
    item = repo.create_missing_item(
        tenant_id,
        {
            "tenant_id": tenant_id,
            "manifest_id": req.manifest_id,
            "customer_id": req.customer_id,
            "carton_tags": req.carton_tags,
            "description": req.description,
            "status": "reported",
            "reported_by": actor_id,
        },
    )
    if item is None:
        raise RuntimeError("create_missing_item returned None unexpectedly")

    log_audit(
        tenant_id=tenant_id,
        entity_type="missing_item",
        entity_id=str(item["id"]),
        action="CREATE",
        actor_id=actor_id,
        actor_role=str(ctx.role),
        after_state={"customer_id": req.customer_id, "carton_tags": req.carton_tags, "status": "reported"},
        ip_address=ip_address,
    )
    # The China office is asked to record the supply and loading check, so it is told when one is logged.
    notify_staff(
        tenant_id=tenant_id,
        event_type="missing_item_logged",
        entity_type="missing_item",
        entity_id=str(item["id"]),
        title="Missing item reported",
        body=f"{len(req.carton_tags)} carton(s) reported missing. Please record the supply and loading check.",
        target_role=str(UserRole.CHINA_OFFICE_STAFF),
    )
    return _fmt_missing(item)


# What the China office may record on a missing item: that it is being looked into, or that it has been found. Deciding
# it lost (which is what owes the customer compensation) stays with the Nigeria office.
_CHINA_ITEM_STATUSES = frozenset({MissingItemStatus.investigating, MissingItemStatus.found_and_shipping})
_DECIDED_ITEM_STATUSES = frozenset({MissingItemStatus.confirmed_lost, MissingItemStatus.resolved})


def _can_reopen_compensation(tenant_id: str, existing_refund_id: Any) -> bool:
    """True when no refund is linked yet, or the previously linked refund was rejected."""
    if not existing_refund_id:
        return True
    prior = refund_repo.get_refund_request_by_id(tenant_id, str(existing_refund_id))
    return bool(prior and prior.get("status") == "rejected")


def _assert_china_may_update(item: dict[str, Any], status: str, refund_amount_ngn: Decimal | None) -> None:
    """The limits on a China office update of a missing item (audit UX-08)."""
    if refund_amount_ngn is not None:
        raise InsufficientPermissionsError("China office staff cannot set compensation on a missing item")
    if status not in _CHINA_ITEM_STATUSES:
        raise InsufficientPermissionsError("China office staff can only mark a missing item as investigating or found")
    if item["status"] in _DECIDED_ITEM_STATUSES:
        raise BusinessRuleViolationError(
            "This missing item has already been decided and can no longer be changed by the China office",
            rule_id="MISSING_ITEM_ALREADY_DECIDED",
        )


def update_missing_item(
    tenant_id: str,
    item_id: str,
    status: str,
    notes: str | None,
    actor_id: str,
    ctx: Any,
    refund_amount_ngn: Decimal | None = None,
    ip_address: str | None = None,
) -> dict[str, Any]:
    item = repo.get_missing_item_by_id(tenant_id, item_id)
    if not item:
        raise ResourceNotFoundError("missing_item", item_id)

    # Multi-role safe check: only Nigeria office staff or tenant_admin may decide/compensate.
    if not ctx.has_role(UserRole.NIGERIA_OFFICE_STAFF, UserRole.TENANT_ADMIN):
        _assert_china_may_update(item, status, refund_amount_ngn)

    current_status = item["status"]
    if current_status == MissingItemStatus.resolved:
        raise IllegalTransitionError(
            entity="missing_item",
            current_state=current_status,
            requested_state=status,
            allowed=[],
        )
    if current_status == MissingItemStatus.confirmed_lost and status not in (
        MissingItemStatus.confirmed_lost,
        MissingItemStatus.resolved,
    ):
        raise IllegalTransitionError(
            entity="missing_item",
            current_state=current_status,
            requested_state=status,
            allowed=[MissingItemStatus.confirmed_lost.value, MissingItemStatus.resolved.value],
        )

    if status == MissingItemStatus.confirmed_lost and refund_amount_ngn is not None:
        _check_staff_threshold(tenant_id, refund_amount_ngn, ctx)

    # The status change and, for a compensation, the refund request and its link
    # commit together. Compensation is owed when the item is confirmed lost, and the
    # refund is only opened if no non-rejected refund is linked yet.
    refund_row = None
    with tenant_transaction(tenant_id):
        updated = repo.update_missing_item_status(
            tenant_id, item_id, status, notes=notes, actor_id=actor_id, expected_status=current_status
        )
        if updated is None:
            raise IllegalTransitionError(
                entity="missing_item",
                current_state="changed by another request",
                requested_state=status,
                allowed=[current_status],
            )
        if (
            status == MissingItemStatus.confirmed_lost
            and refund_amount_ngn is not None
            and _can_reopen_compensation(tenant_id, updated.get("refund_request_id"))
        ):
            refund_row = refund_repo.create_refund_request(
                tenant_id,
                {
                    "tenant_id": tenant_id,
                    "customer_id": str(item["customer_id"]),
                    "billing_id": None,
                    "damage_claim_id": None,
                    "refund_type": "missing_item",
                    "amount_ngn": refund_amount_ngn,
                    "reason": f"Compensation for missing item {item_id}",
                    "status": "pending_review",
                    "customer_choice": None,
                    "requested_by": actor_id,
                },
            )
            if refund_row is None:
                raise RuntimeError("create_refund_request returned None unexpectedly")
            linked = repo.link_refund_to_missing_item(tenant_id, item_id, str(refund_row["id"]))
            if linked is not None:
                updated = linked

    log_audit(
        tenant_id=tenant_id,
        entity_type="missing_item",
        entity_id=item_id,
        action="UPDATE",
        actor_id=actor_id,
        actor_role=str(ctx.role),
        before_state={"status": item["status"]},
        after_state={"status": status, "notes": notes},
        ip_address=ip_address,
    )

    result = _fmt_missing(updated)

    if refund_row is not None:
        log_audit(
            tenant_id=tenant_id,
            entity_type="refund_request",
            entity_id=str(refund_row["id"]),
            action="CREATE",
            actor_id=actor_id,
            actor_role=str(ctx.role),
            after_state={
                "customer_id": str(item["customer_id"]),
                "amount_ngn": str(refund_amount_ngn),
                "refund_type": "missing_item",
                "source_missing_item_id": item_id,
            },
            ip_address=ip_address,
        )
        result["refund_request_id"] = str(updated.get("refund_request_id") or refund_row["id"])

    return result


# ---------------------------------------------------------------------------
# Seized item operations
# ---------------------------------------------------------------------------


def log_seized_item(
    tenant_id: str,
    req: Any,
    actor_id: str,
    ctx: Any,
    ip_address: str | None = None,
) -> dict[str, Any]:
    item = repo.create_seized_item(
        tenant_id,
        {
            "tenant_id": tenant_id,
            "container_id": req.container_id,
            "customer_id": req.customer_id,
            "carton_tags": req.carton_tags,
            "description": req.reason,
            "seizure_date": date.today(),
            "recovery_status": "seized",
            "created_by": actor_id,
        },
    )
    if item is None:
        raise RuntimeError("create_seized_item returned None unexpectedly")

    log_audit(
        tenant_id=tenant_id,
        entity_type="seized_item",
        entity_id=str(item["id"]),
        action="CREATE",
        actor_id=actor_id,
        actor_role=str(ctx.role),
        after_state={"customer_id": req.customer_id, "container_id": req.container_id, "recovery_status": "seized"},
        ip_address=ip_address,
    )
    return _fmt_seized(item)


def update_seized_item(
    tenant_id: str,
    item_id: str,
    recovery_status: str,
    notes: str | None,
    actor_id: str,
    ctx: Any,
    refund_amount_ngn: Decimal | None = None,
    ip_address: str | None = None,
) -> dict[str, Any]:
    item = repo.get_seized_item_by_id(tenant_id, item_id)
    if not item:
        raise ResourceNotFoundError("seized_item", item_id)

    current_status = item["recovery_status"]
    if current_status == SeizedItemStatus.recovered:
        raise IllegalTransitionError(
            entity="seized_item",
            current_state=current_status,
            requested_state=recovery_status,
            allowed=[],
        )
    if current_status == SeizedItemStatus.permanently_lost and recovery_status != SeizedItemStatus.permanently_lost:
        raise IllegalTransitionError(
            entity="seized_item",
            current_state=current_status,
            requested_state=recovery_status,
            allowed=[SeizedItemStatus.permanently_lost.value],
        )

    if recovery_status == SeizedItemStatus.permanently_lost and refund_amount_ngn is not None:
        _check_staff_threshold(tenant_id, refund_amount_ngn, ctx)

    # Same shape as update_missing_item: status change, refund request and link in
    # one transaction, and no second refund while a non-rejected refund is linked.
    refund_row = None
    with tenant_transaction(tenant_id):
        updated = repo.update_seized_item_status(
            tenant_id, item_id, recovery_status, notes=notes, actor_id=actor_id, expected_status=current_status
        )
        if updated is None:
            raise IllegalTransitionError(
                entity="seized_item",
                current_state="changed by another request",
                requested_state=recovery_status,
                allowed=[current_status],
            )
        if (
            recovery_status == SeizedItemStatus.permanently_lost
            and refund_amount_ngn is not None
            and _can_reopen_compensation(tenant_id, updated.get("refund_request_id"))
        ):
            refund_row = refund_repo.create_refund_request(
                tenant_id,
                {
                    "tenant_id": tenant_id,
                    "customer_id": str(item["customer_id"]),
                    "billing_id": None,
                    "damage_claim_id": None,
                    "refund_type": "seized_item",
                    "amount_ngn": refund_amount_ngn,
                    "reason": f"Compensation for seized item {item_id}",
                    "status": "pending_review",
                    "customer_choice": None,
                    "requested_by": actor_id,
                },
            )
            if refund_row is None:
                raise RuntimeError("create_refund_request returned None unexpectedly")
            linked = repo.link_refund_to_seized_item(tenant_id, item_id, str(refund_row["id"]))
            if linked is not None:
                updated = linked

    log_audit(
        tenant_id=tenant_id,
        entity_type="seized_item",
        entity_id=item_id,
        action="UPDATE",
        actor_id=actor_id,
        actor_role=str(ctx.role),
        before_state={"recovery_status": item["recovery_status"]},
        after_state={"recovery_status": recovery_status, "notes": notes},
        ip_address=ip_address,
    )

    result = _fmt_seized(updated)

    if refund_row is not None:
        log_audit(
            tenant_id=tenant_id,
            entity_type="refund_request",
            entity_id=str(refund_row["id"]),
            action="CREATE",
            actor_id=actor_id,
            actor_role=str(ctx.role),
            after_state={
                "customer_id": str(item["customer_id"]),
                "amount_ngn": str(refund_amount_ngn),
                "refund_type": "seized_item",
                "source_seized_item_id": item_id,
            },
            ip_address=ip_address,
        )
        result["refund_request_id"] = str(updated.get("refund_request_id") or refund_row["id"])

    return result


# ---------------------------------------------------------------------------
# Internal formatters
# ---------------------------------------------------------------------------


def _notify_customer_claim_update(tenant_id: str, claim: dict[str, Any], status: str, request_id: str = "") -> None:
    """Best-effort "your claim status changed" notification — same gap class
    as payment_claim confirm/reject and billing's payment_due: a claim
    status transition with no customer-facing signal at all. Never raises: a
    notification outage must not fail the status-change request itself."""
    try:
        customer_id = claim.get("customer_id")
        if not customer_id:
            return
        customer = repo.get_customer_contact(tenant_id, str(customer_id))
        if not customer:
            return
        enqueue_notifications(
            tenant_id=tenant_id,
            event_type="damage_claim_update",
            recipient={
                "phone": customer.get("phone") or "",
                "email": customer.get("email") or "",
                "whatsapp": customer.get("whatsapp") or "",
                "name": customer.get("name") or "",
            },
            template_data={"claim_reference": claim.get("reference") or "", "status": status},
            locale=customer.get("locale", "en"),
            request_id=request_id,
            customer_id=str(customer_id),
        )

        # In-app customer bell — see payment_release/service.py's matching
        # comment.
        if customer.get("user_id"):
            notify_staff(
                tenant_id=tenant_id,
                event_type="damage_claim_update",
                entity_type="damage_claim",
                entity_id=str(claim.get("id")) if claim.get("id") else None,
                title="Claim status update",
                body=f"Claim {claim.get('reference') or ''} is now {status}.",
                target_user_id=str(customer["user_id"]),
            )
    except Exception:
        logger.exception(
            "Failed to enqueue damage_claim_update notification for claim %s",
            claim.get("id"),
        )


def _fmt_claim(row: dict[str, Any]) -> dict[str, Any]:
    cartons = row.get("cartons_affected") or []
    if isinstance(cartons, int | float):
        cartons = []
    return {
        "id": str(row["id"]),
        "reference": row.get("reference"),
        "status": row["status"],
        "container_id": str(row["container_id"]) if row.get("container_id") else None,
        "container_number": row.get("container_number"),
        "customer_id": str(row["customer_id"]) if row.get("customer_id") else None,
        "customer_name": row.get("customer_name"),
        "description": row.get("description"),
        "inspection_method": row.get("inspection_method"),
        "cartons_affected": list(cartons),
        "upload_urls": None,
        "created_at": row.get("created_at"),
    }


def _fmt_resolution(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "resolution_type": row["resolution_type"],
        "amount_usd": None,
        "amount_ngn": row.get("resolution_amount_ngn"),
        "approval_level": row["approval_level"],
        "refund_request_id": str(row["refund_request_id"]) if row.get("refund_request_id") else None,
    }


def _fmt_missing(row: dict[str, Any]) -> dict[str, Any]:
    tags = row.get("carton_tags") or []
    return {
        "id": str(row["id"]),
        "manifest_id": str(row["manifest_id"]),
        "customer_id": str(row["customer_id"]),
        "customer_name": row.get("customer_name"),
        "container_number": row.get("container_number"),
        "carton_tags": list(tags),
        "description": row["description"],
        "status": row["status"],
        "created_at": row["created_at"],
    }


def _fmt_seized(row: dict[str, Any]) -> dict[str, Any]:
    tags = row.get("carton_tags") or []
    description = row.get("description") or row.get("notes") or ""
    return {
        "id": str(row["id"]),
        "container_id": str(row["container_id"]),
        "container_number": row.get("container_number"),
        "customer_id": str(row["customer_id"]) if row.get("customer_id") else None,
        "customer_name": row.get("customer_name"),
        "carton_tags": list(tags),
        "reason": description,
        "status": row["recovery_status"],
        "created_at": row["created_at"],
    }
