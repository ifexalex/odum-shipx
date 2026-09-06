# Task 02 — Shared Lambda Layer: DB, Auth, Tenant Context, Responses

## Objective

Implement the shared utility modules that ALL Lambda services depend on. These form the Lambda Layer and enforce multi-tenant isolation at the application level.

## Depends On

- Task 01 (project structure, exceptions.py)

## Architecture Context

Every Lambda function follows this flow:
1. API Gateway receives request with JWT
2. Lambda handler extracts tenant context from JWT claims
3. Handler calls service layer with tenant context
4. Service layer calls repository layer, passing `tenant_id`
5. Repository sets `app.current_tenant_id` PostgreSQL session variable (for RLS)
6. All queries include `WHERE tenant_id = :tenant_id`

**Cognito JWT claims structure:**
```json
{
  "sub": "cognito-user-uuid",
  "custom:tenant_id": "tenant-uuid-or-PLATFORM",
  "cognito:groups": ["tenant-uuid:china_office_staff"]
}
```

**Roles:** `platform_admin`, `tenant_admin`, `china_office_staff`, `nigeria_office_staff`, `warehouse_attendant`, `customer`

## Deliverables

### File: `shared/tenant_context.py`

```python
"""Tenant context extraction and validation."""

from dataclasses import dataclass, field
from enum import Enum


class UserRole(str, Enum):
    PLATFORM_ADMIN = "platform_admin"
    TENANT_ADMIN = "tenant_admin"
    CHINA_OFFICE_STAFF = "china_office_staff"
    NIGERIA_OFFICE_STAFF = "nigeria_office_staff"
    WAREHOUSE_ATTENDANT = "warehouse_attendant"
    CUSTOMER = "customer"


PLATFORM_TENANT_ID = "PLATFORM"


@dataclass(frozen=True)
class TenantContext:
    """Represents the authenticated user's tenant scope."""
    tenant_id: str
    user_id: str  # Cognito sub — used directly as created_by/approved_by/rejected_by
                  # everywhere (UUID REFERENCES tenant_user(id)). There is no separate
                  # resolution step, so tenant_user.id MUST be set to the Cognito sub
                  # at creation time, not left to gen_random_uuid() — see
                  # create_tenant_user() in services/tenant_management/repository.py.
    role: UserRole
    is_platform_admin: bool = field(init=False)

    def __post_init__(self):
        object.__setattr__(self, 'is_platform_admin', self.tenant_id == PLATFORM_TENANT_ID)

    def assert_role(self, *allowed_roles: UserRole) -> None:
        """Raise InsufficientPermissionsError if user doesn't have one of the allowed roles."""
        from shared.exceptions import InsufficientPermissionsError
        if self.role not in allowed_roles:
            raise InsufficientPermissionsError(
                action="this operation",
                required_role=" or ".join(r.value for r in allowed_roles),
            )

    def assert_tenant_scope(self, target_tenant_id: str) -> None:
        """Verify user can access data for the given tenant."""
        from shared.exceptions import InsufficientPermissionsError
        if not self.is_platform_admin and self.tenant_id != target_tenant_id:
            raise InsufficientPermissionsError(
                action="cross-tenant access",
                required_role=UserRole.PLATFORM_ADMIN.value,
            )
```

### File: `shared/distributed_cache.py`

Redis-backed distributed cache — replaces `shared/cache.py` for tenant status.

```python
class DistributedCache:
    """Redis-backed cache. Same interface as Cache but shared across Lambda fleet.

    Values stored as strings with SETEX. Fail-soft: Redis errors log a warning
    and return None/no-op so the caller falls through to the DB.
    """
    def __init__(self, default_ttl: int = 60, key_prefix: str = "") -> None: ...
    def get(self, key: str) -> str | None: ...
    def set(self, key: str, value: str, ttl: int | None = None) -> None: ...
    def delete(self, key: str) -> None: ...
    def clear(self) -> None: ...  # no-op for distributed cache
```

Connection config via env vars: `REDIS_HOST` (default `localhost`), `REDIS_PORT` (default `6379`).
Socket timeouts: 500ms connect, 500ms operation.

### File: `shared/auth.py`

Extract tenant context from API Gateway event. Must handle:
- JWT claim extraction from `event["requestContext"]["authorizer"]["claims"]`
- Role parsing from `cognito:groups` (format: `{tenant_id}:{role}`)
- Tenant suspension check via `DistributedCache` (Redis, 60s TTL) with DB fallback
- Platform Admin detection (`custom:tenant_id == "PLATFORM"`)
- Return `TenantContext` dataclass

**Key function signatures:**
```python
def get_tenant_context(event: dict) -> TenantContext:
    """Extract and validate tenant context from API Gateway event."""
    ...

def require_roles(*roles: UserRole):
    """Decorator that validates the caller has one of the specified roles."""
    ...
```

### File: `shared/db.py`

Database connection management. Must handle:
- Connection pooling via environment variables (RDS Proxy endpoint)
- `get_connection(tenant_id: str)` → sets `SET LOCAL app.current_tenant_id = :tenant_id` for RLS
- Platform Admin connections set a special RLS bypass or use the admin role
- Context manager for transaction handling
- Connection reuse across Lambda invocations (module-level connection)

**Key function signatures:**
```python
def get_connection() -> connection:
    """Get or create a database connection (reused across invocations)."""
    ...

def execute_with_tenant(tenant_id: str, query: str, params: dict) -> list[dict]:
    """Execute a query within a tenant scope (sets RLS session variable)."""
    ...

def execute_write_with_tenant(tenant_id: str, query: str, params: dict) -> dict | None:
    """Execute INSERT/UPDATE/DELETE within tenant scope. Returns the affected row."""
    ...

def execute_transaction(tenant_id: str, queries: list[tuple[str, dict]]) -> list:
    """Execute multiple queries in a single transaction."""
    ...
```

**Environment variables:**
- `DATABASE_HOST` — RDS Proxy endpoint
- `DATABASE_PORT` — 5432
- `DATABASE_NAME` — logistics
- `DATABASE_USER` — logistics_app
- `DATABASE_PASSWORD` — from Secrets Manager

### File: `shared/responses.py`

Standardized API response formatting (RFC 7807 for errors).

```python
def success(data: dict | list, status_code: int = 200, meta: dict | None = None) -> dict:
    """Format a success response."""
    # Returns: {"statusCode": 200, "body": json.dumps({"data": ..., "meta": {...}})}

def paginated(data: list, cursor: str | None, has_more: bool, total_count: int | None = None) -> dict:
    """Format a paginated list response."""

def error_response(error: LogisticsBaseError, instance: str = "") -> dict:
    """Format an RFC 7807 error response from a LogisticsBaseError."""

def validation_error(errors: list[dict], instance: str = "") -> dict:
    """Format a validation error with field-level details."""
```

### File: `shared/events.py`

EventBridge event publisher. All events carry `tenant_id`.

```python
def publish_event(
    source: str,          # e.g., "logistics.packing_list"
    detail_type: str,     # e.g., "PackingListApproved"
    tenant_id: str,
    payload: dict,
) -> str:
    """Publish an event to EventBridge. Returns the event_id."""
```

**Event envelope format:**
```json
{
  "source": "logistics.{service_name}",
  "detail-type": "{EventName}",
  "detail": {
    "tenant_id": "uuid",
    "event_id": "uuid",
    "occurred_at": "ISO 8601",
    "payload": { ... }
  }
}
```

### File: `shared/pagination.py`

Cursor-based pagination utilities.

```python
def encode_cursor(data: dict) -> str:
    """Base64-encode cursor data."""

def decode_cursor(cursor: str | None) -> dict | None:
    """Decode a cursor string. Returns None if cursor is None."""

def parse_pagination_params(query_params: dict) -> tuple[dict | None, int]:
    """Extract cursor and limit from query string params. Default limit=20, max=100."""

def build_paginated_query(
    base_query: str,
    cursor: dict | None,
    limit: int,
    sort_field: str = "created_at",
    sort_direction: str = "DESC",
) -> tuple[str, dict]:
    """Append pagination WHERE clause and LIMIT to a base query."""
```

### File: `shared/audit.py`

Audit logging helper.

```python
def log_audit(
    tenant_id: str,
    entity_type: str,
    entity_id: str,
    action: str,  # CREATE, UPDATE, DELETE, STATUS_CHANGE
    actor_id: str,
    actor_role: str,
    before_state: dict | None = None,
    after_state: dict | None = None,
    ip_address: str | None = None,
) -> None:
    """Insert a record into audit_log table."""
```

## Acceptance Criteria

- [ ] `TenantContext` dataclass correctly parses JWT claims
- [ ] `get_tenant_context()` raises `TenantSuspendedError` for suspended tenants
- [ ] `get_tenant_context()` raises `AuthenticationRequired` for missing/invalid JWT
- [ ] `db.py` always sets `SET LOCAL app.current_tenant_id` before queries
- [ ] `db.py` uses connection reuse pattern (module-level `_connection` variable)
- [ ] `responses.py` produces correct RFC 7807 format for all error types
- [ ] `events.py` publishes to EventBridge with correct envelope including `tenant_id`
- [ ] `pagination.py` handles cursor encoding/decoding and query building
- [ ] All functions have type hints
- [x] `distributed_cache.py` — Redis-backed `DistributedCache` for tenant status, fail-soft on Redis errors


## shared/tier_limits.py (updated 2026-07-09)

`TIER_LIMITS` static defaults plus **runtime override resolution**: `get_effective_limits(tier, tenant_id=None)` merges static defaults → platform_settings `plan_limits` (per-tier, platform-wide) → platform_settings `quota_override:{tenant_id}` (per-tenant). `get_all_plan_limits()` powers the platform Plans editor. DB reads are lazy imports and **fail open** to the static defaults — quota enforcement is a soft commercial limit, so an infra failure must not block tenant operations (auth checks, by contrast, fail closed). Only `users`, `containers_per_month`, `storage_gb` may be overridden (`LIMIT_DIMENSIONS` allowlist).

## shared/notifications.py — channel selection (updated 2026-09-06)

`primary_channel(tenant_id, event_type, recipient) -> str` returns the channel that
will actually carry a notification: WhatsApp when the recipient has a phone, the
tenant permits it, and `SQS_WHATSAPP_QUEUE_URL` is configured; otherwise SMS;
otherwise email. Email is a different medium rather than a worse SMS, so it always
goes out alongside and is never returned here.

`enqueue_notifications` uses it to pick the primary channel, and any caller that
needs to **report** how something was delivered must call it too. It was extracted
because `issue_customer_invite` carried its own copy hardcoded to `"sms"`, so after
the switch to WhatsApp-first every invite told staff the link was sent by SMS while
the message went out over WhatsApp.

Both `enqueue_notification` and `enqueue_notifications` also take an optional
`customer_id`, written onto the queued message and persisted to
`notification_log.customer_id`. The WhatsApp→SMS fallback re-reads the recipient's
phone from the customer record (the log deliberately stores only a masked contact),
so without it the fallback cannot resolve a number and gives up silently. See
`15_api_notifications.md` §"Ground-truth gaps found by draining a real notification".

## Local dev server made single-threaded (2026-09-06) — the actual root cause

`scripts/local_server.py`'s `app.run()` now passes `threaded=False` explicitly.

**This is the real root cause of the connection-self-heal issue below**, not
just one contributing trigger. Flask's own `run()` docstring says *"Threaded
mode is enabled by default"* — the local dev server had been processing
concurrent requests on separate Python threads all along, every one of them
sharing `shared/db.py`'s single module-level `_connection` with no lock. Two
browser XHRs firing in parallel (any page that fetches several endpoints at
once — a dashboard is exactly that) could genuinely interleave `cur.execute()`
calls from different threads on the *same* psycopg2 connection, corrupting
its transaction state in ways no amount of per-call rollback discipline can
prevent. Every fix below (the metering upsert, the self-heal, the PLATFORM
sentinel skip) narrowed *a* trigger; none of them could fully stop the
corruption while two threads could still race on one connection. Confirmed:
the platform dashboard, which reliably crashed 1-in-3 runs before, passed 20
consecutive times after this change with zero
`InFailedSqlTransaction` occurrences in the log.

Real AWS Lambda never has this hazard — a single container processes one
invocation at a time, never two concurrently — so `threaded=False` here is
also the more faithful match to production's actual execution model, not a
workaround that trades correctness for speed. (It does mean the local server
now genuinely serializes concurrent page-load fetches, same as Lambda would
via cold starts / separate containers per concurrent request in practice.)

## shared/db.py — connection self-heal (added 2026-09-06)

`get_connection()` now checks `_connection.get_transaction_status()` and calls
`rollback()` if it's `TRANSACTION_STATUS_INERROR` before handing the connection
to a caller, in addition to creating a fresh one when `None`/closed.

**Ground-truth gap found live via e2e testing.** `shared/metering.py`'s
`record_usage()` hit a duplicate-key race on `usage_record`'s
`(tenant_id, metric_type, period_start, period_end)` unique constraint under
rapid requests. That INSERT is wrapped by `execute_write_with_tenant`, which
does roll back on its own failure — but the connection was still observed left
in a failed-transaction state afterward, and every *subsequent unrelated*
request on the same process then failed with
`psycopg2.errors.InFailedSqlTransaction: current transaction is aborted,
commands ignored until end of transaction block` — regardless of endpoint,
tenant, or service module, since `_connection` is one module-level global
shared by everything. Surfaced first as a genuine page crash
("Internal server error") on `/platform/dashboard` in a new e2e smoke test,
then reproduced hitting `/v1/tenants/me/quota`, `/v1/billing`, and
`/v1/platform/dashboard` interchangeably in the same run — the scattered,
seemingly-random pattern across unrelated endpoints was the signature that
pointed at a shared poisoned resource rather than a per-endpoint bug.

**Why fix `get_connection()` rather than chase the exact original trigger
further:** in production this connection is reused across an entire warm
Lambda container's lifetime — any single unrolled-back failure, from any
current or future code path, would otherwise break every request on that
container until AWS recycles it. Self-healing at the one place every caller
already goes through is more robust than auditing every call site for a
missing rollback, and doesn't depend on finding every future regression of
the same shape. Verified: the exact e2e smoke sweep that surfaced the crash
now runs clean end to end (`frontend/e2e/flows/smoke-navigation.spec.ts`).

Covered by `tests/unit/test_db_connection_healing.py`.

## shared/validation.py — parse_validated() (added 2026-09-06)

`parse_validated(model_class, body)` parses a request body dict into a Pydantic
model, raising the app's `ValidationError` (not a raw `pydantic.ValidationError`)
on failure. Consolidates nine byte-for-byte-identical `_parse_validated()`
copies across `services/*/handler.py` (plus a tenth, differently-shaped
instance inline in `services/auth/handler.py`).

**Real bug found by having nine copies, fixed by having one.** Every copy
built `field_errors` with `str(e["loc"][-1]): e["msg"]` — correct for a
per-field pydantic error, but a `@model_validator` cross-field check reports
an error with an **empty** `loc` tuple (it isn't about one field), and
`()[-1]` raises `IndexError`. That turned a validation failure that should
be a clean 422 into a raw, undiagnosable 500 for any endpoint using a
model-level validator — found live via e2e testing
(`RecordPickupRequest`'s "collected_by_name is required when is_delegate is
false"; see `13_api_payment_release.md`). `parse_validated()` keys a
model-level error `"__root__"` instead. Covered by
`tests/unit/test_shared_validation.py`.

Every `services/*/handler.py` now imports this instead of defining its own
copy — a future fix to this logic can no longer land in eight of nine files
by accident.
