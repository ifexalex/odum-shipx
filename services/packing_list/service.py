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
from shared.cbm_rate import apply_min_cbm, get_min_cbm_per_item, normalize_package_unit
from shared.events import publish_event
from shared.exceptions import (
    BusinessRuleViolationError,
    IllegalTransitionError,
    InsufficientPermissionsError,
    ResourceNotFoundError,
    SelfApprovalForbiddenError,
)
from shared.notifications import enqueue_notifications
from shared.staff_notifications import notify_staff
from shared.tenant_context import UserRole

from . import repository as repo
from .models import (
    ApprovePackingListRequest,
    BulkApproveRequest,
    BulkRejectRequest,
    CreatePackingListRequest,
    RejectPackingListRequest,
    UpdatePackingListRequest,
)

logger = logging.getLogger(__name__)


def _resolve_arrival_warehouse(tenant_id: str, requested_id: str | None) -> dict[str, Any] | None:
    """Resolve the packing list's destination warehouse row.

    A caller-supplied id is validated to belong to this tenant (RLS-scoped read);
    an unknown id raises. When omitted, the tenant's default warehouse is applied
    so a list always records where the cargo is bound, matching the release-note
    flow's own default-warehouse fallback. Returns None only when the tenant has
    no default warehouse at all.
    """
    # Imported here (not at module scope) to avoid a package-level import cycle
    # between the packing_list and payment_release services.
    from services.payment_release import repository as release_repo

    if requested_id:
        warehouse = release_repo.get_warehouse_by_id(tenant_id, requested_id)
        if not warehouse:
            raise ResourceNotFoundError("warehouse", requested_id)
        return dict(warehouse)
    default = release_repo.get_default_warehouse(tenant_id)
    return dict(default) if default else None


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


# Bales are sized by CBM: a bale at/above this threshold is a "big bale",
# below it a "small bale" (abbreviated SM/BIG in the UI). Reported-threshold.
_BIG_BALE_CBM = Decimal("0.3")


def _bale_type_for(package_unit: str | None, cbm: Decimal) -> str | None:
    """Big/small bale label for a bale line item, else None."""
    if normalize_package_unit(package_unit) != "bale":
        return None
    return "BIG BALE" if cbm >= _BIG_BALE_CBM else "SMALL BALE"


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
    min_cbm: Decimal | None = None,
) -> list[dict[str, Any]]:
    """Generate item dicts with carton tags, tracking codes, and CBM values."""
    if min_cbm is None:
        min_cbm = get_min_cbm_per_item(tenant_id)
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

        # Floor the line-item CBM at the tenant's minimum (default 0.1) — a
        # tiny parcel still occupies handling/shipping space and bills at the
        # floor. Applied to the stored cbm, so totals + billing use it too.
        cbm = apply_min_cbm(_compute_cbm(item.length_cm, item.width_cm, item.height_cm), min_cbm)
        package_unit = getattr(item, "package_unit", None)
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
                "declared_value_usd": float(item.declared_value_usd) if item.declared_value_usd is not None else None,
                "package_unit": (package_unit or "carton"),
                "bale_type": _bale_type_for(package_unit, cbm),
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
            f"Container must be in 'loading' status to add packing lists (current: {container.get('status')})",
            rule_id="CONTAINER_NOT_LOADING",
        )

    # 2. Validate customer
    customer = repo.get_customer_by_id(tenant_id, req.customer_id)
    if not customer:
        raise ResourceNotFoundError("customer", req.customer_id)

    # 2b. Resolve arrival warehouse (explicit id validated; else tenant default)
    arrival_warehouse = _resolve_arrival_warehouse(tenant_id, req.arrival_warehouse_id)
    arrival_warehouse_id = str(arrival_warehouse["id"]) if arrival_warehouse else None

    # 3. Derive tenant short code + container number
    tenant_short = repo.get_tenant_short(tenant_id)
    container_number = str(container.get("container_number") or "")

    # 4. Get next carton sequence start and PL reference
    carton_seq = repo.get_next_carton_sequence(tenant_id, req.container_id)
    reference = repo.get_next_pl_reference(tenant_id)

    # 5. Insert packing list row
    pl = repo.create_packing_list(
        tenant_id,
        {
            "tenant_id": tenant_id,
            "container_id": req.container_id,
            "customer_id": req.customer_id,
            "created_by": actor_id,
            "reference": reference,
            "loading_date": req.loading_date,
            "delivery_date": req.delivery_date,
            "arrival_warehouse_id": arrival_warehouse_id,
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

    # Attach customer_name + arrival_warehouse_name (RETURNING * has neither join)
    pl_dict = dict(pl)
    pl_dict["customer_name"] = customer.get("name")
    pl_dict["arrival_warehouse_name"] = arrival_warehouse.get("name") if arrival_warehouse else None
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
) -> tuple[list[dict[str, Any]], str | None, bool, int]:
    # Customer role: force filter to own records only
    if ctx.role == UserRole.CUSTOMER:
        customer = repo.get_customer_by_user_id(tenant_id, ctx.user_id)
        if not customer:
            return [], None, False, 0
        filters = {**filters, "customer_id": str(customer["id"])}

    page, next_cursor, has_more = repo.list_packing_lists(tenant_id, filters, limit, cursor)
    # Only worth a COUNT when there is a further page — otherwise the page
    # length is already the total.
    total = repo.count_packing_lists(tenant_id, filters) if has_more else len(page)
    return page, next_cursor, has_more, total


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
            f"Packing list can only be updated when in 'draft' or 'rejected' status (current: {current_status})",
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

    # Shipment-level dates are editable while the list is a draft/rejected.
    repo.set_packing_list_dates(tenant_id, pl_id, req.loading_date, req.delivery_date)

    # Arrival warehouse is editable too (explicit id validated; else default).
    arrival_warehouse = _resolve_arrival_warehouse(tenant_id, req.arrival_warehouse_id)
    repo.set_packing_list_warehouse(tenant_id, pl_id, str(arrival_warehouse["id"]) if arrival_warehouse else None)

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

    for role in ("china_office_staff", "tenant_admin"):
        notify_staff(
            tenant_id=tenant_id,
            event_type="packing_list_submitted",
            entity_type="packing_list",
            entity_id=pl_id,
            title="Packing list awaiting approval",
            body=f"Packing list {pl.get('reference') or pl_id} needs approval.",
            target_role=role,
        )

    return _assemble_response(dict(updated), items)


def _apply_approval_side_effects(
    tenant_id: str,
    pl: dict[str, Any],
    actor_id: str,
    request_id: str = "",
) -> tuple[str, list[str]]:
    """Everything that must happen when a packing list becomes approved.

    Shared by the single-item and bulk approve paths. It lives in one place
    because it drifted once already: bulk approve only flipped the status, so
    bulk-approved lists had no manifest, no manifest link and — most damaging —
    no shipment_tracking rows, leaving their customers unable to track cargo at
    all and their container unable to seal ("Container must have a manifest").

    Returns (manifest_id, tracking_codes).
    """
    container_id = str(pl["container_id"])
    manifest = repo.get_manifest_by_container(tenant_id, container_id)
    if not manifest:
        manifest = repo.create_manifest(tenant_id, container_id)
    if manifest is None:
        raise RuntimeError("create_manifest returned None unexpectedly")
    manifest_id = str(manifest["id"])

    repo.link_manifest(tenant_id, str(pl["id"]), manifest_id)
    repo.recalculate_manifest_totals(tenant_id, manifest_id)

    items = repo.get_items_by_packing_list(tenant_id, str(pl["id"]))
    seen_codes: set[str] = set()
    for item in items:
        code = item.get("tracking_code")
        if code and code not in seen_codes:
            repo.upsert_shipment_tracking(tenant_id, code)
            seen_codes.add(code)

    publish_event(
        source="logistics.packing_list",
        detail_type="PackingListApproved",
        tenant_id=tenant_id,
        payload={
            "packing_list_id": str(pl["id"]),
            "container_id": container_id,
            "customer_id": str(pl["customer_id"]),
            "manifest_id": manifest_id,
            "approved_by": actor_id,
            "carton_count": len(items),
            "tracking_codes": list(seen_codes),
        },
        request_id=request_id,
    )
    _notify_customer_packing_list_approved(tenant_id, pl, request_id)
    return manifest_id, list(seen_codes)


def _notify_customer_packing_list_approved(tenant_id: str, pl: dict[str, Any], request_id: str) -> None:
    """Best-effort "your packing list was approved" notification — same gap
    class as payment_claim confirm/reject: an approval with no customer-facing
    signal at all. Never raises: a notification outage must not fail
    approval itself (shared by the single-item and bulk approve paths, same
    as the rest of _apply_approval_side_effects)."""
    try:
        customer_id = pl.get("customer_id")
        if not customer_id:
            return
        customer = repo.get_customer_contact(tenant_id, str(customer_id))
        if not customer:
            return
        enqueue_notifications(
            tenant_id=tenant_id,
            event_type="packing_list_approved",
            recipient={
                "phone": customer.get("phone") or "",
                "email": customer.get("email") or "",
                "whatsapp": customer.get("whatsapp") or "",
                "name": customer.get("name") or "",
            },
            template_data={"reference": pl.get("reference") or ""},
            locale=customer.get("locale", "en"),
            request_id=request_id,
            customer_id=str(customer_id),
        )

        # In-app customer bell — see payment_release/service.py's matching
        # comment.
        if customer.get("user_id"):
            notify_staff(
                tenant_id=tenant_id,
                event_type="packing_list_approved",
                entity_type="packing_list",
                entity_id=str(pl.get("id")) if pl.get("id") else None,
                title="Packing list approved",
                body=f"Your packing list {pl.get('reference') or ''} has been approved.",
                target_user_id=str(customer["user_id"]),
            )
    except Exception:
        logger.exception(
            "Failed to enqueue packing_list_approved notification for packing list %s",
            pl.get("id"),
        )


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

    manifest_id, _tracking_codes = _apply_approval_side_effects(tenant_id, pl, actor_id, request_id)
    items = repo.get_items_by_packing_list(tenant_id, pl_id)

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


def bulk_approve_packing_lists(
    tenant_id: str,
    req: BulkApproveRequest,
    actor_id: str,
    ctx: Any,
    request_id: str = "",
    ip_address: str | None = None,
) -> dict[str, Any]:
    """Approve multiple packing lists in one call.

    Guards (per-item):
    - Must be in pending_approval state.
    - Self-approval still forbidden: if all requested PLs were created by the
      actor, the entire bulk is rejected.

    Returns a summary of succeeded / failed / skipped IDs.
    """
    ctx.assert_role(UserRole.CHINA_OFFICE_STAFF, UserRole.TENANT_ADMIN)

    pls = repo.get_packing_lists_by_ids(tenant_id, req.ids)
    pl_map = {str(pl["id"]): pl for pl in pls}

    succeeded: list[str] = []
    failed: list[dict[str, Any]] = []

    approvable_ids: list[str] = []
    for pl_id in req.ids:
        pl = pl_map.get(pl_id)
        if not pl:
            failed.append({"id": pl_id, "reason": "not_found"})
            continue
        if pl["status"] != "pending_approval":
            failed.append({"id": pl_id, "reason": f"wrong_status:{pl['status']}"})
            continue
        if str(pl.get("created_by")) == str(actor_id):
            failed.append({"id": pl_id, "reason": "self_approval_forbidden"})
            continue
        approvable_ids.append(pl_id)

    if approvable_ids:
        repo.bulk_set_status(tenant_id, approvable_ids, "approved", actor_id)
        succeeded = approvable_ids
        # Same side effects as approving one at a time — manifest, manifest
        # link, tracking records, event. Omitting these is what left
        # bulk-approved containers unsealable and their cargo untrackable.
        for pl_id_done in approvable_ids:
            _apply_approval_side_effects(tenant_id, pl_map[pl_id_done], actor_id, request_id)
        log_audit(
            tenant_id=tenant_id,
            entity_type="packing_list",
            entity_id=",".join(approvable_ids),
            action="BULK_APPROVE",
            actor_id=actor_id,
            actor_role=str(ctx.role),
            before_state={"ids": approvable_ids, "status": "pending_approval"},
            after_state={"status": "approved", "count": len(approvable_ids)},
            ip_address=ip_address,
        )

    return {"succeeded": succeeded, "failed": failed}


def bulk_submit_packing_lists(
    tenant_id: str,
    req: Any,
    actor_id: str,
    ctx: Any,
    request_id: str = "",
    ip_address: str | None = None,
) -> dict[str, Any]:
    """Move multiple draft packing lists to pending_approval in one call.

    The counterpart to bulk_approve/bulk_reject, which already existed.

    Import-created lists (manifest and template) land in pending_approval
    directly (see repository.create_packing_list) specifically so a large
    import needs no per-row submit step — so today this exists for drafts
    from the single-item "Create packing list" flow (services/packing_list/
    repository.py), not imports. Kept as a bulk action regardless: nothing
    stops several manual drafts existing at once, and opening each individually
    just to submit it is the same one-at-a-time friction bulk_approve/
    bulk_reject already solve for the review step.

    Guards mirror the single-item submit: draft only. Self-submission is fine —
    the two-person control lives on approval, not here.
    """
    ctx.assert_role(UserRole.CHINA_OFFICE_STAFF, UserRole.TENANT_ADMIN)

    pls = repo.get_packing_lists_by_ids(tenant_id, req.ids)
    pl_map = {str(pl["id"]): pl for pl in pls}

    succeeded: list[str] = []
    failed: list[dict[str, Any]] = []

    submittable_ids: list[str] = []
    for pl_id in req.ids:
        pl = pl_map.get(pl_id)
        if not pl:
            failed.append({"id": pl_id, "reason": "not_found"})
            continue
        if pl["status"] != "draft":
            failed.append({"id": pl_id, "reason": f"wrong_status:{pl['status']}"})
            continue
        submittable_ids.append(pl_id)

    if submittable_ids:
        repo.bulk_set_status(tenant_id, submittable_ids, "pending_approval", actor_id)
        succeeded = submittable_ids
        log_audit(
            tenant_id=tenant_id,
            entity_type="packing_list",
            entity_id=",".join(submittable_ids),
            action="BULK_SUBMIT",
            actor_id=actor_id,
            actor_role=str(ctx.role),
            before_state={"ids": submittable_ids, "status": "draft"},
            after_state={"status": "pending_approval"},
            ip_address=ip_address,
        )
        for role in ("china_office_staff", "tenant_admin"):
            notify_staff(
                tenant_id=tenant_id,
                event_type="packing_list_submitted",
                entity_type="packing_list",
                # entity_id is a single-row UUID column — a bulk action has
                # no one entity to link to, so this is left unset rather than
                # passed a comma-joined id list (which log_audit's own
                # BULK_APPROVE call does above, and which silently fails the
                # same way: UUID columns reject a non-UUID string).
                entity_id=None,
                title="Packing lists awaiting approval",
                body=f"{len(submittable_ids)} packing list(s) need approval.",
                target_role=role,
            )

    return {"succeeded": succeeded, "failed": failed, "total": len(req.ids)}


def bulk_reject_packing_lists(
    tenant_id: str,
    req: BulkRejectRequest,
    actor_id: str,
    ctx: Any,
    ip_address: str | None = None,
) -> dict[str, Any]:
    """Reject multiple packing lists in one call."""
    ctx.assert_role(UserRole.CHINA_OFFICE_STAFF, UserRole.TENANT_ADMIN)

    pls = repo.get_packing_lists_by_ids(tenant_id, req.ids)
    pl_map = {str(pl["id"]): pl for pl in pls}

    succeeded: list[str] = []
    failed: list[dict[str, Any]] = []

    rejectable_ids: list[str] = []
    for pl_id in req.ids:
        pl = pl_map.get(pl_id)
        if not pl:
            failed.append({"id": pl_id, "reason": "not_found"})
            continue
        if pl["status"] != "pending_approval":
            failed.append({"id": pl_id, "reason": f"wrong_status:{pl['status']}"})
            continue
        rejectable_ids.append(pl_id)

    if rejectable_ids:
        repo.bulk_set_status(tenant_id, rejectable_ids, "rejected", actor_id)
        succeeded = rejectable_ids
        log_audit(
            tenant_id=tenant_id,
            entity_type="packing_list",
            entity_id=",".join(rejectable_ids),
            action="BULK_REJECT",
            actor_id=actor_id,
            actor_role=str(ctx.role),
            before_state={"ids": rejectable_ids, "status": "pending_approval"},
            after_state={"status": "rejected", "comments": req.comments, "count": len(rejectable_ids)},
            ip_address=ip_address,
        )

    return {"succeeded": succeeded, "failed": failed}


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

    # Snapshot items before rejection so the audit log captures the exact item
    # versions that were submitted and rejected (items don't change on rejection,
    # but this makes the intent explicit and guards against future races).
    items = repo.get_items_by_packing_list(tenant_id, pl_id)

    updated = repo.reject_packing_list_row(
        tenant_id,
        pl_id,
        actor_id,
        json.dumps(updated_comments),
    )
    if updated is None:
        raise RuntimeError("reject_packing_list_row returned None unexpectedly")

    log_audit(
        tenant_id=tenant_id,
        entity_type="packing_list",
        entity_id=pl_id,
        action="STATUS_CHANGE",
        actor_id=actor_id,
        actor_role=str(ctx.role),
        before_state={"status": pl["status"], "items": items},
        after_state={"status": "rejected", "comments": req.comments},
        ip_address=ip_address,
    )

    return _assemble_response(updated, items)
