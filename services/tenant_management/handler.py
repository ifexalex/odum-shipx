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
from typing import Any

from shared.auth import get_tenant_context
from shared.exceptions import LogisticsBaseError, ResourceNotFoundError
from shared.idempotency import check_idempotency, store_idempotency
from shared.logging_config import bind_log_context, clear_log_context, setup_logging
from shared.metering import record_usage
from shared.observability import init_tracing
from shared.responses import (
    created,
    error_response,
    no_content,
    paginated,
    success,
)
from shared.tenant_context import UserRole
from shared.validation import parse_validated

from . import impersonation, service
from .models import (
    AcceptCustomerInviteRequest,
    ActivateAccountRequest,
    CreateOnboardingRequest,
    CreateTenantRequest,
    CreateTenantUserRequest,
    CustomerRegistrationRequest,
    OnboardingRequestStatusUpdate,
    PaystackConfigRequest,
    SuspendTenantRequest,
    UpdateCbmRateRequest,
    UpdateDollarRateMarkupRequest,
    UpdateTenantConfigRequest,
    UpdateTenantRequest,
    UpdateTenantUserRequest,
    UpsertNotificationTemplateRequest,
)

# Module-level init (runs once on cold start)
setup_logging()
init_tracing()

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


def lambda_handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
    start_time = time.time()
    request_id = event.get("requestContext", {}).get("requestId") or str(uuid.uuid4())
    clear_log_context()
    bind_log_context(request_id=request_id)
    http = event.get("requestContext", {}).get("http", {})
    method = http.get("method", "")
    path = http.get("path", "")
    ip_address = event.get("requestContext", {}).get("identity", {}).get("sourceIp")

    # Public routes — no JWT required; must be checked before get_tenant_context
    public_parts = path.strip("/").split("/")
    if method == "GET" and path.strip("/") == "v1/health":
        return _health_response(request_id)
    # Company (shipping-company) onboarding lead — public, NOT customer sign-up:
    # creates no account/tenant, just records a lead for a platform admin to provision.
    if method == "POST" and path == "/v1/onboarding-requests":
        return _handle_create_onboarding_request(event, request_id, ip_address)
    if method == "POST" and path == "/v1/register":
        return _handle_self_register(event, request_id, ip_address, slug=None)
    if method == "POST" and len(public_parts) == 3 and public_parts[:2] == ["v1", "register"]:
        return _handle_self_register(event, request_id, ip_address, slug=public_parts[2])
    if len(public_parts) >= 3 and public_parts[:2] == ["v1", "invites"]:
        token = public_parts[2]
        if method == "GET" and len(public_parts) == 3:
            return _handle_get_invite(token, request_id)
        if method == "POST" and len(public_parts) == 4 and public_parts[3] == "accept":
            return _handle_accept_invite(event, token, request_id, ip_address)
    # Account activation — public (no JWT): a provisioned staff/admin sets their
    # own password via the ShipX welcome link.
    if method in ("GET", "POST") and len(public_parts) == 3 and public_parts[:2] == ["v1", "activate"]:
        token = public_parts[2]
        if method == "GET":
            return _handle_get_activation(token, request_id)
        return _handle_activate_account(event, token, request_id, ip_address)

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
# Dispatch helpers
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

    if len(parts) >= 2 and parts[0] == "v1":
        section = parts[1]

        if section == "platform":
            ctx.assert_role(UserRole.PLATFORM_ADMIN)
            return _platform_routes(event, parts, method, ctx, request_id, ip_address)

        # /v1/tenants is a shorthand alias for /v1/platform/tenants
        if section == "tenants":
            # GET /v1/tenants/me/quota — accessible to all authenticated staff roles
            if len(parts) >= 4 and parts[2] == "me" and parts[3] == "quota" and method == "GET":
                result = service.get_tenant_quota(ctx.tenant_id)
                return success(result, request_id=request_id)

            ctx.assert_role(UserRole.PLATFORM_ADMIN)
            # Handle POST directly — body is passed as dict (flexible schema)
            if method == "POST" and len(parts) == 2:
                body = _parse_body(event)
                req = parse_validated(CreateTenantRequest, body)
                result = service.create_tenant(
                    req,
                    actor_id=ctx.user_id,
                    request_id=request_id,
                    ip_address=ip_address,
                )
                return created(result, location="/v1/tenants", request_id=request_id)
            aliased_parts = ["v1", "platform", "tenants"] + parts[2:]
            return _platform_routes(event, aliased_parts, method, ctx, request_id, ip_address)

        if section == "tenant":
            # PATCH /v1/tenant/me — self-service locale update for any authenticated role.
            # Must be checked BEFORE the tenant_admin assert_role below.
            if len(parts) >= 3 and parts[2] == "me" and method == "PATCH":
                return _self_update_profile(event, ctx, request_id, ip_address)

            # GET /v1/tenant/dollar-rate and /v1/tenant/cbm-rate are readable by
            # office staff too (not just tenant_admin): the China packing-list
            # wizard shows a live shipping-price estimate computed from the CBM
            # rate + FX rate, and Nigeria staff preview the same when billing.
            # Least-privilege read-only widening — writes (PUT) stay tenant_admin
            # only (the blanket assert below still guards every other method/path).
            if len(parts) == 3 and parts[2] in ("dollar-rate", "cbm-rate") and method == "GET":
                ctx.assert_role(
                    UserRole.TENANT_ADMIN,
                    UserRole.CHINA_OFFICE_STAFF,
                    UserRole.NIGERIA_OFFICE_STAFF,
                )
                return _tenant_admin_routes(event, parts, method, ctx, request_id, ip_address)

            # GET /v1/tenant/config (exact path, read-only) is readable by all
            # staff roles: printable documents (packing list / release note)
            # render the tenant's branding_config (company name, footer text),
            # and warehouse/china/nigeria staff all print them. Also readable
            # by CUSTOMER — MyBillingDetail.tsx's "Manual bank transfer" panel
            # needs this tenant's real bank_transfer_config, not a hardcoded
            # one (ground-truth gap: it previously showed every tenant's
            # customers the same hardcoded account). Safe to widen: the
            # response already masks webhook_config.secret and strips
            # paystack_config's secret key entirely, and every write plus the
            # webhook sub-routes stay behind the tenant_admin assert.
            if len(parts) == 3 and parts[2] == "config" and method == "GET":
                ctx.assert_role(
                    UserRole.TENANT_ADMIN,
                    UserRole.CHINA_OFFICE_STAFF,
                    UserRole.NIGERIA_OFFICE_STAFF,
                    UserRole.WAREHOUSE_ATTENDANT,
                    UserRole.CUSTOMER,
                )
                return _tenant_admin_routes(event, parts, method, ctx, request_id, ip_address)

            # GET /v1/tenant/users (list only — not create/edit/delete) is
            # readable by nigeria_office_staff and warehouse_attendant too:
            # RecordPickupModal needs to let a warehouse attendant pick the
            # Customer Service Officer / Accounting Officer who co-signed a
            # pickup, off the paper form's two further named sign-off lines
            # — a name-only lookup, no secrets in the response. Every other
            # /v1/tenant/users method/path stays behind the blanket
            # tenant_admin assert below.
            if len(parts) == 3 and parts[2] == "users" and method == "GET":
                ctx.assert_role(
                    UserRole.TENANT_ADMIN,
                    UserRole.NIGERIA_OFFICE_STAFF,
                    UserRole.WAREHOUSE_ATTENDANT,
                )
                return _tenant_admin_routes(event, parts, method, ctx, request_id, ip_address)

            # GET /v1/tenant/container-capacities (list only) is readable by all
            # staff roles: the China create-container form and the packing-list
            # wizard show the capacity presets. Writes (POST/DELETE) stay behind
            # the tenant_admin assert below.
            if len(parts) == 3 and parts[2] == "container-capacities" and method == "GET":
                ctx.assert_role(*_STAFF_ROLES)
                return _tenant_admin_routes(event, parts, method, ctx, request_id, ip_address)

            ctx.assert_role(UserRole.TENANT_ADMIN)
            return _tenant_admin_routes(event, parts, method, ctx, request_id, ip_address)

        if section == "customers":
            return _customer_routes(event, parts, method, ctx, request_id, ip_address)

    raise ResourceNotFoundError("route", path)


def _parse_body(event: dict[str, Any]) -> dict[str, Any]:
    raw = event.get("body") or "{}"
    try:
        return json.loads(raw)  # type: ignore[no-any-return]
    except json.JSONDecodeError:
        return {}


def _qp(event: dict[str, Any], key: str, default: Any = None) -> Any:
    return (event.get("queryStringParameters") or {}).get(key, default)


# ---------------------------------------------------------------------------
# Self-service profile (any authenticated role)
# ---------------------------------------------------------------------------


def _self_update_profile(
    event: dict[str, Any],
    ctx: Any,
    request_id: str,
    ip_address: str | None,
) -> dict[str, Any]:
    """PATCH /v1/tenant/me — let any authenticated user update their own locale."""
    from shared.exceptions import ValidationError

    body = _parse_body(event)
    locale = body.get("locale")
    if locale is None:
        raise ValidationError(
            "Request validation failed",
            field_errors={"locale": "locale is required"},
        )
    # Resolve caller's tenant_user record from their Cognito sub
    user = service.get_user_by_cognito_sub(ctx.tenant_id, ctx.user_id)
    result = service.update_user(
        ctx.tenant_id,
        str(user["id"]),
        {"locale": locale},
        actor_id=ctx.user_id,
        ip_address=ip_address,
    )
    return success(result, request_id=request_id)


# ---------------------------------------------------------------------------
# Public routes (no auth)
# ---------------------------------------------------------------------------


def _handle_self_register(
    event: dict[str, Any],
    request_id: str,
    ip_address: str | None,
    slug: str | None,
) -> dict[str, Any]:
    """POST /v1/register/{slug} (or legacy POST /v1/register) — customer self-registration (no JWT)."""
    try:
        body = _parse_body(event)
        req = parse_validated(CustomerRegistrationRequest, body)
        host = (event.get("headers") or {}).get("host") or (event.get("headers") or {}).get("Host", "")
        result = service.self_register_customer(req, slug=slug, host=host, request_id=request_id, ip_address=ip_address)
        return created(result, location=f"/v1/customers/{result['id']}", request_id=request_id)
    except LogisticsBaseError as exc:
        path = (event.get("requestContext", {}).get("http", {}) or {}).get("path", "/v1/register")
        return error_response(exc, instance=path, request_id=request_id)
    except Exception:
        logger.exception("Unhandled error in self-register")
        return error_response(
            LogisticsBaseError("Internal server error", "INTERNAL_ERROR", 500),
            instance="/v1/register",
            request_id=request_id,
        )


def _handle_get_invite(token: str, request_id: str) -> dict[str, Any]:
    """GET /v1/invites/{token} — public preview (no JWT) for the claim page."""
    try:
        result = service.get_customer_invite_public(token)
        return success(result, request_id=request_id)
    except LogisticsBaseError as exc:
        return error_response(exc, instance=f"/v1/invites/{token}", request_id=request_id)
    except Exception:
        logger.exception("Unhandled error resolving invite")
        return error_response(
            LogisticsBaseError("Internal server error", "INTERNAL_ERROR", 500),
            instance=f"/v1/invites/{token}",
            request_id=request_id,
        )


def _handle_accept_invite(
    event: dict[str, Any],
    token: str,
    request_id: str,
    ip_address: str | None,
) -> dict[str, Any]:
    """POST /v1/invites/{token}/accept — public (no JWT) claim of an invite."""
    try:
        body = _parse_body(event)
        req = parse_validated(AcceptCustomerInviteRequest, body)
        result = service.accept_customer_invite(token, req, ip_address=ip_address)
        return success(result, request_id=request_id)
    except LogisticsBaseError as exc:
        return error_response(exc, instance=f"/v1/invites/{token}/accept", request_id=request_id)
    except Exception:
        logger.exception("Unhandled error accepting invite")
        return error_response(
            LogisticsBaseError("Internal server error", "INTERNAL_ERROR", 500),
            instance=f"/v1/invites/{token}/accept",
            request_id=request_id,
        )


def _handle_get_activation(token: str, request_id: str) -> dict[str, Any]:
    """GET /v1/activate/{token} — public preview (no JWT) for the set-password page."""
    try:
        return success(service.get_activation_preview(token), request_id=request_id)
    except LogisticsBaseError as exc:
        return error_response(exc, instance=f"/v1/activate/{token}", request_id=request_id)
    except Exception:
        logger.exception("Unhandled error resolving activation")
        return error_response(
            LogisticsBaseError("Internal server error", "INTERNAL_ERROR", 500),
            instance=f"/v1/activate/{token}",
            request_id=request_id,
        )


def _handle_activate_account(
    event: dict[str, Any],
    token: str,
    request_id: str,
    ip_address: str | None,
) -> dict[str, Any]:
    """POST /v1/activate/{token} — public (no JWT): set the user's chosen password."""
    try:
        req = parse_validated(ActivateAccountRequest, _parse_body(event))
        return success(service.activate_account(token, req.password), request_id=request_id)
    except LogisticsBaseError as exc:
        return error_response(exc, instance=f"/v1/activate/{token}", request_id=request_id)
    except Exception:
        logger.exception("Unhandled error activating account")
        return error_response(
            LogisticsBaseError("Internal server error", "INTERNAL_ERROR", 500),
            instance=f"/v1/activate/{token}",
            request_id=request_id,
        )


def _handle_create_onboarding_request(event: dict[str, Any], request_id: str, ip_address: str | None) -> dict[str, Any]:
    """POST /v1/onboarding-requests — a shipping COMPANY requests onboarding (no JWT).

    Records a lead only; no account or tenant is created (that's customer sign-up's
    job, deliberately kept separate). A platform admin provisions it later.
    """
    try:
        req = parse_validated(CreateOnboardingRequest, _parse_body(event))
        result = service.create_onboarding_request(req, request_id=request_id, ip_address=ip_address)
        return created(result, location=f"/v1/platform/onboarding-requests/{result['id']}", request_id=request_id)
    except LogisticsBaseError as exc:
        return error_response(exc, instance="/v1/onboarding-requests", request_id=request_id)
    except Exception:
        logger.exception("Unhandled error creating onboarding request")
        return error_response(
            LogisticsBaseError("Internal server error", "INTERNAL_ERROR", 500),
            instance="/v1/onboarding-requests",
            request_id=request_id,
        )


# ---------------------------------------------------------------------------
# Platform admin routes  /v1/platform/...
# ---------------------------------------------------------------------------


def _platform_routes(
    event: dict[str, Any],
    parts: list[str],
    method: str,
    ctx: Any,
    request_id: str,
    ip_address: str | None,
) -> dict[str, Any]:
    # parts: ["v1", "platform", <resource>, ...]
    resource = parts[2] if len(parts) > 2 else ""

    # GET /v1/platform/dashboard
    if resource == "dashboard" and method == "GET":
        data = service.get_platform_dashboard()
        return success(data, request_id=request_id)

    # GET /v1/platform/audit-log
    if resource == "audit-log" and method == "GET":
        from shared.pagination import decode_cursor

        cursor_str = _qp(event, "cursor")
        page, next_cursor, has_more = service.list_platform_audit_log(
            limit=int(_qp(event, "limit", 50)),
            cursor=decode_cursor(cursor_str),
            target_tenant_id=_qp(event, "tenant_id") or None,
            action=_qp(event, "action") or None,
        )
        return paginated(page, next_cursor, has_more, request_id=request_id)

    # /v1/platform/onboarding-requests[/{id}] — shipping-company onboarding leads
    if resource == "onboarding-requests":
        req_id = parts[3] if len(parts) > 3 else None
        if method == "GET" and req_id is None:
            return success(service.list_onboarding_requests(status=_qp(event, "status") or None), request_id=request_id)
        if method == "GET" and req_id:
            return success(service.get_onboarding_request(req_id), request_id=request_id)
        if method == "PATCH" and req_id:
            status_req = parse_validated(OnboardingRequestStatusUpdate, _parse_body(event))
            result = service.update_onboarding_request_status(req_id, status_req, actor_id=ctx.user_id, ip_address=ip_address)
            return success(result, request_id=request_id)

    # GET /v1/platform/plans · PUT /v1/platform/plans/{tier}
    if resource == "plans":
        tier = parts[3] if len(parts) > 3 else None
        if method == "GET" and tier is None:
            return success(service.get_plans(), request_id=request_id)
        if method == "PUT" and tier:
            body = _parse_body(event)
            data = service.update_plan(tier, body, actor_id=ctx.user_id, ip_address=ip_address)
            return success(data, request_id=request_id)

    # /v1/platform/settings[/{kind}-gateway[/test]]
    if resource == "settings":
        sub = parts[3] if len(parts) > 3 else None  # "sms-gateway" | "gateways" | None
        sub_action = parts[4] if len(parts) > 4 else None  # "test"

        # GET /v1/platform/settings/gateways — all three, secrets masked
        if sub == "gateways" and method == "GET":
            return success(service.get_gateway_settings(), request_id=request_id)

        # PUT /v1/platform/settings/{sms|whatsapp|email}-gateway (+ POST …/test)
        if sub and sub.endswith("-gateway"):
            kind = sub.removesuffix("-gateway")
            if sub_action == "test" and method == "POST":
                return success(service.test_gateway(kind), request_id=request_id)
            if sub_action is None and method == "PUT":
                body = _parse_body(event)
                data = service.update_gateway_settings(kind, body, actor_id=ctx.user_id, ip_address=ip_address)
                return success(data, request_id=request_id)

        if sub is None and method == "GET":
            data = service.get_platform_settings()
            return success(data, request_id=request_id)
        if sub is None and method == "PUT":
            body = _parse_body(event)
            data = service.update_platform_settings(body, actor_id=ctx.user_id)
            return success(data, request_id=request_id)

    # /v1/platform/impersonation/{session_id}
    if resource == "impersonation":
        session_id = parts[3] if len(parts) > 3 else None
        # DELETE /v1/platform/impersonation/{session_id} — end session
        if session_id and method == "DELETE":
            result = impersonation.end_impersonation(
                session_id=session_id,
                platform_admin_id=ctx.user_id,
                end_reason="manual",
                ip_address=ip_address,
            )
            return success(result, request_id=request_id)

    # /v1/platform/tenants[/{id}[/suspend|activate|impersonate]]
    if resource == "tenants":
        tenant_id = parts[3] if len(parts) > 3 else None
        action = parts[4] if len(parts) > 4 else None

        if not tenant_id:
            # POST /v1/platform/tenants
            if method == "POST":
                body = _parse_body(event)
                req = parse_validated(CreateTenantRequest, body)
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
                req = parse_validated(SuspendTenantRequest, body)
                result = service.suspend_tenant(tenant_id, req.reason, actor_id=ctx.user_id, ip_address=ip_address)
                return success(result, request_id=request_id)

            # PATCH /v1/platform/tenants/{id}/activate
            if action == "activate" and method == "PATCH":
                result = service.activate_tenant(tenant_id, actor_id=ctx.user_id, ip_address=ip_address)
                return success(result, request_id=request_id)

            # PATCH /v1/platform/tenants/{id}/reactivate
            if action == "reactivate" and method == "PATCH":
                result = service.reactivate_tenant(tenant_id, actor_id=ctx.user_id, ip_address=ip_address)
                return success(result, request_id=request_id)

            # GET /v1/platform/tenants/{id}/users — staff users of that tenant
            if action == "users" and method == "GET":
                return success(service.list_users(tenant_id), request_id=request_id)

            # GET /v1/platform/tenants/{id}/config — read-only config view
            if action == "config" and method == "GET":
                return success(service.get_tenant_config(tenant_id), request_id=request_id)

            # POST /v1/platform/tenants/{id}/quota-override — per-tenant limit override
            if action == "quota-override" and method == "POST":
                body = _parse_body(event)
                result = service.set_quota_override(tenant_id, body, actor_id=ctx.user_id, ip_address=ip_address)
                return success(result, request_id=request_id)

            # POST /v1/platform/tenants/{id}/impersonate — start impersonation session
            if action == "impersonate" and method == "POST":
                result = impersonation.start_impersonation(
                    platform_admin_id=ctx.user_id,
                    target_tenant_id=tenant_id,
                    ip_address=ip_address,
                )
                return created(result, location=f"/v1/platform/impersonation/{result['session_id']}", request_id=request_id)

            # GET /v1/platform/tenants/{id}
            if method == "GET":
                return success(service.get_tenant(tenant_id), request_id=request_id)

            # PATCH /v1/platform/tenants/{id}
            if method == "PATCH":
                body = _parse_body(event)
                req = parse_validated(UpdateTenantRequest, body)
                result = service.update_tenant(tenant_id, req, actor_id=ctx.user_id, ip_address=ip_address)
                return success(result, request_id=request_id)

            # DELETE /v1/platform/tenants/{id}
            if method == "DELETE":
                result = service.offboard_tenant(tenant_id, actor_id=ctx.user_id, ip_address=ip_address)
                return success(result, request_id=request_id)

    raise ResourceNotFoundError("route", "/".join(parts))


# ---------------------------------------------------------------------------
# Tenant admin routes  /v1/tenant/...
# ---------------------------------------------------------------------------


def _tenant_admin_routes(
    event: dict[str, Any],
    parts: list[str],
    method: str,
    ctx: Any,
    request_id: str,
    ip_address: str | None,
) -> dict[str, Any]:
    tenant_id = ctx.tenant_id
    resource = parts[2] if len(parts) > 2 else ""

    # GET /v1/tenant/reports
    if resource == "reports" and method == "GET":
        data = service.get_tenant_report(tenant_id)
        return success(data, request_id=request_id)

    # GET /v1/tenant/activity — tenant-scoped audit feed (audit gap B6).
    # ?actor_id= narrows to one staff member (staff-profile 3.4).
    # ?entity_type= narrows to one or more kinds of record — comma-separated
    # for a category filter (e.g. every money-related type at once), same
    # contract as GET /v1/containers's comma-separated ?status=.
    # ?action=, ?q= (actor name or record id), ?created_after=/?created_before=,
    # ?sort= (asc|desc) round out real filtering/search/sort for the
    # tenant-admin Activity Log page.
    if resource == "activity" and method == "GET":
        from shared.pagination import decode_cursor

        entity_type_param = _qp(event, "entity_type")
        page, next_cursor, has_more = service.list_tenant_activity(
            tenant_id,
            limit=int(_qp(event, "limit", 20)),
            cursor=decode_cursor(_qp(event, "cursor")),
            actor_id=_qp(event, "actor_id") or None,
            entity_type=[t for t in entity_type_param.split(",") if t] if entity_type_param else None,
            action=_qp(event, "action") or None,
            q=_qp(event, "q") or None,
            created_after=_qp(event, "created_after") or None,
            created_before=_qp(event, "created_before") or None,
            sort_direction=_qp(event, "sort", "desc"),
        )
        return paginated(page, next_cursor, has_more, request_id=request_id)

    # /v1/tenant/config[/webhook/(rotate-secret|test)][/paystack[/test]]
    if resource == "config":
        config_sub = parts[3] if len(parts) > 3 else None  # "webhook" | "paystack"
        config_action = parts[4] if len(parts) > 4 else None  # "rotate-secret" | "test"

        # POST /v1/tenant/config/webhook/rotate-secret
        if config_sub == "webhook" and config_action == "rotate-secret" and method == "POST":
            ctx.assert_role(UserRole.TENANT_ADMIN)
            result = service.rotate_webhook_secret(tenant_id, actor_id=ctx.user_id, ip_address=ip_address)
            return success(result, request_id=request_id)

        # POST /v1/tenant/config/webhook/test
        if config_sub == "webhook" and config_action == "test" and method == "POST":
            ctx.assert_role(UserRole.TENANT_ADMIN)
            result = service.test_webhook_delivery(tenant_id, actor_id=ctx.user_id, request_id=request_id)
            return success(result, request_id=request_id)

        # PUT /v1/tenant/config/paystack — connect/replace this tenant's own key
        if config_sub == "paystack" and config_action is None and method == "PUT":
            ctx.assert_role(UserRole.TENANT_ADMIN)
            body = _parse_body(event)
            req = parse_validated(PaystackConfigRequest, body)
            result = service.update_paystack_config(tenant_id, req, actor_id=ctx.user_id, ip_address=ip_address)
            return success(result, request_id=request_id)

        # DELETE /v1/tenant/config/paystack — disconnect (bank-transfer-only until reconfigured)
        if config_sub == "paystack" and config_action is None and method == "DELETE":
            ctx.assert_role(UserRole.TENANT_ADMIN)
            result = service.delete_paystack_config(tenant_id, actor_id=ctx.user_id, ip_address=ip_address)
            return success(result, request_id=request_id)

        # POST /v1/tenant/config/paystack/test — live connectivity check
        if config_sub == "paystack" and config_action == "test" and method == "POST":
            ctx.assert_role(UserRole.TENANT_ADMIN)
            result = service.test_paystack_connection(tenant_id, actor_id=ctx.user_id, request_id=request_id)
            return success(result, request_id=request_id)

        if method == "GET":
            return success(service.get_tenant_config(tenant_id), request_id=request_id)
        if method == "PUT":
            body = _parse_body(event)
            req = parse_validated(UpdateTenantConfigRequest, body)
            result = service.update_tenant_config(tenant_id, req, actor_id=ctx.user_id, ip_address=ip_address)
            return success(result, request_id=request_id)

    # /v1/tenant/dollar-rate
    if resource == "dollar-rate":
        if method == "GET":
            return success(service.get_dollar_rate(tenant_id), request_id=request_id)
        if method == "PUT":
            body = _parse_body(event)
            req = parse_validated(UpdateDollarRateMarkupRequest, body)
            result = service.update_dollar_rate(tenant_id, req, actor_id=ctx.user_id, ip_address=ip_address)
            return success(result, request_id=request_id)

    # /v1/tenant/cbm-rate
    if resource == "cbm-rate":
        if method == "GET":
            return success(service.get_cbm_rate(tenant_id), request_id=request_id)
        if method == "PUT":
            body = _parse_body(event)
            req = parse_validated(UpdateCbmRateRequest, body)
            result = service.update_cbm_rate(tenant_id, req, actor_id=ctx.user_id, ip_address=ip_address)
            return success(result, request_id=request_id)

    # /v1/tenant/users[/{id}]
    if resource == "users":
        user_id = parts[3] if len(parts) > 3 else None

        if not user_id:
            if method == "POST":
                body = _parse_body(event)
                req = parse_validated(CreateTenantUserRequest, body)
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
            action = parts[4] if len(parts) > 4 else None
            if action == "resend-invite" and method == "POST":
                service.resend_user_invite(tenant_id, user_id)
                return success({"message": "Invite resent"}, request_id=request_id)
            if action == "reset-password" and method == "POST":
                service.reset_user_password(tenant_id, user_id)
                return success({"message": "Password reset email sent"}, request_id=request_id)
            if action == "reactivate" and method == "POST":
                # POST sub-action rather than reusing PATCH: deactivation is a
                # DELETE, so its inverse is a deliberate named action, not a
                # field someone could flip by accident in a partial update.
                result = service.reactivate_user(tenant_id, user_id, actor_id=ctx.user_id, ip_address=ip_address)
                return success(result, request_id=request_id)
            if action == "resend-activation" and method == "POST":
                result = service.resend_activation(tenant_id, user_id, actor_id=ctx.user_id, request_id=request_id)
                return success(result, request_id=request_id)
            if method == "GET":
                return success(service.get_user(tenant_id, user_id), request_id=request_id)
            if method == "PATCH":
                body = _parse_body(event)
                req = parse_validated(UpdateTenantUserRequest, body)
                # exclude_none, not exclude_unset: the model's after-validator
                # defaults primary_role to roles[0] via direct attribute
                # assignment, which pydantic doesn't mark as "set" — only a
                # None-based filter reliably keeps that default in the dump.
                updates = req.model_dump(exclude_none=True)
                result = service.update_user(tenant_id, user_id, updates, actor_id=ctx.user_id, ip_address=ip_address)
                return success(result, request_id=request_id)
            if method == "DELETE":
                service.deactivate_user(tenant_id, user_id, actor_id=ctx.user_id, ip_address=ip_address)
                return no_content(request_id=request_id)

    # /v1/tenant/notification-templates[/{event_type}/{channel}]
    if resource == "notification-templates":
        event_type = parts[3] if len(parts) > 3 else None
        channel = parts[4] if len(parts) > 4 else None

        if not event_type:
            if method == "GET":
                return success(service.list_notification_templates(tenant_id), request_id=request_id)
        elif event_type and channel:
            if method == "GET":
                result = service.get_notification_template(tenant_id, event_type, channel)
                return success(result, request_id=request_id)
            if method == "PUT":
                body = _parse_body(event)
                req = parse_validated(UpsertNotificationTemplateRequest, body)
                result = service.upsert_notification_template(
                    tenant_id,
                    event_type,
                    channel,
                    req,
                    actor_id=ctx.user_id,
                    ip_address=ip_address,
                )
                return success(result, request_id=request_id)

    # GET /v1/tenant/rate-history
    if resource == "rate-history" and method == "GET":
        from shared.pagination import decode_cursor

        page, next_cursor, has_more = service.list_rate_history(
            tenant_id,
            rate_type=_qp(event, "rate_type") or None,
            limit=int(_qp(event, "limit", 50)),
            cursor=decode_cursor(_qp(event, "cursor")),
        )
        return paginated(page, next_cursor, has_more, request_id=request_id)

    # /v1/tenant/charge-types[/{id}]
    if resource == "charge-types":
        charge_type_id = parts[3] if len(parts) > 3 else None

        if not charge_type_id:
            if method == "POST":
                body = _parse_body(event)
                result = service.create_charge_type(tenant_id, body, actor_id=ctx.user_id, ip_address=ip_address)
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
                result = service.update_charge_type(tenant_id, charge_type_id, body, actor_id=ctx.user_id, ip_address=ip_address)
                return success(result, request_id=request_id)
            if method == "DELETE":
                service.deactivate_charge_type(tenant_id, charge_type_id, actor_id=ctx.user_id, ip_address=ip_address)
                return no_content(request_id=request_id)

    # /v1/tenant/container-capacities[/{id}]
    # GET is role-widened to all staff in the dispatcher; POST/DELETE are
    # tenant_admin-only (blanket assert before this function).
    if resource == "container-capacities":
        capacity_id = parts[3] if len(parts) > 3 else None

        if not capacity_id:
            if method == "GET":
                return success(service.list_container_capacities(tenant_id), request_id=request_id)
            if method == "POST":
                body = _parse_body(event)
                result = service.create_container_capacity(tenant_id, body, actor_id=ctx.user_id, ip_address=ip_address)
                return created(
                    result,
                    location=f"/v1/tenant/container-capacities/{result['id']}",
                    request_id=request_id,
                )
        else:
            if method == "PATCH":
                body = _parse_body(event)
                result = service.update_container_capacity(
                    tenant_id, capacity_id, body, actor_id=ctx.user_id, ip_address=ip_address
                )
                return success(result, request_id=request_id)
            if method == "DELETE":
                service.delete_container_capacity(tenant_id, capacity_id, actor_id=ctx.user_id, ip_address=ip_address)
                return no_content(request_id=request_id)

    # Warehouse CRUD lives on the payment_release service's /v1/warehouses
    # surface (the one the frontend uses); a duplicate /v1/tenant/warehouses
    # implementation that lived here was removed — it was never wired to the
    # frontend, Terraform, or Postman.

    raise ResourceNotFoundError("route", "/".join(parts))


# ---------------------------------------------------------------------------
# Customer routes  /v1/customers[/{id}]
# ---------------------------------------------------------------------------


def _customer_routes(
    event: dict[str, Any],
    parts: list[str],
    method: str,
    ctx: Any,
    request_id: str,
    ip_address: str | None,
) -> dict[str, Any]:
    tenant_id = ctx.tenant_id
    customer_id = parts[2] if len(parts) > 2 else None
    action = parts[3] if len(parts) > 3 else None
    is_customer_role = ctx.role == UserRole.CUSTOMER

    # GET /v1/customers/stats — tenant-wide customer aggregates for the list
    # stats row (SQL-computed). Staff only; checked before the {id} branch.
    if customer_id == "stats" and action is None:
        if method == "GET":
            ctx.assert_role(*_STAFF_ROLES)
            return success(service.get_customer_stats(tenant_id), request_id=request_id)
        raise ResourceNotFoundError("route", "/".join(parts))

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
            result = service.create_customer(tenant_id, body, actor_id=ctx.user_id, request_id=request_id, ip_address=ip_address)
            return created(
                result,
                location=f"/v1/customers/{result['id']}",
                request_id=request_id,
            )

        # GET /v1/customers — staff see the full list; a customer sees only
        # their own record (this doubles as the portal's "who am I" lookup —
        # there is no separate /v1/customers/me endpoint).
        if method == "GET":
            if is_customer_role:
                own = service.get_customer_for_user(tenant_id, ctx.user_id)
                return paginated([own] if own else [], None, False, request_id=request_id)
            ctx.assert_role(*_STAFF_ROLES)
            q = _qp(event, "q")
            limit = int(_qp(event, "limit", 50))
            cursor_str = _qp(event, "cursor")
            from shared.pagination import decode_cursor

            cursor = decode_cursor(cursor_str)
            page, next_cursor, has_more = service.list_customers(tenant_id, q=q, limit=limit, cursor=cursor)
            return paginated(page, next_cursor, has_more, request_id=request_id)

    else:
        if action is None:
            # GET /v1/customers/{id}
            if method == "GET":
                result = service.get_customer(
                    tenant_id,
                    customer_id,
                    requesting_user_id=ctx.user_id,
                    is_customer_role=is_customer_role,
                )
                return success(result, request_id=request_id)

            # PATCH /v1/customers/{id} — staff (full field set) or the customer
            # themselves (own record, restricted self-service fields only)
            if method == "PATCH":
                body = _parse_body(event)
                if is_customer_role:
                    # Ownership check — 404s when the record is not theirs.
                    service.get_customer(
                        tenant_id,
                        customer_id,
                        requesting_user_id=ctx.user_id,
                        is_customer_role=True,
                    )
                    # Self-service surface: contact channels, consent, and
                    # notification language only. Never name/email (identity),
                    # contract_details, or user_id.
                    allowed = {"phone", "whatsapp", "delivery_address", "notification_consent", "locale"}
                    body = {k: v for k, v in body.items() if k in allowed}
                else:
                    ctx.assert_role(*_STAFF_ROLES)
                result = service.update_customer(tenant_id, customer_id, body, actor_id=ctx.user_id, ip_address=ip_address)
                return success(result, request_id=request_id)

            # DELETE /v1/customers/{id} — GDPR/NDPR Art. 17 erasure.
            # tenant_admin, or the customer exercising their own right to be
            # forgotten (ownership verified; billing/shipment rows are kept but
            # de-linked by the anonymise routine).
            if method == "DELETE":
                if is_customer_role:
                    service.get_customer(
                        tenant_id,
                        customer_id,
                        requesting_user_id=ctx.user_id,
                        is_customer_role=True,
                    )
                else:
                    ctx.assert_role(UserRole.TENANT_ADMIN)
                anonymised = service.anonymise_customer(
                    tenant_id,
                    customer_id,
                    actor_id=ctx.user_id,
                    ip_address=ip_address,
                )
                return success(anonymised or {}, request_id=request_id)

        else:
            # POST /v1/customers/{id}/invite — staff only; issues a new invite,
            # or resends (which invalidates any prior unconsumed one).
            if action == "invite" and method == "POST":
                ctx.assert_role(*_STAFF_ROLES)
                result = service.issue_customer_invite(tenant_id, customer_id, actor_id=ctx.user_id, request_id=request_id)
                return created(result, location=f"/v1/customers/{customer_id}", request_id=request_id)

            # GET /v1/customers/{id}/export — tenant_admin or the customer themselves
            if action == "export" and method == "GET":
                ctx.assert_role(UserRole.TENANT_ADMIN, UserRole.CUSTOMER)
                result = service.export_customer_data(
                    tenant_id,
                    customer_id,
                    requesting_user_id=ctx.user_id,
                    is_customer_role=is_customer_role,
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
