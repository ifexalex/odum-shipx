"""Excel Lambda handler — export and import routes.

Routes:
  GET  /v1/packing-lists/{id}/export          — china_office_staff, nigeria_office_staff, tenant_admin
  GET  /v1/packing-lists/{id}/pdf             — china_office_staff, nigeria_office_staff, tenant_admin, customer (own only)
  GET  /v1/billing/{id}/pdf                   — the invoice: nigeria_office_staff, tenant_admin, customer (own only)
  GET  /v1/manifests/{id}/pdf                 — platform_admin, tenant_admin, china/nigeria office staff
  GET  /v1/release-notes/{id}/pdf             — nigeria_office_staff, tenant_admin, warehouse_attendant, customer (own only)
  GET  /v1/payments/{id}/receipt/pdf          — nigeria_office_staff, tenant_admin, customer (own only)
  GET  /v1/manifests/{id}/export              — china_office_staff, nigeria_office_staff, tenant_admin
  GET  /v1/billing/{id}/export                — nigeria_office_staff, tenant_admin, customer (own only)
  GET  /v1/containers/{id}/events/export      — tenant_admin, nigeria/china office staff, warehouse_attendant
                                                 (the tracking tab's event log; xlsx or csv)
  GET  /v1/containers/{id}/billing/export     — nigeria_office_staff, tenant_admin (all customers on the
                                                 container — never customer-facing)
  GET  /v1/billing/export                     — tenant_admin only (the invoice list's
                                                 filters and sort; xlsx or csv)
  GET  /v1/billing/report/export              — tenant_admin only (the reports page's billing by
                                                 container for its period; xlsx or csv)
  GET  /v1/containers/export                  — china_office_staff, nigeria_office_staff, tenant_admin
                                                 (the container list's filters and sort; xlsx or csv)
  POST /v1/packing-lists/import               — china_office_staff
  POST /v1/packing-lists/import/presigned-url — china_office_staff
  POST /v1/manifests/import                   — china_office_staff (flexible, auto-creating —
                                                 see 19_excel_import_export.md §"Manifest Import";
                                                 reuses the packing-lists presigned-url flow above)
"""

import json
import logging
import time
import uuid
from typing import Any, cast

from shared.auth import get_tenant_context
from shared.exceptions import LogisticsBaseError, ResourceNotFoundError
from shared.idempotency import check_idempotency, get_idempotency_key, store_idempotency
from shared.logging_config import bind_log_context, clear_log_context, setup_logging
from shared.metering import record_usage
from shared.observability import init_tracing
from shared.responses import created, error_response, success
from shared.tenant_context import UserRole
from shared.validation import parse_validated

from . import service
from .models import (
    ContainerListExportQuery,
    ImportPresignedUrlRequest,
    ImportRequest,
    ListExportQuery,
    ManifestImportRequest,
    ReportExportQuery,
    ShareWhatsAppRequest,
)

setup_logging()
init_tracing()

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
# Single-billing-record export doubles as the customer's downloadable
# invoice (own record only, enforced in export_billing()) — the
# container-level export above stays staff-only, it would otherwise leak
# every other customer's billing sharing that container.
_BILLING_SINGLE_EXPORT_ROLES = (*_BILLING_EXPORT_ROLES, UserRole.CUSTOMER)
# The whole invoice list, every customer's invoices in one file, is the tenant admin's to export (owner decision,
# 2026-11-17). Nigeria staff export one invoice or one container's billing.
_BILLING_LIST_EXPORT_ROLES = (UserRole.TENANT_ADMIN,)
_IMPORT_ROLES = (UserRole.CHINA_OFFICE_STAFF,)
# Everyone who can read a container's events (GET /v1/containers/{id}/events) can export them.
_EVENT_EXPORT_ROLES = (
    UserRole.TENANT_ADMIN,
    UserRole.NIGERIA_OFFICE_STAFF,
    UserRole.CHINA_OFFICE_STAFF,
    UserRole.WAREHOUSE_ATTENDANT,
)
_PL_PDF_ROLES = (
    UserRole.CHINA_OFFICE_STAFF,
    UserRole.NIGERIA_OFFICE_STAFF,
    UserRole.TENANT_ADMIN,
    UserRole.CUSTOMER,
)
_RELEASE_NOTE_PDF_ROLES = (
    UserRole.NIGERIA_OFFICE_STAFF,
    UserRole.TENANT_ADMIN,
    UserRole.WAREHOUSE_ATTENDANT,
    UserRole.CUSTOMER,
)
# Cash receipt PDF — the paying customer may re-download their own receipt;
# staff who can record a payment can also reprint it.
_RECEIPT_PDF_ROLES = (
    UserRole.NIGERIA_OFFICE_STAFF,
    UserRole.TENANT_ADMIN,
    UserRole.CUSTOMER,
)


def lambda_handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
    start_time = time.time()
    request_id = event.get("requestContext", {}).get("requestId") or str(uuid.uuid4())
    clear_log_context()
    bind_log_context(request_id=request_id)
    http = event.get("requestContext", {}).get("http", {})
    method = http.get("method", "")
    path = http.get("path", "")

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

        response: dict[str, Any] = _dispatch(event, method, path, tenant_ctx, request_id)

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


def _health_response(request_id: str) -> dict[str, Any]:
    import datetime

    return {
        "statusCode": 200,
        "headers": {"Content-Type": "application/json", "X-Request-Id": request_id},
        "body": json.dumps(
            {
                "status": "healthy",
                "timestamp": datetime.datetime.now(datetime.UTC).isoformat(),
            }
        ),
    }


def _parse_body(event: dict[str, Any]) -> dict[str, Any]:
    raw = event.get("body") or "{}"
    try:
        return json.loads(raw)  # type: ignore[no-any-return]
    except json.JSONDecodeError:
        return {}


def _customer_user_id(ctx: Any, *allowed_roles: UserRole) -> str | None:
    staff_roles = tuple(r for r in allowed_roles if r != UserRole.CUSTOMER)
    must_scope = getattr(ctx, "must_scope_to_customer", None)
    if callable(must_scope):
        return str(ctx.user_id) if must_scope(*staff_roles) else None
    is_customer_only = bool(getattr(ctx, "is_customer_only", ctx.role == UserRole.CUSTOMER))
    return str(ctx.user_id) if is_customer_only else None


def _dispatch(
    event: dict[str, Any],
    method: str,
    path: str,
    ctx: Any,
    request_id: str,
) -> dict[str, Any]:
    parts = path.strip("/").split("/")
    tenant_id = ctx.tenant_id

    if len(parts) < 2 or parts[0] != "v1":
        raise ResourceNotFoundError("route", path)

    resource = parts[1]

    # POST /v1/packing-lists/import/presigned-url
    if (
        resource == "packing-lists"
        and len(parts) == 4
        and parts[2] == "import"
        and parts[3] == "presigned-url"
        and method == "POST"
    ):
        ctx.assert_role(*_IMPORT_ROLES)
        body = _parse_body(event)
        req = parse_validated(ImportPresignedUrlRequest, body)
        result = service.generate_import_presigned_url(tenant_id, content_type=req.content_type, size_bytes=req.size_bytes)
        return success(result, request_id=request_id)

    # POST /v1/packing-lists/import
    if resource == "packing-lists" and len(parts) == 3 and parts[2] == "import" and method == "POST":
        ctx.assert_role(*_IMPORT_ROLES)
        body = _parse_body(event)
        req = parse_validated(ImportRequest, body)
        result = service.import_packing_list(
            tenant_id,
            container_id=req.container_id,
            file_key=req.file_key,
            actor_id=ctx.user_id,
            ctx=ctx,
        )
        return created(result, location="/v1/packing-lists", request_id=request_id)

    # POST /v1/manifests/import — flexible, auto-creating (see 19_excel_import_export.md)
    if resource == "manifests" and len(parts) == 3 and parts[2] == "import" and method == "POST":
        ctx.assert_role(*_IMPORT_ROLES)
        body = _parse_body(event)
        req = parse_validated(ManifestImportRequest, body)
        result = service.process_manifest_import(
            tenant_id,
            file_key=req.file_key,
            actor_id=ctx.user_id,
            ctx=ctx,
        )
        return created(result, location="/v1/packing-lists", request_id=request_id)

    # GET /v1/packing-lists/{id}/documents?lang_lr=zh&lang_pl=en (ENG-5)
    if resource == "packing-lists" and len(parts) == 4 and parts[3] == "documents" and method == "GET":
        ctx.assert_role(*_PL_PDF_ROLES)
        qs = event.get("queryStringParameters") or {}
        customer_user_id = _customer_user_id(ctx, *_PL_PDF_ROLES)
        result = service.get_packing_list_documents(
            tenant_id,
            parts[2],
            customer_user_id=customer_user_id,
            lang_lr=qs.get("lang_lr") or "zh",
            lang_pl=qs.get("lang_pl") or "en",
        )
        return success(result, request_id=request_id)

    # POST /v1/packing-lists/{id}/share-whatsapp (ENG-5)
    if resource == "packing-lists" and len(parts) == 4 and parts[3] == "share-whatsapp" and method == "POST":
        ctx.assert_role(*_EXPORT_ROLES)
        body = _parse_body(event)
        req = parse_validated(ShareWhatsAppRequest, body)
        result = service.share_packing_list_document_whatsapp(
            tenant_id,
            parts[2],
            req.document_type,
            lang=req.lang,
            actor_id=ctx.user_id,
            actor_role=str(ctx.role),
        )
        return success(result, request_id=request_id)

    # GET /v1/packing-lists/{id}/loading-receipt/pdf?lang=zh|en (ENG-4)
    if (
        resource == "packing-lists"
        and len(parts) == 5
        and parts[3] == "loading-receipt"
        and parts[4] == "pdf"
        and method == "GET"
    ):
        ctx.assert_role(*_PL_PDF_ROLES)
        qs = event.get("queryStringParameters") or {}
        customer_user_id = _customer_user_id(ctx, *_PL_PDF_ROLES)
        result = service.export_loading_receipt_pdf(
            tenant_id,
            parts[2],
            actor_id=ctx.user_id,
            actor_role=str(ctx.role),
            customer_user_id=customer_user_id,
            lang=qs.get("lang") or "zh",
        )
        return success(result, request_id=request_id)

    # GET /v1/packing-lists/{id}/loading-receipt/image?lang=zh|en (ENG-5)
    if (
        resource == "packing-lists"
        and len(parts) == 5
        and parts[3] == "loading-receipt"
        and parts[4] == "image"
        and method == "GET"
    ):
        ctx.assert_role(*_PL_PDF_ROLES)
        qs = event.get("queryStringParameters") or {}
        customer_user_id = _customer_user_id(ctx, *_PL_PDF_ROLES)
        result = service.export_loading_receipt_image(
            tenant_id,
            parts[2],
            actor_id=ctx.user_id,
            actor_role=str(ctx.role),
            customer_user_id=customer_user_id,
            lang=qs.get("lang") or "zh",
        )
        return success(result, request_id=request_id)

    # GET /v1/packing-lists/{id}/image?lang=en|zh (ENG-5)
    if resource == "packing-lists" and len(parts) == 4 and parts[3] == "image" and method == "GET":
        ctx.assert_role(*_PL_PDF_ROLES)
        qs = event.get("queryStringParameters") or {}
        customer_user_id = _customer_user_id(ctx, *_PL_PDF_ROLES)
        result = service.export_packing_list_image(
            tenant_id,
            parts[2],
            actor_id=ctx.user_id,
            actor_role=str(ctx.role),
            customer_user_id=customer_user_id,
            lang=qs.get("lang") or "en",
        )
        return success(result, request_id=request_id)

    # GET /v1/packing-lists/{id}/pdf?lang=en|zh
    if resource == "packing-lists" and len(parts) == 4 and parts[3] == "pdf" and method == "GET":
        ctx.assert_role(*_PL_PDF_ROLES)
        qs = event.get("queryStringParameters") or {}
        customer_user_id = _customer_user_id(ctx, *_PL_PDF_ROLES)
        result = service.export_packing_list_pdf(
            tenant_id,
            parts[2],
            actor_id=ctx.user_id,
            actor_role=str(ctx.role),
            customer_user_id=customer_user_id,
            lang=qs.get("lang") or "en",
        )
        return success(result, request_id=request_id)

    # GET /v1/billing/{id}/pdf — the invoice (FD-39); a customer gets their own only
    if resource == "billing" and len(parts) == 4 and parts[3] == "pdf" and method == "GET":
        ctx.assert_role(*_BILLING_SINGLE_EXPORT_ROLES)
        customer_user_id = _customer_user_id(ctx, *_BILLING_SINGLE_EXPORT_ROLES)
        result = service.export_invoice_pdf(
            tenant_id, parts[2], actor_id=ctx.user_id, actor_role=str(ctx.role), customer_user_id=customer_user_id
        )
        return success(result, request_id=request_id)

    # GET /v1/manifests/{id}/pdf — the manifest (FD-39), staff who can export it
    if resource == "manifests" and len(parts) == 4 and parts[3] == "pdf" and method == "GET":
        ctx.assert_role(*_EXPORT_ROLES)
        result = service.export_manifest_pdf(tenant_id, parts[2], actor_id=ctx.user_id, actor_role=str(ctx.role))
        return success(result, request_id=request_id)

    # GET /v1/release-notes/{id}/pdf
    if resource == "release-notes" and len(parts) == 4 and parts[3] == "pdf" and method == "GET":
        ctx.assert_role(*_RELEASE_NOTE_PDF_ROLES)
        customer_user_id = _customer_user_id(ctx, *_RELEASE_NOTE_PDF_ROLES)
        result = service.export_release_note_pdf(
            tenant_id,
            parts[2],
            actor_id=ctx.user_id,
            actor_role=str(ctx.role),
            customer_user_id=customer_user_id,
        )
        return success(result, request_id=request_id)

    # GET /v1/payments/{id}/receipt/pdf
    if resource == "payments" and len(parts) == 5 and parts[3] == "receipt" and parts[4] == "pdf" and method == "GET":
        ctx.assert_role(*_RECEIPT_PDF_ROLES)
        customer_user_id = _customer_user_id(ctx, *_RECEIPT_PDF_ROLES)
        result = service.export_receipt_pdf(
            tenant_id,
            parts[2],
            actor_id=ctx.user_id,
            actor_role=str(ctx.role),
            customer_user_id=customer_user_id,
        )
        return success(result, request_id=request_id)

    # GET /v1/billing/export — the invoice list, filtered and sorted as on screen
    if resource == "billing" and len(parts) == 3 and parts[2] == "export" and method == "GET":
        ctx.assert_role(*_BILLING_LIST_EXPORT_ROLES)
        query = parse_validated(ListExportQuery, _query_params(event))
        result = service.export_billing_list(
            tenant_id,
            query.filters(),
            fmt=query.format,
            sort_field=query.sort,
            sort_direction=query.direction,
            actor_id=ctx.user_id,
            actor_role=str(ctx.role),
        )
        return success(result, request_id=request_id)

    # GET /v1/billing/report/export — the reports page's billing by container, every container in its period
    if resource == "billing" and len(parts) == 4 and parts[2] == "report" and parts[3] == "export" and method == "GET":
        ctx.assert_role(*_BILLING_LIST_EXPORT_ROLES)
        report_query = parse_validated(ReportExportQuery, _query_params(event))
        result = service.export_report_container_billing(
            tenant_id,
            report_query.filters(),
            fmt=report_query.format,
            actor_id=ctx.user_id,
            actor_role=str(ctx.role),
        )
        return success(result, request_id=request_id)

    # GET /v1/containers/export — the container list, filtered and sorted as on screen
    if resource == "containers" and len(parts) == 3 and parts[2] == "export" and method == "GET":
        ctx.assert_role(*_EXPORT_ROLES)
        container_query = parse_validated(ContainerListExportQuery, _query_params(event))
        result = service.export_container_list(
            tenant_id,
            container_query.filters(),
            fmt=container_query.format,
            sort_field=container_query.sort,
            sort_direction=container_query.direction,
            actor_id=ctx.user_id,
            actor_role=str(ctx.role),
        )
        return success(result, request_id=request_id)

    fmt = _resolve_format(event)

    # GET /v1/packing-lists/{id}/export
    if resource == "packing-lists" and len(parts) == 4 and parts[3] == "export" and method == "GET":
        ctx.assert_role(*_EXPORT_ROLES)
        result = service.export_packing_list(tenant_id, parts[2], fmt=fmt, actor_id=ctx.user_id, actor_role=str(ctx.role))
        return success(result, request_id=request_id)

    # GET /v1/manifests/{id}/export
    if resource == "manifests" and len(parts) == 4 and parts[3] == "export" and method == "GET":
        ctx.assert_role(*_EXPORT_ROLES)
        result = service.export_manifest(tenant_id, parts[2], fmt=fmt, actor_id=ctx.user_id, actor_role=str(ctx.role))
        return success(result, request_id=request_id)

    # GET /v1/billing/{id}/export — the customer's downloadable invoice
    if resource == "billing" and len(parts) == 4 and parts[3] == "export" and method == "GET":
        ctx.assert_role(*_BILLING_SINGLE_EXPORT_ROLES)
        customer_user_id = _customer_user_id(ctx, *_BILLING_SINGLE_EXPORT_ROLES)
        result = service.export_billing(
            tenant_id,
            parts[2],
            fmt=fmt,
            customer_user_id=customer_user_id,
            actor_id=ctx.user_id,
            actor_role=str(ctx.role),
        )
        return success(result, request_id=request_id)

    # GET /v1/containers/{id}/events/export — the tracking tab's event log, xlsx or csv
    if resource == "containers" and len(parts) == 5 and parts[3] == "events" and parts[4] == "export" and method == "GET":
        ctx.assert_role(*_EVENT_EXPORT_ROLES)
        result = service.export_container_events(tenant_id, parts[2], fmt=fmt, actor_id=ctx.user_id, actor_role=str(ctx.role))
        return success(result, request_id=request_id)

    # GET /v1/containers/{id}/billing/export
    if resource == "containers" and len(parts) == 5 and parts[3] == "billing" and parts[4] == "export" and method == "GET":
        ctx.assert_role(*_BILLING_EXPORT_ROLES)
        result = service.export_container_billing(tenant_id, parts[2], fmt=fmt, actor_id=ctx.user_id, actor_role=str(ctx.role))
        return success(result, request_id=request_id)

    raise ResourceNotFoundError("route", path)


def _query_params(event: dict[str, Any]) -> dict[str, Any]:
    return dict(event.get("queryStringParameters") or {})


def _resolve_format(event: dict[str, Any]) -> str:
    """Return validated export format from ?format= query param (default: xlsx).

    The data exports are spreadsheets only (FD-39): a PDF is a document with its own layout, served from the record's
    ``/pdf`` route, never a table of column names.
    """
    raw = cast(str, (event.get("queryStringParameters") or {}).get("format", "xlsx")).lower()
    if raw not in {"xlsx", "csv"}:
        from shared.exceptions import ValidationError

        raise ValidationError(
            "Invalid export format: use xlsx or csv. A record's PDF has its own /pdf link.",
            field_errors={"format": f"Must be one of: xlsx, csv. Got: '{raw}'."},
        )
    return raw
