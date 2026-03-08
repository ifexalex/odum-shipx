"""Metering Lambda handler.

Supports two trigger modes detected at runtime:

1. **SQS consumer** — triggered by the logistics-metering SQS queue.
   Processes batches of up to 10 UsageRecorded messages.
   Returns partial-batch-failure response so successfully processed messages
   are acknowledged while failed ones are retried.

2. **API handler** — triggered by API Gateway for Platform Admin usage endpoints:
     GET /v1/platform/tenants/{id}/usage    — per-tenant usage breakdown
     GET /v1/platform/dashboard             — aggregated platform metrics
"""
import logging
import time
import uuid

from aws_xray_sdk.core import patch_all

from shared.auth import get_tenant_context
from shared.exceptions import LogisticsBaseError, ResourceNotFoundError
from shared.logging_config import setup_logging
from shared.responses import error_response, success
from shared.tenant_context import UserRole

from . import service

setup_logging()
patch_all()

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Lambda entry point
# ---------------------------------------------------------------------------


def lambda_handler(event: dict, context) -> dict:
    # Detect SQS batch trigger
    if "Records" in event and event["Records"] and event["Records"][0].get("eventSource") == "aws:sqs":
        return _handle_sqs_batch(event)

    # Otherwise treat as API Gateway event
    return _handle_api(event, context)


# ---------------------------------------------------------------------------
# SQS consumer
# ---------------------------------------------------------------------------


def _handle_sqs_batch(event: dict) -> dict:
    """Process SQS batch; return itemIdentifier list for partial-batch failure."""
    batch_item_failures = []

    for record in event.get("Records", []):
        message_id = record.get("messageId", "unknown")
        try:
            service.process_usage_event(record["body"])
            logger.info("Processed SQS message %s", message_id)
        except Exception as exc:
            logger.error("Failed to process message %s: %s", message_id, exc)
            batch_item_failures.append({"itemIdentifier": message_id})

    return {"batchItemFailures": batch_item_failures}


# ---------------------------------------------------------------------------
# API handler
# ---------------------------------------------------------------------------


def _handle_api(event: dict, context) -> dict:
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
        response = _dispatch_api(event, method, path, tenant_ctx, request_id)
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
            method, path, duration_ms,
            extra={"request_id": request_id, "duration_ms": duration_ms},
        )


def _qp(event: dict, key: str, default=None):
    return (event.get("queryStringParameters") or {}).get(key, default)


def _dispatch_api(event, method, path, ctx, request_id):
    parts = path.strip("/").split("/")

    # /v1/platform/tenants/{id}/usage
    if (
        len(parts) == 5
        and parts[:2] == ["v1", "platform"]
        and parts[2] == "tenants"
        and parts[4] == "usage"
        and method == "GET"
    ):
        ctx.assert_role(UserRole.PLATFORM_ADMIN)
        target_tenant_id = parts[3]
        period = _qp(event, "period")
        result = service.get_tenant_usage(target_tenant_id, period)
        return success(result, request_id=request_id)

    # /v1/platform/dashboard
    if (
        len(parts) == 3
        and parts[:3] == ["v1", "platform", "dashboard"]
        and method == "GET"
    ):
        ctx.assert_role(UserRole.PLATFORM_ADMIN)
        result = _build_dashboard()
        return success(result, request_id=request_id)

    raise ResourceNotFoundError("route", path)


def _build_dashboard() -> dict:
    """Return platform-wide aggregated metrics (minimal — expandable)."""
    # A lightweight summary; full aggregation would query all tenants in production.
    return {
        "message": "Platform dashboard — aggregate metrics available per-tenant via /v1/platform/tenants/{id}/usage"
    }
