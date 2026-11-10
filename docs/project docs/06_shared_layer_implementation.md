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

def execute_write_with_tenant_many(tenant_id: str, query: str, params: dict | None = None) -> list[dict]:
    """Execute a multi-row INSERT/UPDATE/DELETE within tenant scope. Returns every affected row.

    Use for bulk writes (`WHERE id = ANY(...)`) — `execute_write_with_tenant` only
    returns the first row, and `execute_with_tenant` never commits.
    """
    conn = get_connection()
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute("SET LOCAL app.current_tenant_id = %s", (tenant_id,))
            cur.execute(query, params or {})
            results = cur.fetchall() if cur.description else []
        conn.commit()
        return [dict(row) for row in results]
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
- [x] `notifications.py`: `enqueue_notifications()` checks preferences before SQS enqueue; looks up `notification_template` per channel and embeds custom copy as `template_override` in SQS payload
- [x] `notifications.py`: `enqueue_notification()` (singular) accepts `locale: str = "en"` and includes it in the SQS message body so notification Lambdas select the correct template language
- [x] `webhook.py`: `fire_tenant_webhook()` signs outbound HTTP POST with HMAC-SHA256 (`X-ShipX-Signature-256: sha256=<hex>`); `test_fire_tenant_webhook()` sends a test event and returns `{success, status_code, error}`
- [x] `fx_rate.py` (2026-09-19): `get_effective_dollar_rate(tenant_id)` centralizes what used to be four independent `tenant_config['dollar_rate']` readers; base rate fetched live from Bybit's public P2P order book (`fetch_bybit_ngn_rate()`, circuit-breaker guarded), cached in Redis (`DistributedCache`, 10 min TTL) with a `platform_settings`-persisted last-known-good fallback for outages; `ssl_context.py::verified_ssl_context()` shares a small TLS-context helper with `paystack.py` rather than duplicating it a second time. See `02_shared_utilities.md`.
- [x] `cbm_rate.py` (2026-09-20): `get_cbm_rate_config(tenant_id)` + `compute_cbm_charge(cbm_by_unit, config)` centralize CBM freight pricing — a tenant admin picks a currency (USD/NGN) and either one flat rate or separate carton/bag/bale rates ("flat" is just the case where all three are equal, one code path, no mode branching in the money math). `normalize_package_unit()` folds any package type other than exact "bag"/"bale" into the carton bucket. Backward-compatible at read time with the pre-2026-09-20 single-rate shape — no data migration. See `02_shared_utilities.md`.
- [ ] `logging_config.py`: Structured JSON formatter with service, environment, request_id, tenant_id
- [ ] Handler pattern includes X-Ray tracing initialization
- [ ] Handler pattern includes idempotency key handling for POST
- [ ] Handler pattern includes request timing and structured logging
- [ ] All modules have comprehensive logging
- [ ] All functions have type hints

### `shared/url_safety.py` — added 2026-09-23

New shared module (SSRF guard for tenant-supplied webhook URLs). Full contract in
[02_shared_utilities.md](02_shared_utilities.md#sharedurl_safetypy-added-2026-09-23).
`shared/webhook.py` now delivers through `open_public_https()` instead of
`urllib.request.urlopen()`, and builds the signed request inside its `try` so a
malformed URL stored before this validation existed can no longer raise out of
`fire_tenant_webhook` (documented as never raising).

## `shared/db_credentials.py` — `ensure_app_role_password()` (2026-11-10)

Applies `logistics_app`'s password from `APP_DB_PASSWORD`, idempotently, after
every successful Alembic upgrade. Called from both migrate entrypoints:
`scripts/migrate.py` (the container image's `migrate` command, so Azure and
local/CI) and `services/migrate/handler.py` (AWS).

**Why it is not just migration 060.** 060 sets the same password, but Alembic
runs a migration once per database and 060's effect depends on an *environment
variable*, not on the schema. An environment that applied 060 before its secret
existed got the no-op branch, a role left NOLOGIN, and 060 permanently recorded
as applied — provisioning the secret afterwards changed nothing. Azure dev hit
exactly this and the phase-2 cutover failed authentication on every request.

Returns a status string (`"set"`, `"skipped-no-password"`, `"skipped-no-role"`)
which both entrypoints log, so a deploy says what it did to the credential.

An unset `APP_DB_PASSWORD` is not an error — an environment awaiting cutover has
no such secret, and refusing to migrate would block its deploy. The skip happens
*before* connecting, which `tests/unit/test_db_credentials.py` asserts directly.

The password is bound as a parameter into a transaction-local `set_config`, then
quoted by `format('%L')` inside a DO block: `ALTER ROLE` cannot take a bind
parameter, and the project forbids interpolating values into SQL text. A test
asserts the secret never appears in any statement string.

### `NOBYPASSRLS` requires SUPERUSER, so it is conditional (2026-11-10)

The first version of `ensure_app_role_password()` ran
`ALTER ROLE logistics_app NOBYPASSRLS` unconditionally. That **failed every Azure
deploy** with `must be superuser to change bypassrls attribute`, while passing
locally — the local Docker Postgres superuser can run it; a managed Flexible
Server / RDS admin login cannot.

Two changes:

1. **The statement is conditional.** `CREATE ROLE` defaults to NOBYPASSRLS, so
   the attribute is already correct and nothing is issued. It runs only when the
   role genuinely has BYPASSRLS, and then the error is allowed to propagate —
   an app role that bypasses RLS makes 059's policies inert.
2. **The password is committed first.** The two statements were one DO block, so
   the privilege error rolled the password back as well: a failed deploy *also*
   left the credential unset, two problems reported as one. Verified against a
   real non-superuser — `rolcanlogin` goes `false → true` even when the BYPASSRLS
   change raises.

Migration 060 carried the identical statement and the identical latent bug. It
escaped only because it took its no-op branch on the one managed server it ran
against; it is now guarded the same way.

Verified by simulating the managed-server privilege model locally — a
`CREATEROLE NOSUPERUSER` role — rather than trusting the local superuser:

| case | result |
|---|---|
| non-superuser, role already NOBYPASSRLS | `set`, app connects |
| non-superuser, old unconditional statement | `ERROR: must be superuser…` (the regression) |
| non-superuser, role **has** BYPASSRLS | raises `InsufficientPrivilege` — correct |
| superuser, role **has** BYPASSRLS | `set-and-stripped-bypassrls` |

