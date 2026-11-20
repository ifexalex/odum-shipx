"""Billing Lambda handler.

Routes:
  GET   /v1/billing/carryovers                       — tenant_admin, nigeria_office_staff
  PATCH /v1/billing/carryovers/{id}/exempt           — tenant_admin
  POST  /v1/billing/{billing-id}/charges             — tenant_admin, nigeria_office_staff
  GET   /v1/billing/{billing-id}/charges             — tenant_admin, nigeria_office_staff, customer (own)
  DELETE /v1/billing/{billing-id}/charges/{id}       — tenant_admin
  GET   /v1/billing/{billing-id}/storage-fees        — tenant_admin, nigeria_office_staff, customer (own)
  GET   /v1/billing/disputes                         — nigeria_office_staff, tenant_admin, china_office_staff
  GET   /v1/billing/disputes/{dispute-id}            — same roles; measurement data only, no payment data
  GET   /v1/billing/{customer-id}                    — tenant_admin, nigeria_office_staff, customer (own)
  GET   /v1/billing/{billing-id}/detail              — tenant_admin, nigeria_office_staff, customer (own)
  POST  /v1/billing/{billing-id}/dispute             — customer
  GET   /v1/billing/{billing-id}/disputes            — nigeria_office_staff, tenant_admin, customer (own)
  PATCH /v1/billing/disputes/{dispute-id}/acknowledge — nigeria_office_staff
  PATCH /v1/billing/disputes/{dispute-id}/resolve    — nigeria_office_staff, china_office_staff, tenant_admin
  PATCH /v1/billing/{billing-id}/cancel              — tenant_admin, nigeria_office_staff
  PATCH /v1/billing/{billing-id}/apply-carryover     — tenant_admin, nigeria_office_staff

EventBridge:
  source=logistics.tracking, detail-type=PaymentDue → auto-create billing
"""

import json
import logging
import time
import uuid
from typing import Any

from shared.auth import get_tenant_context
from shared.client_ip import client_ip
from shared.exceptions import LogisticsBaseError, ResourceNotFoundError
from shared.idempotency import check_idempotency, store_idempotency
from shared.logging_config import bind_log_context, clear_log_context, setup_logging
from shared.metering import record_usage
from shared.observability import init_tracing, record_failure
from shared.pagination import decode_cursor
from shared.responses import created, error_response, no_content, paginated, success
from shared.tenant_context import UserRole
from shared.validation import parse_validated

from . import service
from .models import (
    CancelBillingRequest,
    ExemptCarryoverRequest,
    FileCBMDisputeRequest,
    GenerateBillingRequest,
    ResolveCBMDisputeRequest,
)

# Module-level init (runs once on cold start)
setup_logging()
init_tracing()

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
_CARRYOVER_APPLY_ROLES = (UserRole.TENANT_ADMIN, UserRole.NIGERIA_OFFICE_STAFF)
_CHARGE_WRITE_ROLES = (UserRole.TENANT_ADMIN, UserRole.NIGERIA_OFFICE_STAFF)
_CHARGE_READ_ROLES = (UserRole.TENANT_ADMIN, UserRole.NIGERIA_OFFICE_STAFF, UserRole.CUSTOMER)
_CHARGE_DELETE_ROLES = (UserRole.TENANT_ADMIN,)
_STORAGE_FEE_READ_ROLES = (UserRole.TENANT_ADMIN, UserRole.NIGERIA_OFFICE_STAFF, UserRole.CUSTOMER)
_CANCEL_BILLING_ROLES = (UserRole.TENANT_ADMIN, UserRole.NIGERIA_OFFICE_STAFF)


# ---------------------------------------------------------------------------
# Lambda entry point
# ---------------------------------------------------------------------------


def lambda_handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
    # EventBridge events arrive with a "source" key
    if event.get("source") == "logistics.tracking":
        return _handle_event(event)

    # API Gateway HTTP
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
            idempotency_key = (event.get("headers") or {}).get("idempotency-key")
            cached = check_idempotency(idempotency_key, tenant_ctx.tenant_id)
            if cached:
                return cached

        response = _dispatch(event, method, path, tenant_ctx, request_id, ip_address)

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
# EventBridge handler
# ---------------------------------------------------------------------------


def _handle_event(event: dict[str, Any]) -> dict[str, Any]:
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
            record_failure("invoice_generation")
    else:
        logger.info("Ignoring unhandled event type: %s", detail_type)

    return {"statusCode": 200}


# ---------------------------------------------------------------------------
# HTTP dispatch
# ---------------------------------------------------------------------------


def _dispatch(event: dict[str, Any], method: str, path: str, ctx: Any, request_id: str, ip_address: str | None) -> dict[str, Any]:
    parts = path.strip("/").split("/")

    if len(parts) < 2 or parts[0] != "v1" or parts[1] != "billing":
        raise ResourceNotFoundError("route", path)

    segment = parts[2] if len(parts) > 2 else None

    # /v1/billing — top-level list and generate
    if segment is None:
        if method == "GET":
            ctx.assert_role(*_BILLING_READ_ROLES)
            filters: dict[str, Any] = {}
            if _qp(event, "status"):
                # Comma-separated multi-select (Filters panel) — a single
                # status is just a 1-element list, matched against
                # ANY(%(statuses)s) in list_billing_all.
                filters["status"] = [s for s in _qp(event, "status", "").split(",") if s]
            if _qp(event, "customer_id"):
                filters["customer_id"] = _qp(event, "customer_id")
            if _qp(event, "created_after"):
                filters["created_after"] = _qp(event, "created_after")
            if _qp(event, "created_before"):
                filters["created_before"] = _qp(event, "created_before")
            if (_qp(event, "overdue") or "").lower() in ("true", "1"):
                # Only invoices owed for over 30 days: what the "Overdue" stat opens (FD-18).
                filters["overdue"] = True
            if _qp(event, "q"):
                # Free-text search over invoice_number / customer name /
                # container_number (ILIKE in list_billing_all). The frontend
                # BillingList search box sends ?q= — it was silently dropped.
                filters["q"] = _qp(event, "q")
            limit = int(_qp(event, "limit", 50))
            cursor = decode_cursor(_qp(event, "cursor"))
            sort_field = _qp(event, "sort") or "created_at"
            sort_direction = _qp(event, "direction") or "desc"
            page, next_cursor, has_more = service.list_billing(
                ctx.tenant_id,
                filters,
                limit,
                cursor,
                ctx=ctx,
                sort_field=sort_field,
                sort_direction=sort_direction,
            )
            return paginated(page, next_cursor, has_more, request_id=request_id)
        if method == "POST":
            ctx.assert_role(*_CHARGE_WRITE_ROLES)
            req = parse_validated(GenerateBillingRequest, _parse_body(event))
            result = service.generate_billing(ctx.tenant_id, req, actor_id=ctx.user_id, ctx=ctx)
            if req.customer_id is None:
                return success(result, request_id=request_id)
            return created(result, location="/v1/billing", request_id=request_id)
        raise ResourceNotFoundError("route", path)

    # GET /v1/billing/stats — tenant-wide aggregates for the list stats row +
    # status-chip counts. Staff only (a tenant-wide money summary is not for
    # the customer role), and computed in SQL so it stays correct at scale.
    if segment == "stats":
        if method == "GET":
            ctx.assert_role(UserRole.TENANT_ADMIN, UserRole.NIGERIA_OFFICE_STAFF)
            return success(service.get_billing_stats(ctx.tenant_id), request_id=request_id)
        raise ResourceNotFoundError("route", path)

    # GET /v1/billing/unbilled — customers on cleared containers with CBM to bill and no
    # invoice (dashboard queue). Staff only; completed by POST /v1/billing {container_id}.
    if segment == "unbilled":
        if method == "GET":
            ctx.assert_role(UserRole.TENANT_ADMIN, UserRole.NIGERIA_OFFICE_STAFF)
            return success(service.list_unbilled_customers(ctx.tenant_id), request_id=request_id)
        raise ResourceNotFoundError("route", path)

    # GET /v1/billing/report?created_after=&created_before= — period report
    # aggregates for the TenantReports page (revenue, CBM, by-status, top
    # customers, per-container billing). Tenant-admin only; SQL-computed.
    if segment == "report":
        if method == "GET":
            # Same tenant-wide-aggregate data class as /billing/stats (which
            # both staff roles already read); the reports *page* is tenant-admin
            # gated in the UI route table.
            ctx.assert_role(UserRole.TENANT_ADMIN, UserRole.NIGERIA_OFFICE_STAFF)
            return success(
                service.get_tenant_report(
                    ctx.tenant_id,
                    created_after=_qp(event, "created_after") or None,
                    created_before=_qp(event, "created_before") or None,
                ),
                request_id=request_id,
            )
        raise ResourceNotFoundError("route", path)

    # /v1/billing/carryovers[/{id}/exempt]
    if segment == "carryovers":
        return _carryover_routes(event, parts, method, ctx, request_id, ip_address)

    # /v1/billing/disputes[/{dispute_id}/{action}]
    if segment == "disputes":
        return _dispute_action_routes(event, parts, method, ctx, request_id, ip_address)

    # GET /v1/billing/payments — recent payments across all billings (§6.1
    # dashboard feed, P2-5). Staff only — a tenant-wide money feed is not for
    # the customer role.
    if segment == "payments":
        if method == "GET":
            ctx.assert_role(UserRole.TENANT_ADMIN, UserRole.NIGERIA_OFFICE_STAFF)
            limit = min(int(_qp(event, "limit", 8)), 50)
            results = service.list_recent_payments(ctx.tenant_id, limit)
            return success(results, request_id=request_id)
        raise ResourceNotFoundError("route", path)

    # /v1/billing/{resource_id}[/{action}[/{sub_id}]]
    resource_id = segment
    action = parts[3] if len(parts) > 3 else None
    sub_id = parts[4] if len(parts) > 4 else None

    return _billing_routes(event, parts, method, ctx, request_id, ip_address, resource_id, action, sub_id)


def _carryover_routes(
    event: dict[str, Any], parts: list[str], method: str, ctx: Any, request_id: str, ip_address: str | None
) -> dict[str, Any]:
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
            page, next_cursor, has_more = service.list_carryovers(tenant_id, filters, limit, cursor)
            return paginated(page, next_cursor, has_more, request_id=request_id)

    elif action == "exempt" and method == "PATCH":
        # PATCH /v1/billing/carryovers/{id}/exempt
        ctx.assert_role(*_CARRYOVER_EXEMPT_ROLES)
        body = _parse_body(event)
        req = parse_validated(ExemptCarryoverRequest, body)
        result = service.exempt_carryover(
            tenant_id,
            carryover_id,
            req.notes,
            actor_id=ctx.user_id,
            ip_address=ip_address,
        )
        return success(result, request_id=request_id)

    raise ResourceNotFoundError("route", "/".join(parts))


def _billing_routes(
    event: dict[str, Any],
    parts: list[str],
    method: str,
    ctx: Any,
    request_id: str,
    ip_address: str | None,
    resource_id: str,
    action: str | None,
    sub_id: str | None = None,
) -> dict[str, Any]:
    tenant_id = ctx.tenant_id

    if action is None:
        # GET /v1/billing/{customer-id}
        if method == "GET":
            ctx.assert_role(*_BILLING_READ_ROLES)
            container_id = _qp(event, "container_id")
            results = service.get_billing_for_customer(tenant_id, resource_id, ctx, container_id)
            return success(results, request_id=request_id)

    else:
        if action == "dispute" and method == "POST":
            # POST /v1/billing/{billing-id}/dispute
            ctx.assert_role(UserRole.CUSTOMER)
            body = _parse_body(event)
            req = parse_validated(FileCBMDisputeRequest, body)
            result = service.file_cbm_dispute(
                tenant_id,
                resource_id,
                req,
                actor_id=ctx.user_id,
                ctx=ctx,
                request_id=request_id,
            )
            return created(result, location=f"/v1/billing/{resource_id}/disputes", request_id=request_id)

        if action == "detail" and method == "GET":
            # GET /v1/billing/{billing-id}/detail — single record by its OWN id.
            # It lives under /{billing-id}/ rather than at /v1/billing/{id}
            # because that bare shape is already taken by the customer-id read
            # above, and both ids are UUIDs so the two cannot be told apart.
            ctx.assert_role(*_BILLING_READ_ROLES)
            return success(service.get_billing(tenant_id, resource_id, ctx), request_id=request_id)

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
                    tenant_id,
                    resource_id,
                    body,
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
                    tenant_id,
                    resource_id,
                    sub_id,
                    actor_id=ctx.user_id,
                    ip_address=ip_address,
                )
                return no_content(request_id=request_id)

        if action == "storage-fees" and method == "GET":
            # GET /v1/billing/{billing-id}/storage-fees
            ctx.assert_role(*_STORAGE_FEE_READ_ROLES)
            results = service.list_storage_fees(tenant_id, resource_id, ctx)
            return success(results, request_id=request_id)

        if action == "storage-fees" and sub_id == "waive" and method == "POST":
            # POST /v1/billing/{billing-id}/storage-fees/waive
            ctx.assert_role(UserRole.TENANT_ADMIN, UserRole.NIGERIA_OFFICE_STAFF)
            body = _parse_body(event)
            reason = body.get("reason", "")
            result = service.waive_storage_fees(
                tenant_id,
                resource_id,
                reason=reason,
                actor_id=ctx.user_id,
                ip_address=ip_address or "",
            )
            return success(result, request_id=request_id)

        if action == "cancel" and method == "PATCH":
            # PATCH /v1/billing/{billing-id}/cancel
            ctx.assert_role(*_CANCEL_BILLING_ROLES)
            body = _parse_body(event)
            req = parse_validated(CancelBillingRequest, body)
            result = service.cancel_billing(
                tenant_id,
                resource_id,
                req.cancel_reason,
                actor_id=ctx.user_id,
                ip_address=ip_address,
            )
            return success(result, request_id=request_id)

        if action == "apply-carryover" and method == "PATCH":
            # PATCH /v1/billing/{billing-id}/apply-carryover
            ctx.assert_role(*_CARRYOVER_APPLY_ROLES)
            body = _parse_body(event)
            carryover_id = body.get("carryover_id", "")
            if not carryover_id:
                from shared.exceptions import ValidationError

                raise ValidationError("Request validation failed", field_errors={"carryover_id": "required"})
            result = service.apply_carryover(
                tenant_id,
                resource_id,
                carryover_id,
                actor_id=ctx.user_id,
                ip_address=ip_address,
            )
            return success(result, request_id=request_id)

    raise ResourceNotFoundError("route", "/".join(parts))


def _dispute_action_routes(
    event: dict[str, Any], parts: list[str], method: str, ctx: Any, request_id: str, ip_address: str | None
) -> dict[str, Any]:
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
            page, next_cursor, has_more, total = service.list_disputes(tenant_id, filters, limit, cursor)
            return paginated(page, next_cursor, has_more, total_count=total, request_id=request_id)
        # POST /v1/billing/disputes — create a dispute (billing_id in body)
        if method == "POST":
            ctx.assert_role(*_DISPUTE_LIST_ALL_ROLES)
            body = _parse_body(event)
            result = service.create_dispute(tenant_id, body, actor_id=ctx.user_id, ctx=ctx, request_id=request_id)
            return created(result, location=f"/v1/billing/disputes/{result.get('id', '')}", request_id=request_id)
        raise ResourceNotFoundError("route", "/".join(parts))

    # GET /v1/billing/disputes/{dispute-id} — measurement data only (UX-01)
    if action is None and method == "GET":
        ctx.assert_role(*_DISPUTE_LIST_ALL_ROLES)
        return success(service.get_dispute_detail(tenant_id, dispute_id), request_id=request_id)

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
        req = parse_validated(ResolveCBMDisputeRequest, body)
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
