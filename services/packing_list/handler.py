"""Packing List Lambda handler.

Dispatches all routes for packing list CRUD and approval workflow.
Follows the standard handler pattern from 00_CROSS_CUTTING_STANDARDS.md.

Route groups:
  POST   /v1/packing-lists            — china_office_staff
  GET    /v1/packing-lists            — staff + customer (own only)
  GET    /v1/packing-lists/{id}       — staff + customer (own only)
  PUT    /v1/packing-lists/{id}       — china_office_staff (draft/rejected only)
  PATCH  /v1/packing-lists/{id}/submit   — china_office_staff, tenant_admin
  PATCH  /v1/packing-lists/{id}/approve  — china_office_staff, tenant_admin
  PATCH  /v1/packing-lists/{id}/reject   — china_office_staff, tenant_admin
  POST   /v1/packing-lists/bulk-submit   — china_office_staff, tenant_admin (draft -> pending_approval)
  POST   /v1/packing-lists/bulk-approve  — china_office_staff, tenant_admin (pending_approval -> approved)
  POST   /v1/packing-lists/bulk-reject   — china_office_staff, tenant_admin (pending_approval -> rejected)
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
from shared.logging_config import bind_log_context, clear_log_context, setup_logging
from shared.metering import record_usage
from shared.pagination import decode_cursor
from shared.responses import (
    created,
    error_response,
    paginated,
    success,
)
from shared.tenant_context import UserRole
from shared.validation import parse_validated

from . import service
from .models import (
    ApprovePackingListRequest,
    BulkApproveRequest,
    BulkRejectRequest,
    BulkSubmitRequest,
    CreatePackingListRequest,
    RejectPackingListRequest,
    UpdatePackingListRequest,
)

# Module-level init (runs once on cold start)
setup_logging()
patch_all()

logger = logging.getLogger(__name__)

# Roles that can read packing lists
_READ_ROLES = (
    UserRole.PLATFORM_ADMIN,
    UserRole.TENANT_ADMIN,
    UserRole.CHINA_OFFICE_STAFF,
    UserRole.NIGERIA_OFFICE_STAFF,
    UserRole.CUSTOMER,
)

# Roles that can approve/reject/submit
_WORKFLOW_ROLES = (
    UserRole.CHINA_OFFICE_STAFF,
    UserRole.TENANT_ADMIN,
)


# ---------------------------------------------------------------------------
# Lambda entry point
# ---------------------------------------------------------------------------


def lambda_handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
    start_time = time.time()
    request_id = event.get("requestContext", {}).get("requestId") or str(uuid.uuid4())
    clear_log_context()
    bind_log_context(request_id=request_id)
    http = event.get("requestContext", {}).get("http", {})
    method = http.get("method", "")
    path = http.get("path", "")
    ip_address = event.get("requestContext", {}).get("identity", {}).get("sourceIp")

    if method == "GET" and path.strip("/") == "v1/health":
        return _health_response(request_id)

    try:
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

        response: dict[str, Any] = _dispatch(event, method, path, tenant_ctx, request_id, ip_address)

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
# Dispatch
# ---------------------------------------------------------------------------


def _dispatch(
    event: dict[str, Any],
    method: str,
    path: str,
    ctx: Any,
    request_id: str,
    ip_address: str | None,
) -> dict[str, Any]:
    parts = path.strip("/").split("/")

    # GET /v1/containers/{id}/packing-lists — sub-resource alias
    if len(parts) >= 4 and parts[0] == "v1" and parts[1] == "containers" and parts[3] == "packing-lists" and method == "GET":
        container_id = parts[2]
        return _container_packing_lists(event, method, ctx, request_id, container_id)

    # /v1/packing-lists[/{id}[/{action}]]
    if len(parts) >= 2 and parts[0] == "v1" and parts[1] == "packing-lists":
        pl_id = parts[2] if len(parts) > 2 else None
        action = parts[3] if len(parts) > 3 else None
        return _packing_list_routes(event, parts, method, ctx, request_id, ip_address, pl_id, action)

    raise ResourceNotFoundError("route", path)


def _container_packing_lists(
    event: dict[str, Any],
    method: str,
    ctx: Any,
    request_id: str,
    container_id: str,
) -> dict[str, Any]:
    """GET /v1/containers/{id}/packing-lists — ergonomic sub-resource."""
    ctx.assert_role(*_READ_ROLES)
    filters = {"container_id": container_id}
    if _qp(event, "q"):
        filters["q"] = _qp(event, "q")
    if _qp(event, "status"):
        filters["status"] = _qp(event, "status")
    if _qp(event, "customer_id"):
        filters["customer_id"] = _qp(event, "customer_id")
    limit = int(_qp(event, "limit", 50))
    cursor = decode_cursor(_qp(event, "cursor"))
    page, next_cursor, has_more, total = service.list_packing_lists(ctx.tenant_id, filters, limit, cursor, ctx)
    return paginated(page, next_cursor, has_more, total_count=total, request_id=request_id)


def _parse_body(event: dict[str, Any]) -> dict[str, Any]:
    raw = event.get("body") or "{}"
    try:
        return json.loads(raw)  # type: ignore[no-any-return]
    except json.JSONDecodeError:
        return {}


def _qp(event: dict[str, Any], key: str, default: Any = None) -> Any:
    return (event.get("queryStringParameters") or {}).get(key, default)


# ---------------------------------------------------------------------------
# Route handler
# ---------------------------------------------------------------------------


def _packing_list_routes(
    event: dict[str, Any],
    parts: list[str],
    method: str,
    ctx: Any,
    request_id: str,
    ip_address: str | None,
    pl_id: str | None,
    action: str | None,
) -> dict[str, Any]:
    tenant_id = ctx.tenant_id

    # Bulk operations — must come before individual-ID handling
    if pl_id == "bulk-approve" and method == "POST":
        ctx.assert_role(*_WORKFLOW_ROLES)
        body = _parse_body(event)
        req = parse_validated(BulkApproveRequest, body)
        result = service.bulk_approve_packing_lists(
            tenant_id,
            req,
            actor_id=ctx.user_id,
            ctx=ctx,
            request_id=request_id,
            ip_address=ip_address,
        )
        return success(result, request_id=request_id)

    if pl_id == "bulk-submit" and method == "POST":
        ctx.assert_role(*_WORKFLOW_ROLES)
        body = _parse_body(event)
        req = parse_validated(BulkSubmitRequest, body)
        result = service.bulk_submit_packing_lists(
            tenant_id,
            req,
            actor_id=ctx.user_id,
            ctx=ctx,
            request_id=request_id,
            ip_address=ip_address,
        )
        return success(result, request_id=request_id)

    if pl_id == "bulk-reject" and method == "POST":
        ctx.assert_role(*_WORKFLOW_ROLES)
        body = _parse_body(event)
        req = parse_validated(BulkRejectRequest, body)
        result = service.bulk_reject_packing_lists(
            tenant_id,
            req,
            actor_id=ctx.user_id,
            ctx=ctx,
            ip_address=ip_address,
        )
        return success(result, request_id=request_id)

    if pl_id is None:
        # POST /v1/packing-lists
        if method == "POST":
            ctx.assert_role(UserRole.CHINA_OFFICE_STAFF, UserRole.NIGERIA_OFFICE_STAFF)
            body = _parse_body(event)
            req = parse_validated(CreatePackingListRequest, body)
            result = service.create_packing_list(
                tenant_id,
                req,
                actor_id=ctx.user_id,
                request_id=request_id,
                ip_address=ip_address,
            )
            pl_id_new = str(result["id"])
            return created(
                result,
                location=f"/v1/packing-lists/{pl_id_new}",
                request_id=request_id,
            )

        # GET /v1/packing-lists
        if method == "GET":
            ctx.assert_role(*_READ_ROLES)
            filters = {}
            # Free-text search. The repository has supported this all along and
            # the UI has always sent it — the handler simply never read it, so
            # every search silently returned the unfiltered list.
            if _qp(event, "q"):
                filters["q"] = _qp(event, "q")
            if _qp(event, "status"):
                filters["status"] = _qp(event, "status")
            if _qp(event, "container_id"):
                filters["container_id"] = _qp(event, "container_id")
            if _qp(event, "customer_id"):
                filters["customer_id"] = _qp(event, "customer_id")
            if _qp(event, "created_after"):
                filters["created_after"] = _qp(event, "created_after")
            if _qp(event, "created_before"):
                filters["created_before"] = _qp(event, "created_before")
            limit = int(_qp(event, "limit", 50))
            cursor = decode_cursor(_qp(event, "cursor"))
            page, next_cursor, has_more, total = service.list_packing_lists(tenant_id, filters, limit, cursor, ctx)
            return paginated(page, next_cursor, has_more, total_count=total, request_id=request_id)

    else:
        if action is None:
            # GET /v1/packing-lists/{id}
            if method == "GET":
                ctx.assert_role(*_READ_ROLES)
                result = service.get_packing_list(tenant_id, pl_id, ctx)
                return success(result, request_id=request_id)

            # PUT /v1/packing-lists/{id}
            if method == "PUT":
                ctx.assert_role(UserRole.CHINA_OFFICE_STAFF)
                body = _parse_body(event)
                req = parse_validated(UpdatePackingListRequest, body)
                result = service.update_packing_list(
                    tenant_id,
                    pl_id,
                    req,
                    actor_id=ctx.user_id,
                    ctx=ctx,
                    ip_address=ip_address,
                )
                return success(result, request_id=request_id)

        else:
            # PATCH /v1/packing-lists/{id}/submit
            if action == "submit" and method == "PATCH":
                ctx.assert_role(*_WORKFLOW_ROLES)
                result = service.submit_packing_list(
                    pl_id,
                    tenant_id,
                    ctx=ctx,
                    actor_id=ctx.user_id,
                    ip_address=ip_address,
                )
                return success(result, request_id=request_id)

            # PATCH /v1/packing-lists/{id}/approve
            if action == "approve" and method == "PATCH":
                ctx.assert_role(*_WORKFLOW_ROLES)
                body = _parse_body(event)
                req = parse_validated(ApprovePackingListRequest, body)
                result = service.approve_packing_list(
                    tenant_id,
                    pl_id,
                    req,
                    actor_id=ctx.user_id,
                    ctx=ctx,
                    request_id=request_id,
                    ip_address=ip_address,
                )
                return success(result, request_id=request_id)

            # PATCH /v1/packing-lists/{id}/reject
            if action == "reject" and method == "PATCH":
                ctx.assert_role(*_WORKFLOW_ROLES)
                body = _parse_body(event)
                req = parse_validated(RejectPackingListRequest, body)
                result = service.reject_packing_list(
                    tenant_id,
                    pl_id,
                    req,
                    actor_id=ctx.user_id,
                    ctx=ctx,
                    ip_address=ip_address,
                )
                return success(result, request_id=request_id)

    raise ResourceNotFoundError("route", "/".join(parts))


# ---------------------------------------------------------------------------
# Health check (no auth)
# ---------------------------------------------------------------------------


def _health_response(request_id: str) -> dict[str, Any]:
    import datetime
    import json as _json

    return {
        "statusCode": 200,
        "headers": {"Content-Type": "application/json", "X-Request-Id": request_id},
        "body": _json.dumps(
            {
                "status": "healthy",
                "timestamp": datetime.datetime.now(datetime.UTC).isoformat(),
            }
        ),
    }
