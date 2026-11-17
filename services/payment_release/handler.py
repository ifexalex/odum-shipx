"""Payment Release Lambda handler.

Routes:
  POST  /v1/payments/{billing-id}/confirm       — tenant_admin, nigeria_office_staff
  POST  /v1/payments/{billing-id}/initialize    — customer (own billing); Paystack hosted checkout
  POST  /v1/payments/{billing-id}/verify        — customer (own billing); reconcile a Paystack
                                                   payment directly, without waiting on the webhook
  POST  /v1/payments/claims/presigned-url       — customer (own billing)
  POST  /v1/payments/{billing-id}/claims        — customer (own billing)
  GET   /v1/payments/{billing-id}/claims        — tenant_admin, nigeria_office_staff, customer (own)
  PATCH /v1/payments/claims/{id}/confirm        — tenant_admin, nigeria_office_staff
  PATCH /v1/payments/claims/{id}/reject         — tenant_admin, nigeria_office_staff
  GET   /v1/payments/claims/{id}/evidence-url   — tenant_admin, nigeria_office_staff, customer (own)
  GET   /v1/release-notes                       — tenant_admin, nigeria_office_staff,
                                                   warehouse_attendant, customer (own)
  POST  /v1/release-notes                       — tenant_admin, nigeria_office_staff
  GET   /v1/release-notes/stats                 — tenant_admin, nigeria_office_staff, warehouse_attendant
  GET   /v1/release-notes/{id}                  — tenant_admin, nigeria_office_staff,
                                                   warehouse_attendant, customer (own)
  PATCH /v1/release-notes/{id}/release          — warehouse_attendant
  POST  /v1/release-notes/{id}/split            — tenant_admin, nigeria_office_staff
  POST  /v1/release-notes/{id}/reissue          — tenant_admin, nigeria_office_staff
  POST  /v1/release-notes/{id}/pickup-code      — tenant_admin, nigeria_office_staff (a fresh code, sent to the
                                                  customer; the response says where, never what)
  GET   /v1/warehouses                          — tenant_admin, nigeria_office_staff, warehouse_attendant
  POST  /v1/warehouses                          — tenant_admin
  PATCH /v1/warehouses/{id}/set-default         — tenant_admin
  POST  /v1/webhooks/payment                    — no JWT auth; HMAC-verified gateway webhook
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
from shared.observability import init_tracing
from shared.responses import created, error_response, success
from shared.tenant_context import UserRole
from shared.validation import parse_validated

from . import repository as repo
from . import service
from . import webhook as wh
from .models import (
    ConfirmPaymentRequest,
    CreateWarehouseRequest,
    GenerateReleaseNoteRequest,
    RecordPickupRequest,
    RejectPaymentClaimRequest,
    SplitReleaseNoteRequest,
    SubmitPaymentClaimRequest,
    UpdateWarehouseRequest,
    VerifyOnlinePaymentRequest,
)

# Module-level init (runs once on cold start)
setup_logging()
init_tracing()

logger = logging.getLogger(__name__)

_PAYMENT_ROLES = (
    UserRole.TENANT_ADMIN,
    UserRole.NIGERIA_OFFICE_STAFF,
)
_RELEASE_CREATE_ROLES = (
    UserRole.TENANT_ADMIN,
    UserRole.NIGERIA_OFFICE_STAFF,
)
_RELEASE_READ_ROLES = (
    UserRole.TENANT_ADMIN,
    UserRole.NIGERIA_OFFICE_STAFF,
    UserRole.WAREHOUSE_ATTENDANT,
    UserRole.CUSTOMER,
)
_PICKUP_ROLES = (UserRole.WAREHOUSE_ATTENDANT,)
_RELEASE_LIST_ROLES = (
    UserRole.TENANT_ADMIN,
    UserRole.NIGERIA_OFFICE_STAFF,
    UserRole.WAREHOUSE_ATTENDANT,
    UserRole.CUSTOMER,
)
_SPLIT_ROLES = (
    UserRole.TENANT_ADMIN,
    UserRole.NIGERIA_OFFICE_STAFF,
)
_CLAIM_SUBMIT_ROLES = (UserRole.CUSTOMER,)
_CLAIM_READ_ROLES = (
    UserRole.TENANT_ADMIN,
    UserRole.NIGERIA_OFFICE_STAFF,
    UserRole.CUSTOMER,
)
_CLAIM_REVIEW_ROLES = (
    UserRole.TENANT_ADMIN,
    UserRole.NIGERIA_OFFICE_STAFF,
)
_REISSUE_ROLES = (
    UserRole.TENANT_ADMIN,
    UserRole.NIGERIA_OFFICE_STAFF,
)
# Reading the warehouse list is not a Nigeria-side concern only: CHINA_OFFICE_STAFF
# are the people who create packing lists, and a packing list records which
# destination warehouse the cargo is bound for (migration 053). Omitting them
# here 403'd the arrival-warehouse picker, and because the frontend swallowed the
# failure the form showed "No warehouses configured" — a permission error
# displayed as a configuration state. Writing stays tenant_admin-only.
_WAREHOUSE_READ_ROLES = (
    UserRole.TENANT_ADMIN,
    UserRole.CHINA_OFFICE_STAFF,
    UserRole.NIGERIA_OFFICE_STAFF,
    UserRole.WAREHOUSE_ATTENDANT,
)
_WAREHOUSE_WRITE_ROLES = (UserRole.TENANT_ADMIN,)


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

    # Webhook routes bypass JWT auth — handle before get_tenant_context()
    parts = path.strip("/").split("/")
    if len(parts) >= 2 and parts[1] == "webhooks":
        try:
            return _webhook_routes(event, parts, method, request_id)
        except LogisticsBaseError as exc:
            logger.warning("Webhook error: %s - %s", exc.error_code, exc.message)
            return error_response(exc, instance=path, request_id=request_id)
        except Exception:
            logger.exception("Unhandled webhook error")
            return error_response(
                LogisticsBaseError("Internal server error", "INTERNAL_ERROR", 500),
                instance=path,
                request_id=request_id,
            )

    try:
        tenant_ctx = get_tenant_context(event)
        logger.info(
            "→ %s %s",
            method,
            path,
            extra={"request_id": request_id, "tenant_id": tenant_ctx.tenant_id},
        )

        # Idempotency for payment confirmation (POST only)
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
# Dispatch
# ---------------------------------------------------------------------------


def _dispatch(event: dict[str, Any], method: str, path: str, ctx: Any, request_id: str, ip_address: str | None) -> dict[str, Any]:
    parts = path.strip("/").split("/")

    if len(parts) < 2:
        raise ResourceNotFoundError("route", path)

    section = parts[1]

    if section == "payments":
        return _payment_routes(event, parts, method, ctx, request_id, ip_address)

    if section == "release-notes":
        return _release_note_routes(event, parts, method, ctx, request_id, ip_address)

    if section == "warehouses":
        return _warehouse_routes(event, parts, method, ctx, request_id)

    raise ResourceNotFoundError("route", path)


# ---------------------------------------------------------------------------
# Payment routes
# ---------------------------------------------------------------------------


def _payment_routes(
    event: dict[str, Any], parts: list[str], method: str, ctx: Any, request_id: str, ip_address: str | None
) -> dict[str, Any]:
    # /v1/payments/claims/... — claim-id-scoped and presigned-url routes,
    # distinguished from /v1/payments/{billing_id}/... by the literal "claims"
    # segment (a billing_id is a UUID and can never collide with it).
    if len(parts) > 2 and parts[2] == "claims":
        return _payment_claim_routes(event, parts, method, ctx, request_id)

    billing_id = parts[2] if len(parts) > 2 else None
    action = parts[3] if len(parts) > 3 else None

    # POST/GET /v1/payments/{billing-id}/claims — billing-scoped claim submission/listing
    if billing_id and action == "claims":
        if method == "POST":
            ctx.assert_role(*_CLAIM_SUBMIT_ROLES)
            body = _parse_body(event)
            req = parse_validated(SubmitPaymentClaimRequest, body)
            result: Any = service.submit_payment_claim(
                ctx.tenant_id, billing_id, req, actor_id=ctx.user_id, ctx=ctx, request_id=request_id
            )
            return created(result, location=f"/v1/payments/{billing_id}/claims/{result['id']}", request_id=request_id)
        if method == "GET":
            ctx.assert_role(*_CLAIM_READ_ROLES)
            result = service.list_payment_claims(ctx.tenant_id, billing_id, ctx)
            return success(result, request_id=request_id)

    # POST /v1/payments/{billing-id}/initialize — customer-own Paystack checkout
    # (audit gap B12). Ownership + amount guards live in the service; the
    # payment itself is only ever recorded by the verified gateway webhook.
    if billing_id and action == "initialize" and method == "POST":
        ctx.assert_role(UserRole.CUSTOMER)
        body = _parse_body(event)
        result = service.initialize_online_payment(
            ctx.tenant_id,
            billing_id,
            ctx,
            callback_url=body.get("callback_url"),
            request_id=request_id,
        )
        return success(result, request_id=request_id)

    # POST /v1/payments/{billing-id}/verify — reconcile a Paystack payment
    # directly (ground-truth gap: the webhook alone never reaches a local
    # dev URL, and can be delayed/lost even in production). Same customer-
    # own-billing ownership check as initialize; a real ExternalServiceError
    # (Paystack unreachable) is allowed to surface as a 502 to the caller —
    # there's nothing to silently swallow here the way the webhook route does.
    if billing_id and action == "verify" and method == "POST":
        ctx.assert_role(UserRole.CUSTOMER)
        body = _parse_body(event)
        req = parse_validated(VerifyOnlinePaymentRequest, body)
        result = service.confirm_online_payment(
            ctx.tenant_id,
            billing_id,
            req.reference,
            ctx,
            request_id=request_id,
        )
        return success(result, request_id=request_id)

    if billing_id and action == "confirm" and method == "POST":
        ctx.assert_role(*_PAYMENT_ROLES)
        body = _parse_body(event)
        req = parse_validated(ConfirmPaymentRequest, body)
        result = service.confirm_payment(
            ctx.tenant_id,
            billing_id,
            req,
            actor_id=ctx.user_id,
            ctx=ctx,
            request_id=request_id,
        )
        return created(result, location=f"/v1/payments/{billing_id}/confirm", request_id=request_id)

    raise ResourceNotFoundError("route", "/".join(parts))


def _payment_claim_routes(event: dict[str, Any], parts: list[str], method: str, ctx: Any, request_id: str) -> dict[str, Any]:
    """Routes under /v1/payments/claims/... — see _payment_routes for the
    billing-scoped submit/list routes under /v1/payments/{billing_id}/claims.
    """
    sub = parts[3] if len(parts) > 3 else None  # "presigned-url" | claim_id

    # POST /v1/payments/claims/presigned-url — evidence upload for a claim
    # not yet created (mirrors services/claims's presigned-URL flow: the file
    # is uploaded first, then its key is included in the claim submission).
    if sub == "presigned-url" and method == "POST":
        ctx.assert_role(*_CLAIM_SUBMIT_ROLES)
        body = _parse_body(event)
        billing_id = body.get("billing_id")
        filename = body.get("filename")
        content_type = body.get("content_type")
        if not billing_id or not filename or not content_type:
            from shared.exceptions import ValidationError

            raise ValidationError(
                "billing_id, filename, and content_type are required",
                field_errors={"body": "billing_id, filename, and content_type are required"},
            )
        result = service.generate_payment_claim_upload_url(ctx.tenant_id, billing_id, filename, content_type, ctx)
        return success(result, request_id=request_id)

    claim_id = sub
    action = parts[4] if len(parts) > 4 else None

    if claim_id and action == "confirm" and method == "PATCH":
        ctx.assert_role(*_CLAIM_REVIEW_ROLES)
        result = service.confirm_payment_claim(ctx.tenant_id, claim_id, actor_id=ctx.user_id, ctx=ctx, request_id=request_id)
        return success(result, request_id=request_id)

    if claim_id and action == "reject" and method == "PATCH":
        ctx.assert_role(*_CLAIM_REVIEW_ROLES)
        body = _parse_body(event)
        req = parse_validated(RejectPaymentClaimRequest, body)
        result = service.reject_payment_claim(ctx.tenant_id, claim_id, req, actor_id=ctx.user_id, ctx=ctx, request_id=request_id)
        return success(result, request_id=request_id)

    # GET /v1/payments/claims/{id}/evidence-url — staff need to actually see
    # the receipt before confirming; customer (own claim) can also re-view
    # what they uploaded.
    if claim_id and action == "evidence-url" and method == "GET":
        ctx.assert_role(*_CLAIM_READ_ROLES)
        result = service.get_payment_claim_evidence_url(ctx.tenant_id, claim_id, ctx)
        return success(result, request_id=request_id)

    raise ResourceNotFoundError("route", "/".join(parts))


# ---------------------------------------------------------------------------
# Release note routes
# ---------------------------------------------------------------------------


def _release_note_routes(
    event: dict[str, Any], parts: list[str], method: str, ctx: Any, request_id: str, ip_address: str | None
) -> dict[str, Any]:
    note_id = parts[2] if len(parts) > 2 else None
    action = parts[3] if len(parts) > 3 else None

    if note_id is None:
        # GET /v1/release-notes
        if method == "GET":
            ctx.assert_role(*_RELEASE_LIST_ROLES)
            filters = {}
            if _qp(event, "customer_id"):
                filters["customer_id"] = _qp(event, "customer_id")
            if _qp(event, "container_id"):
                filters["container_id"] = _qp(event, "container_id")
            if _qp(event, "status"):
                filters["status"] = _qp(event, "status")
            if _qp(event, "reference"):
                # Warehouse scan-or-type lookup (P2-2) — exact reference match.
                filters["reference"] = _qp(event, "reference")
            from shared.pagination import decode_cursor

            limit = int(_qp(event, "limit", 50))
            cursor = decode_cursor(_qp(event, "cursor"))
            page, next_cursor, has_more = service.list_release_notes(ctx.tenant_id, filters, limit, cursor, ctx)
            from shared.responses import paginated

            return paginated(page, next_cursor, has_more, request_id=request_id)

        # POST /v1/release-notes
        if method == "POST":
            ctx.assert_role(*_RELEASE_CREATE_ROLES)
            body = _parse_body(event)
            req = parse_validated(GenerateReleaseNoteRequest, body)
            result = service.generate_release_note(
                ctx.tenant_id,
                req,
                actor_id=ctx.user_id,
                ctx=ctx,
                request_id=request_id,
            )
            return created(result, location=f"/v1/release-notes/{result['id']}", request_id=request_id)

    elif note_id == "stats":
        # GET /v1/release-notes/stats — per-status counts for the list stats
        # row (§9.1, P2-3). Staff/warehouse only: tenant-wide aggregates are
        # not for the customer role.
        if method == "GET":
            ctx.assert_role(UserRole.TENANT_ADMIN, UserRole.NIGERIA_OFFICE_STAFF, UserRole.WAREHOUSE_ATTENDANT)
            return success(service.get_release_note_stats(ctx.tenant_id), request_id=request_id)

    else:
        if action is None:
            # GET /v1/release-notes/{id}
            if method == "GET":
                ctx.assert_role(*_RELEASE_READ_ROLES)
                result = service.get_release_note(ctx.tenant_id, note_id, ctx)
                return success(result, request_id=request_id)

        else:
            # PATCH /v1/release-notes/{id}/release
            if action == "release" and method == "PATCH":
                ctx.assert_role(*_PICKUP_ROLES)
                body = _parse_body(event)
                req = parse_validated(RecordPickupRequest, body)
                result = service.record_pickup(
                    ctx.tenant_id,
                    note_id,
                    req,
                    actor_id=ctx.user_id,
                    ctx=ctx,
                    request_id=request_id,
                )
                return success(result, request_id=request_id)

            # POST /v1/release-notes/{id}/split
            if action == "split" and method == "POST":
                ctx.assert_role(*_SPLIT_ROLES)
                body = _parse_body(event)
                req = parse_validated(SplitReleaseNoteRequest, body)
                result = service.split_release_note(
                    ctx.tenant_id,
                    note_id,
                    req,
                    actor_id=ctx.user_id,
                    ctx=ctx,
                    request_id=request_id,
                )
                return created(result, location=f"/v1/release-notes/{result['id']}", request_id=request_id)

            # POST /v1/release-notes/{id}/pickup-code — a fresh pickup code, sent to the customer (audit UX-09)
            if action == "pickup-code" and method == "POST":
                ctx.assert_role(*_REISSUE_ROLES)
                result = service.reissue_pickup_code(
                    ctx.tenant_id,
                    note_id,
                    actor_id=ctx.user_id,
                    ctx=ctx,
                    request_id=request_id,
                )
                return success(result, request_id=request_id)

            # POST /v1/release-notes/{id}/reissue
            if action == "reissue" and method == "POST":
                ctx.assert_role(*_REISSUE_ROLES)
                result = service.reissue_release_note(
                    ctx.tenant_id,
                    note_id,
                    actor_id=ctx.user_id,
                    ctx=ctx,
                    request_id=request_id,
                )
                return created(result, location=f"/v1/release-notes/{result['id']}", request_id=request_id)

    raise ResourceNotFoundError("route", "/".join(parts))


# ---------------------------------------------------------------------------
# Warehouse routes — branch/office letterheads for release-note generation
# and pickup recording (multi-branch tenants, per the paper form this
# feature was audited against).
# ---------------------------------------------------------------------------


def _warehouse_routes(event: dict[str, Any], parts: list[str], method: str, ctx: Any, request_id: str) -> dict[str, Any]:
    warehouse_id = parts[2] if len(parts) > 2 else None
    action = parts[3] if len(parts) > 3 else None

    # GET /v1/warehouses
    if warehouse_id is None and method == "GET":
        ctx.assert_role(*_WAREHOUSE_READ_ROLES)
        result: Any = service.list_warehouses(ctx.tenant_id)
        return success(result, request_id=request_id)

    # POST /v1/warehouses
    if warehouse_id is None and method == "POST":
        ctx.assert_role(*_WAREHOUSE_WRITE_ROLES)
        body = _parse_body(event)
        req = parse_validated(CreateWarehouseRequest, body)
        result = service.create_warehouse(ctx.tenant_id, req, actor_id=ctx.user_id, actor_role=str(ctx.role))
        return created(result, location="/v1/warehouses", request_id=request_id)

    # PATCH /v1/warehouses/{id}/set-default
    if warehouse_id and action == "set-default" and method == "PATCH":
        ctx.assert_role(*_WAREHOUSE_WRITE_ROLES)
        result = service.set_default_warehouse(ctx.tenant_id, warehouse_id, actor_id=ctx.user_id, actor_role=str(ctx.role))
        return success(result, request_id=request_id)

    # PATCH /v1/warehouses/{id} — edit letterhead fields
    if warehouse_id and action is None and method == "PATCH":
        ctx.assert_role(*_WAREHOUSE_WRITE_ROLES)
        body = _parse_body(event)
        req = parse_validated(UpdateWarehouseRequest, body)
        result = service.update_warehouse(ctx.tenant_id, warehouse_id, req, actor_id=ctx.user_id, actor_role=str(ctx.role))
        return success(result, request_id=request_id)

    # PATCH /v1/warehouses/{id}/deactivate — retire without deleting.
    # The path for a warehouse handover documents reference, so DELETE refuses it.
    if warehouse_id and action == "deactivate" and method == "PATCH":
        ctx.assert_role(*_WAREHOUSE_WRITE_ROLES)
        result = service.deactivate_warehouse(ctx.tenant_id, warehouse_id, actor_id=ctx.user_id, actor_role=str(ctx.role))
        return success(result, request_id=request_id)

    # DELETE /v1/warehouses/{id} — a real delete. Refused with WAREHOUSE_IN_USE
    # when a release note / pickup / payment record / packing list references it;
    # the caller is then pointed at the deactivate route above.
    if warehouse_id and action is None and method == "DELETE":
        ctx.assert_role(*_WAREHOUSE_WRITE_ROLES)
        result = service.delete_warehouse(ctx.tenant_id, warehouse_id, actor_id=ctx.user_id, actor_role=str(ctx.role))
        return success(result, request_id=request_id)

    raise ResourceNotFoundError("route", "/".join(parts))


# ---------------------------------------------------------------------------
# Webhook routes (no JWT auth — HMAC verified)
# ---------------------------------------------------------------------------


def _webhook_routes(event: dict[str, Any], parts: list[str], method: str, request_id: str) -> dict[str, Any]:
    """Handle POST /v1/webhooks/payment from Paystack or Flutterwave.

    No JWT auth. Signature is verified via HMAC before any processing.
    Returns 200 immediately on any rejection (bad signature, unknown
    billing_id, tenant has no gateway configured) to avoid timing/response
    differences that would let an outside caller distinguish these cases —
    same posture regardless of *why* a webhook was rejected.

    Paystack (2026-07-19 — multi-tenant): there is no shared platform secret
    to verify against anymore, so the usual "verify signature, then resolve
    tenant" order is inverted for this gateway — tenant must be resolved
    FIRST (from the billing_id in the payload's reference, a harmless read)
    so the signature can be checked against that specific tenant's own key.
    No database write happens, and nothing about the outcome is ever
    reflected in the response, until AFTER a valid signature is confirmed —
    see webhook.py's module docstring for the full security reasoning.
    """
    resource = parts[2] if len(parts) > 2 else None

    if resource == "payment" and method == "POST":
        headers = event.get("headers") or {}
        raw_body: bytes = (event.get("body") or "").encode()
        payload = _parse_body(event)

        paystack_sig = headers.get("x-paystack-signature", "")
        flutterwave_hash = headers.get("verif-hash", "")

        extracted: dict[str, Any] | None = None
        tenant_id: str | None = None

        if paystack_sig:
            extracted = wh.extract_paystack_payment(payload)
            if not extracted:
                # Non-payment event type or non-successful status — acknowledge and skip.
                return {"statusCode": 200, "body": ""}

            billing_id = extracted.get("billing_id", "")
            tenant_id = wh.get_billing_tenant(billing_id)
            if not tenant_id:
                logger.warning("Paystack webhook for unknown billing_id=%s — rejecting", billing_id)
                return {"statusCode": 200, "body": ""}

            secret_key = repo.get_tenant_paystack_secret(tenant_id)
            if not secret_key:
                logger.warning("Paystack webhook for tenant=%s with no configured gateway — rejecting", tenant_id)
                return {"statusCode": 200, "body": ""}

            if not wh.verify_paystack_signature(raw_body, paystack_sig, secret_key):
                logger.warning("Invalid Paystack HMAC signature for tenant=%s — rejecting webhook", tenant_id)
                return {"statusCode": 200, "body": ""}

        elif flutterwave_hash:
            # Out of scope for the Paystack multi-tenant migration — no
            # frontend integration exists for Flutterwave, kept on its
            # original single env-var secret. Tenant is still resolved the
            # old way (after verification), since it has no per-tenant key.
            if not wh.verify_flutterwave_signature(flutterwave_hash):
                logger.warning("Invalid Flutterwave verif-hash — rejecting webhook")
                return {"statusCode": 200, "body": ""}
            extracted = wh.extract_flutterwave_payment(payload)
            if not extracted:
                return {"statusCode": 200, "body": ""}
            billing_id = extracted.get("billing_id", "")
            tenant_id = wh.get_billing_tenant(billing_id)
            if not tenant_id:
                logger.warning("Flutterwave webhook for unknown billing_id=%s — rejecting", billing_id)
                return {"statusCode": 200, "body": ""}

        else:
            logger.warning("Webhook missing gateway signature headers — rejecting")
            return {"statusCode": 200, "body": ""}

        result = service.process_webhook_payment(
            tenant_id=tenant_id,
            billing_id=billing_id,
            amount_ngn=extracted["amount_ngn"],
            payment_method=extracted["payment_method"],
            payment_reference=extracted["payment_reference"],
            gateway_transaction_id=extracted["gateway_transaction_id"],
            request_id=request_id,
        )

        logger.info(
            "Webhook payment processed: billing=%s gateway_tx=%s result=%s",
            billing_id,
            extracted["gateway_transaction_id"],
            "duplicate_skipped" if result is None else result.get("new_payment_status"),
        )
        return {"statusCode": 200, "body": ""}

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
