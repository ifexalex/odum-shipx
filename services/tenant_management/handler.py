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

from shared import rate_limit
from shared.auth import get_tenant_context
from shared.client_ip import client_ip
from shared.exceptions import BusinessRuleViolationError, LogisticsBaseError, ResourceNotFoundError, ValidationError
from shared.idempotency import check_idempotency, get_idempotency_key, store_idempotency
from shared.logging_config import bind_log_context, clear_log_context, setup_logging
from shared.metering import record_usage
from shared.observability import init_tracing
from shared.pagination import parse_pagination_params
from shared.platform_roles import PlatformPermission
from shared.responses import (
    accepted,
    created,
    error_response,
    no_content,
    paginated,
    success,
)
from shared.tenant_context import PLATFORM_TENANT_ID, UserRole
from shared.validation import parse_validated

from . import approvals, branding_logo, impersonation, platform, platform_admins, service, step_up
from .models import (
    AcceptCustomerInviteRequest,
    ActivateAccountRequest,
    ApprovalDecisionRequest,
    ApprovalListQuery,
    CreateOnboardingRequest,
    CreateTenantRequest,
    CreateTenantUserRequest,
    CustomerRegistrationRequest,
    InvitePlatformAdminRequest,
    LogoUploadRequest,
    OffboardTenantRequest,
    OnboardingRequestStatusUpdate,
    PaystackConfigRequest,
    SelfRegistrationUpdateRequest,
    SetLogoRequest,
    StepUpRequest,
    SuspendTenantRequest,
    TenantListQuery,
    UpdateCbmRateRequest,
    UpdateCustomerCreditRequest,
    UpdateDollarRateMarkupRequest,
    UpdatePlatformAdminRequest,
    UpdatePolicyRequest,
    UpdateTenantConfigRequest,
    UpdateTenantRequest,
    UpdateTenantUserRequest,
    UpsertNotificationTemplateRequest,
)

# Module-level init (runs once on cold start)
setup_logging()
init_tracing()

logger = logging.getLogger(__name__)

# Roles allowed to manage customers (platform_admin must impersonate a tenant_admin)
_STAFF_ROLES = (
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
    ip_address = client_ip(event)

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
            # GET /v1/tenants/me/quota — accessible to tenant staff roles only (not customers or platform admin)
            if len(parts) == 4 and parts[2] == "me" and parts[3] == "quota" and method == "GET":
                ctx.assert_role(
                    UserRole.TENANT_ADMIN,
                    UserRole.CHINA_OFFICE_STAFF,
                    UserRole.NIGERIA_OFFICE_STAFF,
                    UserRole.WAREHOUSE_ATTENDANT,
                )
                if ctx.tenant_id == PLATFORM_TENANT_ID:
                    raise ResourceNotFoundError("tenant", "me")
                result = service.get_tenant_quota(ctx.tenant_id)
                return success(result, request_id=request_id)

            ctx.assert_role(UserRole.PLATFORM_ADMIN)
            # Handle POST directly — body is passed as dict (flexible schema)
            if method == "POST" and len(parts) == 2:
                ctx.assert_platform_permission(PlatformPermission.TENANT_LIFECYCLE)
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

            # GET /v1/tenant/permissions — server-served role capability matrix (TC-05).
            if len(parts) == 3 and parts[2] == "permissions" and method == "GET":
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
        actor_role=ctx.role.value,
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
        rate_limit.hit_for_client(rate_limit.REGISTER_IP, event)
        body = _parse_body(event)
        req = parse_validated(CustomerRegistrationRequest, body)
        host = (event.get("headers") or {}).get("host") or (event.get("headers") or {}).get("Host", "")
        service.self_register_customer(req, slug=slug, host=host, request_id=request_id, ip_address=ip_address)
        # The same answer whether the email was new or already had an account: see self_register_customer.
        return accepted({"status": "received"}, request_id=request_id)
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
        rate_limit.hit_for_client(rate_limit.ONBOARDING_IP, event)
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


def _is_uuid(value: str | None) -> bool:
    try:
        uuid.UUID(str(value))
    except ValueError:
        return False
    return True


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

    # Every platform route asks the caller's directory role for one permission (platform audit Phase 1, C-28).
    ctx.assert_platform_permission(_required_platform_permission(method, parts))

    if resource in ("me", "auth", "admins", "approvals"):
        return _platform_security_routes(event, parts, method, ctx, request_id, ip_address)

    # GET /v1/platform/dashboard
    if resource == "dashboard" and method == "GET":
        data = service.get_platform_dashboard()
        return success(data, request_id=request_id)

    # GET /v1/platform/audit-log
    if resource == "audit-log" and method == "GET":
        cursor, limit = parse_pagination_params(event.get("queryStringParameters"), default_limit=50)
        page, next_cursor, has_more = service.list_platform_audit_log(
            limit=limit,
            cursor=cursor,
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
                confirm = body.pop("confirm", None)
                plain, secrets = platform.split_gateway_update(kind, body)
                if secrets:
                    # A new provider key needs re-authentication and a second admin (decision D4).
                    step_up.require_step_up(event, ctx)
                    protected = approvals.ProtectedAction(
                        action=approvals.ApprovalAction.GATEWAY_SECRET_CHANGE,
                        target_label=kind,
                        summary=f"Change the {kind} gateway's secret",
                        confirm_text=kind,
                        payload={"kind": kind, "body": plain, "secret_fields": sorted(secrets)},
                        secret=secrets,
                    )
                    return _protected_response(ctx, protected, confirm, ip_address, request_id)
                data = service.update_gateway_settings(kind, body, actor_id=ctx.user_id, ip_address=ip_address)
                return success(data, request_id=request_id)

        if sub is None and method == "GET":
            data = service.get_platform_settings()
            return success(data, request_id=request_id)
        if sub is None and method == "PUT":
            body = _parse_body(event)
            confirm = body.pop("confirm", None)
            if body.get("maintenance_mode") is True and not service.get_platform_settings().get("maintenance_mode"):
                # Turning maintenance on takes every tenant offline: re-authentication and a second admin (D4).
                if set(body) != {"maintenance_mode"}:
                    raise ValidationError(
                        "Turn maintenance mode on by itself, then save the other settings.",
                        field_errors={"maintenance_mode": "Save on its own"},
                    )
                step_up.require_step_up(event, ctx)
                protected = approvals.ProtectedAction(
                    action=approvals.ApprovalAction.MAINTENANCE_ON,
                    target_label="maintenance_mode",
                    summary="Turn maintenance mode on for every tenant",
                    confirm_text="maintenance",
                )
                return _protected_response(ctx, protected, confirm, ip_address, request_id)
            data = service.update_platform_settings(body, actor_id=ctx.user_id, ip_address=ip_address)
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
            # GET /v1/platform/tenants?status=&tier=&q=&cursor=&limit= — paginated (audit PA-02)
            if method == "GET":
                cursor, limit = parse_pagination_params(event.get("queryStringParameters"), default_limit=50)
                filters = parse_validated(
                    TenantListQuery,
                    {"status": _qp(event, "status"), "tier": _qp(event, "tier"), "q": _qp(event, "q")},
                )
                page, next_cursor, has_more, total = service.list_tenants(
                    limit=limit,
                    cursor=cursor,
                    status=filters.status,
                    tier=filters.tier,
                    q=filters.q,
                )
                return paginated(page, next_cursor, has_more, total_count=total, request_id=request_id)

        else:
            # PATCH /v1/platform/tenants/{id}/suspend
            if action == "suspend" and method == "PATCH":
                body = _parse_body(event)
                req = parse_validated(SuspendTenantRequest, body)
                # Takes the whole tenant offline at once: re-authenticate first (C-29).
                step_up.require_step_up(event, ctx)
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

            # /v1/platform/tenants/{id}/offboarding-export[/link] — the tenant's data export (audit BE-10)
            if action == "offboarding-export":
                if not _is_uuid(tenant_id):
                    raise ResourceNotFoundError("tenant", tenant_id or "")
                export_action = parts[5] if len(parts) > 5 else None
                if export_action is None and method == "GET":
                    return success(service.get_offboarding_export(tenant_id), request_id=request_id)
                if export_action is None and method == "POST":
                    result = service.queue_offboarding_export(tenant_id, actor_id=ctx.user_id, ip_address=ip_address)
                    return success(result, request_id=request_id)
                if export_action == "link" and method == "POST":
                    result = service.create_offboarding_export_link(tenant_id, actor_id=ctx.user_id, ip_address=ip_address)
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

            if action is None:
                # GET /v1/platform/tenants/{id}
                if method == "GET":
                    return success(service.get_tenant(tenant_id), request_id=request_id)

                # PATCH /v1/platform/tenants/{id}
                if method == "PATCH":
                    body = _parse_body(event)
                    req = parse_validated(UpdateTenantRequest, body)
                    result = service.update_tenant(tenant_id, req, actor_id=ctx.user_id, ip_address=ip_address)
                    return success(result, request_id=request_id)

                # DELETE /v1/platform/tenants/{id} — body {"reason", "confirm"?}: re-authentication and a second
                # admin (decision D4); a sole admin's offboarding runs 24 hours later unless cancelled.
                if method == "DELETE":
                    offboard_req = parse_validated(OffboardTenantRequest, _parse_body(event))
                    step_up.require_step_up(event, ctx)
                    tenant = service.get_tenant(tenant_id)
                    if tenant["status"] == "offboarded":
                        raise BusinessRuleViolationError("Tenant is already offboarded")
                    protected = approvals.ProtectedAction(
                        action=approvals.ApprovalAction.OFFBOARD_TENANT,
                        target_label=str(tenant["id"]),
                        target_tenant_id=str(tenant["id"]),
                        summary=f"Offboard {tenant['company_name']}",
                        confirm_text=str(tenant["slug"]),
                        payload={"tenant_id": str(tenant["id"]), "reason": offboard_req.reason},
                        reason=offboard_req.reason,
                    )
                    return _protected_response(ctx, protected, offboard_req.confirm, ip_address, request_id)

    raise ResourceNotFoundError("route", "/".join(parts))


# ---------------------------------------------------------------------------
# Platform security: the caller, step-up, the admin directory and approvals (platform audit Phase 1)
# ---------------------------------------------------------------------------

_PLATFORM_READ_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})


def _required_platform_permission(method: str, parts: list[str]) -> PlatformPermission:
    """The one permission a platform route needs. Reads need READ; each write names its own.

    Unknown writes need ADMINS, the narrowest grant, so a route added without an entry here is owner-only until it is
    given one (fail-closed).
    """
    resource = parts[2] if len(parts) > 2 else ""
    action = parts[4] if len(parts) > 4 else None
    if resource == "auth":  # re-authenticating is open to every platform role
        return PlatformPermission.READ
    if method in _PLATFORM_READ_METHODS:
        return PlatformPermission.READ
    if resource == "approvals":
        verb = parts[4] if len(parts) > 4 else None
        # Cancel is checked in approvals.cancel (requester or owner); approve and reject need APPROVE.
        return PlatformPermission.READ if verb == "cancel" else PlatformPermission.APPROVE
    if resource == "tenants":
        if action == "impersonate":
            return PlatformPermission.SUPPORT
        if action == "quota-override":
            return PlatformPermission.PLANS
        return PlatformPermission.TENANT_LIFECYCLE
    return {
        "admins": PlatformPermission.ADMINS,
        "plans": PlatformPermission.PLANS,
        "settings": PlatformPermission.SETTINGS,
        "impersonation": PlatformPermission.SUPPORT,
        "onboarding-requests": PlatformPermission.SUPPORT,
    }.get(resource, PlatformPermission.ADMINS)


def _protected_response(
    ctx: Any,
    protected: approvals.ProtectedAction,
    confirm: str | None,
    ip_address: str | None,
    request_id: str,
) -> dict[str, Any]:
    """Run a protected action through approvals: 202 while it waits, 200 when it ran (sole admin)."""
    outcome = approvals.request_protected_action(ctx, protected, confirm=confirm, ip_address=ip_address)
    status_code = 200 if outcome["outcome"] == "executed" else 202
    return success(outcome, status_code=status_code, request_id=request_id)


def _platform_security_routes(
    event: dict[str, Any],
    parts: list[str],
    method: str,
    ctx: Any,
    request_id: str,
    ip_address: str | None,
) -> dict[str, Any]:
    resource = parts[2]
    item = parts[3] if len(parts) > 3 else None
    verb = parts[4] if len(parts) > 4 else None

    # GET /v1/platform/me — the caller's directory row and permissions
    if resource == "me" and item is None and method == "GET":
        return success(platform_admins.get_me(ctx), request_id=request_id)

    # POST /v1/platform/auth/step-up — re-authenticate; returns a 5-minute step-up token
    if resource == "auth" and item == "step-up" and method == "POST":
        req = parse_validated(StepUpRequest, _parse_body(event))
        me = platform_admins.get_me(ctx)
        result = step_up.step_up(
            ctx,
            str(me["email"]),
            password=req.password,
            mfa_code=req.mfa_code,
            id_token=req.id_token,
            ip_address=ip_address,
        )
        return success(result, request_id=request_id)

    if resource == "admins":
        if item is None and method == "GET":
            return success(platform_admins.list_admins(), request_id=request_id)
        if item is None and method == "POST":
            invite = parse_validated(InvitePlatformAdminRequest, _parse_body(event))
            step_up.require_step_up(event, ctx)
            created_admin = platform_admins.invite_admin(ctx, invite, ip_address=ip_address)
            return created(created_admin, location=f"/v1/platform/admins/{created_admin['id']}", request_id=request_id)
        if item and verb is None and method == "PATCH":
            if not _is_uuid(item):
                raise ResourceNotFoundError("platform admin", item)
            update = parse_validated(UpdatePlatformAdminRequest, _parse_body(event))
            step_up.require_step_up(event, ctx)
            return success(platform_admins.update_admin(ctx, item, update, ip_address=ip_address), request_id=request_id)

    if resource == "approvals":
        if item is None and method == "GET":
            query = parse_validated(
                ApprovalListQuery,
                {k: v for k, v in {"status": _qp(event, "status"), "limit": _qp(event, "limit")}.items() if v},
            )
            return success(approvals.list_approvals(query.status, query.limit), request_id=request_id)
        if item and not _is_uuid(item):
            raise ResourceNotFoundError("approval", item)
        if item and verb is None and method == "GET":
            return success(approvals.get_approval(item), request_id=request_id)
        if item and method == "POST" and verb in ("approve", "reject", "cancel"):
            decision = parse_validated(ApprovalDecisionRequest, _parse_body(event))
            if verb == "approve":
                step_up.require_step_up(event, ctx)
                return success(approvals.approve(ctx, item, decision.note, ip_address), request_id=request_id)
            if verb == "reject":
                step_up.require_step_up(event, ctx)
                return success(approvals.reject(ctx, item, decision.note, ip_address), request_id=request_id)
            return success(approvals.cancel(ctx, item, decision.note, ip_address), request_id=request_id)

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

    # GET/PUT /v1/tenant/policies — effective-dated business policies (Phase 1, TC-01, D4)
    if resource == "policies":
        if method == "GET":
            return success(service.get_tenant_policies(tenant_id), request_id=request_id)
        if method == "PUT":
            ctx.assert_role(UserRole.TENANT_ADMIN)
            req = parse_validated(UpdatePolicyRequest, _parse_body(event))
            result = service.update_tenant_policy(
                tenant_id,
                req.policy_key,
                req.value,
                req.effective_date,
                actor_id=ctx.user_id,
                ip_address=ip_address,
            )
            return success(result, request_id=request_id)

    # GET /v1/tenant/approvals — unified admin approvals inbox read model (Phase 1, TC-02, D5)
    if resource == "approvals" and method == "GET":
        ctx.assert_role(UserRole.TENANT_ADMIN)
        counts_only = str(_qp(event, "counts_only", "")).lower() in ("1", "true", "yes")
        data = service.get_tenant_approvals(
            tenant_id,
            actor_id=ctx.user_id,
            item_type=_qp(event, "type") or None,
            counts_only=counts_only,
        )
        return success(data, request_id=request_id)

    # GET /v1/tenant/permissions — server-served role-to-action map (Phase 1, TC-05)
    if resource == "permissions" and method == "GET":
        from shared.role_permissions import get_role_permissions_payload

        return success(get_role_permissions_payload(), request_id=request_id)

    # GET /v1/tenant/activity — tenant-scoped audit feed (audit gap B6).
    # ?actor_id= narrows to one staff member (staff-profile 3.4).
    # ?entity_type= narrows to one or more kinds of record — comma-separated
    # for a category filter (e.g. every money-related type at once), same
    # contract as GET /v1/containers's comma-separated ?status=.
    # ?action=, ?q= (actor name or record id), ?created_after=/?created_before=,
    # ?sort= (asc|desc) round out real filtering/search/sort for the
    # tenant-admin Activity Log page.
    if resource == "activity" and method == "GET":
        cursor, limit = parse_pagination_params(event.get("queryStringParameters"), default_limit=20)
        entity_type_param = _qp(event, "entity_type")
        page, next_cursor, has_more = service.list_tenant_activity(
            tenant_id,
            limit=limit,
            cursor=cursor,
            actor_id=_qp(event, "actor_id") or None,
            entity_type=[t for t in entity_type_param.split(",") if t] if entity_type_param else None,
            action=_qp(event, "action") or None,
            q=_qp(event, "q") or None,
            created_after=_qp(event, "created_after") or None,
            created_before=_qp(event, "created_before") or None,
            sort_direction=_qp(event, "sort", "desc"),
        )
        return paginated(page, next_cursor, has_more, request_id=request_id)

    # /v1/tenant/registration-link — the company-facing view of the public
    # customer signup link, and the switch that governs it.
    #
    # Read is open to any staff role: knowing your own company's signup link is
    # not privileged, and staff share it. Changing it is tenant_admin only,
    # because turning it on opens an unauthenticated route into the tenant.
    if resource == "registration-link":
        if method == "GET":
            return success(service.get_self_registration_setting(tenant_id), request_id=request_id)

        if method == "PATCH":
            ctx.assert_role(UserRole.TENANT_ADMIN)
            body = _parse_body(event)
            req = parse_validated(SelfRegistrationUpdateRequest, body)
            result = service.set_self_registration_enabled(
                tenant_id,
                req.enabled,
                actor_id=ctx.user_id,
                actor_role=ctx.role.value if ctx.role else "",
                ip_address=ip_address,
            )
            return success(result, request_id=request_id)

    # /v1/tenant/config[/webhook/(rotate-secret|test)][/paystack[/test]]
    if resource == "config":
        config_sub = parts[3] if len(parts) > 3 else None  # "webhook" | "paystack"
        config_action = parts[4] if len(parts) > 4 else None  # "rotate-secret" | "test"

        # POST /v1/tenant/config/logo/upload-url — presign the logo upload (FD-29)
        if config_sub == "logo" and config_action == "upload-url" and method == "POST":
            ctx.assert_role(UserRole.TENANT_ADMIN)
            req_upload = parse_validated(LogoUploadRequest, _parse_body(event))
            result = branding_logo.create_logo_upload(
                tenant_id, req_upload.filename, req_upload.content_type, req_upload.size_bytes
            )
            return success(result, request_id=request_id, status_code=201)

        # PUT /v1/tenant/config/logo — use the uploaded file as the logo
        if config_sub == "logo" and config_action is None and method == "PUT":
            ctx.assert_role(UserRole.TENANT_ADMIN)
            req_logo = parse_validated(SetLogoRequest, _parse_body(event))
            result = branding_logo.set_logo(tenant_id, req_logo.file_key, actor_id=ctx.user_id, ip_address=ip_address)
            return success(result, request_id=request_id)

        # DELETE /v1/tenant/config/logo — back to the initials tile
        if config_sub == "logo" and config_action is None and method == "DELETE":
            ctx.assert_role(UserRole.TENANT_ADMIN)
            result = branding_logo.remove_logo(tenant_id, actor_id=ctx.user_id, ip_address=ip_address)
            return success(result, request_id=request_id)

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

        if config_sub is None:
            if method == "GET":
                return success(service.get_tenant_config(tenant_id, ctx=ctx), request_id=request_id)
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
                users = service.list_users(tenant_id)
                if not ctx.has_role(UserRole.TENANT_ADMIN):
                    users = [
                        {
                            "id": u.get("id"),
                            "full_name": u.get("full_name"),
                            "role": u.get("role"),
                            "roles": u.get("roles"),
                            "status": u.get("status"),
                        }
                        for u in users
                    ]
                return success(users, request_id=request_id)
        else:
            action = parts[4] if len(parts) > 4 else None
            if action == "resend-invite" and method == "POST":
                service.resend_user_invite(
                    tenant_id, user_id, actor_id=ctx.user_id, actor_role=ctx.role.value, ip_address=ip_address
                )
                return success({"message": "Invite resent"}, request_id=request_id)
            if action == "reset-password" and method == "POST":
                service.reset_user_password(
                    tenant_id, user_id, actor_id=ctx.user_id, actor_role=ctx.role.value, ip_address=ip_address
                )
                return success({"message": "Password reset email sent"}, request_id=request_id)
            if action == "reactivate" and method == "POST":
                # POST sub-action rather than reusing PATCH: deactivation is a
                # DELETE, so its inverse is a deliberate named action, not a
                # field someone could flip by accident in a partial update.
                result = service.reactivate_user(tenant_id, user_id, actor_id=ctx.user_id, ip_address=ip_address)
                return success(result, request_id=request_id)
            if action == "resend-activation" and method == "POST":
                result = service.resend_activation(
                    tenant_id,
                    user_id,
                    actor_id=ctx.user_id,
                    request_id=request_id,
                    actor_role=ctx.role.value,
                    ip_address=ip_address,
                )
                return success(result, request_id=request_id)
            if action is None:
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
                    result = service.update_user(
                        tenant_id,
                        user_id,
                        updates,
                        actor_id=ctx.user_id,
                        actor_role=ctx.role.value,
                        ip_address=ip_address,
                    )
                    return success(result, request_id=request_id)
                if method == "DELETE":
                    service.deactivate_user(
                        tenant_id,
                        user_id,
                        actor_id=ctx.user_id,
                        actor_role=ctx.role.value,
                        ip_address=ip_address,
                    )
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
        cursor, limit = parse_pagination_params(event.get("queryStringParameters"), default_limit=50)
        page, next_cursor, has_more = service.list_rate_history(
            tenant_id,
            rate_type=_qp(event, "rate_type") or None,
            limit=limit,
            cursor=cursor,
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
    customer_read_staff = (
        UserRole.TENANT_ADMIN,
        UserRole.CHINA_OFFICE_STAFF,
        UserRole.NIGERIA_OFFICE_STAFF,
        UserRole.WAREHOUSE_ATTENDANT,
    )
    customer_write_staff = (
        UserRole.TENANT_ADMIN,
        UserRole.CHINA_OFFICE_STAFF,
        UserRole.NIGERIA_OFFICE_STAFF,
    )

    # GET /v1/customers/stats — tenant-wide customer aggregates for the list
    # stats row (SQL-computed). Staff only; checked before the {id} branch.
    if customer_id == "stats" and action is None:
        if method == "GET":
            ctx.assert_role(*customer_read_staff)
            return success(service.get_customer_stats(tenant_id), request_id=request_id)
        raise ResourceNotFoundError("route", "/".join(parts))

    if not customer_id:
        # POST /v1/customers — office staff & tenant admin only
        if method == "POST":
            ctx.assert_role(*customer_write_staff)
            body = _parse_body(event)
            result = service.create_customer(
                tenant_id,
                body,
                actor_id=ctx.user_id,
                request_id=request_id,
                ip_address=ip_address,
                actor_role=ctx.role.value,
            )
            return created(
                result,
                location=f"/v1/customers/{result['id']}",
                request_id=request_id,
            )

        # GET /v1/customers — staff see the full list; a customer sees only
        # their own record (this doubles as the portal's "who am I" lookup —
        # there is no separate /v1/customers/me endpoint).
        if method == "GET":
            ctx.assert_role(*customer_read_staff, UserRole.CUSTOMER)
            if ctx.must_scope_to_customer(*customer_read_staff):
                own = service.get_customer_for_user(tenant_id, ctx.user_id)
                return paginated([own] if own else [], None, False, request_id=request_id)
            q = _qp(event, "q")
            cursor, limit = parse_pagination_params(event.get("queryStringParameters"), default_limit=50)
            page, next_cursor, has_more = service.list_customers(tenant_id, q=q, limit=limit, cursor=cursor)
            return paginated(page, next_cursor, has_more, request_id=request_id)

    else:
        if action is None:
            # GET /v1/customers/{id}
            if method == "GET":
                ctx.assert_role(*customer_read_staff, UserRole.CUSTOMER)
                result = service.get_customer(
                    tenant_id,
                    customer_id,
                    requesting_user_id=ctx.user_id,
                    is_customer_role=ctx.must_scope_to_customer(*customer_read_staff),
                )
                return success(result, request_id=request_id)

            # PATCH /v1/customers/{id} — office staff/admin (full field set, excluding user_id)
            # or the customer themselves (own record, restricted self-service fields only)
            if method == "PATCH":
                ctx.assert_role(*customer_write_staff, UserRole.CUSTOMER)
                body = _parse_body(event)
                if ctx.must_scope_to_customer(*customer_write_staff):
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
                result = service.update_customer(
                    tenant_id,
                    customer_id,
                    body,
                    actor_id=ctx.user_id,
                    actor_role=ctx.role.value,
                    ip_address=ip_address,
                )
                return success(result, request_id=request_id)

            # DELETE /v1/customers/{id} — GDPR/NDPR Art. 17 erasure.
            # tenant_admin, or the customer exercising their own right to be
            # forgotten (ownership verified; billing/shipment rows are kept but
            # de-linked by the anonymise routine).
            if method == "DELETE":
                ctx.assert_role(UserRole.TENANT_ADMIN, UserRole.CUSTOMER)
                is_self_erasure = ctx.must_scope_to_customer(UserRole.TENANT_ADMIN)
                if is_self_erasure:
                    service.get_customer(
                        tenant_id,
                        customer_id,
                        requesting_user_id=ctx.user_id,
                        is_customer_role=True,
                    )
                anonymised = service.anonymise_customer(
                    tenant_id,
                    customer_id,
                    actor_id=ctx.user_id,
                    actor_role="customer" if is_self_erasure else "tenant_admin",
                    ip_address=ip_address,
                )
                return success(anonymised or {}, request_id=request_id)

        else:
            # PATCH /v1/customers/{id}/credit — tenant_admin only (Phase 1, TC-04, D3)
            if action == "credit" and method == "PATCH":
                ctx.assert_role(UserRole.TENANT_ADMIN)
                req = parse_validated(UpdateCustomerCreditRequest, _parse_body(event))
                result = service.update_customer_credit(
                    tenant_id,
                    customer_id,
                    credit_limit_ngn=req.credit_limit_ngn,
                    credit_terms_days=req.credit_terms_days,
                    actor_id=ctx.user_id,
                    ip_address=ip_address,
                )
                return success(result, request_id=request_id)

            # POST /v1/customers/{id}/invite — office staff & tenant admin only;
            # issues a new invite, or resends (which invalidates any prior unconsumed one).
            if action == "invite" and method == "POST":
                ctx.assert_role(*customer_write_staff)
                result = service.issue_customer_invite(tenant_id, customer_id, actor_id=ctx.user_id, request_id=request_id)
                return created(result, location=f"/v1/customers/{customer_id}", request_id=request_id)

            # GET /v1/customers/{id}/export — tenant_admin or the customer themselves
            if action == "export" and method == "GET":
                ctx.assert_role(UserRole.TENANT_ADMIN, UserRole.CUSTOMER)
                is_customer_export = ctx.must_scope_to_customer(UserRole.TENANT_ADMIN)
                result = service.export_customer_data(
                    tenant_id,
                    customer_id,
                    requesting_user_id=ctx.user_id,
                    is_customer_role=is_customer_export,
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
