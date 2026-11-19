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

def tenant_transaction(tenant_id: str):  # reusable: execute_* calls for the same tenant join it (see 02_shared_utilities.md)
    """Context manager yielding a cursor inside one tenant-scoped transaction.

    Commit on normal exit, full rollback on any exception. Use when later statements depend on the
    rows returned by earlier ones (`execute_transaction` takes its statement list up front).
    `next_tenant_counter(cursor, tenant_id, name)` takes the next per-tenant number from `tenant_counter`
    with a row-locking upsert, so concurrent callers get distinct values. Added with migration 062.
    """


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

- [x] `db.py`: Connection reuse works across Lambda invocations
- [x] `db.py`: `SET LOCAL app.current_tenant_id` is called before EVERY query
- [x] `db.py`: Transactions rollback on error
- [x] `auth.py`: Correctly parses Cognito JWT claims from API Gateway event
- [x] `auth.py`: Tenant suspension check, cached (**corrected 2026-11-11:** it is a *distributed* Redis cache — `DistributedCache` in `shared/distributed_cache.py`, not `shared/cache.py` — and the tenant-status TTL is **15s**, not 60s. The original criterion named the wrong mechanism and a TTL 4× too long; four comments in `shared/auth.py` repeated the 60s figure and have been corrected. Redis was chosen deliberately: an in-process cache is per-Lambda-instance, so a suspended tenant could keep working for the TTL on every warm instance independently.)
- [x] `auth.py`: `@require_roles` decorator blocks unauthorized access
- [x] `responses.py`: All response formats match the API contract spec
- [x] `responses.py`: Security headers included on every response (see Standards §1.4)
- [x] `responses.py`: `X-Request-Id` header included on every response
- [x] `responses.py`: `created()` includes `Location` header
- [x] `responses.py`: `no_content()` returns 204 with empty body
- [x] `events.py`: Publishes to correct EventBridge bus with full envelope including `request_id`
- [x] `pagination.py`: Cursor-based pagination produces correct SQL
- [x] `idempotency.py`: Checks and stores idempotency keys with 24h TTL
- [x] `cache.py`: TTL-based in-memory cache with per-key expiry
- [x] `circuit_breaker.py`: Tracks failures, opens circuit after threshold, recovers after timeout
- [x] `metering.py`: `record_usage()` publishes UsageRecorded events
- [x] `notifications.py`: `enqueue_notifications()` checks preferences before SQS enqueue; looks up `notification_template` per channel and embeds custom copy as `template_override` in SQS payload
- [x] `notifications.py`: `enqueue_notification()` (singular) accepts `locale: str = "en"` and includes it in the SQS message body so notification Lambdas select the correct template language
- [x] `webhook.py`: `fire_tenant_webhook()` signs outbound HTTP POST with HMAC-SHA256 (`X-ShipX-Signature-256: sha256=<hex>`); `test_fire_tenant_webhook()` sends a test event and returns `{success, status_code, error}`
- [x] `fx_rate.py` (2026-09-19): `get_effective_dollar_rate(tenant_id)` centralizes what used to be four independent `tenant_config['dollar_rate']` readers; base rate fetched live from Bybit's public P2P order book (`fetch_bybit_ngn_rate()`, circuit-breaker guarded), cached in Redis (`DistributedCache`, 10 min TTL) with a `platform_settings`-persisted last-known-good fallback for outages; `ssl_context.py::verified_ssl_context()` shares a small TLS-context helper with `paystack.py` rather than duplicating it a second time. See `02_shared_utilities.md`.
- [x] `cbm_rate.py` (2026-09-20): `get_cbm_rate_config(tenant_id)` + `compute_cbm_charge(cbm_by_unit, config)` centralize CBM freight pricing — a tenant admin picks a currency (USD/NGN) and either one flat rate or separate carton/bag/bale rates ("flat" is just the case where all three are equal, one code path, no mode branching in the money math). `normalize_package_unit()` folds any package type other than exact "bag"/"bale" into the carton bucket. Backward-compatible at read time with the pre-2026-09-20 single-rate shape — no data migration. See `02_shared_utilities.md`.
- [x] `logging_config.py`: Structured JSON formatter with service, environment, request_id, tenant_id
- [x] Handler pattern includes X-Ray tracing initialization
- [x] Handler pattern includes idempotency key handling for POST
- [ ] Handler pattern includes request timing and structured logging — **partially: structured logging is universal** (every handler goes through `shared/logging_config.py`), **but explicit request timing is in 4 of 14 handlers** (`auth`, `excel`, `payment_release`, `tracking`). `logging_config` only passes a caller-supplied `duration_ms` through; it does not measure. Audited 2026-11-11.
- [ ] All modules have comprehensive logging — **not met: 20 of 32 `shared/` modules bind a logger.** The remaining 12 are mostly pure helpers with nothing worth logging, so the gap may be correct — but "all" is not true, and this stays unchecked rather than being ticked on a generous reading. Audited 2026-11-11.
- [x] All functions have type hints

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

## `shared/` additions — audit Phase 2 (2026-11-15)

(Same table as in `02_shared_utilities.md`.)

| Module | Purpose |
|---|---|
| `shared/auth.py` | `get_tenant_context` now confirms the user still has an active `tenant_user` row (`_check_user_active`, 401 / 503), and counts the tenant against its rate limit. New `evict_identity_cache(user_id)`; `_active_identity` is the strict cached lookup (raises on DB failure) and `resolve_identity_from_db` the tolerant wrapper the identity fallback keeps using. |
| `shared/origin_guard.py` | `trusted_origins()`, `assert_trusted_origin(event)` (403 `ORIGIN_NOT_ALLOWED`; a missing `Origin` is refused; fail closed when none is configured), `assert_json_content_type(event)` (415). Used by `services/auth/handler.py`. |
| `shared/rate_limit.py` | Redis fixed-window limiter: `hit`, `peek` + `record_failure` + `clear`, `hit_for_client`; named policies (`LOGIN_IP`, `LOGIN_FAILURES`, `REGISTER_IP`, `ONBOARDING_IP`, `TRACKING_IP`, `TRACKING_FAILURES`, `SESSION_IP`, `TENANT`); `RATE_LIMIT_<NAME>` overrides and `RATE_LIMIT_ENABLED`. Fails open, logging `rate_limiter_unavailable`. Identifiers are hashed in keys. |
| `shared/client_ip.py` | `client_ip(event)` (reads `requestContext.http.sourceIp` then `identity.sourceIp`), `resolve_client_ip(peer, xff, hops)`, `trusted_proxy_hops()` (`TRUSTED_PROXY_HOPS`). All handlers now use `client_ip` for `ip_address`. |
| `shared/notification_consent.py` | Pure policy: `ACCOUNT_EVENTS`, `OPERATIONAL_EVENTS`, `CONSENT_BOUND_EVENTS`, `is_consent_bound`, `permits`. |
| `shared/notifications.py` | `consent_verdict`, `ConsentVerdict`, `record_suppressed`; both enqueue paths apply them; channels are de-duplicated. |
| `shared/distributed_cache.py` | `incr_window` (atomic INCR + expiry in one Lua script) and `window_state`; **no client retries and a 5 s circuit breaker** (a Redis outage cost ~4 s per call before). |
| `shared/exceptions.py` / `shared/responses.py` | `UntrustedOriginError` (403), `UnsupportedMediaTypeError` (415), `RateLimitExceededError` (429, `retry_after`); `accepted()` (202); `error_response` sets `Retry-After`. |
| `shared/app_urls.py` | `origin_of` is now public (shared with the origin guard); new `login_url()`. |

## `shared/list_filters.py` (2026-11-16)

The invoice-list and container-list filters (`status`, dates, `q`, ...) as pure functions returning a WHERE clause and bound parameters. `services/billing/repository.py::list_billing_all`, `services/tracking/repository.py::list_containers` and `services/excel/repository.py::list_billing_for_export` / `list_containers_for_export` all build from them. Lives in `shared/` because each Lambda ships only its own `services/<name>/` plus the layer, so the excel service cannot import the billing or tracking repositories.

## `shared/` additions — tenant data export (audit BE-10, 2026-11-17)

- **`shared/tenant_data.py`** — the single inventory of tables holding a tenant's data, parent-first: `TENANT_TABLES` (each a `TenantTable(name, via=(fk_column, parent) | None, omit=…, decrypt=…)` with `select_sql()` / `delete_sql()`; names are checked to be plain SQL identifiers), `NOT_TENANT_DATA` (platform tables, with the reason), `redact_config(config_key, value)` (drops the webhook secret and the Paystack key), `table(name)`. The export reads it forwards, the cleanup deletes it backwards. `tests/unit/test_tenant_data.py` reads every migration and fails when a table is unaccounted for or the order breaks a foreign key: **add new tables here.**
- **`shared/tenant_export.py`** — the `tenant_offboarding_export` record: `export_prefix`, `object_key` (UUID-checked), `queue_export`, `latest_export`, `has_completed_export(tenant_id, since)`, `claim_next` (`SKIP LOCKED`), `mark_completed` / `mark_failed` / `mark_cancelled` (only from the right state), `cancel_open_exports`. `MAX_ATTEMPTS = 3`, `STALE_AFTER_MINUTES = 60`. PLATFORM scope throughout.
- **`shared/platform_audit.py`** — `insert_platform_audit(action, actor_id, target_tenant_id, details, ip_address)`, moved out of `services/tenant_management/repository.py` (which re-exports it) so platform jobs can write the platform trail.

## `shared/observability.py` — failure counters (audit OPS-04, 2026-11-17)

`record_failure(operation)` counts one failure that was caught and not re-raised; `record_outcome(operation, failed=)` counts an attempt and whether it failed (for a rate). Both write one log line through the normal JSON formatter in CloudWatch's Embedded Metric Format (namespace `ShipX`, dimensions `Environment` and `Operation`); on Azure the same line is queried in Log Analytics. Never raises. `operation` must be one of the fixed `OPERATIONS` (`invoice_generation`, `notification_enqueue`, `notification_send`, `audit_write`, `scheduled_job_step`, `tenant_deletion_refused`): a name is a billed metric dimension, so it is never built from data. The `shipx.metrics` logger is pinned at INFO so a higher `LOG_LEVEL` cannot switch the counts off. Called from `shared/audit.py`, `shared/platform_audit.py` (counts, then re-raises), `shared/notifications.py`, `services/billing` (invoice generation), `services/notification/service.py` (`log_sent` / `log_failed`), and the per-tenant and per-record catches of every scheduled job.

## `shared/uploads.py` — one set of upload rules (audit BE-12, 2026-11-17)

Every direct-to-storage upload goes through it: claim evidence, manifest evidence, payment-claim evidence, container documents and the packing-list import. `UploadPolicy(name, content_types, expires_in)` with three instances — `EVIDENCE` (JPEG, PNG, PDF; 1 h), `CONTAINER_DOCUMENT` (those plus WebP; 15 min), `SPREADSHEET_IMPORT` (`.xlsx`; 15 min). `policy.check_content_type(ct)` raises `BusinessRuleViolationError(rule_id="INVALID_CONTENT_TYPE")` and is called before any database read; `presign_upload(policy, tenant_id, segments, filename, ct)` checks again, builds `upload_key(...)` = `{tenant_id}/{segments...}/{safe_filename(filename)}` (the tenant ID must parse as a UUID; a segment that is empty or holds `/`, `\\` or `..` raises `ValueError`) and returns `PresignedUpload(key, expires_in, ticket)` with `as_response()`. A policy cannot be declared with `application/octet-stream`.

Changed behaviour: container documents no longer accept `application/octet-stream` (it let any file through the type check); the frontend now refuses a file the browser cannot type, in the upload dialog. ~~Known limits, not fixed here: no upload size is enforced anywhere (the per-service `_MAX_FILE_SIZE` constants were never read and are removed; runbook "Upload size is not limited"); the declared type binds the upload only on AWS S3 (SigV4) — an Azure SAS and the local Moto do not enforce it.~~ **Superseded 2026-11-17:** uploads are limited to 5 MB (`MAX_UPLOAD_BYTES`, every policy's `max_bytes`). `policy.check(content_type, size_bytes)` refuses a missing size (`ValidationError`) or one over the limit (`FILE_TOO_LARGE`) before any database work; `presign_upload(..., size_bytes)` passes it to the provider as `content_length`. `S3StorageProvider` uses SigV4 against real AWS (`Config(signature_version="s3v4")`; botocore's presign default can be SigV2, which signs nothing), so the URL signs `content-length;content-type;host` and S3 refuses a different size or type. Azure SAS cannot bind either, and local Moto uses SigV2: there, `check_stored_size(policy, key)` (missing → `UPLOAD_NOT_FOUND`, over → `FILE_TOO_LARGE`) guards where a file is used — payment-claim submit and both spreadsheet imports. ~~Evidence and container documents are not re-checked after upload on Azure.~~ **2026-11-19:** they are, by `confirm_stored_upload(policy, key)` at the new confirm routes (see below).

## Upload confirmation in `shared/uploads.py` (2026-11-19)

- `upload_key` now ends `{uuid4 hex}-{safe_filename}`: two uploads of one name to one record no longer share a key, so one cannot overwrite, or be deleted with, the other. `PresignedUpload.filename` carries the plain safe name for the row.
- `confirm_stored_upload(policy, key) -> int`: the stored size; nothing there → `UPLOAD_NOT_FOUND`; over `max_bytes` → the object is deleted, then `FILE_TOO_LARGE`. Used by the claim-evidence, manifest-evidence and container-document confirm routes.
- `StorageProvider.delete_object(key)` (S3: `delete_object`, the bucket's noncurrent-version rule purges the old version after 30 days; Azure: `delete_blob` with snapshots, a missing blob is not an error).

## Paging past empty sort values (2026-11-19)

**Ground-truth gap closed (found 2026-11-17):** `build_paginated_query` ignored a cursor whose sort value was NULL, so a list sorted by a column that is empty on some rows (invoices by billed date, with unbilled ones) restarted at page one once it reached them. Now every paginated list orders `NULLS LAST` in both directions, the cursor carries `sort_is_null: true` for an empty value, and the next page continues by id among the empty rows; a cursor on a real value also admits the empty rows after it. Visible change: empty values sort at the end even in descending order (Postgres had put them first). Applies to every list using `shared.pagination` (23 call sites). Tests: `tests/unit/test_pagination_walk.py::TestEmptySortValues` (walks page by page through SQLite; all 6 fail on the old code).
