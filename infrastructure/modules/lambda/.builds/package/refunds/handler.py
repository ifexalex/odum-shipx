"""Refunds Lambda handler.

Routes:
  POST  /v1/refunds                      — nigeria_office_staff
  GET   /v1/refunds                      — tenant_admin, nigeria_office_staff
  GET   /v1/refunds/{id}                 — tenant_admin, nigeria_office_staff, customer (own)
  PATCH /v1/refunds/{id}/review          — nigeria_office_staff
  PATCH /v1/refunds/{id}/approve         — tenant_admin, nigeria_office_staff
  PATCH /v1/refunds/{id}/reject          — tenant_admin, nigeria_office_staff
"""

import json
import logging
import time
import uuid

from aws_xray_sdk.core import patch_all

from shared.auth import get_tenant_context
from shared.exceptions import LogisticsBaseError, ResourceNotFoundError
from shared.logging_config import setup_logging
from shared.metering import record_usage
from shared.pagination import decode_cursor
from shared.responses import created, error_response, paginated, success
from shared.tenant_context import UserRole

from .models import AccountsReviewRequest, ApproveRefundRequest, CreateRefundRequest
from . import service

# Module-level init (runs once on cold start)
setup_logging()
patch_all()

logger = logging.getLogger(__name__)

_CREATE_ROLES      = (UserRole.NIGERIA_OFFICE_STAFF,)
_LIST_ROLES        = (UserRole.TENANT_ADMIN, UserRole.NIGERIA_OFFICE_STAFF)
_READ_ROLES        = (UserRole.TENANT_ADMIN, UserRole.NIGERIA_OFFICE_STAFF, UserRole.CUSTOMER)
_REVIEW_ROLES      = (UserRole.NIGERIA_OFFICE_STAFF,)
_APPROVE_ROLES     = (UserRole.TENANT_ADMIN, UserRole.NIGERIA_OFFICE_STAFF)
_REJECT_ROLES      = (UserRole.TENANT_ADMIN, UserRole.NIGERIA_OFFICE_STAFF)


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

        response = _dispatch(event, method, path, tenant_ctx, request_id, ip_address)
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

    if len(parts) < 2 or parts[1] != "refunds":
        raise ResourceNotFoundError("route", path)

    refund_id = parts[2] if len(parts) > 2 else None
    action = parts[3] if len(parts) > 3 else None

    if refund_id is None:
        # POST /v1/refunds
        if method == "POST":
            ctx.assert_role(*_CREATE_ROLES)
            body = _parse_body(event)
            req = _parse_validated(CreateRefundRequest, body)
            result = service.create_refund(
                ctx.tenant_id, req,
                actor_id=ctx.user_id,
                ctx=ctx,
                request_id=request_id,
            )
            return created(
                result,
                location=f"/v1/refunds/{result['id']}",
                request_id=request_id,
            )

        # GET /v1/refunds
        if method == "GET":
            ctx.assert_role(*_LIST_ROLES)
            filters = {}
            if _qp(event, "status"):
                filters["status"] = _qp(event, "status")
            if _qp(event, "customer_id"):
                filters["customer_id"] = _qp(event, "customer_id")
            limit = int(_qp(event, "limit", 50))
            cursor = decode_cursor(_qp(event, "cursor"))
            page, next_cursor, has_more = service.list_refunds(
                ctx.tenant_id, ctx, filters, limit, cursor
            )
            return paginated(page, next_cursor, has_more, request_id=request_id)

    else:
        if action is None:
            # GET /v1/refunds/{id}
            if method == "GET":
                ctx.assert_role(*_READ_ROLES)
                result = service.get_refund(ctx.tenant_id, refund_id, ctx)
                return success(result, request_id=request_id)

        else:
            # PATCH /v1/refunds/{id}/review
            if action == "review" and method == "PATCH":
                ctx.assert_role(*_REVIEW_ROLES)
                body = _parse_body(event)
                req = _parse_validated(AccountsReviewRequest, body)
                result = service.accounts_review(
                    ctx.tenant_id, refund_id, req,
                    actor_id=ctx.user_id,
                    ctx=ctx,
                )
                return success(result, request_id=request_id)

            # PATCH /v1/refunds/{id}/approve
            if action == "approve" and method == "PATCH":
                ctx.assert_role(*_APPROVE_ROLES)
                body = _parse_body(event)
                req = _parse_validated(ApproveRefundRequest, body)
                result = service.approve_refund(
                    ctx.tenant_id, refund_id, req,
                    actor_id=ctx.user_id,
                    ctx=ctx,
                    request_id=request_id,
                )
                return success(result, request_id=request_id)

            # PATCH /v1/refunds/{id}/reject
            if action == "reject" and method == "PATCH":
                ctx.assert_role(*_REJECT_ROLES)
                body = _parse_body(event)
                reason = body.get("reason") or ""
                if not reason:
                    from shared.exceptions import BusinessRuleViolationError
                    raise BusinessRuleViolationError(
                        "reason is required for rejection",
                        rule_id="MISSING_REJECTION_REASON",
                    )
                result = service.reject_refund(
                    ctx.tenant_id, refund_id, reason,
                    actor_id=ctx.user_id,
                    ctx=ctx,
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
