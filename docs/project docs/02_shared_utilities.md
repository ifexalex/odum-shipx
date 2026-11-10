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
    # Emits `rule_id` when the error carries one (BusinessRuleViolationError).
    # Fixed 2026-11-02: dozens of business rules across every service set a
    # rule_id and it was never serialized, so a client could only tell *which*
    # rule refused a request by matching the English message. Clients read it
    # as ApiError.ruleId (frontend/src/api/client.ts).

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
    actor_id: str | None,  # None for a system-triggered action — see below
    actor_role: str,
    before_state: dict | None = None,
    after_state: dict | None = None,
    ip_address: str | None = None,
) -> None:
    """Insert a record into audit_log table."""
```

**Ground-truth gap found live (2026-09-07) while auditing log coverage across every service:** `audit_log.actor_id` is a `UUID REFERENCES tenant_user(id)` column, but two system-triggered call sites (`payment_release/service.py::process_webhook_payment` and, at the time, a newly-added one in `billing/service.py::handle_payment_due`) passed placeholder strings (`"gateway"`, `"system"`) instead of a real UUID or `None`. `log_audit()` never raises — any failure is caught and logged as a WARNING — so every webhook-confirmed payment (real money, gateway-triggered, no human actor) had **silently never been written to the audit trail** since that code was first written; the insert failed with `invalid input syntax for type uuid` on every single call, with nothing surfacing it. Confirmed live: reproduced the failure directly against the local DB, then confirmed the fix writes a real row. Fixed: `actor_id` is now typed `str | None`, and both system-triggered call sites pass `None` (with `actor_role="system"` saying who/what it was) instead of a placeholder string. **This is exactly the kind of gap `07_api_tenant_management.md`'s new Activity Log page (2026-09-07) exists to make visible and preventable** — before that page existed, there was no way for anyone to notice this had been silently failing.

**A second, much larger instance of the identical failure mode, found the same day while wiring up the Activity Log's Action filter:** `audit_log.action` (migration 004) is `VARCHAR(30) CHECK (action IN ('CREATE', 'UPDATE', 'DELETE', 'STATUS_CHANGE'))`. A grep across every `log_audit()` call site found **20** passing a more descriptive verb the check doesn't allow — `EXPORT`, `CANCEL`, `RETRY`, `EXEMPT`, `DEACTIVATE`, `SELF_REGISTER`, `INVITE_ACCEPTED`, `DISCREPANCY_RESOLVED`, `WAIVE_STORAGE_FEES`, `APPLY_CARRYOVER`, `BULK_APPROVE`, `BULK_SUBMIT`, `BULK_REJECT`, `IMPERSONATION_START`, `IMPERSONATION_END`, and others — across billing, packing lists, tracking, manifest, notifications, excel exports, and tenant management. Every one of these calls has been silently failing since it was written. Migration 045 drops the CHECK constraint and widens the column to `VARCHAR(100)`, matching `platform_audit_log.action`'s already-looser design (that sibling table has never had a CHECK constraint and has taken free-text action verbs without incident) — a permanent fix, not a one-time backfill: any future action verb a developer chooses is valid immediately, with no migration required, closing this entire class of bug rather than just today's 20 instances.

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

## shared/fx_rate.py + shared/ssl_context.py (added 2026-09-19)

`shared/fx_rate.py` centralizes "the USD/NGN dollar rate" — previously four
independent `tenant_config['dollar_rate']` readers (`tenant_management`,
`billing`, `claims`, `refunds`), each with its own default-if-missing logic.
The rate itself changed source: instead of a value a tenant_admin types in,
the base rate is fetched live from Bybit's public P2P USDT/NGN order book,
and a tenant only controls a markup (percentage or flat ₦) on top of it. See
`07_api_tenant_management.md`'s Dollar Rate section for the full fetch/
cache/fallback design (Redis `DistributedCache`, a circuit breaker via
`shared/circuit_breaker.py`, and a `platform_settings`-persisted last-known-
good fallback) and `00_MASTER_PLAN.md` for the feature's rollout, including
a real bug caught live (raw `Decimal` values breaking `rate_history`'s
`json.dumps()`, since it has no `default=str` the way `shared/audit.py`'s
does).

Public surface:
- `get_effective_dollar_rate(tenant_id) -> dict` — the one function every
  consumer should call. `{"rate", "base_rate", "markup_type",
  "markup_value", "source", "fetched_at", "markup_updated_at"}`.
- `get_base_market_rate() -> dict` — platform-wide, not tenant-scoped.
- `compute_effective_rate(base_rate, markup_type, markup_value) -> Decimal` —
  pure, exhaustively unit-tested (`tests/unit/test_fx_rate.py`).
- `fetch_bybit_ngn_rate() -> Decimal` — the actual HTTP call, `urllib`-based
  like `services/payment_release/paystack.py`, mean of the 5 cheapest online
  sell-USDT ads (`side="1"` — verified live to be the cheaper, best-first
  side of Bybit's order book).

`shared/ssl_context.py::verified_ssl_context()` is a small extraction out of
`paystack.py` (which had its own private `_ssl_context()` doing the exact
same certifi-preferring, verification-never-disabled thing) — `fx_rate.py`
needed the identical helper, and two real call sites justified sharing it
rather than a second copy. `paystack.py` now imports it too.

## shared/cbm_rate.py (added 2026-09-20)

Mirrors `shared/fx_rate.py`'s role: the one place `services/billing` reads
tenant CBM-pricing config from, via a direct `tenant_config` SQL read rather
than importing `services.tenant_management`'s repository. Unlike the dollar
rate, there's no external fetch/cache/circuit-breaker here — the CBM rate is
entirely tenant-configured, not sourced from a market.

Lets a tenant admin choose (1) the currency the rate is priced in (USD or
NGN) and (2) whether it's one flat rate or three separate carton/bag/bale
rates — modeled as **one code path, not two**: "flat" is simply the state
where `carton_rate == bag_rate == bale_rate`; nothing in `compute_cbm_charge`
branches on a `rate_mode` flag.

Public surface:
- `normalize_package_unit(unit: str | None) -> str` — maps a free-text
  `packing_list_item.package_unit` to `"carton"`, `"bag"`, or `"bale"`; only
  an exact (case-insensitive) match for "bag"/"bale" gets its own bucket,
  everything else (carton, pallet, item, mixed, unspecified, null, or any
  future free-text value) folds into `"carton"`.
- `get_cbm_rate_config(tenant_id) -> dict` — `{"currency", "rate_mode",
  "carton_rate", "bag_rate", "bale_rate", "effective_from"}`.
  Backward-compatible at read time with the pre-2026-09-20 single-rate shape
  (`{"rate_usd": ...}`, from any tenant provisioned before this feature) and
  with a missing/never-configured row (defaults all three rates to 0, which
  the caller's skip-guard treats the same as today's "missing rate → skip
  billing" behavior) — no data migration needed for either case.
- `compute_cbm_charge(cbm_by_unit: dict[str, Decimal], config: dict) -> dict`
  — pure, exhaustively unit-tested (`tests/unit/test_cbm_rate.py`). Buckets
  CBM by `normalize_package_unit`, prices each bucket at its own rate,
  rounds each bucket's subtotal to 2dp *before* summing (so a displayed
  breakdown always sums exactly to the displayed total). Returns
  `{"amount": Decimal, "currency": str, "breakdown": {"carton": {"cbm",
  "rate", "subtotal"}, "bag": {...}, "bale": {...}}}`.

See `07_api_tenant_management.md`'s CBM Rate section and `11_api_billing.md`'s
Billing Calculation section for the full design, including how `billing`'s
pre-existing `cbm_rate_usd` column stays exact (no new rounding drift) for
the common case where the tenant's three rates are all equal, and only
falls back to a blended average when they genuinely differ.

## shared/url_safety.py (added 2026-09-23)

SSRF defence for outbound calls to **tenant-supplied** URLs — today only the
tenant webhook (`shared/webhook.py`). A tenant admin controls
`webhook_config.endpoint_url`, and the Lambda that fetches it runs inside the
VPC next to Aurora and Redis. The old guard, a `^https://` regex on the
request model, still allowed `https://169.254.169.254/...`,
`https://10.x.x.x/...`, `https://localhost/...`, any hostname whose DNS record
points at those, and any public server that answers with a redirect to one
(`urllib` follows redirects). `test_fire_tenant_webhook` also returned
`str(exc)`, turning connect errors into a port-scan oracle.

Three layers, each usable on its own:

| Function | Layer | Notes |
|---|---|---|
| `validate_public_https_url(url) -> (host, port)` | Syntactic, no I/O — safe in a Pydantic validator | https only; no embedded credentials; rejects `localhost`, `.local`/`.internal`/`.lan`/`.home.arpa`; IP literals must be globally routable, **including** the legacy numeric IPv4 forms a resolver accepts but `ipaddress` rejects (`2130706433`, `0x7f.1`, `127.1`) and IPv4-mapped IPv6 (`::ffff:10.0.0.1`) |
| `resolve_public_ips(host, port) -> list[str]` | Delivery-time DNS check | Refuses if **any** resolved address is non-public — a multi-record answer is not accepted because one record is public. Re-run at delivery since DNS changes after save |
| `open_public_https(req, timeout)` | `urlopen` replacement | Validates, resolves, then connects to the exact validated IP (TLS SNI + certificate verification stay on the original hostname, so a wrong-host cert still fails), ignores proxy env vars, and refuses redirects (a 3xx surfaces as `HTTPError`) so nothing can swap the target after the check |

`UnsafeUrlError` (a `ValueError`) is raised before any connection is made.
`WebhookConfigRequest.endpoint_url` runs the syntactic layer at save time;
`shared/webhook.py` uses `open_public_https` for both `fire_tenant_webhook`
(still never raises) and `test_fire_tenant_webhook` (returns the
`UnsafeUrlError` message rather than a raw socket error). Verified against
real TLS: pinned-IP delivery to a public endpoint succeeds, a redirect to the
metadata address is refused, private/localhost targets are blocked, and a
hostname-mismatched certificate still fails verification.

Any future outbound call to a URL a tenant or customer can influence must go
through this module — see `00_CROSS_CUTTING_STANDARDS.md` §8.4. Fixed-URL
provider calls (Paystack, Bybit, Africa's Talking, Meta, JWKS) do not need it.

## shared/validation.py — safe_filename() (added 2026-09-23)

`safe_filename(name, *, default=None, max_length=100) -> str` reduces a client-supplied upload name to something safe to
embed in an S3 key and in a `Content-Disposition` value: directory components (`/` and `\\`) dropped; every character
outside Unicode word characters, `.`, `(`, `)`, space and `-` replaced with `_` (this removes quotes, semicolons,
CR/LF/NUL and bidi-override characters such as U+202E, which renders `fdp.exe` as `exe.pdf`, while keeping CJK names);
leading/trailing dots and spaces stripped (no hidden `.`/`..`); length capped with the extension preserved. A non-string
or unusable name raises `ValidationError` (`422`) unless `default=` is given — the download paths pass a default
(`"evidence"` / `"document"`) because rows written before the fix may hold an unsafe stored name.

Used by the four presigned-upload flows — `claims.generate_presigned_url`, `manifest.generate_evidence_upload`,
`tracking.generate_document_presigned_url`, `payment_release.generate_payment_claim_upload_url` — and by the two
`ResponseContentDisposition` builders (payment-claim evidence, container documents). `services/excel` builds its own
export names from a `_safe_name` helper over server-controlled values and is unaffected.

## shared/providers/ — cloud-portability ports (added 2026-10-05)

Ports-and-adapters layer that keeps `services/` and the rest of `shared/` free of cloud SDKs, so ShipX can be
deployed to **AWS or Azure** by switching one env var. The active cloud is `CLOUD_PROVIDER` (`aws` default | `azure`),
read once in `shared/providers/__init__.py`.

- **`shared/providers/base.py`** — the interfaces (`typing.Protocol`):
  - `KeyProvider` — envelope-encryption key ops (`generate_data_key` / `decrypt_data_key`). Consumed by
    `shared/encryption.py`; AWS adapter `shared/providers/aws/kms.py` (`KmsKeyProvider`).
  - `StorageProvider` — object storage (`presigned_get_url`, `presigned_upload`, `put_object`, `get_object`,
    `object_size`, `delete_prefix`). AWS adapter `shared/providers/aws/s3.py` (`S3StorageProvider`). `presigned_upload`
    returns an `UploadTicket` (`url`, `method="PUT"`, `headers`) — the **cloud-neutral PUT upload contract** both S3
    (presigned PUT) and Azure Blob (SAS PUT) satisfy, replacing the old S3 presigned-POST `{url, fields}` form. Its
    `.as_response()` is spread into every presigned-upload endpoint's JSON (`{upload_url, upload_method, upload_headers}`).
  - `SecretsProvider` — `get_secret(secret_id) -> str` returning the raw secret string (callers that store JSON parse
    it themselves). AWS adapter `shared/providers/aws/secrets.py` (`SecretsManagerProvider`); Azure → Key Vault secrets.
    Consumed by `shared/db.py` (DB password), `services/tenant_management/impersonation.py` (HS256 signing key),
    `services/migrate/handler.py` (DB password for Alembic).
  - `EventProvider` — `publish(source, detail_type, detail, bus_name)`; raises `ExternalServiceError` on delivery
    failure. The envelope (event_id / occurred_at / tenant_id / payload) is still built in `shared/events.py`; only the
    delivery is cloud-specific. AWS adapter `shared/providers/aws/eventbridge.py` (`EventBridgeProvider`, `put_events` +
    `FailedEntryCount` handling); Azure → Event Grid.
  - `QueueProvider` — `send(destination, body)` where `destination` is an opaque queue reference the caller resolves
    from config (SQS queue URL on AWS, Service Bus queue name on Azure). AWS adapter `shared/providers/aws/sqs.py`
    (`SqsQueueProvider`, `send_message`); Azure → Service Bus. Consumed by `shared/notifications.py`
    (`enqueue_notification` / event-notification fan-out) and `services/notification/service.py` (SMS fallback + retry).
  - `EmailProvider` — `send(sender, to_email, subject, html_body, text_body)`; raises on hard failure so the caller's
    log/retry path runs. AWS adapter `shared/providers/aws/ses.py` (`SesEmailProvider`, SES `send_email`); Azure →
    Communication Services. Consumed by `services/notification/service.py::send_email`.
  - `IdentityProvider` — user/role provisioning (14 methods: create/create-with-password, update attrs, enable/disable,
    global sign-out, resend-invite, reset-password, group create/add/remove/list, `sync_user_groups`). AWS adapter
    `shared/providers/aws/cognito.py` (`CognitoIdentityProvider`, the former `cognito_client.py`, byte-identical);
    Azure → Entra/MS Graph. Consumed by `services/tenant_management/service.py`. This is the **management** side of
    identity only; the authN side (JWT verify + claim shape) is separate — see **ADR-004**. Phase 1 of that ADR.
  - `ClaimsMapper` — reads ShipX's logical identity fields (`user_id`, `tenant_id`, `groups`, `primary_role`) out of a
    verified JWT's raw claims. Only the claim *names/shape* are cloud-specific (Cognito `sub`/`custom:tenant_id`/
    `cognito:groups`/`custom:role`); the `{tenant_id}:{role}` interpretation + `platform_admin` + primary-role fallback
    stay in `shared/auth.py`. AWS adapter `shared/providers/aws/cognito_claims.py` (`CognitoClaimsMapper`, holds the
    `cognito:groups` bracket-parsing); Azure → Entra (normalizes its role claims into the same `{tenant_id}:{role}`
    canonical form so `auth.py` never changes). Consumed by `shared/auth.py`. **ADR-004 Phase 2.**
    - `EntraClaimsMapper.groups()` closes the Cognito↔Entra gap (ADR-004 addendum 2026-10-11): Entra emits
      *cloud-only* group membership as object ids (GUIDs), not `{tenant_id}:{role}` names, so it accepts three shapes —
      canonical names pass through; object ids are mapped via `ENTRA_PLATFORM_ADMIN_GROUP_ID` / `ENTRA_GROUP_ID_MAP`;
      and the canonical group is **synthesized** from the `tenant_id` + `role` optional claims (`ENTRA_TENANT_ID_CLAIM` /
      `ENTRA_ROLE_CLAIM`), the primary policy-free path. Provisioned by `scripts/setup_entra_platform_admin.sh`.
    - `EntraClaimsMapper.tenant_id()` **derives** `PLATFORM` from `platform_admin` membership when no tenant claim is
      present — Entra External ID (CIAM) does not emit app-manifest directory-extension optional claims, so a real CIAM
      token often carries only the `platform_admin` group GUID; a platform admin is tenant-less by invariant, so the
      group that grants the role also fixes the scope (just set `ENTRA_PLATFORM_ADMIN_GROUP_ID`). Tenant-scoped users
      still need an explicit tenant claim.
    - **Tenant users on CIAM** get that claim from the **custom authentication extension** (ADR-004): a standalone
      Container App (`services/entra_token_claims/` on the shared image via the `claims` entrypoint, in Terraform
      `modules/container_app` — Functions aren't an option: App Service quota is 0) injects `tenant_id` + `role` at
      token issuance, read from **`tenant_user` in the ShipX DB** by the Entra `oid` (→ the globally-unique
      `cognito_sub`, stamped by `migrate_users_to_entra.py`). No Graph permission — a DB read, in-VNet and
      least-privilege; email is not used as the key (unique only per tenant).
- **Factories** (`shared/providers/__init__.py`):
  - `get_key_provider()` → `KeyProvider | None` (None = field encryption not configured; preserves the dev
    plaintext-fallback in `shared/encryption.py`).
  - `get_storage_provider(bucket=None)` → `StorageProvider`, cached per bucket. `None` resolves the default assets
    bucket (`S3_BUCKET_NAME`); an explicit name is used for the GDPR `TENANT_DATA_BUCKET` purge in
    `services/scheduled/data_cleanup.py`.
  - `get_secrets_provider()` → `SecretsProvider` (cached singleton).
  - `get_event_provider()` → `EventProvider` (cached singleton).
  - `get_queue_provider()` → `QueueProvider` (cached singleton).
  - `get_email_provider()` → `EmailProvider` (cached singleton).
  - `get_identity_provider()` → `IdentityProvider` (cached singleton).
  - `get_claims_mapper()` → `ClaimsMapper` (cached singleton).
- **Migrated call sites** (no longer touch `boto3` directly): storage — `services/manifest`, `services/excel`,
  `services/claims`, `services/payment_release`, `services/tracking`, `services/scheduled/data_cleanup`; secrets —
  `shared/db.py`, `services/tenant_management/impersonation.py`, `services/migrate/handler.py`; events — `shared/events.py`;
  queue — `shared/notifications.py`, `services/notification/service.py`; email — `services/notification/service.py`;
  identity (user/role mgmt) — `services/tenant_management/service.py` (the former `cognito_client.py` moved to the AWS
  adapter and was deleted); claim reading — `shared/auth.py` (Cognito claim names now behind `ClaimsMapper`).
  `delete_prefix` encapsulates the version-aware S3 purge (current objects + non-current versions + delete-markers) for
  GDPR Art. 17 immediate erasure.
- **Azure adapters:** `shared/providers/azure/blob.py` (`BlobStorageProvider`) is **implemented and Azurite-tested**
  (`tests/unit/test_azure_blob_provider.py` — real SAS PUT/GET round-trips; the upload ticket carries the Azure-required
  `x-ms-blob-type: BlockBlob` header so the frontend's one PUT path works unchanged). `shared/providers/azure/servicebus.py`
  (`ServiceBusQueueProvider`) is implemented and **mocked-SDK tested** (`tests/unit/test_azure_servicebus_provider.py` —
  verifies real `ServiceBusMessage` construction + queue targeting; Service Bus's emulator needs a SQL Edge sidecar and
  is arm64-finicky, so full e2e is a follow-up). `shared/providers/azure/keyvault.py` (`KeyVaultKeyProvider`, envelope via RSA-OAEP key wrap/unwrap — Key Vault has no
  KMS-style data-key gen, so the 32-byte key is generated locally and wrapped) and `azure/keyvault_secrets.py`
  (`KeyVaultSecretsProvider`) are implemented and **mocked-SDK tested** (`tests/unit/test_azure_keyvault_provider.py` —
  incl. a real `shared/encryption.py` Fernet-envelope round-trip with only the Key-Vault wrap stubbed). `shared/providers/azure/eventgrid.py` (`EventGridProvider`, EventBridge `detail_type`→Event Grid `event_type`,
  `source`→`subject`; normalizes SDK errors to `ExternalServiceError`) and `azure/acs_email.py` (`AcsEmailProvider`, ACS
  `begin_send`) are implemented and **mocked-SDK tested** (`tests/unit/test_azure_eventgrid_acs_providers.py`). The only
  remaining adapters are **identity** (`entra.py`, `entra_claims.py`) — ADR-004 phases 3–5, which need a real Entra
  tenant. All other azure branches resolve at call time only when `CLOUD_PROVIDER=azure`. Azure runtime deps are pinned
  as the `azure` optional-dependency extra in `pyproject.toml` (`uv sync --extra azure`); kept out of
  the default set so the AWS Lambda bundle stays lean.
- **Still on boto3 directly** (the authN *execution* remainder — see ADR-004 phases 3–5, which need an actual Azure
  tenant, not a code sweep): the authorizer's JWT/JWKS *verification* (`services/authorizer/handler.py` — env-driven
  `COGNITO_JWKS_URL`/`COGNITO_AUDIENCE`, ports by pointing at Entra's JWKS); token refresh
  (`services/auth/cognito_refresh.py`, `initiate_auth`/`revoke_token`); and the GDPR Cognito user-purge in
  `services/scheduled/data_cleanup.py` (`list_users` + `admin_delete_user`). The claim *shape* that used to live inline
  in `shared/auth.py` is now behind `ClaimsMapper` (Phase 2 done), so `auth.py` itself is cloud-agnostic. SQS/Service Bus
  and SES/ACS are consumed as
  *producers* via the ports above; the SQS **consumer** side is the Lambda event-source trigger
  (`services/notification/handler.py`, `services/metering/handler.py`) — on Azure that becomes a Functions Service Bus
  trigger binding, handled by the entry adapter, not a boto3 call.

## shared/observability.py — tracing shim (added 2026-10-05)

`init_tracing()` replaces the direct `from aws_xray_sdk.core import patch_all; patch_all()` that sat at module load in
all 19 Lambda entry points (every `services/*/handler.py` + the `services/scheduled/*` jobs). On AWS it calls
`patch_all()` (X-Ray instrumentation of boto3/psycopg2/requests, unchanged); on any other cloud it is a no-op, since
tracing there is wired at the platform level (e.g. Azure Application Insights auto-instrumentation) rather than
in-process. Selected by `CLOUD_PROVIDER` (from `shared/providers`). Call it once next to `setup_logging()` at module
load. This removes the hard `aws_xray_sdk` import from the handlers' startup path on non-AWS clouds.
- **Tests:** `tests/unit/test_encryption.py` (KeyProvider via a fake), `tests/unit/test_storage_provider.py`
  (S3StorageProvider against moto + the factory wiring).

**Trade-off recorded:** the S3 presigned-POST `content-length-range` enforced max upload size at the edge; a presigned
PUT cannot. Size is now enforced client-side (`useFileUpload.ts`) and should be re-verified server-side via
`StorageProvider.object_size` on any flow that gains a post-upload confirm step.

## shared/auth_verify.py + shared/http_routing.py — container compute edge (added 2026-10-09)

Added for the Azure Container Apps compute path (ADR-005); AWS behavior unchanged.

**`shared/auth_verify.py`** — bearer-token verification, extracted verbatim from the AWS Lambda
authorizer so the **same** logic backs both the authorizer (AWS) and the container's in-process
auth middleware (Azure). `build_authorizer_claims(token)` tries an OIDC RS256 JWT (JWKS-verified)
then a ShipX HS256 impersonation token, returning the flat, Cognito-shaped claims dict
(`sub`/`custom:tenant_id`/`cognito:groups` + impersonation markers) that `shared/auth.py`'s
`get_tenant_context` reads from `requestContext.authorizer`, or `None` to deny (401). The JWKS
endpoint/audience are read from `OIDC_JWKS_URL`/`OIDC_AUDIENCE`, falling back to
`COGNITO_JWKS_URL`/`COGNITO_AUDIENCE` (so AWS is unchanged; Entra points the `OIDC_*` vars at its
own JWKS in ADR-004 Phase 4). `services/authorizer/handler.py` is now a thin adapter over this.

**`shared/http_routing.py`** — the HTTP path→service route table + public-route set, extracted from
`scripts/local_server.py` so the dev server, the container HTTP app, and (by mirroring) production
API Gateway share **one** source of truth. `resolve_service(path)` returns the handling service
module (with the excel export/pdf/import and container-sub-resource and platform-usage special
cases); `is_public_route(method, path)` matches the no-JWT routes (`local.public_routes` in the
api-gateway module); `invoke_handler(service, event)` lazily imports and calls the handler.
`local_server.py` now imports these instead of its own duplicated copy.

- **Tests:** `tests/unit/test_auth_verify.py` (9 — both token strategies, groups-list flattening,
  env precedence/fallback), `tests/unit/test_http_routing.py` (19 — every routing special case +
  public-route matching), both fully mocked.

## services/http_app/ + services/queue_worker/ + services/scheduled/run.py — container workloads (added 2026-10-09)

The container entry points (ADR-005). One image (`Dockerfile`), workload chosen by the entrypoint
arg (`docker-entrypoint.sh`: `api` / `worker` / `job` / `migrate`):

- **`services/http_app/app.py`** — the production WSGI app (gunicorn), the cloud-neutral sibling of
  `scripts/local_server.py`. Verifies a real token via `shared/auth_verify.py` (no `X-Role` dev
  shim), gates public vs authenticated routes via `shared/http_routing.py`, builds the
  API-Gateway-v2 event, and dispatches. Runs gunicorn **processes, 1 thread each** (the `shared/db.py`
  connection singleton is not thread-safe — see the single-threaded dev-server note above).
- **`services/queue_worker/worker.py`** — Service Bus consumer, the Azure analogue of AWS's SQS →
  Lambda event sources. One worker per queue (`--queue sms|whatsapp|email|metering`); wraps each
  message into a single-record SQS-shaped event and calls the **same** handler the Lambda event
  source would (`notification.handler.{sms,whatsapp,email}_handler`, `metering.handler.lambda_handler`).
- **`services/scheduled/run.py`** — Container App Jobs cron runner; `--job <name>` invokes the
  matching `services/scheduled/*` `lambda_handler` once and exits 0/1 (mirrors the EventBridge rules).

- **Tests:** `tests/unit/test_http_app.py` (8), `tests/unit/test_queue_worker.py` (7),
  `tests/unit/test_scheduled_run.py` (5) — fully mocked (no gunicorn, Service Bus, JWKS, or DB).
  Build/run verified locally: `docker build` + the api container serves `/health` 200 and gates
  `/v1/*` to 401 without a token.

## shared/db.py + shared/distributed_cache.py — Azure connection portability (added 2026-10-09)

Two small, backward-compatible runtime additions so the Phase-3 Container Apps can reach the
Azure data layer (Postgres Flexible Server + Azure Cache for Redis), both of which mandate TLS —
AWS/local behavior is unchanged (the new env vars default to the old posture):

- **`shared/db.py`** — `sslmode` now honours an explicit `DATABASE_SSLMODE` env (Container Apps
  sets `require`); otherwise the previous default stands (`require` when `DB_SECRET_ARN` is set,
  else `prefer`). Azure has no `DB_SECRET_ARN`, so this is how it gets TLS.
- **`shared/distributed_cache.py`** — the redis client now passes `password` (from
  `REDIS_PASSWORD`) and `ssl` (from `REDIS_SSL=true`). Both default off → AWS ElastiCache
  (in-VPC, plain TCP, no auth) and local Redis connect exactly as before; Azure Redis Basic
  (public, TLS + access key) now works.

- **Tests:** `tests/unit/test_db_connection_healing.py::TestSslMode` (3) and
  `tests/unit/test_distributed_cache.py` (3) — assert the connection kwargs for the AWS/local vs
  Azure env, fully mocked.

## shared/providers/azure/entra.py + entra_claims.py — Entra identity (added 2026-10-09)

The Azure side of the `IdentityProvider` + `ClaimsMapper` ports (ADR-004 Phase 4). The factory in
`shared/providers/__init__.py` already selected these paths; this fills them in.

- **`EntraIdentityProvider`** (`entra.py`) — the 14 `IdentityProvider` methods over **Microsoft
  Graph** (v1.0). Auth is a bearer token from `azure-identity` `DefaultAzureCredential` (the
  Container Apps managed identity in prod); Graph calls go over **stdlib `urllib`** so no HTTP
  dependency is added. Roles are **security groups** named `{tenant_id}:{role}` — the faithful
  Cognito mirror, so `sync_user_groups`'s reconcile logic is byte-identical. Users are created with
  a `passwordProfile` (`forceChangePasswordNextSignIn`) — the invite/reset analogue (Entra has no
  Cognito-style invite email out of the box; the migration script + tenant SSPR config drive the
  email). `username` is the UPN/email, resolved to the Graph object id as needed. Errors normalize
  to the same exceptions as Cognito: 409 → `DuplicateResourceError`, else `ExternalServiceError("Entra", …)`.
- **`EntraClaimsMapper`** (`entra_claims.py`) — reads `oid`/`sub` (user id), a configurable tenant
  claim (`ENTRA_TENANT_ID_CLAIM`, default `tenant_id`), the `groups` claim normalized to
  `{tenant_id}:{role}` names, and a configurable role claim (`ENTRA_ROLE_CLAIM`, default `role`).
  The downstream interpretation stays in `shared/auth.py`, unchanged. (Entra must be configured to
  emit group *display names* in the token — documented in the Phase-4 checklist.)
- **Tests:** `tests/unit/test_entra_claims.py` (7) and `tests/unit/test_entra_identity_provider.py`
  (8) — fully mocked (stubbed Graph / token + urlopen); cover the claim shapes, the group-sync
  reconcile, create-user flows, 409→duplicate error mapping, factory selection, and the
  `AUTH_PROVIDER` decoupling. Real end-to-end needs an Entra tenant (see the ADR-004 / Phase-4
  checklist). The bulk user migration is `scripts/migrate_users_to_entra.py`.

**`AUTH_PROVIDER` — auth cloud decoupled from infra cloud (added 2026-10-10).** `get_identity_provider()`
and `get_claims_mapper()` now select on `AUTH_PROVIDER` (default `CLOUD_PROVIDER`), not `CLOUD_PROVIDER`
directly. This is the ADR-004 dual-run seam: run compute + data on Azure (`CLOUD_PROVIDER=azure`)
while auth stays on Cognito (`AUTH_PROVIDER=aws` + `OIDC_JWKS_URL`/`OIDC_AUDIENCE` pointed at the
Cognito pool) — so the Azure API validates Cognito JWTs with the Cognito claims mapper. Default
behavior is unchanged (unset → equals `CLOUD_PROVIDER`).

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

