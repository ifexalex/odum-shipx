"""Business logic for the Claims service.

Handles damage claim lifecycle, S3 presigned upload URL generation,
claim resolution with approval threshold enforcement, and logging of
missing/seized items.
"""

import logging
import os
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any

import boto3

from services.refunds import repository as refund_repo
from shared.audit import log_audit
from shared.events import publish_event
from shared.exceptions import (
    ApprovalThresholdExceededError,
    BusinessRuleViolationError,
    IllegalTransitionError,
    InsufficientPermissionsError,
    ResourceNotFoundError,
)
from shared.tenant_context import UserRole

from . import repository as repo

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# S3 configuration (module-level client — reused across warm invocations)
# ---------------------------------------------------------------------------

_s3_client = boto3.client("s3")
_BUCKET = os.environ.get("S3_BUCKET_NAME", "logistics-assets")
_ALLOWED_CONTENT_TYPES = frozenset({"image/jpeg", "image/png", "application/pdf"})
_MAX_FILE_SIZE = 10 * 1024 * 1024  # 10 MB
_URL_EXPIRY = 3600  # 1 hour

# ---------------------------------------------------------------------------
# Damage claim state machine
# ---------------------------------------------------------------------------

# Valid source states for resolve_claim
_RESOLVABLE_STATES = {"under_inspection", "inspection_complete", "pending_resolution"}


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
) -> dict[str, Any]:
    """File a new damage claim.

    For CUSTOMER role: customer_id is derived from ctx.user_id.
    For staff roles: customer_id_override (from request body) is used.
    """
    if ctx.role == UserRole.CUSTOMER:
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

    # FileDamageClaimRequest.container_id was passed straight through to a
    # `uuid` column with no resolution — a customer typing what they actually
    # see (the container number; they never see its internal UUID) crashed
    # with InvalidTextRepresentation, despite the frontend's own field label
    # promising number support ("Container ID or number ... e.g. ACME-001 or
    # paste the UUID"). Found live: every attempt to file a claim by number
    # failed.
    container_id = repo.resolve_container_id(tenant_id, req.container_id)
    if not container_id:
        raise ResourceNotFoundError("container", req.container_id)
    if ctx.role == UserRole.CUSTOMER and not repo.customer_has_cargo_in_container(
        tenant_id, customer_id, container_id
    ):
        # Without this, a customer could file a claim against any container
        # in the tenant by guessing/enumerating numbers, not only their own.
        raise ResourceNotFoundError("container", req.container_id)

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

    return _fmt_claim(claim)


def list_claims(
    tenant_id: str,
    ctx: Any,
    filters: dict[str, Any],
    limit: int,
    cursor: dict[str, Any] | None,
    sort_field: str = "created_at",
    sort_direction: str = "DESC",
) -> tuple[list[dict[str, Any]], str | None, bool]:
    if ctx.role == UserRole.CUSTOMER:
        customer = repo.get_customer_by_user_id(tenant_id, ctx.user_id)
        if not customer:
            return [], None, False
        filters = {**filters, "customer_id": str(customer["id"])}

    rows, next_cursor, has_more = repo.list_damage_claims(
        tenant_id, filters, limit, cursor, sort_field=sort_field, sort_direction=sort_direction
    )
    return [_fmt_claim(r) for r in rows], next_cursor, has_more


def get_claim(tenant_id: str, claim_id: str, ctx: Any) -> dict[str, Any]:
    claim = repo.get_damage_claim_by_id(tenant_id, claim_id)
    if not claim:
        raise ResourceNotFoundError("damage_claim", claim_id)

    if ctx.role == UserRole.CUSTOMER:
        customer = repo.get_customer_by_user_id(tenant_id, ctx.user_id)
        if not customer or str(customer["id"]) != str(claim["customer_id"]):
            raise InsufficientPermissionsError("Customers may only view their own claims")

    return _fmt_claim(claim)


def start_inspection(
    tenant_id: str,
    claim_id: str,
    req: Any,
    actor_id: str,
    ip_address: str | None = None,
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
    )
    if updated is None:
        raise RuntimeError("update_claim_status returned None unexpectedly")

    log_audit(
        tenant_id=tenant_id,
        entity_type="damage_claim",
        entity_id=claim_id,
        action="STATUS_CHANGE",
        actor_id=actor_id,
        actor_role=str(UserRole.NIGERIA_OFFICE_STAFF),
        before_state={"status": "filed"},
        after_state={"status": "under_inspection"},
        ip_address=ip_address,
    )
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

    # New-style request uses settlement_amount_usd + notes (no threshold check, no claim_resolution record)
    settlement_usd = getattr(req, "settlement_amount_usd", None)
    if isinstance(settlement_usd, Decimal):
        return _resolve_claim_new_style(
            tenant_id,
            claim_id,
            claim,
            req,
            resolution_type,
            actor_id,
            ctx,
            request_id,
            ip_address,
        )

    # Determine approval level + enforce threshold.
    #
    # Ground-truth gap found live via e2e testing: this checked req.amount_usd,
    # but ResolveClaimInput (the frontend's real request body) only ever sends
    # amount_ngn — no field named amount_usd exists on it at all. `if ...
    # req.amount_usd:` was therefore always falsy from the one call site that
    # actually reaches this code, and the entire staff-approval-threshold
    # enforcement was dead: nigeria_office_staff could resolve a refund of any
    # size with no tenant_admin escalation. Confirmed live — a ₦500,000
    # refund resolved cleanly as nigeria_office_staff with no rejection.
    # Fixed by converting the NGN amount actually sent to USD via the
    # tenant's configured dollar rate, the same conversion this file already
    # does the other direction for the new-style resolution path below.
    approval_level = "nigeria_staff"
    if resolution_type == "refund" and req.amount_ngn:
        threshold_cfg = repo.get_tenant_config_value(tenant_id, "refund_threshold_usd") or {}
        staff_limit_usd = Decimal(str(threshold_cfg.get("staff_limit", 50)))
        dollar_rate = repo.get_dollar_rate(tenant_id)
        amount_usd = Decimal(str(req.amount_ngn)) / dollar_rate if dollar_rate > 0 else Decimal(0)
        if amount_usd > staff_limit_usd:
            if ctx.role != UserRole.TENANT_ADMIN:
                raise ApprovalThresholdExceededError(
                    f"Refund of ₦{req.amount_ngn} (~${amount_usd:.2f}) exceeds staff limit of "
                    f"${staff_limit_usd}; tenant_admin approval required"
                )
            approval_level = "tenant_admin"

    # Create refund_request if refund type
    refund_request_id = None
    if resolution_type == "refund":
        refund_ngn = req.amount_ngn or Decimal("0")
        refund_row = repo.create_refund_request_for_claim(
            tenant_id,
            {
                "tenant_id": tenant_id,
                "customer_id": str(claim["customer_id"]),
                "billing_id": None,
                "amount_ngn": refund_ngn,
                "reason": f"Damage claim resolution — {req.reason}",
            },
        )
        refund_request_id = str(refund_row["id"]) if refund_row else None

    # Create claim_resolution record
    resolution = repo.create_claim_resolution(
        tenant_id,
        {
            "tenant_id": tenant_id,
            "damage_claim_id": claim_id,
            "resolution_type": resolution_type,
            "resolution_amount_ngn": req.amount_ngn,
            "approval_level": approval_level,
            "approved_by": actor_id,
            "notes": req.reason,
            "refund_request_id": refund_request_id,
            "discount_percentage": req.discount_percentage,
        },
    )

    # Update claim status
    now = datetime.now(UTC)
    updated = repo.update_claim_status(
        tenant_id,
        claim_id,
        "resolved",
        extra={"reviewed_by": actor_id, "reviewed_at": now},
    )
    if updated is None:
        raise RuntimeError("update_claim_status returned None unexpectedly")

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
        after_state={"status": "resolved"},
        ip_address=ip_address,
    )

    if resolution is None:
        raise RuntimeError("create_claim_resolution returned None unexpectedly")
    return {
        **_fmt_claim(updated),
        "resolution": _fmt_resolution(resolution),
    }


# ---------------------------------------------------------------------------
# New-style claim resolution helper (settlement_amount_usd path)
# ---------------------------------------------------------------------------


def _resolve_claim_new_style(
    tenant_id: str,
    claim_id: str,
    claim: dict[str, Any],
    req: Any,
    resolution_type: str,
    actor_id: str,
    ctx: Any,
    request_id: str,
    ip_address: str | None,
) -> dict[str, Any]:
    """Handle resolve_claim when req.settlement_amount_usd is a Decimal.

    Skips approval threshold check and claim_resolution record creation;
    creates a refund_request when resolution_type == 'refund'.
    """
    dollar_rate = repo.get_dollar_rate(tenant_id)
    amount_ngn = req.settlement_amount_usd * dollar_rate

    # Look up associated billing (optional — may be None)
    billing = repo.get_billing_by_id(tenant_id, claim.get("billing_id", ""))
    billing_id = str(billing["id"]) if billing else None

    refund_request_id = None
    if resolution_type == "refund":
        notes_text = getattr(req, "notes", None) or ""
        refund_row = repo.create_refund_request_for_claim(
            tenant_id,
            {
                "tenant_id": tenant_id,
                "customer_id": str(claim["customer_id"]),
                "billing_id": billing_id,
                "amount_ngn": amount_ngn,
                "reason": f"Damage claim resolution — {notes_text}",
            },
        )
        refund_request_id = str(refund_row["id"]) if refund_row else None

    now = datetime.now(UTC)
    updated = repo.update_claim_status(
        tenant_id,
        claim_id,
        "resolved",
        extra={"reviewed_by": actor_id, "reviewed_at": now},
    )
    if updated is None:
        raise RuntimeError("update_claim_status returned None unexpectedly")

    publish_event(
        source="logistics.claims",
        detail_type="DamageClaimResolved",
        tenant_id=tenant_id,
        payload={
            "claim_id": claim_id,
            "resolution_type": resolution_type,
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
        after_state={"status": "resolved"},
        ip_address=ip_address,
    )

    return {
        **_fmt_claim(updated),
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
    actor_id: str,
) -> dict[str, Any]:
    if content_type not in _ALLOWED_CONTENT_TYPES:
        raise BusinessRuleViolationError(
            f"content_type '{content_type}' is not allowed. " f"Allowed: {', '.join(sorted(_ALLOWED_CONTENT_TYPES))}",
            rule_id="INVALID_CONTENT_TYPE",
        )

    claim = repo.get_damage_claim_by_id(tenant_id, claim_id)
    if not claim:
        raise ResourceNotFoundError("damage_claim", claim_id)

    file_key = f"{tenant_id}/claims/{claim_id}/{filename}"

    presigned = _s3_client.generate_presigned_post(
        Bucket=_BUCKET,
        Key=file_key,
        Fields={"Content-Type": content_type},
        Conditions=[
            {"Content-Type": content_type},
            ["content-length-range", 1, _MAX_FILE_SIZE],
        ],
        ExpiresIn=_URL_EXPIRY,
    )

    evidence = repo.create_claim_evidence(
        {
            "damage_claim_id": claim_id,
            "file_key": file_key,
            "file_name": filename,
            "file_type": content_type,
            "file_size_bytes": None,
            "uploaded_by": actor_id,
        }
    )

    return {
        "upload_url": presigned["url"],
        "fields": presigned["fields"],
        "evidence_id": str(evidence["id"]) if evidence else None,
        "file_key": file_key,
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
    return _fmt_missing(item)


def update_missing_item(
    tenant_id: str,
    item_id: str,
    status: str,
    notes: str | None,
    actor_id: str,
    refund_amount_ngn: Decimal | None = None,
) -> dict[str, Any]:
    item = repo.get_missing_item_by_id(tenant_id, item_id)
    if not item:
        raise ResourceNotFoundError("missing_item", item_id)

    updated = repo.update_missing_item_status(tenant_id, item_id, status, notes=notes, actor_id=actor_id)
    if updated is None:
        raise RuntimeError("update_missing_item_status returned None unexpectedly")

    result = _fmt_missing(updated)

    if status == "compensated" and refund_amount_ngn is not None:
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
        linked = repo.link_refund_to_missing_item(tenant_id, item_id, str(refund_row["id"]))
        result["refund_request_id"] = str(refund_row["id"]) if refund_row else None
        if linked is not None:
            result["refund_request_id"] = str(linked.get("refund_request_id") or refund_row["id"])

    return result


# ---------------------------------------------------------------------------
# Seized item operations
# ---------------------------------------------------------------------------


def log_seized_item(
    tenant_id: str,
    req: Any,
    actor_id: str,
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
    return _fmt_seized(item)


def update_seized_item(
    tenant_id: str,
    item_id: str,
    recovery_status: str,
    notes: str | None,
    actor_id: str,
    refund_amount_ngn: Decimal | None = None,
) -> dict[str, Any]:
    item = repo.get_seized_item_by_id(tenant_id, item_id)
    if not item:
        raise ResourceNotFoundError("seized_item", item_id)

    updated = repo.update_seized_item_status(tenant_id, item_id, recovery_status, notes=notes, actor_id=actor_id)
    if updated is None:
        raise RuntimeError("update_seized_item_status returned None unexpectedly")

    result = _fmt_seized(updated)

    if recovery_status in ("recovered", "forfeited") and refund_amount_ngn is not None:
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
        linked = repo.link_refund_to_seized_item(tenant_id, item_id, str(refund_row["id"]))
        result["refund_request_id"] = str(refund_row["id"]) if refund_row else None
        if linked is not None:
            result["refund_request_id"] = str(linked.get("refund_request_id") or refund_row["id"])

    return result


# ---------------------------------------------------------------------------
# Internal formatters
# ---------------------------------------------------------------------------


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
        "customer_id": str(row["customer_id"]) if row.get("customer_id") else None,
        "carton_tags": list(tags),
        "reason": description,
        "status": row["recovery_status"],
        "created_at": row["created_at"],
    }
