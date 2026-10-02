"""Tracking Lambda handler.

Routes:
  POST  /v1/containers             — china_office_staff
  GET   /v1/containers             — china_office_staff, nigeria_office_staff, tenant_admin
  GET   /v1/containers/{id}        — same
  PATCH /v1/containers/{id}/status — china_office_staff (China stages), nigeria_office_staff (Nigeria stages)

  GET   /v1/shipments              — all authenticated roles (customer filtered to own)
  GET   /v1/shipments/{code}?phone — public customer lookup (no JWT required)
"""

import json
import logging
import time
import uuid
from typing import Any

from aws_xray_sdk.core import patch_all

from shared.auth import get_tenant_context
from shared.exceptions import LogisticsBaseError, ResourceNotFoundError
from shared.idempotency import check_idempotency, store_idempotency
from shared.logging_config import setup_logging
from shared.metering import record_usage
from shared.pagination import decode_cursor
from shared.responses import created, error_response, paginated, success
from shared.tenant_context import UserRole

from . import service

# Module-level init (runs once on cold start)
setup_logging()
patch_all()

logger = logging.getLogger(__name__)

_CONTAINER_READ_ROLES = (
    UserRole.CHINA_OFFICE_STAFF,
    UserRole.NIGERIA_OFFICE_STAFF,
    UserRole.TENANT_ADMIN,
)
_ALL_AUTH_ROLES = (
    UserRole.PLATFORM_ADMIN,
    UserRole.TENANT_ADMIN,
    UserRole.CHINA_OFFICE_STAFF,
    UserRole.NIGERIA_OFFICE_STAFF,
    UserRole.WAREHOUSE_ATTENDANT,
    UserRole.CUSTOMER,
)


# ---------------------------------------------------------------------------
# Lambda entry point
# ---------------------------------------------------------------------------


def lambda_handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
    start_time = time.time()
    request_id = event.get("requestContext", {}).get("requestId") or str(uuid.uuid4())
    http = event.get("requestContext", {}).get("http", {})
    method = http.get("method", "")
    path = http.get("path", "")
    ip_address = event.get("requestContext", {}).get("identity", {}).get("sourceIp")

    try:
        parts = path.strip("/").split("/")

        # Health check — no auth required
        if method == "GET" and path.strip("/") == "v1/health":
            return _handle_health_check(request_id)

        # Public customer tracking lookup — no JWT required
        if method == "GET" and len(parts) == 3 and parts[0] == "v1" and parts[1] == "shipments" and _qp(event, "phone"):
            response = _handle_public_tracking(event, parts[2], request_id)
            return response

        # All other routes require authentication
        tenant_ctx = get_tenant_context(event)
        logger.info(
            "→ %s %s",
            method,
            path,
            extra={"request_id": request_id, "tenant_id": tenant_ctx.tenant_id},
        )

        # Idempotency for POST requests
        idempotency_key = None
        if method == "POST":
            idempotency_key = (event.get("headers") or {}).get("idempotency-key")
            cached = check_idempotency(idempotency_key, tenant_ctx.tenant_id)
            if cached:
                return cached

        response = _dispatch(event, method, path, parts, tenant_ctx, request_id, ip_address)

        if method == "POST" and idempotency_key and response.get("statusCode", 500) < 400:
            store_idempotency(idempotency_key, response, tenant_ctx.tenant_id)

        record_usage(tenant_ctx.tenant_id, "api_calls", request_id=request_id)
        return response

    except LogisticsBaseError as exc:
        logger.warning("Business error: %s - %s", exc.error_code, exc.message)
        return error_response(exc, instance=path, request_id=request_id)
    except Exception:
        logger.exception("Unhandled error")
        return error_response(
            LogisticsBaseError("Internal server error", "INTERNAL_ERROR", 500),
            instance=path,
            request_id=request_id,
        )
    finally:
        duration_ms = (time.time() - start_time) * 1000
        logger.info(
            "← %s %s %.0fms",
            method,
            path,
            duration_ms,
            extra={"request_id": request_id, "duration_ms": duration_ms},
        )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _parse_body(event: dict[str, Any]) -> dict[str, Any]:
    raw = event.get("body") or "{}"
    try:
        return json.loads(raw)  # type: ignore[no-any-return]
    except json.JSONDecodeError:
        return {}


def _qp(event: dict[str, Any], key: str, default: Any = None) -> Any:
    return (event.get("queryStringParameters") or {}).get(key, default)


# ---------------------------------------------------------------------------
# Health check (no auth)
# ---------------------------------------------------------------------------


def _handle_health_check(request_id: str) -> dict[str, Any]:
    import datetime

    return {
        "statusCode": 200,
        "headers": {"Content-Type": "application/json"},
        "body": __import__("json").dumps(
            {
                "status": "healthy",
                "version": "1.0.0",
                "timestamp": datetime.datetime.now(datetime.UTC).isoformat(),
            }
        ),
    }


# ---------------------------------------------------------------------------
# Public tracking lookup (no auth)
# ---------------------------------------------------------------------------


def _handle_public_tracking(event: dict[str, Any], tracking_code: str, request_id: str) -> dict[str, Any]:
    phone = _qp(event, "phone", "")
    result = service.get_shipment_by_code_and_phone(tracking_code, phone)
    return success(result, request_id=request_id)


# ---------------------------------------------------------------------------
# Authenticated dispatch
# ---------------------------------------------------------------------------


def _dispatch(
    event: dict[str, Any],
    method: str,
    path: str,
    parts: list[str],
    ctx: Any,
    request_id: str,
    ip_address: str | None,
) -> dict[str, Any]:
    if len(parts) < 2 or parts[0] != "v1":
        raise ResourceNotFoundError("route", path)

    section = parts[1]

    if section == "containers":
        return _container_routes(event, parts, method, ctx, request_id, ip_address)

    if section == "shipments":
        return _shipment_routes(event, parts, method, ctx, request_id, ip_address)

    raise ResourceNotFoundError("route", path)


# ---------------------------------------------------------------------------
# Container routes
# ---------------------------------------------------------------------------


def _container_routes(
    event: dict[str, Any],
    parts: list[str],
    method: str,
    ctx: Any,
    request_id: str,
    ip_address: str | None,
) -> dict[str, Any]:
    tenant_id = ctx.tenant_id
    container_id = parts[2] if len(parts) > 2 else None
    action = parts[3] if len(parts) > 3 else None
    sub_action = parts[4] if len(parts) > 4 else None

    download_action = parts[5] if len(parts) > 5 else None

    # GET /v1/containers/stats — tenant-wide per-status counts for the list
    # stats row + status chips (SQL-computed so it's correct at scale). Must be
    # checked before the container_id branch, which would treat "stats" as an id.
    if container_id == "stats" and action is None:
        if method == "GET":
            ctx.assert_role(*_CONTAINER_READ_ROLES)
            return success(service.get_container_stats(tenant_id), request_id=request_id)
        raise ResourceNotFoundError("route", "/".join(parts))

    if container_id is None:
        # POST /v1/containers
        if method == "POST":
            ctx.assert_role(UserRole.CHINA_OFFICE_STAFF)
            body = _parse_body(event)
            result: Any = service.create_container(
                tenant_id,
                body,
                actor_id=ctx.user_id,
                request_id=request_id,
                ip_address=ip_address,
            )
            return created(
                result,
                location=f"/v1/containers/{result['id']}",
                request_id=request_id,
            )

        # GET /v1/containers
        if method == "GET":
            ctx.assert_role(*_CONTAINER_READ_ROLES)
            filters = {}
            if _qp(event, "status"):
                # Comma-separated list — the Filters panel's status multi-select
                # sends several statuses in one request (see repository.list_containers's
                # ANY(%(statuses)s) clause). A single status is just a 1-element list.
                filters["status"] = [s for s in _qp(event, "status", "").split(",") if s]
            if _qp(event, "q"):
                filters["q"] = _qp(event, "q")
            if _qp(event, "created_after"):
                filters["created_after"] = _qp(event, "created_after")
            if _qp(event, "created_before"):
                filters["created_before"] = _qp(event, "created_before")
            if _qp(event, "eta_after"):
                filters["eta_after"] = _qp(event, "eta_after")
            if _qp(event, "eta_before"):
                filters["eta_before"] = _qp(event, "eta_before")
            limit = int(_qp(event, "limit", 50))
            cursor = decode_cursor(_qp(event, "cursor"))
            sort_field = _qp(event, "sort") or "created_at"
            sort_direction = _qp(event, "direction") or "desc"
            page, next_cursor, has_more = service.list_containers(
                tenant_id, filters, limit, cursor, sort_field=sort_field, sort_direction=sort_direction
            )
            return paginated(page, next_cursor, has_more, request_id=request_id)

    else:
        if action is None:
            # GET /v1/containers/{id}
            if method == "GET":
                ctx.assert_role(*_CONTAINER_READ_ROLES)
                result = service.get_container(tenant_id, container_id)
                return success(result, request_id=request_id)

            # DELETE /v1/containers/{id}
            if method == "DELETE":
                ctx.assert_role(UserRole.CHINA_OFFICE_STAFF, UserRole.TENANT_ADMIN)
                service.delete_container(
                    tenant_id,
                    container_id,
                    actor_id=ctx.user_id,
                    request_id=request_id,
                    ip_address=ip_address,
                )
                return success({"deleted": True}, request_id=request_id)

        else:
            # POST /v1/containers/{id}/cancel
            if action == "cancel" and method == "POST":
                ctx.assert_role(UserRole.CHINA_OFFICE_STAFF, UserRole.TENANT_ADMIN)
                body = _parse_body(event)
                result = service.cancel_container(
                    tenant_id,
                    container_id,
                    actor_id=ctx.user_id,
                    notes=body.get("notes"),
                    request_id=request_id,
                    ip_address=ip_address,
                )
                return success(result, request_id=request_id)

            # GET /v1/containers/{id}/events
            if action == "events" and method == "GET":
                ctx.assert_role(
                    UserRole.TENANT_ADMIN,
                    UserRole.NIGERIA_OFFICE_STAFF,
                    UserRole.CHINA_OFFICE_STAFF,
                    UserRole.WAREHOUSE_ATTENDANT,
                )
                result = service.get_container_events(tenant_id, container_id)
                return success(result, request_id=request_id)

            # PATCH /v1/containers/{id}/status
            if action == "status" and method == "PATCH":
                body = _parse_body(event)
                new_status = body.get("new_status", "")
                extra = {k: body.get(k) for k in ("ship_date", "actual_arrival_date", "notes") if body.get(k)}
                result = service.update_container_status(
                    tenant_id,
                    container_id,
                    new_status,
                    extra,
                    actor_id=ctx.user_id,
                    ctx=ctx,
                    request_id=request_id,
                    ip_address=ip_address,
                )
                return success(result, request_id=request_id)

            # GET /v1/containers/{id}/documents
            if action == "documents" and sub_action is None and method == "GET":
                ctx.assert_role(
                    UserRole.CHINA_OFFICE_STAFF,
                    UserRole.NIGERIA_OFFICE_STAFF,
                    UserRole.TENANT_ADMIN,
                )
                result = service.list_container_documents(tenant_id, container_id)
                return success(result, request_id=request_id)

            # GET /v1/containers/{id}/documents/{doc-id}/download
            if action == "documents" and sub_action and download_action == "download" and method == "GET":
                ctx.assert_role(
                    UserRole.CHINA_OFFICE_STAFF,
                    UserRole.NIGERIA_OFFICE_STAFF,
                    UserRole.TENANT_ADMIN,
                )
                result = service.get_document_download_url(
                    tenant_id=tenant_id,
                    container_id=container_id,
                    doc_id=sub_action,
                    actor_id=ctx.user_id,
                    actor_role=str(ctx.role),
                )
                return success(result, request_id=request_id)

            # POST /v1/containers/{id}/documents/presigned-url
            if action == "documents" and sub_action == "presigned-url" and method == "POST":
                ctx.assert_role(
                    UserRole.CHINA_OFFICE_STAFF,
                    UserRole.NIGERIA_OFFICE_STAFF,
                    UserRole.TENANT_ADMIN,
                )
                body = _parse_body(event)
                result = service.generate_document_presigned_url(
                    tenant_id=tenant_id,
                    container_id=container_id,
                    filename=body.get("filename", ""),
                    content_type=body.get("content_type", ""),
                    document_type=body.get("document_type", "other"),
                    actor_id=ctx.user_id,
                )
                return created(result, location=f"/v1/containers/{container_id}/documents", request_id=request_id)

    raise ResourceNotFoundError("route", "/".join(parts))


# ---------------------------------------------------------------------------
# Shipment routes (authenticated list only)
# ---------------------------------------------------------------------------


def _shipment_routes(
    event: dict[str, Any],
    parts: list[str],
    method: str,
    ctx: Any,
    request_id: str,
    ip_address: str | None,
) -> dict[str, Any]:
    tenant_id = ctx.tenant_id

    # GET /v1/shipments (list — all auth roles, customer filtered)
    if len(parts) == 2 and method == "GET":
        ctx.assert_role(*_ALL_AUTH_ROLES)
        filters = {}
        if _qp(event, "status"):
            filters["status"] = _qp(event, "status")
        if _qp(event, "tracking_code"):
            filters["tracking_code"] = _qp(event, "tracking_code")
        limit = int(_qp(event, "limit", 50))
        cursor = decode_cursor(_qp(event, "cursor"))
        page, next_cursor, has_more = service.list_shipments(tenant_id, filters, limit, cursor, ctx)
        return paginated(page, next_cursor, has_more, request_id=request_id)

    raise ResourceNotFoundError("route", "/".join(parts))
