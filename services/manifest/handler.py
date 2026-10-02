"""Manifest Lambda handler.

Routes:
  GET   /v1/manifests                        — china_office_staff, nigeria_office_staff, tenant_admin
  GET   /v1/manifests/{id}                   — same
  PATCH /v1/manifests/{id}/verify            — china_office_staff, nigeria_office_staff
  PATCH /v1/manifests/{id}/revoke-verification — china_office_staff, nigeria_office_staff, tenant_admin
  POST  /v1/manifests/{id}/evidence          — china_office_staff, nigeria_office_staff (presigned upload)

Manifests are auto-created when packing lists are approved (Task 08); the only
POST is the verification-evidence presigned-upload contract.
"""

import json
import logging
import time
import uuid
from typing import Any

from aws_xray_sdk.core import patch_all

from shared.auth import get_tenant_context
from shared.exceptions import LogisticsBaseError, ResourceNotFoundError
from shared.logging_config import bind_log_context, clear_log_context, setup_logging
from shared.metering import record_usage
from shared.pagination import decode_cursor
from shared.responses import error_response, paginated, success
from shared.tenant_context import UserRole
from shared.validation import parse_validated

from . import service
from .models import EvidenceUploadRequest, ResolveDiscrepancyRequest, VerifyManifestRequest

# Module-level init (runs once on cold start)
setup_logging()
patch_all()

logger = logging.getLogger(__name__)

_READ_ROLES = (
    UserRole.CHINA_OFFICE_STAFF,
    UserRole.NIGERIA_OFFICE_STAFF,
    UserRole.TENANT_ADMIN,
)
_VERIFY_ROLES = (
    UserRole.CHINA_OFFICE_STAFF,
    UserRole.NIGERIA_OFFICE_STAFF,
)
_RESOLVE_ROLES = (
    UserRole.NIGERIA_OFFICE_STAFF,
    UserRole.TENANT_ADMIN,
)
_REVOKE_ROLES = (
    UserRole.CHINA_OFFICE_STAFF,
    UserRole.NIGERIA_OFFICE_STAFF,
    UserRole.TENANT_ADMIN,
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


def _dispatch(event: dict[str, Any], method: str, path: str, ctx: Any, request_id: str, ip_address: str | None) -> dict[str, Any]:
    parts = path.strip("/").split("/")

    if len(parts) >= 2 and parts[0] == "v1" and parts[1] == "manifests":
        manifest_id = parts[2] if len(parts) > 2 else None
        action = parts[3] if len(parts) > 3 else None
        return _manifest_routes(event, parts, method, ctx, request_id, ip_address, manifest_id, action)

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
# Route handler
# ---------------------------------------------------------------------------


def _manifest_routes(
    event: dict[str, Any],
    parts: list[str],
    method: str,
    ctx: Any,
    request_id: str,
    ip_address: str | None,
    manifest_id: str | None,
    action: str | None,
) -> dict[str, Any]:
    tenant_id = ctx.tenant_id

    if manifest_id is None:
        # GET /v1/manifests
        if method == "GET":
            ctx.assert_role(*_READ_ROLES)
            filters = {}
            if _qp(event, "verification_status"):
                filters["verification_status"] = _qp(event, "verification_status")
            if _qp(event, "container_id"):
                filters["container_id"] = _qp(event, "container_id")
            limit = int(_qp(event, "limit", 50))
            cursor = decode_cursor(_qp(event, "cursor"))
            page, next_cursor, has_more = service.list_manifests(tenant_id, filters, limit, cursor)
            return paginated(page, next_cursor, has_more, request_id=request_id)

    elif manifest_id == "stats":
        # GET /v1/manifests/stats — per-status counts + overdue for the list
        # stats row (§6.2, P2-4).
        if method == "GET":
            ctx.assert_role(*_READ_ROLES)
            return success(service.get_manifest_stats(tenant_id), request_id=request_id)

    else:
        if action is None:
            # GET /v1/manifests/{id}
            if method == "GET":
                ctx.assert_role(*_READ_ROLES)
                result = service.get_manifest(tenant_id, manifest_id)
                return success(result, request_id=request_id)

        else:
            # PATCH /v1/manifests/{id}/verify
            if action == "verify" and method == "PATCH":
                ctx.assert_role(*_VERIFY_ROLES)
                body = _parse_body(event)
                req = parse_validated(VerifyManifestRequest, body)
                result = service.verify_manifest(
                    tenant_id,
                    manifest_id,
                    req,
                    actor_id=ctx.user_id,
                    ctx=ctx,
                    ip_address=ip_address,
                )
                return success(result, request_id=request_id)

            # PATCH /v1/manifests/{id}/revoke-verification
            if action == "revoke-verification" and method == "PATCH":
                ctx.assert_role(*_REVOKE_ROLES)
                result = service.revoke_verification(
                    tenant_id,
                    manifest_id,
                    actor_id=ctx.user_id,
                    ctx=ctx,
                    ip_address=ip_address,
                )
                return success(result, request_id=request_id)

            # POST /v1/manifests/{id}/evidence — presigned upload for a verify photo/doc
            if action == "evidence" and method == "POST":
                ctx.assert_role(*_VERIFY_ROLES)
                body = _parse_body(event)
                req = parse_validated(EvidenceUploadRequest, body)
                result = service.generate_evidence_upload(
                    tenant_id,
                    manifest_id,
                    filename=req.filename,
                    content_type=req.content_type,
                    actor_id=ctx.user_id,
                    label=req.label,
                )
                return success(result, request_id=request_id, status_code=201)

            # PATCH /v1/manifests/{id}/resolve-discrepancy
            if action == "resolve-discrepancy" and method == "PATCH":
                ctx.assert_role(*_RESOLVE_ROLES)
                body = _parse_body(event)
                req = parse_validated(ResolveDiscrepancyRequest, body)
                result = service.resolve_discrepancy(
                    tenant_id,
                    manifest_id,
                    req,
                    actor_id=ctx.user_id,
                    ctx=ctx,
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
