"""Tenant Management Lambda handler.

Dispatches all 25+ routes for platform admin, tenant admin, and customer
management. Follows the standard handler pattern from
00_CROSS_CUTTING_STANDARDS.md.

Route groups:
  /v1/platform/*     — platform_admin only
  /v1/tenant/*       — tenant_admin only
  /v1/customers/*    — all staff roles + customer (own record only)
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
from shared.responses import (
    created,
    error_response,
    no_content,
    paginated,
    success,
    validation_error,
)
from shared.tenant_context import UserRole

from .models import (
    CreateTenantRequest,
    CreateTenantUserRequest,
    SuspendTenantRequest,
    UpdateDollarRateRequest,
    UpdateTenantConfigRequest,
    UpdateTenantRequest,
)
from . import service

# Module-level init (runs once on cold start)
setup_logging()
patch_all()

logger = logging.getLogger(__name__)

# Roles allowed to manage customers
_STAFF_ROLES = (
    UserRole.PLATFORM_ADMIN,
    UserRole.TENANT_ADMIN,
    UserRole.CHINA_OFFICE_STAFF,
    UserRole.NIGERIA_OFFICE_STAFF,
    UserRole.WAREHOUSE_ATTENDANT,
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
# Dispatch helpers
# ---------------------------------------------------------------------------


def _dispatch(event, method, path, ctx, request_id, ip_address):
    parts = path.strip("/").split("/")

    if len(parts) >= 2 and parts[0] == "v1":
        section = parts[1]

        if section == "platform":
            ctx.assert_role(UserRole.PLATFORM_ADMIN)
            return _platform_routes(event, parts, method, ctx, request_id, ip_address)

        # /v1/tenants is a shorthand alias for /v1/platform/tenants
        if section == "tenants":
            ctx.assert_role(UserRole.PLATFORM_ADMIN)
            # Handle POST directly — body is passed as dict (flexible schema)
            if method == "POST" and len(parts) == 2:
                body = _parse_body(event)
                result = service.create_tenant(
                    body,
                    actor_id=ctx.user_id,
                    request_id=request_id,
                    ip_address=ip_address,
                )
                return created(result, location="/v1/tenants", request_id=request_id)
            aliased_parts = ["v1", "platform", "tenants"] + parts[2:]
            return _platform_routes(event, aliased_parts, method, ctx, request_id, ip_address)

        if section == "tenant":
            ctx.assert_role(UserRole.TENANT_ADMIN)
            return _tenant_admin_routes(event, parts, method, ctx, request_id, ip_address)

        if section == "customers":
            return _customer_routes(event, parts, method, ctx, request_id, ip_address)

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
    """Parse body dict with Pydantic model; raise validation_error on failure."""
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
# Platform admin routes  /v1/platform/...
# ---------------------------------------------------------------------------


def _platform_routes(event, parts, method, ctx, request_id, ip_address):
    # parts: ["v1", "platform", <resource>, ...]
    resource = parts[2] if len(parts) > 2 else ""

    # GET /v1/platform/dashboard
    if resource == "dashboard" and method == "GET":
        data = service.get_platform_dashboard()
        return success(data, request_id=request_id)

    # GET /v1/platform/audit-log
    if resource == "audit-log" and method == "GET":
        rows = service.list_platform_audit_log(limit=int(_qp(event, "limit", 50)))
        return success(rows, request_id=request_id)

    # GET /PUT /v1/platform/settings
    if resource == "settings":
        if method == "GET":
            data = service.get_platform_settings()
            return success(data, request_id=request_id)
        if method == "PUT":
            body = _parse_body(event)
            data = service.update_platform_settings(body, actor_id=ctx.user_id)
            return success(data, request_id=request_id)

    # /v1/platform/tenants[/{id}[/suspend|activate]]
    if resource == "tenants":
        tenant_id = parts[3] if len(parts) > 3 else None
        action = parts[4] if len(parts) > 4 else None

        if not tenant_id:
            # POST /v1/platform/tenants
            if method == "POST":
                body = _parse_body(event)
                req = _parse_validated(CreateTenantRequest, body)
                result = service.create_tenant(
                    req,
                    actor_id=ctx.user_id,
                    request_id=request_id,
                    ip_address=ip_address,
                )
                tenant_id_new = str(result["tenant"]["id"])
                return created(
                    result,
                    location=f"/v1/platform/tenants/{tenant_id_new}",
                    request_id=request_id,
                )
            # GET /v1/platform/tenants
            if method == "GET":
                tenants = service.list_tenants(limit=int(_qp(event, "limit", 50)))
                return success(tenants, request_id=request_id)

        else:
            # PATCH /v1/platform/tenants/{id}/suspend
            if action == "suspend" and method == "PATCH":
                body = _parse_body(event)
                req = _parse_validated(SuspendTenantRequest, body)
                result = service.suspend_tenant(
                    tenant_id, req.reason, actor_id=ctx.user_id, ip_address=ip_address
                )
                return success(result, request_id=request_id)

            # PATCH /v1/platform/tenants/{id}/activate
            if action == "activate" and method == "PATCH":
                result = service.activate_tenant(
                    tenant_id, actor_id=ctx.user_id, ip_address=ip_address
                )
                return success(result, request_id=request_id)

            # GET /v1/platform/tenants/{id}
            if method == "GET":
                return success(service.get_tenant(tenant_id), request_id=request_id)

            # PATCH /v1/platform/tenants/{id}
            if method == "PATCH":
                body = _parse_body(event)
                req = _parse_validated(UpdateTenantRequest, body)
                result = service.update_tenant(
                    tenant_id, req, actor_id=ctx.user_id, ip_address=ip_address
                )
                return success(result, request_id=request_id)

            # DELETE /v1/platform/tenants/{id}
            if method == "DELETE":
                service.offboard_tenant(
                    tenant_id, actor_id=ctx.user_id, ip_address=ip_address
                )
                return no_content(request_id=request_id)

    raise ResourceNotFoundError("route", "/".join(parts))


# ---------------------------------------------------------------------------
# Tenant admin routes  /v1/tenant/...
# ---------------------------------------------------------------------------


def _tenant_admin_routes(event, parts, method, ctx, request_id, ip_address):
    tenant_id = ctx.tenant_id
    resource = parts[2] if len(parts) > 2 else ""

    # GET /v1/tenant/reports
    if resource == "reports" and method == "GET":
        data = service.get_tenant_report(tenant_id)
        return success(data, request_id=request_id)

    # /v1/tenant/config
    if resource == "config":
        if method == "GET":
            return success(service.get_tenant_config(tenant_id), request_id=request_id)
        if method == "PUT":
            body = _parse_body(event)
            req = _parse_validated(UpdateTenantConfigRequest, body)
            result = service.update_tenant_config(
                tenant_id, req, actor_id=ctx.user_id, ip_address=ip_address
            )
            return success(result, request_id=request_id)

    # /v1/tenant/dollar-rate
    if resource == "dollar-rate":
        if method == "GET":
            return success(service.get_dollar_rate(tenant_id), request_id=request_id)
        if method == "PUT":
            body = _parse_body(event)
            req = _parse_validated(UpdateDollarRateRequest, body)
            result = service.update_dollar_rate(
                tenant_id, req, actor_id=ctx.user_id, ip_address=ip_address
            )
            return success(result, request_id=request_id)

    # /v1/tenant/users[/{id}]
    if resource == "users":
        user_id = parts[3] if len(parts) > 3 else None

        if not user_id:
            if method == "POST":
                body = _parse_body(event)
                req = _parse_validated(CreateTenantUserRequest, body)
                user = service.create_user(
                    tenant_id,
                    req,
                    actor_id=ctx.user_id,
                    request_id=request_id,
                    ip_address=ip_address,
                )
                return created(
                    user,
                    location=f"/v1/tenant/users/{user['id']}",
                    request_id=request_id,
                )
            if method == "GET":
                return success(service.list_users(tenant_id), request_id=request_id)
        else:
            if method == "GET":
                return success(service.get_user(tenant_id, user_id), request_id=request_id)
            if method == "PATCH":
                body = _parse_body(event)
                # Only allow full_name updates via PATCH
                updates = {k: v for k, v in body.items() if k in ("full_name",)}
                result = service.update_user(
                    tenant_id, user_id, updates, actor_id=ctx.user_id, ip_address=ip_address
                )
                return success(result, request_id=request_id)
            if method == "DELETE":
                service.deactivate_user(
                    tenant_id, user_id, actor_id=ctx.user_id, ip_address=ip_address
                )
                return no_content(request_id=request_id)

    # /v1/tenant/charge-types[/{id}]
    if resource == "charge-types":
        charge_type_id = parts[3] if len(parts) > 3 else None

        if not charge_type_id:
            if method == "POST":
                body = _parse_body(event)
                result = service.create_charge_type(
                    tenant_id, body, actor_id=ctx.user_id, ip_address=ip_address
                )
                return created(
                    result,
                    location=f"/v1/tenant/charge-types/{result['id']}",
                    request_id=request_id,
                )
            if method == "GET":
                return success(service.list_charge_types(tenant_id), request_id=request_id)
        else:
            if method == "PUT":
                body = _parse_body(event)
                result = service.update_charge_type(
                    tenant_id, charge_type_id, body, actor_id=ctx.user_id, ip_address=ip_address
                )
                return success(result, request_id=request_id)
            if method == "DELETE":
                service.deactivate_charge_type(
                    tenant_id, charge_type_id, actor_id=ctx.user_id, ip_address=ip_address
                )
                return no_content(request_id=request_id)

    raise ResourceNotFoundError("route", "/".join(parts))


# ---------------------------------------------------------------------------
# Customer routes  /v1/customers[/{id}]
# ---------------------------------------------------------------------------


def _customer_routes(event, parts, method, ctx, request_id, ip_address):
    tenant_id = ctx.tenant_id
    customer_id = parts[2] if len(parts) > 2 else None
    is_customer_role = ctx.role == UserRole.CUSTOMER

    if not customer_id:
        # POST /v1/customers — staff only
        if method == "POST":
            ctx.assert_role(
                UserRole.PLATFORM_ADMIN,
                UserRole.TENANT_ADMIN,
                UserRole.CHINA_OFFICE_STAFF,
                UserRole.NIGERIA_OFFICE_STAFF,
            )
            body = _parse_body(event)
            result = service.create_customer(
                tenant_id, body, actor_id=ctx.user_id, request_id=request_id, ip_address=ip_address
            )
            return created(
                result,
                location=f"/v1/customers/{result['id']}",
                request_id=request_id,
            )

        # GET /v1/customers — staff + customer
        if method == "GET":
            q = _qp(event, "q")
            limit = int(_qp(event, "limit", 50))
            cursor_str = _qp(event, "cursor")
            from shared.pagination import decode_cursor
            cursor = decode_cursor(cursor_str)
            page, next_cursor, has_more = service.list_customers(
                tenant_id, q=q, limit=limit, cursor=cursor
            )
            return paginated(page, next_cursor, has_more, request_id=request_id)

    else:
        # GET /v1/customers/{id}
        if method == "GET":
            result = service.get_customer(
                tenant_id,
                customer_id,
                requesting_user_id=ctx.user_id,
                is_customer_role=is_customer_role,
            )
            return success(result, request_id=request_id)

        # PATCH /v1/customers/{id} — staff only
        if method == "PATCH":
            ctx.assert_role(*_STAFF_ROLES)
            body = _parse_body(event)
            result = service.update_customer(
                tenant_id, customer_id, body, actor_id=ctx.user_id, ip_address=ip_address
            )
            return success(result, request_id=request_id)

    raise ResourceNotFoundError("route", "/".join(parts))
