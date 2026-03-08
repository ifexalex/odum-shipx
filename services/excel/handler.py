"""Excel Lambda handler — export and import routes.

Routes:
  GET  /v1/packing-lists/{id}/export          — china_office_staff, nigeria_office_staff, tenant_admin
  GET  /v1/manifests/{id}/export              — china_office_staff, nigeria_office_staff, tenant_admin
  GET  /v1/billing/{id}/export                — nigeria_office_staff, tenant_admin
  GET  /v1/containers/{id}/billing/export     — nigeria_office_staff, tenant_admin
  POST /v1/packing-lists/import               — china_office_staff
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
from .models import ImportRequest

setup_logging()
patch_all()

logger = logging.getLogger(__name__)

_EXPORT_ROLES = (
    UserRole.PLATFORM_ADMIN,
    UserRole.TENANT_ADMIN,
    UserRole.CHINA_OFFICE_STAFF,
    UserRole.NIGERIA_OFFICE_STAFF,
)
_BILLING_EXPORT_ROLES = (
    UserRole.PLATFORM_ADMIN,
    UserRole.TENANT_ADMIN,
    UserRole.NIGERIA_OFFICE_STAFF,
)
_IMPORT_ROLES = (UserRole.CHINA_OFFICE_STAFF,)


def lambda_handler(event: dict, context) -> dict:
    start_time = time.time()
    request_id = (
        event.get("requestContext", {}).get("requestId") or str(uuid.uuid4())
    )
    http = event.get("requestContext", {}).get("http", {})
    method = http.get("method", "")
    path = http.get("path", "")

    try:
        tenant_ctx = get_tenant_context(event)
        logger.info(
            "→ %s %s",
            method,
            path,
            extra={"request_id": request_id, "tenant_id": tenant_ctx.tenant_id},
        )
        response = _dispatch(event, method, path, tenant_ctx, request_id)
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


def _parse_body(event: dict) -> dict:
    raw = event.get("body") or "{}"
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return {}


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


def _dispatch(event, method, path, ctx, request_id):
    parts = path.strip("/").split("/")
    tenant_id = ctx.tenant_id

    if len(parts) < 2 or parts[0] != "v1":
        raise ResourceNotFoundError("route", path)

    resource = parts[1]

    # POST /v1/packing-lists/import
    if resource == "packing-lists" and len(parts) == 3 and parts[2] == "import" and method == "POST":
        ctx.assert_role(*_IMPORT_ROLES)
        body = _parse_body(event)
        req = _parse_validated(ImportRequest, body)
        result = service.import_packing_list(
            tenant_id,
            container_id=req.container_id,
            file_key=req.file_key,
            actor_id=ctx.user_id,
        )
        return created(result, location="/v1/packing-lists", request_id=request_id)

    fmt = _resolve_format(event)

    # GET /v1/packing-lists/{id}/export
    if resource == "packing-lists" and len(parts) == 4 and parts[3] == "export" and method == "GET":
        ctx.assert_role(*_EXPORT_ROLES)
        result = service.export_packing_list(tenant_id, parts[2], fmt=fmt)
        return success(result, request_id=request_id)

    # GET /v1/manifests/{id}/export
    if resource == "manifests" and len(parts) == 4 and parts[3] == "export" and method == "GET":
        ctx.assert_role(*_EXPORT_ROLES)
        result = service.export_manifest(tenant_id, parts[2], fmt=fmt)
        return success(result, request_id=request_id)

    # GET /v1/billing/{id}/export
    if resource == "billing" and len(parts) == 4 and parts[3] == "export" and method == "GET":
        ctx.assert_role(*_BILLING_EXPORT_ROLES)
        result = service.export_billing(tenant_id, parts[2], fmt=fmt)
        return success(result, request_id=request_id)

    # GET /v1/containers/{id}/billing/export
    if (
        resource == "containers"
        and len(parts) == 5
        and parts[3] == "billing"
        and parts[4] == "export"
        and method == "GET"
    ):
        ctx.assert_role(*_BILLING_EXPORT_ROLES)
        result = service.export_container_billing(tenant_id, parts[2], fmt=fmt)
        return success(result, request_id=request_id)

    raise ResourceNotFoundError("route", path)


def _resolve_format(event: dict) -> str:
    """Return validated export format from ?format= query param (default: xlsx)."""
    raw = (event.get("queryStringParameters") or {}).get("format", "xlsx").lower()
    if raw not in {"xlsx", "csv", "pdf"}:
        from shared.exceptions import ValidationError
        raise ValidationError(
            "Invalid export format",
            field_errors={"format": f"Must be one of: xlsx, csv, pdf. Got: '{raw}'"},
        )
    return raw
