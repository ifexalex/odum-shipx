# Task 06 — Shared Layer Full Implementation

> **Prerequisite:** Read `00_CROSS_CUTTING_STANDARDS.md` in its entirety. This task implements the standards.

## Objective

Fully implement all shared utility modules: db.py, auth.py, responses.py, events.py, pagination.py, audit.py, **plus** the new modules: idempotency.py, cache.py, circuit_breaker.py, metering.py, notifications.py, logging_config.py. This is the production-ready implementation of every cross-cutting concern.

## Depends On

- Task 02 (interfaces defined), Task 03 (models), Task 04a (Aurora/RDS Proxy), Task 05c (RLS policies)

## Key Implementation Details

### `shared/db.py` — Full Implementation

```python
"""Database connection management with tenant-scoped RLS."""
import os
import json
import logging
import psycopg2
import psycopg2.extras
import boto3

logger = logging.getLogger(__name__)
_connection = None  # Module-level connection reuse

def _get_db_password() -> str:
    """Fetch DB password from Secrets Manager."""
    client = boto3.client("secretsmanager", region_name=os.environ["AWS_REGION"])
    secret = client.get_secret_value(SecretId=os.environ["DB_SECRET_ARN"])
    return json.loads(secret["SecretString"])["password"]

def get_connection():
    """Get or create a reusable database connection."""
    global _connection
    if _connection is None or _connection.closed:
        _connection = psycopg2.connect(
            host=os.environ["DATABASE_HOST"],
            port=int(os.environ.get("DATABASE_PORT", "5432")),
            dbname=os.environ["DATABASE_NAME"],
            user=os.environ["DATABASE_USER"],
            password=_get_db_password(),
            connect_timeout=5,
        )
        _connection.autocommit = False
    return _connection

def execute_with_tenant(tenant_id: str, query: str, params: dict | None = None) -> list[dict]:
    """Execute SELECT within tenant scope. Sets RLS session variable."""
    conn = get_connection()
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute("SET LOCAL app.current_tenant_id = %s", (tenant_id,))
            cur.execute(query, params or {})
            results = cur.fetchall()
        conn.commit()
        return [dict(row) for row in results]
    except Exception:
        conn.rollback()
        raise

def execute_write_with_tenant(tenant_id: str, query: str, params: dict | None = None) -> dict | None:
    """Execute INSERT/UPDATE/DELETE within tenant scope. Returns affected row."""
    conn = get_connection()
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute("SET LOCAL app.current_tenant_id = %s", (tenant_id,))
            cur.execute(query, params or {})
            result = cur.fetchone() if cur.description else None
        conn.commit()
        return dict(result) if result else None
    except Exception:
        conn.rollback()
        raise

def execute_transaction(tenant_id: str, operations: list[tuple[str, dict]]) -> list:
    """Execute multiple queries in a single transaction."""
    conn = get_connection()
    results = []
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute("SET LOCAL app.current_tenant_id = %s", (tenant_id,))
            for query, params in operations:
                cur.execute(query, params)
                if cur.description:
                    results.append(dict(cur.fetchone()))
                else:
                    results.append(None)
        conn.commit()
        return results
    except Exception:
        conn.rollback()
        raise
```

### `shared/auth.py` — Full Implementation

Must implement:
1. JWT claim extraction from API Gateway event
2. Role parsing from `cognito:groups` format `{tenant_id}:{role}`
3. Tenant suspension check with simple cache (dict + timestamp, 60s TTL)
4. Decorator `@require_roles(*roles)` for handler-level auth

**Tenant suspension check:** Query `SELECT status FROM tenant WHERE id = :tenant_id` with 60-second in-memory cache.

### `shared/responses.py` — Full Implementation

- Standard headers on EVERY response (see Standards §1.4):
  ```python
  STANDARD_HEADERS = {
      "Content-Type": "application/json",
      "X-Content-Type-Options": "nosniff",
      "Strict-Transport-Security": "max-age=31536000; includeSubDomains",
      "Cache-Control": "no-store",
  }
  ```
- `success(data, request_id)` → `{"statusCode": 200, "headers": {**STANDARD_HEADERS, "X-Request-Id": request_id}, "body": json.dumps({"data": ..., "meta": {...}})}`
- `created(data, resource_uri, request_id)` → same with statusCode 201 and `Location` header
- `no_content(request_id)` → `{"statusCode": 204, "headers": {**STANDARD_HEADERS, "X-Request-Id": request_id}, "body": ""}`
- `paginated(data, cursor, has_more, total_count, request_id)` → includes `pagination` block
- `error_response(error, instance, request_id)` → RFC 7807 format from LogisticsBaseError
- `validation_error(errors, instance, request_id)` → 422 with field-level errors

### `shared/events.py` — Full Implementation

- Use boto3 EventBridge client
- Event bus name from `EVENT_BUS_NAME` env var
- Generate UUID for `event_id`
- Include ISO 8601 `occurred_at` timestamp

### `shared/pagination.py` — Full Implementation

- Base64 encode/decode cursor as JSON: `{"id": "...", "created_at": "..."}`
- `build_paginated_query()` appends `WHERE (created_at, id) < (:cursor_created_at, :cursor_id) ORDER BY created_at DESC, id DESC LIMIT :limit + 1`
- Fetch limit+1 rows to determine `has_more`

### `shared/audit.py` — Full Implementation

- Insert into `audit_log` table within the tenant scope
- Accept optional `ip_address` from `event["requestContext"]["identity"]["sourceIp"]`

## Handler Pattern (Template for All Services)

Every Lambda handler should follow this exact pattern:

```python
"""{Service Name} Lambda handler.

See 00_CROSS_CUTTING_STANDARDS.md for mandatory conventions.
"""
import os
import time
import logging
from shared.logging_config import setup_logging
from shared.auth import get_tenant_context
from shared.responses import success, created, no_content, error_response, validation_error
from shared.exceptions import LogisticsBaseError
from shared.idempotency import check_idempotency, store_idempotency
from .service import {Service}Service

# Module-level init (runs once on cold start)
setup_logging()
logger = logging.getLogger(__name__)

# X-Ray tracing
from aws_xray_sdk.core import patch_all
patch_all()


def lambda_handler(event: dict, context) -> dict:
    start_time = time.time()
    request_id = event.get("requestContext", {}).get("requestId", "unknown")
    path = event.get("requestContext", {}).get("http", {}).get("path", "")
    method = event.get("requestContext", {}).get("http", {}).get("method", "")

    try:
        tenant_ctx = get_tenant_context(event)

        # Structured logging with context
        extra = {"request_id": request_id, "tenant_id": tenant_ctx.tenant_id}
        logger.info(f"→ {method} {path}", extra=extra)

        # Idempotency check for POST
        idempotency_key = None
        if method == "POST":
            idempotency_key = (event.get("headers") or {}).get("idempotency-key")
            cached = check_idempotency(idempotency_key)
            if cached:
                return cached

        # Route dispatch
        if method == "POST" and path == "/v1/{resource}":
            response = _handle_create(event, tenant_ctx, request_id)
        elif method == "GET" and path == "/v1/{resource}":
            response = _handle_list(event, tenant_ctx, request_id)
        # ... etc
        else:
            from shared.exceptions import ResourceNotFoundError
            response = error_response(ResourceNotFoundError("route", path), request_id=request_id)

        # Store idempotency for successful POST
        if method == "POST" and idempotency_key and response.get("statusCode", 500) < 400:
            store_idempotency(idempotency_key, response)

        return response

    except LogisticsBaseError as e:
        logger.warning(f"Business error: {e.error_code} - {e.message}")
        return error_response(e, instance=path, request_id=request_id)
    except Exception:
        logger.exception("Unhandled error")
        return error_response(
            LogisticsBaseError("Internal server error", "INTERNAL_ERROR", 500),
            instance=path, request_id=request_id,
        )
    finally:
        duration = (time.time() - start_time) * 1000
        logger.info(f"← {method} {path} {duration:.0f}ms", extra={"duration_ms": duration})
```

## Acceptance Criteria

- [ ] `db.py`: Connection reuse works across Lambda invocations
- [ ] `db.py`: `SET LOCAL app.current_tenant_id` is called before EVERY query
- [ ] `db.py`: Transactions rollback on error
- [ ] `auth.py`: Correctly parses Cognito JWT claims from API Gateway event
- [ ] `auth.py`: Tenant suspension check with 60s cache (uses `shared/cache.py`)
- [ ] `auth.py`: `@require_roles` decorator blocks unauthorized access
- [ ] `responses.py`: All response formats match the API contract spec
- [ ] `responses.py`: Security headers included on every response (see Standards §1.4)
- [ ] `responses.py`: `X-Request-Id` header included on every response
- [ ] `responses.py`: `created()` includes `Location` header
- [ ] `responses.py`: `no_content()` returns 204 with empty body
- [ ] `events.py`: Publishes to correct EventBridge bus with full envelope including `request_id`
- [ ] `pagination.py`: Cursor-based pagination produces correct SQL
- [ ] `idempotency.py`: Checks and stores idempotency keys with 24h TTL
- [ ] `cache.py`: TTL-based in-memory cache with per-key expiry
- [ ] `circuit_breaker.py`: Tracks failures, opens circuit after threshold, recovers after timeout
- [ ] `metering.py`: `record_usage()` publishes UsageRecorded events
- [ ] `notifications.py`: `enqueue_notifications()` checks preferences before SQS enqueue
- [ ] `logging_config.py`: Structured JSON formatter with service, environment, request_id, tenant_id
- [ ] Handler pattern includes X-Ray tracing initialization
- [ ] Handler pattern includes idempotency key handling for POST
- [ ] Handler pattern includes request timing and structured logging
- [ ] All modules have comprehensive logging
- [ ] All functions have type hints
