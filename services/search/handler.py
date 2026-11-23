"""Search Lambda handler.

Routes:
  GET /v1/search?q=<text> — every authenticated role except platform_admin. What a caller may find depends on
                            their role; a customer only ever finds their own records (see service.py).
"""

import logging
import time
import uuid
from typing import Any

from shared.auth import get_tenant_context
from shared.exceptions import LogisticsBaseError, ResourceNotFoundError
from shared.logging_config import bind_log_context, clear_log_context, setup_logging
from shared.observability import init_tracing
from shared.responses import error_response, success

from . import service

setup_logging()
init_tracing()

logger = logging.getLogger(__name__)


def _qp(event: dict[str, Any], name: str, default: str = "") -> str:
    return str((event.get("queryStringParameters") or {}).get(name) or default)


def lambda_handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
    start_time = time.time()
    request_id = event.get("requestContext", {}).get("requestId") or str(uuid.uuid4())
    clear_log_context()
    bind_log_context(request_id=request_id)
    http = event.get("requestContext", {}).get("http", {})
    method = http.get("method", "")
    path = http.get("path", "")

    try:
        if method == "GET" and path.rstrip("/") == "/v1/search":
            ctx = get_tenant_context(event)
            # The text searched for is never logged: it can be a customer's name or phone number.
            return success(service.search(ctx.tenant_id, _qp(event, "q"), ctx), request_id=request_id)
        raise ResourceNotFoundError("route", path)
    except LogisticsBaseError as exc:
        logger.warning("Business error: %s - %s", exc.error_code, exc.message)
        return error_response(exc, instance=path, request_id=request_id)
    except Exception:
        logger.exception("Unhandled error")
        return error_response(
            LogisticsBaseError("Internal server error", "INTERNAL_ERROR", 500), instance=path, request_id=request_id
        )
    finally:
        duration_ms = (time.time() - start_time) * 1000
        logger.info("← %s %s %.0fms", method, path, duration_ms, extra={"request_id": request_id, "duration_ms": duration_ms})
