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
from typing import Any

from shared.auth import get_tenant_context
from shared.client_ip import client_ip
from shared.exceptions import LogisticsBaseError, ResourceNotFoundError
from shared.idempotency import check_idempotency, get_idempotency_key, store_idempotency
from shared.logging_config import bind_log_context, clear_log_context, setup_logging
from shared.metering import record_usage
from shared.observability import init_tracing
from shared.pagination import parse_pagination_params
from shared.responses import created, error_response, paginated, success
from shared.tenant_context import UserRole
from shared.validation import parse_validated

from . import service
from .models import AccountsReviewRequest, ApproveRefundRequest, CreateRefundRequest

# Module-level init (runs once on cold start)
setup_logging()
init_tracing()

logger = logging.getLogger(__name__)

# CUSTOMER added here (ground-truth gap found live) — RefundRequest.tsx's
# self-service "Request a Refund" flow, reachable from every customer's
# billing page, always 403'd on this check alone. See create_refund()'s
# docstring in services/refunds/service.py for the full account, including
# the customer_id-derivation bug that would have hit next.
_CREATE_ROLES = (UserRole.NIGERIA_OFFICE_STAFF, UserRole.CUSTOMER)
_LIST_ROLES = (UserRole.TENANT_ADMIN, UserRole.NIGERIA_OFFICE_STAFF)
_READ_ROLES = (UserRole.TENANT_ADMIN, UserRole.NIGERIA_OFFICE_STAFF, UserRole.CUSTOMER)
_REVIEW_ROLES = (UserRole.NIGERIA_OFFICE_STAFF,)
_APPROVE_ROLES = (UserRole.TENANT_ADMIN, UserRole.NIGERIA_OFFICE_STAFF)
_REJECT_ROLES = (UserRole.TENANT_ADMIN, UserRole.NIGERIA_OFFICE_STAFF)


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
    ip_address = client_ip(event)

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

        idempotency_key = None
        if method == "POST":
            idempotency_key = get_idempotency_key(event)
            cached = check_idempotency(
                idempotency_key,
                tenant_ctx.tenant_id,
                actor_id=tenant_ctx.user_id,
                method=method,
                path=path,
                body=event.get("body"),
            )
            if cached:
                return cached

        response: dict[str, Any] = _dispatch(event, method, path, tenant_ctx, request_id, ip_address)

        if method == "POST" and idempotency_key and response.get("statusCode", 500) < 400:
            store_idempotency(
                idempotency_key,
                response,
                tenant_ctx.tenant_id,
                actor_id=tenant_ctx.user_id,
                method=method,
                path=path,
                body=event.get("body"),
            )

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

    if len(parts) < 2 or parts[1] != "refunds":
        raise ResourceNotFoundError("route", path)

    refund_id = parts[2] if len(parts) > 2 else None
    action = parts[3] if len(parts) > 3 else None

    if refund_id is None:
        # POST /v1/refunds
        if method == "POST":
            ctx.assert_role(*_CREATE_ROLES)
            body = _parse_body(event)
            req = parse_validated(CreateRefundRequest, body)
            result = service.create_refund(
                ctx.tenant_id,
                req,
                actor_id=ctx.user_id,
                ctx=ctx,
                request_id=request_id,
                ip_address=ip_address,
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
            cursor, limit = parse_pagination_params(event.get("queryStringParameters"), default_limit=50)
            page, next_cursor, has_more = service.list_refunds(ctx.tenant_id, ctx, filters, limit, cursor)
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
                req = parse_validated(AccountsReviewRequest, body)
                result = service.accounts_review(
                    ctx.tenant_id,
                    refund_id,
                    req,
                    actor_id=ctx.user_id,
                    ctx=ctx,
                    ip_address=ip_address,
                )
                return success(result, request_id=request_id)

            # PATCH /v1/refunds/{id}/approve
            if action == "approve" and method == "PATCH":
                ctx.assert_role(*_APPROVE_ROLES)
                body = _parse_body(event)
                req = parse_validated(ApproveRefundRequest, body)
                result = service.approve_refund(
                    ctx.tenant_id,
                    refund_id,
                    req,
                    actor_id=ctx.user_id,
                    ctx=ctx,
                    request_id=request_id,
                    ip_address=ip_address,
                )
                return success(result, request_id=request_id)

            # PATCH /v1/refunds/{id}/reject
            if action == "reject" and method == "PATCH":
                ctx.assert_role(*_REJECT_ROLES)
                body = _parse_body(event)
                reason = (body.get("reason") or "").strip() if isinstance(body.get("reason"), str) else ""
                if not reason:
                    from shared.exceptions import BusinessRuleViolationError

                    raise BusinessRuleViolationError(
                        "reason is required for rejection",
                        rule_id="MISSING_REJECTION_REASON",
                    )
                result = service.reject_refund(
                    ctx.tenant_id,
                    refund_id,
                    reason,
                    actor_id=ctx.user_id,
                    ctx=ctx,
                    ip_address=ip_address,
                )
                return success(result, request_id=request_id)

    raise ResourceNotFoundError("route", "/".join(parts))


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
