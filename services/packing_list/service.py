"""Business logic for the Packing List service.

Orchestrates repository calls, code generation, state-machine enforcement,
event publishing, and audit logging.
"""

import json
import logging
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any

from shared.audit import log_audit
from shared.cbm_rate import apply_min_cbm, get_min_cbm_per_item, normalize_package_unit
from shared.db import tenant_transaction
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


def _is_customer_only(ctx: Any) -> bool:
    return bool(getattr(ctx, "is_customer_only", ctx.role == UserRole.CUSTOMER))


def _assert_container_loading(tenant_id: str, pl: dict[str, Any]) -> None:
    """Verify the packing list's container is still in 'loading' status."""
    container_status = pl.get("container_status")
    if container_status is not None:
        if container_status != "loading":
            raise BusinessRuleViolationError(
                f"Container must be in 'loading' status (current: {container_status})",
                rule_id="CONTAINER_NOT_LOADING",
            )
        return
    container_id = pl.get("container_id")
    if not container_id:
        return
    container = repo.get_container_by_id(tenant_id, str(container_id))
    if container is not None and container.get("status") != "loading":
        raise BusinessRuleViolationError(
            f"Container must be in 'loading' status (current: {container.get('status')})",
            rule_id="CONTAINER_NOT_LOADING",
        )


def _container_capacity_cbm(container: dict[str, Any]) -> Decimal | None:
    """Resolve a container's maximum CBM capacity (explicit capacity_cbm, else standard type fallback)."""
    raw_cap = container.get("capacity_cbm")
    if raw_cap is not None:
        cap = Decimal(str(raw_cap))
        if cap > Decimal("0"):
            return cap
    ctype = str(container.get("container_type") or "").lower()
    if not ctype:
        return None
    if "45" in ctype:
        return Decimal("86")
    if "hc" in ctype or "high cube" in ctype:
        return Decimal("76")
    if "40" in ctype:
        return Decimal("67")
    if "20" in ctype:
        return Decimal("33")
    return None


def _assert_container_capacity(
    tenant_id: str,
    container: dict[str, Any],
    added_cbm: Decimal,
    *,
    exclude_pl_id: str | None = None,
) -> None:
    """Refuse packing list items that would push the container over its CBM capacity."""
    capacity = _container_capacity_cbm(container)
    if capacity is None:
        return
    used_cbm = repo.get_container_used_cbm(tenant_id, str(container["id"]), exclude_pl_id=exclude_pl_id)
    if used_cbm + added_cbm > capacity:
        remaining = max(Decimal("0"), capacity - used_cbm)
        cnum = container.get("container_number") or str(container["id"])
        raise BusinessRuleViolationError(
            f"Items total {added_cbm:.3f} CBM, which exceeds container {cnum} remaining capacity "
            f"of {remaining:.3f} CBM ({used_cbm:.3f} / {capacity:.3f} CBM used).",
            rule_id="CONTAINER_CAPACITY_EXCEEDED",
        )


def _assemble_response(pl: dict[str, Any], items: list[dict[str, Any]]) -> dict[str, Any]:
    """Attach items and computed totals to a packing list row."""
    total_cbm = sum((i.get("cbm") or Decimal("0")) for i in items)
    total_weight = sum((i.get("weight_actual_kg") or Decimal("0")) for i in items)
    carton_count = sum(int(i.get("quantity") or 1) for i in items)
    return {
        **pl,
        "items": items,
        "carton_count": carton_count,
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
    # Cache next available in-batch tracking seq per date_prefix
    tracking_seq_cache: dict[str, int] = {}

    for item in items:
        item_date: date = item.received_date or date.today()
        date_str = item_date.strftime("%Y%m%d")
        date_prefix = f"{tenant_short}-TRK-{date_str}"
        cache_key = (customer_id, item_date)

        # Resolve tracking code: same container+customer+date → same code
        if cache_key in tracking_cache:
            tracking_code = tracking_cache[cache_key]
        else:
            existing = repo.get_existing_tracking_code(tenant_id, customer_id, item_date, container_id=container_id)
            if existing:
                tracking_code = existing
            else:
                if date_prefix not in tracking_seq_cache:
                    trk_seq = repo.get_next_tracking_sequence(tenant_id, date_prefix)
                    tracking_seq_cache[date_prefix] = trk_seq + 1
                else:
                    trk_seq = tracking_seq_cache[date_prefix]
                    tracking_seq_cache[date_prefix] = trk_seq + 1
                tracking_code = f"{date_prefix}-{trk_seq:03d}"
            tracking_cache[cache_key] = tracking_code

        # Floor the per-package CBM at the tenant's minimum (default 0.1).
        # Preserve an explicit item.cbm if dimensions are omitted (e.g. manifest-imported rows).
        computed_cbm = _compute_cbm(item.length_cm, item.width_cm, item.height_cm)
        explicit_cbm = getattr(item, "cbm", None)
        raw_cbm = computed_cbm if computed_cbm > Decimal("0") else (explicit_cbm if explicit_cbm is not None else computed_cbm)
        unit_cbm = apply_min_cbm(raw_cbm, min_cbm)
        package_unit = getattr(item, "package_unit", None)

        # Store one row with one carton_tag for the entire line item regardless of
        # quantity (quantity = N). Line-level CBM and weights are multiplied by
        # quantity so every downstream SUM(pli.cbm) / SUM(weight) stays exact,
        # while declared_value_usd stays per unit.
        quantity = max(1, int(getattr(item, "quantity", 1) or 1))
        line_cbm = unit_cbm * quantity

        rows.append(
            {
                "packing_list_id": pl_id,
                "description": item.description,
                "weight_dispatch_kg": (
                    float(item.weight_dispatch_kg * quantity) if item.weight_dispatch_kg is not None else None
                ),
                "weight_actual_kg": (float(item.weight_actual_kg * quantity) if item.weight_actual_kg is not None else None),
                "carton_tag": f"{tenant_short}-{container_number}-{seq:03d}",
                "tracking_code": tracking_code,
                "cbm": float(line_cbm),
                "length_cm": float(item.length_cm) if item.length_cm is not None else None,
                "width_cm": float(item.width_cm) if item.width_cm is not None else None,
                "height_cm": float(item.height_cm) if item.height_cm is not None else None,
                "received_date": item_date,
                # Stored per unit (multiply by quantity for line total value).
                "declared_value_usd": (float(item.declared_value_usd) if item.declared_value_usd is not None else None),
                "quantity": quantity,
                "package_unit": (package_unit or "carton"),
                "bale_type": _bale_type_for(package_unit, unit_cbm),
                "batch_ref": None,
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
    ctx: Any = None,
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

    with tenant_transaction(tenant_id):
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

        # 6. Build item rows with generated tags/codes and validate container capacity
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
        added_cbm = sum((Decimal(str(r["cbm"])) for r in item_rows), Decimal("0"))
        _assert_container_capacity(tenant_id, container, added_cbm)

        # 7. Insert items
        inserted_items = [r for r in repo.insert_packing_list_items(tenant_id, item_rows) if r is not None]

    # 8. Audit
    log_audit(
        tenant_id=tenant_id,
        entity_type="packing_list",
        entity_id=pl_id,
        action="CREATE",
        actor_id=actor_id,
        actor_role=str(ctx.role) if ctx is not None else str(UserRole.CHINA_OFFICE_STAFF),
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

    # Customer-only role: can only view their own packing list
    if _is_customer_only(ctx):
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
    # Customer-only role: force filter to own records only
    if _is_customer_only(ctx):
        customer = repo.get_customer_by_user_id(tenant_id, ctx.user_id)
        if not customer:
            return [], None, False, 0
        filters = {**filters, "customer_id": str(customer["id"])}

    page, next_cursor, has_more = repo.list_packing_lists(tenant_id, filters, limit, cursor)
    # Count whenever there is another page OR we are past the first page (cursor set).
    total = repo.count_packing_lists(tenant_id, filters) if (has_more or cursor is not None) else len(page)
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

    ctx.assert_role(UserRole.CHINA_OFFICE_STAFF, UserRole.NIGERIA_OFFICE_STAFF, UserRole.TENANT_ADMIN)

    # Validate container & warehouse BEFORE mutating/deleting items
    container = repo.get_container_by_id(tenant_id, str(pl["container_id"]))
    if not container:
        raise ResourceNotFoundError("container", str(pl["container_id"]))
    if container.get("status") != "loading":
        raise BusinessRuleViolationError(
            f"Container must be in 'loading' status to edit packing lists (current: {container.get('status')})",
            rule_id="CONTAINER_NOT_LOADING",
        )

    fields_set: set[str] = getattr(req, "model_fields_set", set())
    loading_date = req.loading_date if "loading_date" in fields_set else pl.get("loading_date")
    delivery_date = req.delivery_date if "delivery_date" in fields_set else pl.get("delivery_date")

    if "arrival_warehouse_id" in fields_set:
        arrival_warehouse = _resolve_arrival_warehouse(tenant_id, req.arrival_warehouse_id)
        arrival_warehouse_id = str(arrival_warehouse["id"]) if arrival_warehouse else None
    elif pl.get("arrival_warehouse_id"):
        arrival_warehouse_id = str(pl["arrival_warehouse_id"])
    else:
        arrival_warehouse = _resolve_arrival_warehouse(tenant_id, None)
        arrival_warehouse_id = str(arrival_warehouse["id"]) if arrival_warehouse else None

    existing_items = repo.get_items_by_packing_list(tenant_id, pl_id)
    before_state = {"status": current_status, "item_count": len(existing_items)}

    tenant_short = repo.get_tenant_short(tenant_id)
    container_number = str(container.get("container_number") or "")

    with tenant_transaction(tenant_id):
        # Compute next sequence BEFORE deleting so newly generated carton tags never
        # collide with tags previously assigned or referenced on other records.
        carton_seq = repo.get_next_carton_sequence(tenant_id, str(pl["container_id"]))
        repo.delete_items_by_packing_list(tenant_id, pl_id)

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
        updated_cbm = sum((Decimal(str(r["cbm"])) for r in item_rows), Decimal("0"))
        _assert_container_capacity(tenant_id, container, updated_cbm, exclude_pl_id=pl_id)
        inserted_items = [r for r in repo.insert_packing_list_items(tenant_id, item_rows) if r is not None]

        repo.set_packing_list_dates(tenant_id, pl_id, loading_date, delivery_date)
        repo.set_packing_list_warehouse(tenant_id, pl_id, arrival_warehouse_id)

        updated_pl: dict[str, Any]
        if current_status == "rejected":
            _result = repo.set_packing_list_status(tenant_id, pl_id, "draft", expected_status="rejected")
            if _result is None:
                raise BusinessRuleViolationError(
                    "Packing list status changed concurrently — reload and retry.",
                    rule_id="INVALID_UPDATE_STATUS",
                )
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
    _assert_container_loading(tenant_id, pl)

    items = repo.list_packing_list_items(tenant_id, pl_id)
    if not items:
        raise BusinessRuleViolationError(
            "Cannot submit an empty packing list — add at least one item first.",
            rule_id="EMPTY_PACKING_LIST",
        )

    updated = repo.update_packing_list_status(tenant_id, pl_id, "pending_approval")
    if updated is None:
        raise BusinessRuleViolationError(
            "Packing list is no longer in draft status.",
            rule_id="INVALID_TRANSITION",
        )

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


def _apply_approval_db_writes(
    tenant_id: str,
    pl: dict[str, Any],
) -> tuple[str, list[str], int]:
    """Tenant-scoped DB writes for an approved packing list (safe inside tenant_transaction)."""
    container_id = str(pl["container_id"])
    manifest = repo.get_manifest_by_container(tenant_id, container_id)
    if not manifest:
        manifest = repo.create_manifest(tenant_id, container_id)
    if manifest is None:
        raise RuntimeError("create_manifest returned None unexpectedly")
    manifest_id = str(manifest["id"])

    repo.link_manifest(tenant_id, str(pl["id"]), manifest_id)
    repo.recalculate_manifest_totals(tenant_id, manifest_id)
    repo.reset_manifest_verification_if_verified(tenant_id, manifest_id)

    items = repo.get_items_by_packing_list(tenant_id, str(pl["id"]))
    seen_codes: set[str] = set()
    for item in items:
        code = item.get("tracking_code")
        if code and code not in seen_codes:
            repo.upsert_shipment_tracking(tenant_id, code)
            seen_codes.add(code)
    carton_count = sum(int(i.get("quantity") or 1) for i in items)
    return manifest_id, list(seen_codes), carton_count


def _emit_approval_notifications(
    tenant_id: str,
    pl: dict[str, Any],
    manifest_id: str,
    tracking_codes: list[str],
    carton_count: int,
    actor_id: str,
    request_id: str = "",
) -> None:
    """Post-commit events and notifications for an approved packing list."""
    publish_event(
        source="logistics.packing_list",
        detail_type="PackingListApproved",
        tenant_id=tenant_id,
        payload={
            "packing_list_id": str(pl["id"]),
            "container_id": str(pl["container_id"]),
            "customer_id": str(pl["customer_id"]),
            "manifest_id": manifest_id,
            "approved_by": actor_id,
            "carton_count": carton_count,
            "tracking_codes": tracking_codes,
        },
        request_id=request_id,
    )
    _notify_customer_packing_list_approved(tenant_id, pl, request_id)


def _apply_approval_side_effects(
    tenant_id: str,
    pl: dict[str, Any],
    actor_id: str,
    request_id: str = "",
) -> tuple[str, list[str]]:
    """Everything that must happen when a packing list becomes approved."""
    manifest_id, tracking_codes, carton_count = _apply_approval_db_writes(tenant_id, pl)
    _emit_approval_notifications(tenant_id, pl, manifest_id, tracking_codes, carton_count, actor_id, request_id)
    return manifest_id, tracking_codes


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

    _assert_container_loading(tenant_id, pl)

    with tenant_transaction(tenant_id):
        updated = repo.approve_packing_list_row(tenant_id, pl_id, actor_id)
        if updated is None:
            raise BusinessRuleViolationError(
                "Packing list is no longer pending approval.",
                rule_id="INVALID_TRANSITION",
            )
        manifest_id, tracking_codes, carton_count = _apply_approval_db_writes(tenant_id, pl)

    _emit_approval_notifications(tenant_id, pl, manifest_id, tracking_codes, carton_count, actor_id, request_id)
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

    return _assemble_response({**dict(updated), "manifest_id": manifest_id}, items)


def bulk_approve_packing_lists(
    tenant_id: str,
    req: BulkApproveRequest,
    actor_id: str,
    ctx: Any,
    request_id: str = "",
    ip_address: str | None = None,
) -> dict[str, Any]:
    """Approve multiple packing lists in one call."""
    ctx.assert_role(UserRole.CHINA_OFFICE_STAFF, UserRole.TENANT_ADMIN)

    unique_ids = list(dict.fromkeys(req.ids))
    pls = repo.get_packing_lists_by_ids(tenant_id, unique_ids)
    pl_map = {str(pl["id"]): pl for pl in pls}

    succeeded: list[str] = []
    failed: list[dict[str, Any]] = []

    container_status_cache: dict[str, str | None] = {}
    approvable_ids: list[str] = []
    for pl_id in unique_ids:
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
        cid = pl.get("container_id")
        if cid:
            cid_str = str(cid)
            if cid_str not in container_status_cache:
                cont = repo.get_container_by_id(tenant_id, cid_str)
                container_status_cache[cid_str] = cont.get("status") if cont else None
            c_status = container_status_cache[cid_str]
            if c_status is not None and c_status != "loading":
                failed.append({"id": pl_id, "reason": f"container_not_loading:{c_status}"})
                continue
        approvable_ids.append(pl_id)

    if approvable_ids:
        post_commit_effects: list[tuple[dict[str, Any], str, list[str], int]] = []
        with tenant_transaction(tenant_id):
            updated_rows = repo.bulk_set_status(
                tenant_id, approvable_ids, "approved", actor_id, expected_status="pending_approval"
            )
            if isinstance(updated_rows, list):
                succeeded = [str(r["id"]) for r in updated_rows]
                missed = set(approvable_ids) - set(succeeded)
                for missed_id in approvable_ids:
                    if missed_id in missed:
                        failed.append({"id": missed_id, "reason": "concurrent_status_change"})
            else:
                succeeded = approvable_ids

            for pl_id_done in succeeded:
                m_id, t_codes, c_cnt = _apply_approval_db_writes(tenant_id, pl_map[pl_id_done])
                post_commit_effects.append((pl_map[pl_id_done], m_id, t_codes, c_cnt))

        for pl_row, m_id, t_codes, c_cnt in post_commit_effects:
            _emit_approval_notifications(tenant_id, pl_row, m_id, t_codes, c_cnt, actor_id, request_id)

        for pl_id_done in succeeded:
            log_audit(
                tenant_id=tenant_id,
                entity_type="packing_list",
                entity_id=pl_id_done,
                action="BULK_APPROVE",
                actor_id=actor_id,
                actor_role=str(ctx.role),
                before_state={"status": "pending_approval"},
                after_state={"status": "approved"},
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
    """Move multiple draft packing lists to pending_approval in one call."""
    ctx.assert_role(UserRole.CHINA_OFFICE_STAFF, UserRole.TENANT_ADMIN, UserRole.NIGERIA_OFFICE_STAFF)

    unique_ids = list(dict.fromkeys(req.ids))
    pls = repo.get_packing_lists_by_ids(tenant_id, unique_ids)
    pl_map = {str(pl["id"]): pl for pl in pls}

    succeeded: list[str] = []
    failed: list[dict[str, Any]] = []

    container_status_cache: dict[str, str | None] = {}
    submittable_ids: list[str] = []
    for pl_id in unique_ids:
        pl = pl_map.get(pl_id)
        if not pl:
            failed.append({"id": pl_id, "reason": "not_found"})
            continue
        if pl["status"] != "draft":
            failed.append({"id": pl_id, "reason": f"wrong_status:{pl['status']}"})
            continue
        cid = pl.get("container_id")
        if cid:
            cid_str = str(cid)
            if cid_str not in container_status_cache:
                cont = repo.get_container_by_id(tenant_id, cid_str)
                container_status_cache[cid_str] = cont.get("status") if cont else None
            c_status = container_status_cache[cid_str]
            if c_status is not None and c_status != "loading":
                failed.append({"id": pl_id, "reason": f"container_not_loading:{c_status}"})
                continue
        submittable_ids.append(pl_id)

    if submittable_ids:
        updated_rows = repo.bulk_set_status(tenant_id, submittable_ids, "pending_approval", actor_id, expected_status="draft")
        if isinstance(updated_rows, list):
            succeeded = [str(r["id"]) for r in updated_rows]
            missed = set(submittable_ids) - set(succeeded)
            for missed_id in submittable_ids:
                if missed_id in missed:
                    failed.append({"id": missed_id, "reason": "concurrent_status_change"})
        else:
            succeeded = submittable_ids

        for pl_id_done in succeeded:
            log_audit(
                tenant_id=tenant_id,
                entity_type="packing_list",
                entity_id=pl_id_done,
                action="BULK_SUBMIT",
                actor_id=actor_id,
                actor_role=str(ctx.role),
                before_state={"status": "draft"},
                after_state={"status": "pending_approval"},
                ip_address=ip_address,
            )
        if succeeded:
            for role in ("china_office_staff", "tenant_admin"):
                notify_staff(
                    tenant_id=tenant_id,
                    event_type="packing_list_submitted",
                    entity_type="packing_list",
                    entity_id=None,
                    title="Packing lists awaiting approval",
                    body=f"{len(succeeded)} packing list(s) need approval.",
                    target_role=role,
                )

    return {"succeeded": succeeded, "failed": failed, "total": len(unique_ids)}


def bulk_reject_packing_lists(
    tenant_id: str,
    req: BulkRejectRequest,
    actor_id: str,
    ctx: Any,
    ip_address: str | None = None,
) -> dict[str, Any]:
    """Reject multiple packing lists in one call."""
    ctx.assert_role(UserRole.CHINA_OFFICE_STAFF, UserRole.TENANT_ADMIN)

    unique_ids = list(dict.fromkeys(req.ids))
    pls = repo.get_packing_lists_by_ids(tenant_id, unique_ids)
    pl_map = {str(pl["id"]): pl for pl in pls}

    succeeded: list[str] = []
    failed: list[dict[str, Any]] = []

    container_status_cache: dict[str, str | None] = {}
    rejectable_ids: list[str] = []
    for pl_id in unique_ids:
        pl = pl_map.get(pl_id)
        if not pl:
            failed.append({"id": pl_id, "reason": "not_found"})
            continue
        if pl["status"] != "pending_approval":
            failed.append({"id": pl_id, "reason": f"wrong_status:{pl['status']}"})
            continue
        cid = pl.get("container_id")
        if cid:
            cid_str = str(cid)
            if cid_str not in container_status_cache:
                cont = repo.get_container_by_id(tenant_id, cid_str)
                container_status_cache[cid_str] = cont.get("status") if cont else None
            c_status = container_status_cache[cid_str]
            if c_status is not None and c_status != "loading":
                failed.append({"id": pl_id, "reason": f"container_not_loading:{c_status}"})
                continue
        rejectable_ids.append(pl_id)

    if rejectable_ids:
        comment_entry = json.dumps(
            [{"actor_id": actor_id, "comments": req.comments, "item_rejections": [], "at": datetime.now(UTC).isoformat()}]
        )
        updated_rows = repo.bulk_set_status(
            tenant_id,
            rejectable_ids,
            "rejected",
            actor_id,
            expected_status="pending_approval",
            approval_comments_json=comment_entry,
        )
        if isinstance(updated_rows, list):
            succeeded = [str(r["id"]) for r in updated_rows]
            missed = set(rejectable_ids) - set(succeeded)
            for missed_id in rejectable_ids:
                if missed_id in missed:
                    failed.append({"id": missed_id, "reason": "concurrent_status_change"})
        else:
            succeeded = rejectable_ids

        for pl_id_done in succeeded:
            log_audit(
                tenant_id=tenant_id,
                entity_type="packing_list",
                entity_id=pl_id_done,
                action="BULK_REJECT",
                actor_id=actor_id,
                actor_role=str(ctx.role),
                before_state={"status": "pending_approval"},
                after_state={"status": "rejected", "comments": req.comments},
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
    _assert_container_loading(tenant_id, pl)

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
        "at": datetime.now(UTC).isoformat(),
    }
    updated_comments = existing_comments + [new_entry]

    items = repo.get_items_by_packing_list(tenant_id, pl_id)

    updated = repo.reject_packing_list_row(
        tenant_id,
        pl_id,
        actor_id,
        json.dumps(updated_comments),
    )
    if updated is None:
        raise BusinessRuleViolationError(
            "Packing list is no longer pending approval.",
            rule_id="INVALID_TRANSITION",
        )

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
