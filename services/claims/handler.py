"""Claims Lambda handler.

Routes:
  POST  /v1/claims                          — customer, nigeria_office_staff
  GET   /v1/claims                          — nigeria_office_staff, tenant_admin, customer (own)
  GET   /v1/claims/{id}                     — same
  PATCH /v1/claims/{id}/inspect             — nigeria_office_staff
  PATCH /v1/claims/{id}/resolve             — nigeria_office_staff, tenant_admin

  POST  /v1/uploads/presigned-url           — customer, nigeria_office_staff

  POST  /v1/claims/missing-items            — nigeria_office_staff
  PATCH /v1/claims/missing-items/{id}       — nigeria_office_staff
  POST  /v1/claims/seized-items             — nigeria_office_staff
  PATCH /v1/claims/seized-items/{id}        — nigeria_office_staff
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
from shared.responses import created, error_response, paginated, success
from shared.tenant_context import UserRole

from .models import (
    FileDamageClaimRequest,
    LogMissingItemRequest,
    LogSeizedItemRequest,
    ResolveClaimRequest,
    StartInspectionRequest,
)
from . import service

# Module-level init (runs once on cold start)
setup_logging()
patch_all()

logger = logging.getLogger(__name__)

_CLAIM_ROLES = (
    UserRole.NIGERIA_OFFICE_STAFF,
    UserRole.CUSTOMER,
)
_CLAIM_READ_ROLES = (
    UserRole.NIGERIA_OFFICE_STAFF,
    UserRole.TENANT_ADMIN,
    UserRole.CUSTOMER,
)
_INSPECT_ROLES = (UserRole.NIGERIA_OFFICE_STAFF,)
_RESOLVE_ROLES = (
    UserRole.NIGERIA_OFFICE_STAFF,
    UserRole.TENANT_ADMIN,
)
_UPLOAD_ROLES = (
    UserRole.CUSTOMER,
    UserRole.NIGERIA_OFFICE_STAFF,
)
_STAFF_ROLES = (UserRole.NIGERIA_OFFICE_STAFF,)


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

        # Idempotency for POST /claims only
        idempotency_key = None
        if method == "POST" and path.rstrip("/").endswith("/claims"):
            idempotency_key = (event.get("headers") or {}).get("idempotency-key")
            cached = check_idempotency(idempotency_key, tenant_ctx.tenant_id)
            if cached:
                return cached

        response = _dispatch(event, method, path, tenant_ctx, request_id, ip_address)

        if idempotency_key and response.get("statusCode", 500) < 400:
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


def _dispatch(event, method, path, ctx, request_id, ip_address):
    parts = path.strip("/").split("/")

    if len(parts) < 2:
        raise ResourceNotFoundError("route", path)

    section = parts[1]

    if section == "uploads":
        return _upload_routes(event, parts, method, ctx, request_id, ip_address)

    if section == "claims":
        sub = parts[2] if len(parts) > 2 else None

        if sub == "missing-items":
            return _missing_item_routes(event, parts, method, ctx, request_id, ip_address)

        if sub == "seized-items":
            return _seized_item_routes(event, parts, method, ctx, request_id, ip_address)

        # sub is None or a claim UUID
        return _claim_routes(event, parts, method, ctx, request_id, ip_address, sub)

    raise ResourceNotFoundError("route", path)


# ---------------------------------------------------------------------------
# Claim routes
# ---------------------------------------------------------------------------


def _claim_routes(event, parts, method, ctx, request_id, ip_address, claim_id):
    tenant_id = ctx.tenant_id
    action = parts[3] if len(parts) > 3 else None

    if claim_id is None:
        # POST /v1/claims
        if method == "POST":
            ctx.assert_role(*_CLAIM_ROLES)
            body = _parse_body(event)
            req = _parse_validated(FileDamageClaimRequest, body)
            customer_id_override = body.get("customer_id") if ctx.role != UserRole.CUSTOMER else None
            result = service.file_claim(
                tenant_id, req,
                actor_id=ctx.user_id,
                ctx=ctx,
                customer_id_override=customer_id_override,
                request_id=request_id,
            )
            return created(
                result,
                location=f"/v1/claims/{result['id']}",
                request_id=request_id,
            )

        # GET /v1/claims
        if method == "GET":
            ctx.assert_role(*_CLAIM_READ_ROLES)
            filters = {}
            if _qp(event, "status"):
                filters["status"] = _qp(event, "status")
            limit = int(_qp(event, "limit", 50))
            cursor = decode_cursor(_qp(event, "cursor"))
            page, next_cursor, has_more = service.list_claims(
                tenant_id, ctx, filters, limit, cursor
            )
            return paginated(page, next_cursor, has_more, request_id=request_id)

    else:
        if action is None:
            # GET /v1/claims/{id}
            if method == "GET":
                ctx.assert_role(*_CLAIM_READ_ROLES)
                result = service.get_claim(tenant_id, claim_id, ctx)
                return success(result, request_id=request_id)

        else:
            # PATCH /v1/claims/{id}/inspect
            if action == "inspect" and method == "PATCH":
                ctx.assert_role(*_INSPECT_ROLES)
                body = _parse_body(event)
                req = _parse_validated(StartInspectionRequest, body)
                result = service.start_inspection(
                    tenant_id, claim_id, req,
                    actor_id=ctx.user_id,
                    ip_address=ip_address,
                )
                return success(result, request_id=request_id)

            # PATCH /v1/claims/{id}/resolve
            if action == "resolve" and method == "PATCH":
                ctx.assert_role(*_RESOLVE_ROLES)
                body = _parse_body(event)
                req = _parse_validated(ResolveClaimRequest, body)
                result = service.resolve_claim(
                    tenant_id, claim_id, req,
                    actor_id=ctx.user_id,
                    ctx=ctx,
                    request_id=request_id,
                    ip_address=ip_address,
                )
                return success(result, request_id=request_id)

    raise ResourceNotFoundError("route", "/".join(parts))


# ---------------------------------------------------------------------------
# Upload / presigned URL route
# ---------------------------------------------------------------------------


def _upload_routes(event, parts, method, ctx, request_id, ip_address):
    # POST /v1/uploads/presigned-url
    if len(parts) >= 3 and parts[2] == "presigned-url" and method == "POST":
        ctx.assert_role(*_UPLOAD_ROLES)
        body = _parse_body(event)
        claim_id = body.get("claim_id", "")
        filename = body.get("filename", "")
        content_type = body.get("content_type", "")
        if not claim_id or not filename or not content_type:
            from shared.exceptions import BusinessRuleViolationError
            raise BusinessRuleViolationError(
                "claim_id, filename, and content_type are required",
                rule_id="MISSING_PRESIGNED_URL_FIELDS",
            )
        result = service.generate_presigned_url(
            ctx.tenant_id, claim_id, filename, content_type,
            actor_id=ctx.user_id,
        )
        return success(result, request_id=request_id)

    raise ResourceNotFoundError("route", "/".join(parts))


# ---------------------------------------------------------------------------
# Missing item routes
# ---------------------------------------------------------------------------


_ITEM_READ_ROLES = (UserRole.NIGERIA_OFFICE_STAFF, UserRole.TENANT_ADMIN)


def _missing_item_routes(event, parts, method, ctx, request_id, ip_address):
    tenant_id = ctx.tenant_id
    item_id = parts[3] if len(parts) > 3 else None

    if item_id is None:
        # GET /v1/claims/missing-items
        if method == "GET":
            ctx.assert_role(*_ITEM_READ_ROLES)
            filters = {}
            if _qp(event, "container_id"):
                filters["container_id"] = _qp(event, "container_id")
            if _qp(event, "customer_id"):
                filters["customer_id"] = _qp(event, "customer_id")
            if _qp(event, "status"):
                filters["status"] = _qp(event, "status")
            limit = int(_qp(event, "limit", 50))
            cursor = decode_cursor(_qp(event, "cursor"))
            page, next_cursor, has_more = service.list_missing_items(
                tenant_id, filters, limit, cursor
            )
            return paginated(page, next_cursor, has_more, request_id=request_id)

        # POST /v1/claims/missing-items
        if method == "POST":
            ctx.assert_role(*_STAFF_ROLES)
            body = _parse_body(event)
            req = _parse_validated(LogMissingItemRequest, body)
            result = service.log_missing_item(tenant_id, req, actor_id=ctx.user_id)
            return created(
                result,
                location=f"/v1/claims/missing-items/{result['id']}",
                request_id=request_id,
            )
    else:
        # GET /v1/claims/missing-items/{id}
        if method == "GET":
            ctx.assert_role(*_ITEM_READ_ROLES)
            result = service.get_missing_item(tenant_id, item_id)
            return success(result, request_id=request_id)

        # PATCH /v1/claims/missing-items/{id}
        if method == "PATCH":
            ctx.assert_role(*_STAFF_ROLES)
            body = _parse_body(event)
            status = body.get("status", "")
            notes = body.get("notes")
            if not status:
                from shared.exceptions import BusinessRuleViolationError
                raise BusinessRuleViolationError(
                    "status is required", rule_id="MISSING_STATUS"
                )
            result = service.update_missing_item(
                tenant_id, item_id, status, notes, actor_id=ctx.user_id
            )
            return success(result, request_id=request_id)

    raise ResourceNotFoundError("route", "/".join(parts))


# ---------------------------------------------------------------------------
# Seized item routes
# ---------------------------------------------------------------------------


def _seized_item_routes(event, parts, method, ctx, request_id, ip_address):
    tenant_id = ctx.tenant_id
    item_id = parts[3] if len(parts) > 3 else None

    if item_id is None:
        # GET /v1/claims/seized-items
        if method == "GET":
            ctx.assert_role(*_ITEM_READ_ROLES)
            filters = {}
            if _qp(event, "container_id"):
                filters["container_id"] = _qp(event, "container_id")
            if _qp(event, "customer_id"):
                filters["customer_id"] = _qp(event, "customer_id")
            if _qp(event, "status"):
                filters["status"] = _qp(event, "status")
            limit = int(_qp(event, "limit", 50))
            cursor = decode_cursor(_qp(event, "cursor"))
            page, next_cursor, has_more = service.list_seized_items(
                tenant_id, filters, limit, cursor
            )
            return paginated(page, next_cursor, has_more, request_id=request_id)

        # POST /v1/claims/seized-items
        if method == "POST":
            ctx.assert_role(*_STAFF_ROLES)
            body = _parse_body(event)
            req = _parse_validated(LogSeizedItemRequest, body)
            result = service.log_seized_item(tenant_id, req, actor_id=ctx.user_id)
            return created(
                result,
                location=f"/v1/claims/seized-items/{result['id']}",
                request_id=request_id,
            )
    else:
        # GET /v1/claims/seized-items/{id}
        if method == "GET":
            ctx.assert_role(*_ITEM_READ_ROLES)
            result = service.get_seized_item(tenant_id, item_id)
            return success(result, request_id=request_id)

        # PATCH /v1/claims/seized-items/{id}
        if method == "PATCH":
            ctx.assert_role(*_STAFF_ROLES)
            body = _parse_body(event)
            recovery_status = body.get("recovery_status") or body.get("status", "")
            notes = body.get("notes")
            if not recovery_status:
                from shared.exceptions import BusinessRuleViolationError
                raise BusinessRuleViolationError(
                    "recovery_status is required", rule_id="MISSING_STATUS"
                )
            result = service.update_seized_item(
                tenant_id, item_id, recovery_status, notes, actor_id=ctx.user_id
            )
            return success(result, request_id=request_id)

    raise ResourceNotFoundError("route", "/".join(parts))


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _parse_body(event: dict) -> dict:
    raw = event.get("body") or "{}"
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return {}


def _qp(event: dict, key: str, default=None):
    return (event.get("queryStringParameters") or {}).get(key, default)


def _parse_validated(model_class, body: dict):
    from pydantic import ValidationError as PydanticValidationError
    try:
        return model_class(**body)
    except PydanticValidationError as exc:
        from shared.exceptions import ValidationError
        raise ValidationError(
            "Request validation failed",
            field_errors={e["loc"][-1]: e["msg"] for e in exc.errors()},
        ) from exc
