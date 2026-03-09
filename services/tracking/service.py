"""Business logic for the Tracking service.

Handles container CRUD, the 8-stage container state machine, bulk shipment
tracking updates, billing event triggers, and customer-facing tracking lookup.
"""

import logging
from typing import Any

from services.metering.service import check_container_limit
from shared.audit import log_audit
from shared.events import publish_event
from shared.exceptions import (
    BusinessRuleViolationError,
    IllegalTransitionError,
    ResourceNotFoundError,
)
from shared.tenant_context import UserRole

from . import repository as repo
from .models import TrackingStage

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# State machine constants
# ---------------------------------------------------------------------------

_NEXT_STATE: dict[str, str] = {
    "loading": "sealed",
    "sealed": "in_transit",
    "in_transit": "arrived",
    "arrived": "customs_clearance",
    "customs_clearance": "cleared",
    "cleared": "at_warehouse",
    "at_warehouse": "fully_released",
}

# Roles allowed to transition FROM these container statuses
_CHINA_FROM = {"loading", "sealed"}
_NIGERIA_FROM = {"in_transit", "arrived", "customs_clearance", "cleared"}

# Container new_status → shipment_tracking.status (DB CHECK constraint values)
_CONTAINER_TO_TRACKING_STATUS: dict[str, str] = {
    "in_transit": "in_transit",
    "arrived": "arrived_port",
    "customs_clearance": "customs_clearance",
    "cleared": "at_warehouse",
    "at_warehouse": "ready_for_pickup",
    "fully_released": "released",
}

# Container new_status → tracking_event.to_status (TrackingStage enum labels)
_CONTAINER_TO_STAGE_LABEL: dict[str, str] = {
    "in_transit": "in_transit",
    "arrived": "arrived_nigeria",
    "customs_clearance": "customs_clearance",
    "cleared": "cleared",
    "at_warehouse": "ready_for_pickup",
    "fully_released": "picked_up",
}

# shipment_tracking.status DB value → TrackingStage (for customer-facing response)
_STATUS_TO_STAGE: dict[str, str] = {
    "received": TrackingStage.received_china.value,
    "in_transit": TrackingStage.in_transit.value,
    "arrived_port": TrackingStage.arrived_nigeria.value,
    "customs_clearance": TrackingStage.customs_clearance.value,
    "at_warehouse": TrackingStage.cleared.value,
    "ready_for_pickup": TrackingStage.ready_for_pickup.value,
    "released": TrackingStage.picked_up.value,
}


# ---------------------------------------------------------------------------
# Container operations
# ---------------------------------------------------------------------------


def create_container(
    tenant_id: str,
    data: dict[str, Any],
    actor_id: str,
    request_id: str = "",
    ip_address: str | None = None,
) -> dict[str, Any]:
    if not data.get("container_number"):
        raise BusinessRuleViolationError("container_number is required", rule_id="MISSING_CONTAINER_NUMBER")
    check_container_limit(tenant_id)
    row = repo.create_container(
        tenant_id,
        {
            "tenant_id": tenant_id,
            "container_number": data.get("container_number"),
            "parcel_number": data.get("parcel_number"),
            "origin": data.get("origin", "China"),
            "destination": data.get("destination", "Nigeria"),
            "estimated_arrival_date": data.get("estimated_arrival_date"),
            "notes": data.get("notes"),
            "created_by": actor_id,
        },
    )
    if row is None:
        raise RuntimeError("create_container returned None unexpectedly")
    log_audit(
        tenant_id=tenant_id,
        entity_type="container",
        entity_id=str(row["id"]),
        action="CREATE",
        actor_id=actor_id,
        actor_role=str(UserRole.CHINA_OFFICE_STAFF),
        after_state={"container_number": data.get("container_number")},
        ip_address=ip_address,
    )
    return row


def get_container(tenant_id: str, container_id: str) -> dict[str, Any]:
    container = repo.get_container_by_id(tenant_id, container_id)
    if not container:
        raise ResourceNotFoundError("container", container_id)
    return container


def list_containers(
    tenant_id: str,
    filters: dict[str, Any],
    limit: int,
    cursor: dict[str, Any] | None,
) -> tuple[list[dict[str, Any]], str | None, bool]:
    return repo.list_containers(tenant_id, filters, limit, cursor)


def update_container_status(
    tenant_id: str,
    container_id: str,
    new_status: str,
    extra: dict[str, Any],
    actor_id: str,
    ctx: Any,
    request_id: str = "",
    ip_address: str | None = None,
) -> dict[str, Any]:
    container = repo.get_container_by_id(tenant_id, container_id)
    if not container:
        raise ResourceNotFoundError("container", container_id)

    current = container["status"]
    expected_next = _NEXT_STATE.get(current)
    if new_status != expected_next:
        raise IllegalTransitionError(
            entity="container",
            current_state=current,
            requested_state=new_status,
            allowed=[expected_next] if expected_next else [],
        )

    # Role-based stage authorization
    if current in _CHINA_FROM:
        ctx.assert_role(UserRole.CHINA_OFFICE_STAFF, UserRole.TENANT_ADMIN)
    elif current in _NIGERIA_FROM:
        ctx.assert_role(UserRole.NIGERIA_OFFICE_STAFF, UserRole.TENANT_ADMIN)
    # at_warehouse → fully_released is system/auto — allow TENANT_ADMIN or WAREHOUSE_ATTENDANT
    elif current == "at_warehouse":
        ctx.assert_role(UserRole.TENANT_ADMIN, UserRole.WAREHOUSE_ATTENDANT)

    # Pre-transition guard for sealed
    if new_status == "sealed":
        approved_count = repo.count_approved_packing_lists(tenant_id, container_id)
        if approved_count < 1:
            raise BusinessRuleViolationError(
                "Container must have at least 1 approved packing list before sealing",
                rule_id="NO_APPROVED_PACKING_LISTS",
            )
        manifest = repo.get_manifest_for_container(tenant_id, container_id)
        if not manifest:
            raise BusinessRuleViolationError(
                "Container must have a manifest before sealing",
                rule_id="NO_MANIFEST",
            )

    # in_transit requires ship_date
    if new_status == "in_transit" and not extra.get("ship_date"):
        raise BusinessRuleViolationError(
            "ship_date is required when transitioning to in_transit",
            rule_id="MISSING_SHIP_DATE",
        )

    # Update container row
    updated = repo.update_container_status(tenant_id, container_id, new_status, extra)
    if updated is None:
        raise RuntimeError("update_container_status returned None unexpectedly")

    # Bulk tracking side effects
    tracking_status = _CONTAINER_TO_TRACKING_STATUS.get(new_status)
    stage_label = _CONTAINER_TO_STAGE_LABEL.get(new_status)
    notes = extra.get("notes")

    if tracking_status:
        repo.bulk_update_tracking_status(tenant_id, container_id, tracking_status)
        repo.bulk_insert_tracking_events(tenant_id, container_id, stage_label or "", notes, actor_id)

    # Billing trigger when container cleared
    if new_status == "cleared":
        customers = repo.get_customers_for_container(tenant_id, container_id)
        for customer in customers:
            try:
                publish_event(
                    source="logistics.tracking",
                    detail_type="PaymentDue",
                    tenant_id=tenant_id,
                    payload={
                        "container_id": container_id,
                        "container_number": container.get("container_number"),
                        "customer_id": customer["id"],
                        "customer_name": customer.get("name"),
                    },
                    request_id=request_id,
                )
            except Exception:
                logger.exception("Failed to publish PaymentDue for customer %s", customer["id"])

    # Main container event
    publish_event(
        source="logistics.tracking",
        detail_type="ContainerStatusUpdated",
        tenant_id=tenant_id,
        payload={
            "container_id": container_id,
            "container_number": container.get("container_number"),
            "from_status": current,
            "to_status": new_status,
        },
        request_id=request_id,
    )

    log_audit(
        tenant_id=tenant_id,
        entity_type="container",
        entity_id=container_id,
        action="STATUS_CHANGE",
        actor_id=actor_id,
        actor_role=str(ctx.role),
        before_state={"status": current},
        after_state={"status": new_status},
        ip_address=ip_address,
    )

    return dict(updated)


# ---------------------------------------------------------------------------
# Shipment tracking operations
# ---------------------------------------------------------------------------


def list_shipments(
    tenant_id: str,
    filters: dict[str, Any],
    limit: int,
    cursor: dict[str, Any] | None,
    ctx: Any,
) -> tuple[list[dict[str, Any]], str | None, bool]:
    if ctx.role == UserRole.CUSTOMER:
        customer = repo.get_customer_by_user_id(tenant_id, ctx.user_id)
        if not customer:
            return [], None, False
        return repo.list_customer_shipments(tenant_id, str(customer["id"]), limit, cursor)
    return repo.list_shipments(tenant_id, filters, limit, cursor)


def get_shipment_by_code_and_phone(tracking_code: str, phone: str) -> dict[str, Any]:
    """Public tracking lookup — no JWT required; phone used for ownership verification."""
    row = repo.get_shipment_by_tracking_code_and_phone(tracking_code, phone)
    if not row:
        raise ResourceNotFoundError("shipment_tracking", tracking_code)

    events = repo.get_tracking_events(str(row["id"]))

    current_stage = _STATUS_TO_STAGE.get(row["status"], row["status"])
    stage_history = [
        {
            "stage": _STATUS_TO_STAGE.get(e["to_status"], e["to_status"]),
            "occurred_at": e["created_at"],
            "notes": e.get("description"),
        }
        for e in events
        if e.get("to_status")
    ]

    # Extract company_name (may be in branding_config or company_name column)
    company_name = row.get("company_name")
    branding = row.get("branding_config") or {}
    if isinstance(branding, dict):
        company_name = branding.get("display_name") or company_name

    return {
        "tracking_code": row["tracking_code"],
        "current_stage": current_stage,
        "company_name": company_name,
        "stage_history": stage_history,
        "estimated_stages": None,
    }
