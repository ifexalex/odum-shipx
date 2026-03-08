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
    user_id: str  # Cognito sub
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
