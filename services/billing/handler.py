"""Billing Lambda handler.

Routes:
  GET   /v1/billing/carryovers                       — tenant_admin, nigeria_office_staff
  PATCH /v1/billing/carryovers/{id}/exempt           — tenant_admin
  POST  /v1/billing/{billing-id}/charges             — tenant_admin, nigeria_office_staff
  GET   /v1/billing/{billing-id}/charges             — tenant_admin, nigeria_office_staff, customer (own)
  DELETE /v1/billing/{billing-id}/charges/{id}       — tenant_admin
  GET   /v1/billing/{billing-id}/storage-fees        — tenant_admin, nigeria_office_staff, customer (own)
  GET   /v1/billing/disputes                         — nigeria_office_staff, tenant_admin, china_office_staff
  GET   /v1/billing/{customer-id}                    — tenant_admin, nigeria_office_staff, customer (own)
  POST  /v1/billing/{billing-id}/dispute             — customer
  GET   /v1/billing/{billing-id}/disputes            — nigeria_office_staff, tenant_admin, customer (own)
  PATCH /v1/billing/disputes/{dispute-id}/acknowledge — nigeria_office_staff
  PATCH /v1/billing/disputes/{dispute-id}/resolve    — nigeria_office_staff, china_office_staff, tenant_admin

EventBridge:
  source=logistics.tracking, detail-type=PaymentDue → auto-create billing
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
from shared.responses import created, error_response, no_content, paginated, success
from shared.tenant_context import UserRole

from . import service
from .models import FileCBMDisputeRequest, ResolveCBMDisputeRequest

# Module-level init (runs once on cold start)
setup_logging()
patch_all()

logger = logging.getLogger(__name__)

_BILLING_READ_ROLES = (
    UserRole.TENANT_ADMIN,
    UserRole.NIGERIA_OFFICE_STAFF,
    UserRole.CUSTOMER,
)
_DISPUTE_READ_ROLES = (
    UserRole.NIGERIA_OFFICE_STAFF,
    UserRole.TENANT_ADMIN,
    UserRole.CUSTOMER,
)
_DISPUTE_LIST_ALL_ROLES = (
    UserRole.NIGERIA_OFFICE_STAFF,
    UserRole.TENANT_ADMIN,
    UserRole.CHINA_OFFICE_STAFF,
)
_ACKNOWLEDGE_ROLES = (UserRole.NIGERIA_OFFICE_STAFF,)
_RESOLVE_ROLES = (
    UserRole.NIGERIA_OFFICE_STAFF,
    UserRole.CHINA_OFFICE_STAFF,
    UserRole.TENANT_ADMIN,
)
_CARRYOVER_READ_ROLES = (UserRole.TENANT_ADMIN, UserRole.NIGERIA_OFFICE_STAFF)
_CARRYOVER_EXEMPT_ROLES = (UserRole.TENANT_ADMIN,)
_CHARGE_WRITE_ROLES = (UserRole.TENANT_ADMIN, UserRole.NIGERIA_OFFICE_STAFF)
_CHARGE_READ_ROLES = (UserRole.TENANT_ADMIN, UserRole.NIGERIA_OFFICE_STAFF, UserRole.CUSTOMER)
_CHARGE_DELETE_ROLES = (UserRole.TENANT_ADMIN,)
_STORAGE_FEE_READ_ROLES = (UserRole.TENANT_ADMIN, UserRole.NIGERIA_OFFICE_STAFF, UserRole.CUSTOMER)


# ---------------------------------------------------------------------------
# Lambda entry point
# ---------------------------------------------------------------------------


def lambda_handler(event: dict, context) -> dict:
    # EventBridge events arrive with a "source" key
    if event.get("source") == "logistics.tracking":
        return _handle_event(event)

    # API Gateway HTTP
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
# EventBridge handler
# ---------------------------------------------------------------------------


def _handle_event(event: dict) -> dict:
    detail_type = event.get("detail-type", "")
    detail = event.get("detail") or {}
    tenant_id = detail.get("tenant_id", "")
    payload = detail.get("payload") or {}
    request_id = detail.get("request_id", "")

    if detail_type == "PaymentDue":
        try:
            service.handle_payment_due(
                tenant_id=tenant_id,
                container_id=payload.get("container_id", ""),
                customer_id=payload.get("customer_id", ""),
                container_number=payload.get("container_number"),
                request_id=request_id,
            )
        except Exception:
            logger.exception(
                "Failed to process PaymentDue for customer %s / container %s",
                payload.get("customer_id"),
                payload.get("container_id"),
            )
    else:
        logger.info("Ignoring unhandled event type: %s", detail_type)

    return {"statusCode": 200}


# ---------------------------------------------------------------------------
# HTTP dispatch
# ---------------------------------------------------------------------------


def _dispatch(event, method, path, ctx, request_id, ip_address):
    parts = path.strip("/").split("/")

    if len(parts) < 2 or parts[0] != "v1" or parts[1] != "billing":
        raise ResourceNotFoundError("route", path)

    segment = parts[2] if len(parts) > 2 else None

    # /v1/billing — top-level list and generate
    if segment is None:
        if method == "GET":
            ctx.assert_role(*_BILLING_READ_ROLES)
            filters = {}
            if _qp(event, "status"):
                filters["status"] = _qp(event, "status")
            if _qp(event, "customer_id"):
                filters["customer_id"] = _qp(event, "customer_id")
            limit = int(_qp(event, "limit", 50))
            cursor = decode_cursor(_qp(event, "cursor"))
            page, next_cursor, has_more = service.list_billing(
                ctx.tenant_id, filters, limit, cursor
            )
            return paginated(page, next_cursor, has_more, request_id=request_id)
        if method == "POST":
            ctx.assert_role(*_BILLING_READ_ROLES)
            body = _parse_body(event)
            result = service.generate_billing(
                ctx.tenant_id, body, actor_id=ctx.user_id, ctx=ctx
            )
            return created(result, location="/v1/billing", request_id=request_id)
        raise ResourceNotFoundError("route", path)

    # /v1/billing/carryovers[/{id}/exempt]
    if segment == "carryovers":
        return _carryover_routes(event, parts, method, ctx, request_id, ip_address)

    # /v1/billing/disputes[/{dispute_id}/{action}]
    if segment == "disputes":
        return _dispute_action_routes(event, parts, method, ctx, request_id, ip_address)

    # /v1/billing/{resource_id}[/{action}[/{sub_id}]]
    resource_id = segment
    action = parts[3] if len(parts) > 3 else None
    sub_id = parts[4] if len(parts) > 4 else None

    return _billing_routes(event, parts, method, ctx, request_id, ip_address, resource_id, action, sub_id)


def _carryover_routes(event, parts, method, ctx, request_id, ip_address):
    tenant_id = ctx.tenant_id
    carryover_id = parts[3] if len(parts) > 3 else None
    action = parts[4] if len(parts) > 4 else None

    if carryover_id is None:
        # GET /v1/billing/carryovers
        if method == "GET":
            ctx.assert_role(*_CARRYOVER_READ_ROLES)
            filters = {}
            if _qp(event, "customer_id"):
                filters["customer_id"] = _qp(event, "customer_id")
            if _qp(event, "status"):
                filters["status"] = _qp(event, "status")
            limit = int(_qp(event, "limit", 50))
            cursor = decode_cursor(_qp(event, "cursor"))
            page, next_cursor, has_more = service.list_carryovers(
                tenant_id, filters, limit, cursor
            )
            return paginated(page, next_cursor, has_more, request_id=request_id)

    elif action == "exempt" and method == "PATCH":
        # PATCH /v1/billing/carryovers/{id}/exempt
        ctx.assert_role(*_CARRYOVER_EXEMPT_ROLES)
        body = _parse_body(event)
        notes = body.get("notes")
        result = service.exempt_carryover(
            tenant_id, carryover_id, notes,
            actor_id=ctx.user_id,
            ip_address=ip_address,
        )
        return success(result, request_id=request_id)

    raise ResourceNotFoundError("route", "/".join(parts))


def _billing_routes(event, parts, method, ctx, request_id, ip_address, resource_id, action, sub_id=None):
    tenant_id = ctx.tenant_id

    if action is None:
        # GET /v1/billing/{customer-id}
        if method == "GET":
            ctx.assert_role(*_BILLING_READ_ROLES)
            container_id = _qp(event, "container_id")
            results = service.get_billing_for_customer(
                tenant_id, resource_id, ctx, container_id
            )
            return success(results, request_id=request_id)

    else:
        if action == "dispute" and method == "POST":
            # POST /v1/billing/{billing-id}/dispute
            ctx.assert_role(UserRole.CUSTOMER)
            body = _parse_body(event)
            req = _parse_validated(FileCBMDisputeRequest, body)
            result = service.file_cbm_dispute(
                tenant_id,
                resource_id,
                req,
                actor_id=ctx.user_id,
                ctx=ctx,
                request_id=request_id,
            )
            return created(result, location=f"/v1/billing/{resource_id}/disputes", request_id=request_id)

        if action == "disputes" and method == "GET":
            # GET /v1/billing/{billing-id}/disputes
            ctx.assert_role(*_DISPUTE_READ_ROLES)
            results = service.list_billing_disputes(tenant_id, resource_id, ctx)
            return success(results, request_id=request_id)

        if action == "charges":
            # POST /v1/billing/{billing-id}/charges
            if method == "POST" and sub_id is None:
                ctx.assert_role(*_CHARGE_WRITE_ROLES)
                body = _parse_body(event)
                result = service.add_misc_charge(
                    tenant_id, resource_id, body,
                    actor_id=ctx.user_id,
                    ip_address=ip_address,
                )
                return success(result, request_id=request_id, status_code=201)

            # GET /v1/billing/{billing-id}/charges
            if method == "GET" and sub_id is None:
                ctx.assert_role(*_CHARGE_READ_ROLES)
                results = service.list_misc_charges(tenant_id, resource_id, ctx)
                return success(results, request_id=request_id)

            # DELETE /v1/billing/{billing-id}/charges/{charge-id}
            if method == "DELETE" and sub_id:
                ctx.assert_role(*_CHARGE_DELETE_ROLES)
                service.delete_misc_charge(
                    tenant_id, resource_id, sub_id,
                    actor_id=ctx.user_id,
                    ip_address=ip_address,
                )
                return no_content(request_id=request_id)

        if action == "storage-fees" and method == "GET":
            # GET /v1/billing/{billing-id}/storage-fees
            ctx.assert_role(*_STORAGE_FEE_READ_ROLES)
            results = service.list_storage_fees(tenant_id, resource_id, ctx)
            return success(results, request_id=request_id)

    raise ResourceNotFoundError("route", "/".join(parts))


def _dispute_action_routes(event, parts, method, ctx, request_id, ip_address):
    tenant_id = ctx.tenant_id
    dispute_id = parts[3] if len(parts) > 3 else None
    action = parts[4] if len(parts) > 4 else None

    if dispute_id is None:
        # GET /v1/billing/disputes — top-level listing
        if method == "GET":
            ctx.assert_role(*_DISPUTE_LIST_ALL_ROLES)
            filters = {}
            if _qp(event, "status"):
                filters["status"] = _qp(event, "status")
            if _qp(event, "customer_id"):
                filters["customer_id"] = _qp(event, "customer_id")
            limit = int(_qp(event, "limit", 50))
            cursor = decode_cursor(_qp(event, "cursor"))
            page, next_cursor, has_more = service.list_disputes(
                tenant_id, filters, limit, cursor
            )
            return paginated(page, next_cursor, has_more, request_id=request_id)
        # POST /v1/billing/disputes — create a dispute (billing_id in body)
        if method == "POST":
            ctx.assert_role(*_DISPUTE_LIST_ALL_ROLES)
            body = _parse_body(event)
            result = service.create_dispute(
                tenant_id, body, actor_id=ctx.user_id, ctx=ctx, request_id=request_id
            )
            return created(result, location=f"/v1/billing/disputes/{result.get('id', '')}", request_id=request_id)
        raise ResourceNotFoundError("route", "/".join(parts))

    if action == "acknowledge" and method == "PATCH":
        ctx.assert_role(*_ACKNOWLEDGE_ROLES)
        result = service.acknowledge_dispute(
            tenant_id,
            dispute_id,
            actor_id=ctx.user_id,
            ip_address=ip_address,
        )
        return success(result, request_id=request_id)

    if action == "resolve" and method == "PATCH":
        ctx.assert_role(*_RESOLVE_ROLES)
        body = _parse_body(event)
        req = _parse_validated(ResolveCBMDisputeRequest, body)
        result = service.resolve_dispute(
            tenant_id,
            dispute_id,
            req,
            actor_id=ctx.user_id,
            ctx=ctx,
            request_id=request_id,
            ip_address=ip_address,
        )
        return success(result, request_id=request_id)

    if action == "reject" and method == "PATCH":
        ctx.assert_role(*_RESOLVE_ROLES)
        body = _parse_body(event)
        reason = body.get("reason", "")
        result = service.reject_dispute(
            tenant_id,
            dispute_id,
            reason,
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
