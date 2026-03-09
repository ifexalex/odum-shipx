"""Business logic for the Packing List service.

Orchestrates repository calls, code generation, state-machine enforcement,
event publishing, and audit logging.
"""

import json
import logging
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from shared.audit import log_audit
from shared.events import publish_event
from shared.exceptions import (
    BusinessRuleViolationError,
    IllegalTransitionError,
    InsufficientPermissionsError,
    ResourceNotFoundError,
    SelfApprovalForbiddenError,
)
from shared.tenant_context import UserRole

from . import repository as repo
from .models import (
    ApprovePackingListRequest,
    CreatePackingListRequest,
    RejectPackingListRequest,
    UpdatePackingListRequest,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# State machine
# ---------------------------------------------------------------------------

_VALID_TRANSITIONS: dict[str, list[str]] = {
    "draft": ["pending_approval"],
    "pending_approval": ["approved", "rejected"],
    "rejected": ["draft"],
}


def _assert_transition(current: str, target: str, entity_id: str) -> None:
    allowed = _VALID_TRANSITIONS.get(current, [])
    if target not in allowed:
        raise IllegalTransitionError(
            entity="packing_list",
            current_state=current,
            requested_state=target,
            allowed=allowed,
        )


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _compute_cbm(
    length_cm: Decimal | None,
    width_cm: Decimal | None,
    height_cm: Decimal | None,
) -> Decimal:
    if length_cm is not None and width_cm is not None and height_cm is not None:
        return (length_cm * width_cm * height_cm) / Decimal("1000000")
    return Decimal("0")


def _assemble_response(pl: dict[str, Any], items: list[dict[str, Any]]) -> dict[str, Any]:
    """Attach items and computed totals to a packing list row."""
    total_cbm = sum((i.get("cbm") or Decimal("0")) for i in items)
    total_weight = sum((i.get("weight_actual_kg") or Decimal("0")) for i in items)
    return {
        **pl,
        "items": items,
        "carton_count": len(items),
        "total_cbm": total_cbm,
        "total_weight_kg": total_weight,
    }


def _build_item_rows(
    tenant_id: str,
    pl_id: str,
    items: Any,
    container_id: str,
    customer_id: str,
    tenant_short: str,
    container_number: str,
    carton_seq_start: int,
) -> list[dict[str, Any]]:
    """Generate item dicts with carton tags, tracking codes, and CBM values."""
    rows: list[dict[str, Any]] = []
    seq = carton_seq_start
    # Cache tracking codes for (customer_id, received_date) within this batch
    tracking_cache: dict[tuple[str, Any], str] = {}
    # Cache in-batch tracking seq per date_prefix to avoid redundant DB calls
    tracking_seq_cache: dict[str, int] = {}

    for item in items:
        item_date: date = item.received_date or date.today()
        date_str = item_date.strftime("%Y%m%d")
        date_prefix = f"{tenant_short}-TRK-{date_str}"
        cache_key = (customer_id, item_date)

        # Resolve tracking code: same customer+date → same code
        if cache_key in tracking_cache:
            tracking_code = tracking_cache[cache_key]
        else:
            # Check DB for existing code (from prior packing lists)
            existing = repo.get_existing_tracking_code(tenant_id, customer_id, item_date)
            if existing:
                tracking_code = existing
            else:
                # Generate new code; use cached in-batch seq if already incremented
                if date_prefix not in tracking_seq_cache:
                    trk_seq = repo.get_next_tracking_sequence(tenant_id, date_prefix)
                    tracking_seq_cache[date_prefix] = trk_seq
                else:
                    trk_seq = tracking_seq_cache[date_prefix]
                    tracking_seq_cache[date_prefix] += 1
                tracking_code = f"{date_prefix}-{trk_seq:03d}"
            tracking_cache[cache_key] = tracking_code

        cbm = _compute_cbm(item.length_cm, item.width_cm, item.height_cm)
        carton_tag = f"{tenant_short}-{container_number}-{seq:03d}"

        rows.append(
            {
                "packing_list_id": pl_id,
                "description": item.description,
                "weight_dispatch_kg": float(item.weight_dispatch_kg) if item.weight_dispatch_kg is not None else None,
                "weight_actual_kg": float(item.weight_actual_kg) if item.weight_actual_kg is not None else None,
                "carton_tag": carton_tag,
                "tracking_code": tracking_code,
                "cbm": float(cbm),
                "length_cm": float(item.length_cm) if item.length_cm is not None else None,
                "width_cm": float(item.width_cm) if item.width_cm is not None else None,
                "height_cm": float(item.height_cm) if item.height_cm is not None else None,
                "received_date": item_date,
            }
        )
        seq += 1

    return rows


# ---------------------------------------------------------------------------
# Service functions
# ---------------------------------------------------------------------------


def create_packing_list(
    tenant_id: str,
    req: CreatePackingListRequest,
    actor_id: str,
    request_id: str = "",
    ip_address: str | None = None,
) -> dict[str, Any]:
    # 1. Validate container
    container = repo.get_container_by_id(tenant_id, req.container_id)
    if not container:
        raise ResourceNotFoundError("container", req.container_id)
    if container.get("status") != "loading":
        raise BusinessRuleViolationError(
            f"Container must be in 'loading' status to add packing lists " f"(current: {container.get('status')})",
            rule_id="CONTAINER_NOT_LOADING",
        )

    # 2. Validate customer
    customer = repo.get_customer_by_id(tenant_id, req.customer_id)
    if not customer:
        raise ResourceNotFoundError("customer", req.customer_id)

    # 3. Derive tenant short code + container number
    tenant_short = repo.get_tenant_short(tenant_id)
    container_number = str(container.get("container_number") or "")

    # 4. Get next carton sequence start
    carton_seq = repo.get_next_carton_sequence(tenant_id, req.container_id)

    # 5. Insert packing list row
    pl = repo.create_packing_list(
        tenant_id,
        {
            "tenant_id": tenant_id,
            "container_id": req.container_id,
            "customer_id": req.customer_id,
            "created_by": actor_id,
        },
    )
    if pl is None:
        raise RuntimeError("create_packing_list returned None unexpectedly")
    pl_id = str(pl["id"])

    # 6. Build item rows with generated tags/codes
    item_rows = _build_item_rows(
        tenant_id=tenant_id,
        pl_id=pl_id,
        items=req.items,
        container_id=req.container_id,
        customer_id=req.customer_id,
        tenant_short=tenant_short,
        container_number=container_number,
        carton_seq_start=carton_seq,
    )

    # 7. Insert items
    inserted_items = [r for r in repo.insert_packing_list_items(tenant_id, item_rows) if r is not None]

    # 8. Audit
    log_audit(
        tenant_id=tenant_id,
        entity_type="packing_list",
        entity_id=pl_id,
        action="CREATE",
        actor_id=actor_id,
        actor_role=str(UserRole.CHINA_OFFICE_STAFF),
        after_state={"container_id": req.container_id, "customer_id": req.customer_id},
        ip_address=ip_address,
    )

    # Attach customer_name from the fetched customer record
    pl_dict = dict(pl)
    pl_dict["customer_name"] = customer.get("name")
    return _assemble_response(pl_dict, inserted_items)


def get_packing_list(tenant_id: str, pl_id: str, ctx: Any) -> dict[str, Any]:
    pl = repo.get_packing_list_by_id(tenant_id, pl_id)
    if not pl:
        raise ResourceNotFoundError("packing_list", pl_id)

    # Customer role: can only view their own packing list
    if ctx.role == UserRole.CUSTOMER:
        customer = repo.get_customer_by_user_id(tenant_id, ctx.user_id)
        if not customer or str(customer["id"]) != str(pl["customer_id"]):
            raise InsufficientPermissionsError(
                action="get_packing_list",
                required_role="owner",
            )

    items = repo.get_items_by_packing_list(tenant_id, pl_id)
    return _assemble_response(dict(pl), items)


def list_packing_lists(
    tenant_id: str,
    filters: dict[str, Any],
    limit: int,
    cursor: dict[str, Any] | None,
    ctx: Any,
) -> tuple[list[dict[str, Any]], str | None, bool]:
    # Customer role: force filter to own records only
    if ctx.role == UserRole.CUSTOMER:
        customer = repo.get_customer_by_user_id(tenant_id, ctx.user_id)
        if not customer:
            return [], None, False
        filters = {**filters, "customer_id": str(customer["id"])}

    return repo.list_packing_lists(tenant_id, filters, limit, cursor)


def update_packing_list(
    tenant_id: str,
    pl_id: str,
    req: UpdatePackingListRequest,
    actor_id: str,
    ctx: Any,
    ip_address: str | None = None,
) -> dict[str, Any]:
    pl = repo.get_packing_list_by_id(tenant_id, pl_id)
    if not pl:
        raise ResourceNotFoundError("packing_list", pl_id)

    current_status = pl["status"]
    if current_status not in ("draft", "rejected"):
        raise BusinessRuleViolationError(
            f"Packing list can only be updated when in 'draft' or 'rejected' status " f"(current: {current_status})",
            rule_id="INVALID_UPDATE_STATUS",
        )

    ctx.assert_role(UserRole.CHINA_OFFICE_STAFF)

    before_state = {"status": current_status, "item_count": len(req.items)}

    # Get container for tag re-generation
    container = repo.get_container_by_id(tenant_id, str(pl["container_id"]))
    if not container:
        raise ResourceNotFoundError("container", str(pl["container_id"]))
    tenant_short = repo.get_tenant_short(tenant_id)
    container_number = str(container.get("container_number") or "")

    # Delete existing items and re-insert with fresh sequences
    repo.delete_items_by_packing_list(tenant_id, pl_id)
    carton_seq = repo.get_next_carton_sequence(tenant_id, str(pl["container_id"]))

    item_rows = _build_item_rows(
        tenant_id=tenant_id,
        pl_id=pl_id,
        items=req.items,
        container_id=str(pl["container_id"]),
        customer_id=str(pl["customer_id"]),
        tenant_short=tenant_short,
        container_number=container_number,
        carton_seq_start=carton_seq,
    )
    inserted_items = [r for r in repo.insert_packing_list_items(tenant_id, item_rows) if r is not None]

    # If revising a rejected list, transition back to draft
    updated_pl: dict[str, Any]
    if current_status == "rejected":
        _result = repo.set_packing_list_status(tenant_id, pl_id, "draft")
        if _result is None:
            raise RuntimeError("set_packing_list_status returned None unexpectedly")
        updated_pl = _result
    else:
        repo.touch_updated_at(tenant_id, pl_id)
        _fetched = repo.get_packing_list_by_id(tenant_id, pl_id)
        updated_pl = _fetched if _fetched is not None else pl

    log_audit(
        tenant_id=tenant_id,
        entity_type="packing_list",
        entity_id=pl_id,
        action="UPDATE",
        actor_id=actor_id,
        actor_role=str(ctx.role),
        before_state=before_state,
        after_state={"status": updated_pl.get("status"), "item_count": len(inserted_items)},
        ip_address=ip_address,
    )

    return _assemble_response(dict(updated_pl), inserted_items)


def submit_packing_list(
    pl_id: str,
    tenant_id: str,
    ctx: Any,
    actor_id: str | None = None,
    ip_address: str | None = None,
) -> dict[str, Any]:
    effective_actor = actor_id or ctx.user_id
    pl = repo.get_packing_list_by_id(tenant_id, pl_id)
    if not pl:
        raise ResourceNotFoundError("packing_list", pl_id)

    _assert_transition(pl["status"], "pending_approval", pl_id)
    ctx.assert_role(UserRole.CHINA_OFFICE_STAFF, UserRole.TENANT_ADMIN, UserRole.NIGERIA_OFFICE_STAFF)

    items = repo.list_packing_list_items(tenant_id, pl_id)

    updated = repo.update_packing_list_status(tenant_id, pl_id, "pending_approval")
    if updated is None:
        raise RuntimeError("update_packing_list_status returned None unexpectedly")

    log_audit(
        tenant_id=tenant_id,
        entity_type="packing_list",
        entity_id=pl_id,
        action="STATUS_CHANGE",
        actor_id=effective_actor,
        actor_role=str(ctx.role),
        before_state={"status": pl["status"]},
        after_state={"status": "pending_approval"},
        ip_address=ip_address,
    )

    return _assemble_response(dict(updated), items)


def approve_packing_list(
    tenant_id: str,
    pl_id: str,
    req: ApprovePackingListRequest,
    actor_id: str,
    ctx: Any,
    request_id: str = "",
    ip_address: str | None = None,
) -> dict[str, Any]:
    pl = repo.get_packing_list_by_id(tenant_id, pl_id)
    if not pl:
        raise ResourceNotFoundError("packing_list", pl_id)

    _assert_transition(pl["status"], "approved", pl_id)
    ctx.assert_role(UserRole.CHINA_OFFICE_STAFF, UserRole.TENANT_ADMIN)

    # Self-approval prevention
    if str(pl.get("created_by")) == str(actor_id):
        raise SelfApprovalForbiddenError()

    # Update packing list to approved
    updated = repo.approve_packing_list_row(tenant_id, pl_id, actor_id)
    if updated is None:
        raise RuntimeError("approve_packing_list_row returned None unexpectedly")

    # Create manifest for container if not exists
    container_id = str(pl["container_id"])
    manifest = repo.get_manifest_by_container(tenant_id, container_id)
    if not manifest:
        manifest = repo.create_manifest(tenant_id, container_id)
    if manifest is None:
        raise RuntimeError("create_manifest returned None unexpectedly")
    manifest_id = str(manifest["id"])

    # Link packing list to manifest
    repo.link_manifest(tenant_id, pl_id, manifest_id)

    # Recalculate manifest totals
    repo.recalculate_manifest_totals(tenant_id, manifest_id)

    # Create shipment tracking records for each unique tracking_code
    items = repo.get_items_by_packing_list(tenant_id, pl_id)
    seen_codes: set[str] = set()
    for item in items:
        code = item.get("tracking_code")
        if code and code not in seen_codes:
            repo.upsert_shipment_tracking(tenant_id, code)
            seen_codes.add(code)

    # Publish event
    publish_event(
        source="logistics.packing_list",
        detail_type="PackingListApproved",
        tenant_id=tenant_id,
        payload={
            "packing_list_id": pl_id,
            "container_id": container_id,
            "customer_id": str(pl["customer_id"]),
            "manifest_id": manifest_id,
            "approved_by": actor_id,
            "carton_count": len(items),
            "tracking_codes": list(seen_codes),
        },
        request_id=request_id,
    )

    log_audit(
        tenant_id=tenant_id,
        entity_type="packing_list",
        entity_id=pl_id,
        action="STATUS_CHANGE",
        actor_id=actor_id,
        actor_role=str(ctx.role),
        before_state={"status": pl["status"]},
        after_state={"status": "approved", "manifest_id": manifest_id},
        ip_address=ip_address,
    )

    return _assemble_response(updated, items)


def reject_packing_list(
    tenant_id: str,
    pl_id: str,
    req: RejectPackingListRequest,
    actor_id: str,
    ctx: Any,
    ip_address: str | None = None,
) -> dict[str, Any]:
    pl = repo.get_packing_list_by_id(tenant_id, pl_id)
    if not pl:
        raise ResourceNotFoundError("packing_list", pl_id)

    _assert_transition(pl["status"], "rejected", pl_id)
    ctx.assert_role(UserRole.CHINA_OFFICE_STAFF, UserRole.TENANT_ADMIN)

    # Append to approval_comments history (JSONB list)
    existing_comments = pl.get("approval_comments") or []
    if isinstance(existing_comments, str):
        try:
            existing_comments = json.loads(existing_comments)
        except (json.JSONDecodeError, TypeError):
            existing_comments = []

    new_entry = {
        "actor_id": actor_id,
        "comments": req.comments,
        "item_rejections": [{"item_id": r.item_id, "reason": r.reason} for r in (req.item_rejections or [])],
        "at": datetime.utcnow().isoformat(),
    }
    updated_comments = existing_comments + [new_entry]

    updated = repo.reject_packing_list_row(
        tenant_id,
        pl_id,
        actor_id,
        json.dumps(updated_comments),
    )
    if updated is None:
        raise RuntimeError("reject_packing_list_row returned None unexpectedly")

    items = repo.get_items_by_packing_list(tenant_id, pl_id)

    log_audit(
        tenant_id=tenant_id,
        entity_type="packing_list",
        entity_id=pl_id,
        action="STATUS_CHANGE",
        actor_id=actor_id,
        actor_role=str(ctx.role),
        before_state={"status": pl["status"]},
        after_state={"status": "rejected", "comments": req.comments},
        ip_address=ip_address,
    )

    return _assemble_response(updated, items)
