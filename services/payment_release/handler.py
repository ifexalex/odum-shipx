"""Payment Release Lambda handler.

Routes:
  POST  /v1/payments/{billing-id}/confirm       — tenant_admin, nigeria_office_staff
  POST  /v1/release-notes                       — tenant_admin, nigeria_office_staff
  GET   /v1/release-notes/{id}                  — tenant_admin, nigeria_office_staff,
                                                   warehouse_attendant, customer (own)
  PATCH /v1/release-notes/{id}/release          — warehouse_attendant
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
from shared.responses import created, error_response, success
from shared.tenant_context import UserRole

from . import service
from .models import ConfirmPaymentRequest, GenerateReleaseNoteRequest, RecordPickupRequest

# Module-level init (runs once on cold start)
setup_logging()
patch_all()

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

    if len(parts) < 2:
        raise ResourceNotFoundError("route", path)

    section = parts[1]

    if section == "payments":
        return _payment_routes(event, parts, method, ctx, request_id, ip_address)

    if section == "release-notes":
        return _release_note_routes(event, parts, method, ctx, request_id, ip_address)

    raise ResourceNotFoundError("route", path)


# ---------------------------------------------------------------------------
# Payment routes
# ---------------------------------------------------------------------------


def _payment_routes(event, parts, method, ctx, request_id, ip_address):
    billing_id = parts[2] if len(parts) > 2 else None
    action = parts[3] if len(parts) > 3 else None

    if billing_id and action == "confirm" and method == "POST":
        ctx.assert_role(*_PAYMENT_ROLES)
        body = _parse_body(event)
        req = _parse_validated(ConfirmPaymentRequest, body)
        result = service.confirm_payment(
            ctx.tenant_id, billing_id, req,
            actor_id=ctx.user_id,
            ctx=ctx,
            request_id=request_id,
        )
        return created(result, location=f"/v1/payments/{billing_id}/confirm", request_id=request_id)

    raise ResourceNotFoundError("route", "/".join(parts))


# ---------------------------------------------------------------------------
# Release note routes
# ---------------------------------------------------------------------------


def _release_note_routes(event, parts, method, ctx, request_id, ip_address):
    note_id = parts[2] if len(parts) > 2 else None
    action = parts[3] if len(parts) > 3 else None

    if note_id is None:
        # POST /v1/release-notes
        if method == "POST":
            ctx.assert_role(*_RELEASE_CREATE_ROLES)
            body = _parse_body(event)
            req = _parse_validated(GenerateReleaseNoteRequest, body)
            result = service.generate_release_note(
                ctx.tenant_id, req,
                actor_id=ctx.user_id,
                ctx=ctx,
                request_id=request_id,
            )
            return created(result, location=f"/v1/release-notes/{result['id']}", request_id=request_id)

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
                req = _parse_validated(RecordPickupRequest, body)
                result = service.record_pickup(
                    ctx.tenant_id, note_id, req,
                    actor_id=ctx.user_id,
                    ctx=ctx,
                    request_id=request_id,
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
