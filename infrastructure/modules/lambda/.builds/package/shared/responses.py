"""Standardized API response formatting for Lambda proxy integration.

All responses include the security headers mandated by §1.4 of
00_CROSS_CUTTING_STANDARDS.md. Errors follow RFC 7807 Problem Details format.
"""

import json
import os
from typing import Any

from shared.exceptions import LogisticsBaseError


def _standard_headers(request_id: str = "") -> dict[str, str]:
    """Return the mandatory response headers (§1.4)."""
    return {
        "Content-Type": "application/json",
        "X-Request-Id": request_id,
        "X-Content-Type-Options": "nosniff",
        "Strict-Transport-Security": "max-age=31536000; includeSubDomains",
        "Cache-Control": "no-store",
    }


def success(
    data: dict | list,
    status_code: int = 200,
    meta: dict | None = None,
    request_id: str = "",
) -> dict:
    """Format a successful response.

    Returns:
        Lambda proxy integration dict with statusCode, headers, and body.
        Body: {"data": ..., "meta": {...}}
    """
    body: dict[str, Any] = {"data": data}
    if meta:
        body["meta"] = meta
    return {
        "statusCode": status_code,
        "headers": _standard_headers(request_id),
        "body": json.dumps(body, default=str),
    }


def created(
    data: dict,
    location: str,
    request_id: str = "",
) -> dict:
    """Format a 201 Created response with a Location header (§1.3)."""
    headers = _standard_headers(request_id)
    headers["Location"] = location
    return {
        "statusCode": 201,
        "headers": headers,
        "body": json.dumps({"data": data}, default=str),
    }


def no_content(request_id: str = "") -> dict:
    """Format a 204 No Content response (used for DELETE)."""
    return {
        "statusCode": 204,
        "headers": _standard_headers(request_id),
        "body": "",
    }


def paginated(
    data: list,
    cursor: str | None,
    has_more: bool,
    total_count: int | None = None,
    request_id: str = "",
) -> dict:
    """Format a paginated list response.

    Pagination meta is nested under body["meta"]["pagination"].
    """
    pagination: dict[str, Any] = {
        "has_more": has_more,
        "next_cursor": cursor,
    }
    if total_count is not None:
        pagination["total_count"] = total_count

    body: dict[str, Any] = {
        "data": data,
        "meta": {"pagination": pagination},
    }
    return {
        "statusCode": 200,
        "headers": _standard_headers(request_id),
        "body": json.dumps(body, default=str),
    }


def error_response(
    error: LogisticsBaseError,
    instance: str = "",
    request_id: str = "",
) -> dict:
    """Format an RFC 7807 Problem Details error response from a LogisticsBaseError.

    RFC 7807 fields:
        type    — URI reference identifying the problem type
        title   — human-readable summary
        status  — HTTP status code
        detail  — human-readable explanation
        instance — URI reference of the specific occurrence (optional)
    """
    env = os.environ.get("ENVIRONMENT", "unknown")
    problem: dict[str, Any] = {
        "type": f"https://errors.logistics-api.com/{error.error_code.lower().replace('_', '-')}",
        "title": _title_from_code(error.error_code),
        "status": error.status_code,
        "detail": error.message,
        "error_code": error.error_code,
    }
    if instance:
        problem["instance"] = instance

    return {
        "statusCode": error.status_code,
        "headers": _standard_headers(request_id),
        "body": json.dumps(problem, default=str),
    }


def validation_error(
    errors: list[dict],
    instance: str = "",
    request_id: str = "",
) -> dict:
    """Format a 422 Validation Error response with field-level details (RFC 7807)."""
    problem: dict[str, Any] = {
        "type": "https://errors.logistics-api.com/validation-error",
        "title": "Validation Error",
        "status": 422,
        "detail": "One or more fields failed validation.",
        "error_code": "VALIDATION_ERROR",
        "errors": errors,
    }
    if instance:
        problem["instance"] = instance

    return {
        "statusCode": 422,
        "headers": _standard_headers(request_id),
        "body": json.dumps(problem, default=str),
    }


def _title_from_code(error_code: str) -> str:
    """Convert an error code like RESOURCE_NOT_FOUND to a human-readable title."""
    return error_code.replace("_", " ").title()
