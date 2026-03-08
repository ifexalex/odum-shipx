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
"""

import json
import logging
import time
import uuid

from aws_xray_sdk.core import patch_all

from shared.auth import get_tenant_context
from shared.exceptions import LogisticsBaseError, ResourceNotFoundError
from shared.idempotency import check_idempotency, store_idempotency
from shared.logging_config import setup_logging
from shared.metering import record_usage
from shared.pagination import decode_cursor
from shared.responses import (
    created,
    error_response,
    paginated,
    success,
)
from shared.tenant_context import UserRole

from . import service
from .models import (
    ApprovePackingListRequest,
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


def lambda_handler(event: dict, context) -> dict:
    start_time = time.time()
    request_id = (
        event.get("requestContext", {}).get("requestId") or str(uuid.uuid4())
    )
    http = event.get("requestContext", {}).get("http", {})
    method = http.get("method", "")
    path = http.get("path", "")
    ip_address = (
        event.get("requestContext", {}).get("identity", {}).get("sourceIp")
    )

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
            cached = check_idempotency(idempotency_key)
            if cached:
                return cached

        response = _dispatch(event, method, path, tenant_ctx, request_id, ip_address)

        if method == "POST" and idempotency_key and response.get("statusCode", 500) < 400:
            store_idempotency(idempotency_key, response)

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


def _dispatch(event, method, path, ctx, request_id, ip_address):
    parts = path.strip("/").split("/")

    # Expect /v1/packing-lists[/{id}[/{action}]]
    if len(parts) >= 2 and parts[0] == "v1" and parts[1] == "packing-lists":
        pl_id = parts[2] if len(parts) > 2 else None
        action = parts[3] if len(parts) > 3 else None
        return _packing_list_routes(
            event, parts, method, ctx, request_id, ip_address, pl_id, action
        )

    raise ResourceNotFoundError("route", path)


def _parse_body(event: dict) -> dict:
    raw = event.get("body") or "{}"
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return {}


def _qp(event: dict, key: str, default=None):
    return (event.get("queryStringParameters") or {}).get(key, default)


def _parse_validated(model_class, body: dict):
    """Parse body dict with Pydantic model; raise ValidationError on failure."""
    from pydantic import ValidationError as PydanticValidationError
    try:
        return model_class(**body)
    except PydanticValidationError as exc:
        from shared.exceptions import ValidationError
        raise ValidationError(
            "Request validation failed",
            field_errors={e["loc"][-1]: e["msg"] for e in exc.errors()},
        ) from exc


# ---------------------------------------------------------------------------
# Route handler
# ---------------------------------------------------------------------------


def _packing_list_routes(event, parts, method, ctx, request_id, ip_address, pl_id, action):
    tenant_id = ctx.tenant_id

    if pl_id is None:
        # POST /v1/packing-lists
        if method == "POST":
            ctx.assert_role(UserRole.CHINA_OFFICE_STAFF, UserRole.NIGERIA_OFFICE_STAFF)
            body = _parse_body(event)
            req = _parse_validated(CreatePackingListRequest, body)
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
            page, next_cursor, has_more = service.list_packing_lists(
                tenant_id, filters, limit, cursor, ctx
            )
            return paginated(page, next_cursor, has_more, request_id=request_id)

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
                req = _parse_validated(UpdatePackingListRequest, body)
                result = service.update_packing_list(
                    tenant_id, pl_id, req,
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
                    pl_id, tenant_id,
                    ctx=ctx,
                    actor_id=ctx.user_id,
                    ip_address=ip_address,
                )
                return success(result, request_id=request_id)

            # PATCH /v1/packing-lists/{id}/approve
            if action == "approve" and method == "PATCH":
                ctx.assert_role(*_WORKFLOW_ROLES)
                body = _parse_body(event)
                req = _parse_validated(ApprovePackingListRequest, body)
                result = service.approve_packing_list(
                    tenant_id, pl_id, req,
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
                req = _parse_validated(RejectPackingListRequest, body)
                result = service.reject_packing_list(
                    tenant_id, pl_id, req,
                    actor_id=ctx.user_id,
                    ctx=ctx,
                    ip_address=ip_address,
                )
                return success(result, request_id=request_id)

    raise ResourceNotFoundError("route", "/".join(parts))
