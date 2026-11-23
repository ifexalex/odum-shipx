"""Business logic for the Tracking service.

Handles container CRUD, the 8-stage container state machine, bulk shipment
tracking updates, billing event triggers, and customer-facing tracking lookup.
"""

import logging
import math
import re
from typing import Any

from services.billing.service import generate_container_invoices
from services.metering.service import check_container_limit
from shared import uploads
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
# A tenant's brand colour as the public tracking page may use it: a plain #rrggbb value and nothing else, since the
# page puts it into a style (FD-28).
_HEX_COLOR = re.compile(r"^#[0-9a-fA-F]{6}$")
_ALLOWED_DOCUMENT_TYPES = frozenset({"bill_of_lading", "customs_certificate", "insurance", "inspection_report", "other"})

logger = logging.getLogger(__name__)


def _positive_or_none(value: Any) -> float | None:
    """Coerce a capacity/recommended CBM input to a finite positive float, else None."""
    try:
        num = float(value)
    except (TypeError, ValueError):
        return None
    return num if math.isfinite(num) and num > 0 else None


def _is_customer_only(ctx: Any) -> bool:
    return bool(getattr(ctx, "is_customer_only", ctx.role == UserRole.CUSTOMER))


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
    ctx: Any = None,
) -> None:
    """Hard-delete a container that was created by mistake."""
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
        actor_role=str(ctx.role) if ctx is not None else "china_office_staff",
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
    ctx: Any = None,
) -> dict[str, Any]:
    """Soft-cancel a container — sets status to 'cancelled', a terminal state."""
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
        raise BusinessRuleViolationError(
            "Container is no longer in a cancellable status.",
            rule_id="CONTAINER_NOT_CANCELLABLE",
        )

    repo.insert_container_event(tenant_id, container_id, container["status"], "cancelled", actor_id, notes)

    try:
        customers = repo.get_customers_for_container(tenant_id, container_id)
        for customer in customers:
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
                    "status": "cancelled",
                },
                locale=customer.get("locale", "en"),
                request_id=request_id,
                customer_id=str(customer["id"]),
            )
            if customer.get("user_id"):
                notify_staff(
                    tenant_id=tenant_id,
                    event_type="shipment_update",
                    entity_type="container",
                    entity_id=container_id,
                    title="Shipment cancelled",
                    body=f"Container {container.get('container_number', '')} has been cancelled.",
                    target_user_id=str(customer["user_id"]),
                )
    except Exception:
        logger.exception("Failed to notify customers on container cancellation")

    log_audit(
        tenant_id=tenant_id,
        actor_id=actor_id,
        actor_role=str(ctx.role) if ctx is not None else "china_office_staff",
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

    # Role-based stage authorization BEFORE transition validation so unauthorized
    # callers receive 403 InsufficientPermissionsError instead of 409 state details.
    if current in _CHINA_FROM:
        ctx.assert_role(UserRole.CHINA_OFFICE_STAFF, UserRole.TENANT_ADMIN)
    elif current in _NIGERIA_FROM:
        ctx.assert_role(UserRole.NIGERIA_OFFICE_STAFF, UserRole.TENANT_ADMIN)
    elif current == "at_warehouse":
        ctx.assert_role(UserRole.TENANT_ADMIN, UserRole.WAREHOUSE_ATTENDANT)

    expected_next = _NEXT_STATE.get(current)
    if new_status != expected_next:
        raise IllegalTransitionError(
            entity="container",
            current_state=current,
            requested_state=new_status,
            allowed=[expected_next] if expected_next else [],
        )

    # Pre-transition guard for sealed
    if new_status == "sealed":
        approved_count = repo.count_approved_packing_lists(tenant_id, container_id)
        if approved_count < 1:
            raise BusinessRuleViolationError(
                "Container must have at least 1 approved packing list before sealing",
                rule_id="NO_APPROVED_PACKING_LISTS",
            )
        unapproved_count = repo.count_unapproved_packing_lists(tenant_id, container_id)
        if unapproved_count > 0:
            raise BusinessRuleViolationError(
                f"Container has {unapproved_count} unapproved packing list(s) — approve or reject all before sealing",
                rule_id="UNAPPROVED_PACKING_LISTS_REMAIN",
            )
        manifest = repo.get_manifest_for_container(tenant_id, container_id)
        if not manifest:
            raise BusinessRuleViolationError(
                "Container must have a manifest before sealing",
                rule_id="NO_MANIFEST",
            )
        if manifest.get("verification_status") not in ("verified", "resolved"):
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

    # at_warehouse → fully_released requires all billed cartons to have been collected
    if new_status == "fully_released":
        unreleased_cartons = repo.count_unreleased_cartons_for_container(tenant_id, container_id)
        if unreleased_cartons > 0:
            raise BusinessRuleViolationError(
                f"Container still has {unreleased_cartons} uncollected carton(s) — record pickup before marking fully released",
                rule_id="UNRELEASED_CARTONS_REMAIN",
            )

    # Update container row
    updated = repo.update_container_status(tenant_id, container_id, new_status, extra)
    if updated is None:
        raise BusinessRuleViolationError(
            "Container status changed concurrently — reload and retry.",
            rule_id="CONCURRENT_STATUS_CHANGE",
        )

    repo.insert_container_event(
        tenant_id=tenant_id,
        container_id=container_id,
        from_status=current,
        to_status=new_status,
        actor_id=actor_id,
        notes=extra.get("notes"),
    )

    # Bulk tracking side effects — insert tracking_event BEFORE updating shipment_tracking.status
    # so tracking_event.from_status records the true prior status rather than the new status.
    tracking_status = _CONTAINER_TO_TRACKING_STATUS.get(new_status)
    stage_label = _CONTAINER_TO_STAGE_LABEL.get(new_status)
    notes = extra.get("notes")

    if tracking_status:
        repo.bulk_insert_tracking_events(tenant_id, container_id, stage_label or "", notes, actor_id)
        repo.bulk_update_tracking_status(tenant_id, container_id, tracking_status)

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
                    customer_id=str(customer["id"]),
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
    # never actually invoked: there is no rule/target wiring EventBridge to
    # invoke the billing Lambda. So a container could sail all the way through `cleared`
    # → `at_warehouse` with zero billing rows ever created, in both local dev
    # and production. Call the billing generation directly (cross-service
    # import already has precedent — see check_container_limit above and
    # claims/service.py's refunds import) so billing exists the moment the
    # container clears, regardless of whether the event infra is ever fixed.
    # The event publish stays for metering (the bus's only target). The
    # "payment due" message is enqueued directly by handle_payment_due; no
    # EventBridge rule feeds a notification queue (audit BE-09).
    billing_summary: list[dict[str, Any]] | None = None
    if new_status == "cleared":
        customers = repo.get_customers_for_container(tenant_id, container_id)
        billing_summary = generate_container_invoices(
            tenant_id=tenant_id,
            container_id=container_id,
            container_number=container.get("container_number"),
            customers=customers,
            request_id=request_id,
        )
        invoiced = {row["customer_id"] for row in billing_summary if row["status"] == "created"}
        for customer in customers:
            if str(customer["id"]) not in invoiced:
                continue
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

    result = dict(updated)
    if billing_summary is not None:
        # Per-customer invoice outcome, so staff see who was billed, who already
        # had an invoice, and who was skipped or failed (and why) at the moment
        # of clearing rather than discovering it later.
        result["billing_summary"] = billing_summary
    return result


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
    if _is_customer_only(ctx):
        customer = repo.get_customer_by_user_id(tenant_id, ctx.user_id)
        if not customer:
            return [], None, False
        if filters:
            return repo.list_customer_shipments(tenant_id, str(customer["id"]), limit, cursor, filters=filters)
        return repo.list_customer_shipments(tenant_id, str(customer["id"]), limit, cursor)
    return repo.list_shipments(tenant_id, filters, limit, cursor)


def _phone_match_candidates(phone: str) -> list[str]:
    """Every form of `phone` worth matching a stored customer number against.

    Normalises local-format numbers across all supported destination dial codes
    (`shared.phone._DIAL_CODES`) so non-Nigerian tenants (Ghana, Kenya, etc.)
    match E.164 records on public tracking just like Nigerian tenants.
    """
    from shared.phone import _DIAL_CODES, DEFAULT_DIAL_CODE, normalize_phone

    candidates: list[str] = []
    for dial in (DEFAULT_DIAL_CODE, *_DIAL_CODES.values()):
        normalized = normalize_phone(phone, dial_code=dial)
        if normalized and normalized not in candidates:
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
    brand_color: str | None = None
    branding = row.get("branding_config") or {}
    if isinstance(branding, dict):
        company_name = branding.get("display_name") or company_name
        # Returned only after the code and phone matched, like the name: the code alone says nothing about the tenant.
        color = branding.get("primary_color")
        brand_color = color if isinstance(color, str) and _HEX_COLOR.match(color) else None

    return {
        "tracking_code": row["tracking_code"],
        "current_stage": current_stage,
        "company_name": company_name,
        "brand_color": brand_color,
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
    size_bytes: object = None,
) -> dict[str, Any]:
    """Generate an S3 presigned POST URL for uploading a container document.

    Validates container exists and document_type is allowed.
    S3 key is scoped to {tenant_id}/containers/{container_id}/ to enforce
    tenant isolation. The document row is unconfirmed, and not listed, until
    the browser calls `confirm_document_upload` after the upload.
    """
    uploads.CONTAINER_DOCUMENT.check(content_type, size_bytes)
    if document_type not in _ALLOWED_DOCUMENT_TYPES:
        from shared.exceptions import BusinessRuleViolationError

        raise BusinessRuleViolationError(
            f"document_type '{document_type}' not allowed. Allowed: {', '.join(sorted(_ALLOWED_DOCUMENT_TYPES))}",
            rule_id="INVALID_DOCUMENT_TYPE",
        )

    container = repo.get_container_by_id(tenant_id, container_id)
    if not container:
        raise ResourceNotFoundError("container", container_id)

    upload = uploads.presign_upload(
        uploads.CONTAINER_DOCUMENT, tenant_id, ("containers", container_id), filename, content_type, size_bytes
    )
    s3_key = upload.key
    filename = upload.filename

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
        **upload.as_response(),
        "document_id": str(doc["id"]) if doc else None,
        "s3_key": s3_key,
        "expires_in_seconds": upload.expires_in,
    }


def confirm_document_upload(
    tenant_id: str,
    container_id: str,
    doc_id: str,
    actor_id: str,
    actor_role: str,
    ip_address: str | None = None,
) -> dict[str, Any]:
    """Confirm a container document landed: check its stored size, then list it.

    A file over the limit (possible on Azure, where the upload URL cannot bind the length) is deleted with its row.
    Confirming an already confirmed document returns it unchanged.

    Raises:
        ResourceNotFoundError: The container or the document is not the tenant's.
        BusinessRuleViolationError: ``UPLOAD_NOT_FOUND`` or ``FILE_TOO_LARGE``.
    """
    if not repo.get_container_by_id(tenant_id, container_id):
        raise ResourceNotFoundError("container", container_id)
    doc = repo.get_container_document_by_id(tenant_id, container_id, doc_id, include_unconfirmed=True)
    if not doc:
        raise ResourceNotFoundError("container_document", doc_id)
    if doc.get("confirmed_at") is None:
        try:
            size = uploads.confirm_stored_upload(uploads.CONTAINER_DOCUMENT, str(doc["s3_key"]))
        except BusinessRuleViolationError as exc:
            if exc.rule_id == "FILE_TOO_LARGE":
                logger.warning("Container document over the size limit deleted at confirmation (container_id=%s)", container_id)
                repo.delete_unconfirmed_container_document(tenant_id, container_id, doc_id)
            raise
        doc = repo.confirm_container_document(tenant_id, container_id, doc_id, size) or doc
        log_audit(
            tenant_id=tenant_id,
            entity_type="container_document",
            entity_id=doc_id,
            action="CREATE",
            actor_id=actor_id,
            actor_role=actor_role,
            after_state={"container_id": container_id, "document_type": doc["document_type"], "file_size_bytes": size},
            ip_address=ip_address,
        )
    return doc


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
