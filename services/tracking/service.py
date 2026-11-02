"""Business logic for the Tracking service.

Handles container CRUD, the 8-stage container state machine, bulk shipment
tracking updates, billing event triggers, and customer-facing tracking lookup.
"""

import logging
from typing import Any

from services.billing.service import handle_payment_due
from services.metering.service import check_container_limit
from shared.audit import log_audit
from shared.events import publish_event
from shared.exceptions import (
    BusinessRuleViolationError,
    IllegalTransitionError,
    ResourceNotFoundError,
)
from shared.notifications import enqueue_notifications
from shared.providers import get_storage_provider
from shared.staff_notifications import notify_staff
from shared.tenant_context import UserRole
from shared.validation import safe_filename
from shared.webhook import fire_tenant_webhook

from . import repository as repo
from .models import TrackingStage

_URL_EXPIRY = 900  # 15 minutes
_MAX_FILE_SIZE = 20 * 1024 * 1024  # 20 MB
_ALLOWED_DOCUMENT_TYPES = frozenset({"bill_of_lading", "customs_certificate", "insurance", "inspection_report", "other"})
_ALLOWED_CONTENT_TYPES = frozenset({"application/pdf", "image/jpeg", "image/png", "image/webp", "application/octet-stream"})

logger = logging.getLogger(__name__)


def _positive_or_none(value: Any) -> float | None:
    """Coerce a capacity/recommended CBM input to a positive float, else None.

    Guards the NUMERIC(>0) CHECK on container.capacity_cbm/recommended_cbm —
    blank, zero, negative or non-numeric input is stored as NULL (capacity
    simply unknown) rather than raising.
    """
    try:
        num = float(value)
    except (TypeError, ValueError):
        return None
    return num if num > 0 else None


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
            # Vessel/voyage manifest details (migration 030) — all optional.
            "vessel_name": data.get("vessel_name"),
            "voyage_number": data.get("voyage_number"),
            "shipping_line": data.get("shipping_line"),
            "seal_number": data.get("seal_number"),
            "container_type": data.get("container_type"),
            # Capacity preset snapshot (migration 051) — denormalised so the
            # utilization bar survives later edits/deletion of the preset.
            "capacity_cbm": _positive_or_none(data.get("capacity_cbm")),
            "recommended_cbm": _positive_or_none(data.get("recommended_cbm")),
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


def delete_container(
    tenant_id: str,
    container_id: str,
    actor_id: str,
    request_id: str = "",
    ip_address: str | None = None,
) -> None:
    """Hard-delete a container that was created by mistake.

    Rules (enforced here and on the frontend):
    - Status must be 'loading' (never sealed or beyond).
    - No packing lists may exist on the container.
    """
    container = repo.get_container_by_id(tenant_id, container_id)
    if not container:
        raise ResourceNotFoundError("container", container_id)

    if container["status"] != "loading":
        raise BusinessRuleViolationError(
            "Only containers in 'loading' status can be deleted.",
            rule_id="CONTAINER_NOT_DELETABLE",
        )

    pl_count = repo.count_all_packing_lists(tenant_id, container_id)
    if pl_count > 0:
        raise BusinessRuleViolationError(
            f"Cannot delete a container that has {pl_count} packing list(s). Cancel it instead.",
            rule_id="CONTAINER_HAS_PACKING_LISTS",
        )

    repo.delete_container(tenant_id, container_id)
    log_audit(
        tenant_id=tenant_id,
        actor_id=actor_id,
        actor_role="china_office_staff",
        action="DELETE",
        entity_type="container",
        entity_id=container_id,
        before_state={"container_number": container.get("container_number"), "status": container.get("status")},
        after_state=None,
        ip_address=ip_address,
    )


def cancel_container(
    tenant_id: str,
    container_id: str,
    actor_id: str,
    notes: str | None = None,
    request_id: str = "",
    ip_address: str | None = None,
) -> dict[str, Any]:
    """Soft-cancel a container — sets status to 'cancelled', a terminal state.

    Rules:
    - Only 'loading' or 'sealed' containers can be cancelled (China-side only,
      before the container goes to sea).
    """
    container = repo.get_container_by_id(tenant_id, container_id)
    if not container:
        raise ResourceNotFoundError("container", container_id)

    if container["status"] not in ("loading", "sealed"):
        raise BusinessRuleViolationError(
            "Only containers in 'loading' or 'sealed' status can be cancelled.",
            rule_id="CONTAINER_NOT_CANCELLABLE",
        )

    updated = repo.update_container_status(
        tenant_id,
        container_id,
        "cancelled",
        {"notes": notes} if notes else None,
    )
    if not updated:
        raise RuntimeError("cancel_container returned None unexpectedly")

    repo.insert_container_event(tenant_id, container_id, container["status"], "cancelled", actor_id, notes)

    log_audit(
        tenant_id=tenant_id,
        actor_id=actor_id,
        actor_role="china_office_staff",
        action="CANCEL",
        entity_type="container",
        entity_id=container_id,
        before_state={"status": container["status"]},
        after_state={"status": "cancelled"},
        ip_address=ip_address,
    )
    return updated


def get_container_stats(tenant_id: str) -> dict[str, int]:
    """Tenant-wide per-status container counts for the list stats row + chips."""
    return repo.get_container_stats(tenant_id)


def list_containers(
    tenant_id: str,
    filters: dict[str, Any],
    limit: int,
    cursor: dict[str, Any] | None,
    sort_field: str = "created_at",
    sort_direction: str = "DESC",
) -> tuple[list[dict[str, Any]], str | None, bool]:
    return repo.list_containers(tenant_id, filters, limit, cursor, sort_field, sort_direction)


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
        if manifest.get("verification_status") != "verified":
            raise BusinessRuleViolationError(
                "The manifest must be verified before the container can be sealed",
                rule_id="MANIFEST_NOT_VERIFIED",
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

    repo.insert_container_event(
        tenant_id=tenant_id,
        container_id=container_id,
        from_status=current,
        to_status=new_status,
        actor_id=actor_id,
        notes=extra.get("notes"),
    )

    # Bulk tracking side effects
    tracking_status = _CONTAINER_TO_TRACKING_STATUS.get(new_status)
    stage_label = _CONTAINER_TO_STAGE_LABEL.get(new_status)
    notes = extra.get("notes")

    if tracking_status:
        repo.bulk_update_tracking_status(tenant_id, container_id, tracking_status)
        repo.bulk_insert_tracking_events(tenant_id, container_id, stage_label or "", notes, actor_id)

    # Container arrival notification when goods reach the warehouse
    if new_status == "at_warehouse":
        customers = repo.get_customers_for_container(tenant_id, container_id)
        for customer in customers:
            try:
                enqueue_notifications(
                    tenant_id=tenant_id,
                    event_type="container_arrived",
                    recipient={
                        "phone": customer.get("phone", ""),
                        "email": customer.get("email", ""),
                        "whatsapp": customer.get("whatsapp", ""),
                        "name": customer.get("name", ""),
                    },
                    template_data={"container_number": container.get("container_number", "")},
                    locale=customer.get("locale", "en"),
                    request_id=request_id,
                )
                # In-app customer bell — see payment_release/service.py's
                # matching comment.
                if customer.get("user_id"):
                    notify_staff(
                        tenant_id=tenant_id,
                        event_type="container_arrived",
                        entity_type="container",
                        entity_id=container_id,
                        title="Your goods have arrived",
                        body=f"Container {container.get('container_number', '')} has arrived at the warehouse.",
                        target_user_id=str(customer["user_id"]),
                    )
            except Exception:
                logger.exception(
                    "Failed to enqueue ContainerArrived notification for customer %s",
                    customer["id"],
                )

    # Generic "your shipment status changed" notification for the other
    # customer-visible pipeline transitions. `at_warehouse` has its own
    # richer container_arrived notification above, and `cleared` is covered
    # by handle_payment_due's own payment_due notification below (a bare
    # "status changed" ping would be redundant with "here's what you owe").
    # Ground-truth gap found live, reported by the user while investigating
    # a separate missing notification on payment-claim rejection — asked to
    # check every notification in the app: `shipment_update` was defined
    # with full SMS/WhatsApp/email templates but no call site ever used it.
    if new_status in {"in_transit", "arrived", "customs_clearance", "fully_released"}:
        try:
            customers = repo.get_customers_for_container(tenant_id, container_id)
        except Exception:
            logger.exception("Failed to fetch customers for shipment_update notification")
            customers = []
        for customer in customers:
            try:
                enqueue_notifications(
                    tenant_id=tenant_id,
                    event_type="shipment_update",
                    recipient={
                        "phone": customer.get("phone", ""),
                        "email": customer.get("email", ""),
                        "whatsapp": customer.get("whatsapp", ""),
                        "name": customer.get("name", ""),
                    },
                    template_data={
                        "tracking_code": container.get("container_number", ""),
                        "status": new_status.replace("_", " "),
                    },
                    locale=customer.get("locale", "en"),
                    request_id=request_id,
                    customer_id=str(customer["id"]),
                )
                # In-app customer bell — see payment_release/service.py's
                # matching comment.
                if customer.get("user_id"):
                    notify_staff(
                        tenant_id=tenant_id,
                        event_type="shipment_update",
                        entity_type="container",
                        entity_id=container_id,
                        title="Shipment status update",
                        body=f"Your shipment {container.get('container_number', '')} is now {new_status.replace('_', ' ')}.",
                        target_user_id=str(customer["user_id"]),
                    )
            except Exception:
                logger.exception(
                    "Failed to enqueue shipment_update notification for customer %s",
                    customer["id"],
                )

    # Billing trigger when container cleared.
    #
    # Ground-truth fix: billing/handler.py's EventBridge branch (source=
    # logistics.tracking, detail-type=PaymentDue → auto-create billing) is
    # never actually invoked — infrastructure/aws/modules/eventbridge/main.tf's
    # routing rules only fan PaymentDue out to the SMS/WhatsApp notification
    # queues, there is no rule/target wiring EventBridge to invoke the billing
    # Lambda itself. So a container could sail all the way through `cleared`
    # → `at_warehouse` with zero billing rows ever created, in both local dev
    # and production. Call the billing generation directly (cross-service
    # import already has precedent — see check_container_limit above and
    # claims/service.py's refunds import) so billing exists the moment the
    # container clears, regardless of whether the event infra is ever fixed.
    # The event publish stays: it's what the SMS/WhatsApp routing rules key
    # off of for the "payment due" customer notification.
    if new_status == "cleared":
        customers = repo.get_customers_for_container(tenant_id, container_id)
        for customer in customers:
            try:
                handle_payment_due(
                    tenant_id=tenant_id,
                    container_id=container_id,
                    customer_id=str(customer["id"]),
                    container_number=container.get("container_number"),
                    request_id=request_id,
                )
            except Exception:
                logger.exception("Failed to generate billing for customer %s", customer["id"])
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

    # Outbound webhook — fire-and-forget, best-effort
    fire_tenant_webhook(
        tenant_id=tenant_id,
        event_type="container.status_updated",
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


def get_container_events(tenant_id: str, container_id: str) -> list[dict[str, Any]]:
    """Return the audit trail for a container's status history."""
    container = repo.get_container_by_id(tenant_id, container_id)
    if not container:
        raise ResourceNotFoundError("container", container_id)
    return repo.get_container_events(tenant_id, container_id)


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


def _phone_match_candidates(phone: str) -> list[str]:
    """Every form of `phone` worth matching a stored customer number against.

    The browser now submits E.164, but this endpoint is public: saved links, old
    clients and direct API callers still send whatever a human typed. Normalising
    here (rather than only in the UI) is what actually fixes the lookup.

    No tenant is known at this point — the tracking code spans tenants — so the
    platform default dial code (Nigeria) is used. The raw input is kept as a
    candidate too, both for rows written before normalisation existed and for a
    number from a country whose dial code the default would mangle.
    """
    from shared.phone import normalize_phone

    candidates = []
    normalized = normalize_phone(phone)
    if normalized:
        candidates.append(normalized)
    raw = (phone or "").strip()
    if raw and raw not in candidates:
        candidates.append(raw)
    return candidates


def get_shipment_by_code_and_phone(tracking_code: str, phone: str) -> dict[str, Any]:
    """Public tracking lookup — no JWT required; phone used for ownership verification."""
    row = repo.get_shipment_by_tracking_code_and_phone(tracking_code, _phone_match_candidates(phone))
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


# ---------------------------------------------------------------------------
# Container document presigned URL
# ---------------------------------------------------------------------------


def generate_document_presigned_url(
    tenant_id: str,
    container_id: str,
    filename: str,
    content_type: str,
    document_type: str,
    actor_id: str,
) -> dict[str, Any]:
    """Generate an S3 presigned POST URL for uploading a container document.

    Validates container exists and document_type is allowed.
    S3 key is scoped to {tenant_id}/containers/{container_id}/ to enforce
    tenant isolation.
    """
    if content_type not in _ALLOWED_CONTENT_TYPES:
        from shared.exceptions import BusinessRuleViolationError

        raise BusinessRuleViolationError(
            f"content_type '{content_type}' not allowed. Allowed: {', '.join(sorted(_ALLOWED_CONTENT_TYPES))}",
            rule_id="INVALID_CONTENT_TYPE",
        )
    if document_type not in _ALLOWED_DOCUMENT_TYPES:
        from shared.exceptions import BusinessRuleViolationError

        raise BusinessRuleViolationError(
            f"document_type '{document_type}' not allowed. Allowed: {', '.join(sorted(_ALLOWED_DOCUMENT_TYPES))}",
            rule_id="INVALID_DOCUMENT_TYPE",
        )

    container = repo.get_container_by_id(tenant_id, container_id)
    if not container:
        raise ResourceNotFoundError("container", container_id)

    filename = safe_filename(filename)
    s3_key = f"{tenant_id}/containers/{container_id}/{filename}"

    ticket = get_storage_provider().presigned_upload(s3_key, content_type=content_type, expires_in=_URL_EXPIRY)

    doc = repo.create_container_document(
        tenant_id,
        {
            "tenant_id": tenant_id,
            "container_id": container_id,
            "document_type": document_type,
            "s3_key": s3_key,
            "filename": filename,
            "content_type": content_type,
            "uploaded_by": actor_id,
        },
    )

    return {
        **ticket.as_response(),
        "document_id": str(doc["id"]) if doc else None,
        "s3_key": s3_key,
        "expires_in_seconds": _URL_EXPIRY,
    }


def list_container_documents(tenant_id: str, container_id: str) -> list[dict[str, Any]]:
    """Return all uploaded documents for a container."""
    container = repo.get_container_by_id(tenant_id, container_id)
    if not container:
        raise ResourceNotFoundError("container", container_id)
    return repo.list_container_documents(tenant_id, container_id)


def get_document_download_url(
    tenant_id: str,
    container_id: str,
    doc_id: str,
    actor_id: str,
    actor_role: str,
) -> dict[str, Any]:
    """Generate a short-lived S3 presigned GET URL for a container document.

    Returns 404 (never 403) for wrong-tenant/wrong-container docs to prevent
    enumeration. S3 key is validated against the tenant prefix before use.
    """
    container = repo.get_container_by_id(tenant_id, container_id)
    if not container:
        raise ResourceNotFoundError("container_document", doc_id)

    doc = repo.get_container_document_by_id(tenant_id, container_id, doc_id)
    if not doc:
        raise ResourceNotFoundError("container_document", doc_id)

    s3_key: str = doc["s3_key"]
    if not s3_key.startswith(f"{tenant_id}/"):
        raise ResourceNotFoundError("container_document", doc_id)

    disposition = f'attachment; filename="{safe_filename(doc["filename"], default="document")}"'
    presigned_url = get_storage_provider().presigned_get_url(s3_key, expires_in=300, response_content_disposition=disposition)

    log_audit(
        tenant_id=tenant_id,
        entity_type="container_document",
        entity_id=str(doc["id"]),
        action="EXPORT",
        actor_id=actor_id,
        actor_role=actor_role,
        after_state={"doc_id": doc_id, "container_id": container_id, "filename": doc["filename"]},
    )

    return {
        "download_url": presigned_url,
        "filename": doc["filename"],
        "content_type": doc.get("content_type"),
        "expires_in_seconds": 300,
    }
