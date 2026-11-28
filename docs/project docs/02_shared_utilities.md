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

@contextmanager
def tenant_transaction(tenant_id: str) -> Iterator[cursor]:
    """Atomic multi-statement unit of work where later statements depend on earlier results.

    Sets the RLS variable once; commits on normal exit, rolls everything back if the block raises.
    Use instead of `execute_transaction` when a statement needs a value returned by a previous one.
    """
    ...

def next_tenant_counter(cursor: cursor, tenant_id: str, name: str) -> int:
    """Atomically take the next value of a per-tenant named counter (`invoice`, `receipt`, `release_note`).

    Replaces `SELECT COUNT(*) + 1`, which gave two simultaneous requests the same number. Backed by the
    `tenant_counter` table (migration 062); call it inside `tenant_transaction` so a failed insert rolls the
    increment back and leaves no gap.
    """
    ...
```

**Composable (2026-11-14).** Inside a `tenant_transaction` block every `execute_with_tenant` / `execute_write_with_tenant` /
`execute_transaction` call *for the same tenant* runs on the block's cursor and leaves committing to the block, so existing
repository functions can just be called inside it and commit or roll back together. A query for a *different* scope
(PLATFORM lookups, `log_audit`) inside the block raises, because `SET LOCAL` would otherwise silently widen the scope for
every later statement; do those reads first and `log_audit` / `publish_event` / notifications after the block. A nested block
for the same tenant joins the outer one. `take_tenant_counter(tenant_id, name)` takes a counter value in its own transaction
(unique, may skip a number) for callers that need the number before the row exists.

`shared/billing_money.py` is where an invoice's total changes: `adjust_billing` (relative total/misc delta, status recomputed
for the four money statuses; since 2026-11-17 the total is floored at zero and the row returned carries
`total_before_ngn`, so `new_overpayment` can count a reduction past zero as money owed to the customer), `lock_billing` (`SELECT … FOR UPDATE`), `new_overpayment` and
`adjust_billing_and_refund_overpayment` (opens a refund for any *new* excess only). Use these instead of writing
`UPDATE billing SET total_ngn = …` by hand.

**Rule:** any multi-step write that must succeed or fail as a whole (invoice + number + carryovers; payment + invoice
total + overpayment refund) goes through `tenant_transaction`. Separate `execute_write_with_tenant` calls each commit on
their own, so a failure between them leaves the books half-written.

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

- [x] `TenantContext` dataclass correctly parses JWT claims — it lives in `shared/tenant_context.py`, not `shared/auth.py` as a reader might assume from the surrounding items (noted 2026-11-11, after first looking in the wrong file).
- [x] `get_tenant_context()` raises `TenantSuspendedError` for suspended tenants
- [x] `get_tenant_context()` raises `AuthenticationRequired` for missing/invalid JWT
- [x] `db.py` always sets `SET LOCAL app.current_tenant_id` before queries
- [x] `db.py` uses connection reuse pattern (module-level `_connection` variable)
- [x] `responses.py` produces correct RFC 7807 format for all error types
- [x] `events.py` publishes to EventBridge with correct envelope including `tenant_id`
- [x] `pagination.py` handles cursor encoding/decoding and query building
- [x] All functions have type hints
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
    bucket (`S3_BUCKET_NAME`, which the AWS Lambdas are given since 2026-11-17: they were given `S3_BUCKET`, which
    nothing reads); an explicit name is used only when `TENANT_DATA_BUCKET` is set for the purge in
    `services/scheduled/data_cleanup.py`, which otherwise purges the assets bucket.
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


## `shared/app_urls.py` — absolute links for outbound notifications (2026-11-13)

One module resolving the base URL of every link sent to someone outside the
system. It exists because the resolution was previously duplicated per call
site, each reading its own environment variable, and one of those variables was
set in no environment at all:

- activation links read `APP_BASE_URL`, falling back to the origin of
  `ENTRA_REDIRECT_URI` — so Azure worked and AWS, which sets neither, would have
  emailed an empty link;
- customer invite links read `CUSTOMER_PORTAL_BASE_URL`, which **nothing** set —
  not AWS Terraform, not Azure Terraform, not `.env.local`, only `.env.example`.
  Every invite therefore went out as the bare path `/invite/<token>`.

### API

| Function | Returns |
|---|---|
| `app_base_url(*, override_env=None)` | `scheme://host`, no trailing slash |
| `activation_url(token)` | `{base}/activate/{token}` |
| `invite_url(token)` | `{base}/invite/{token}`, preferring `CUSTOMER_PORTAL_BASE_URL` |

Resolution order: `override_env` → `APP_BASE_URL` → the origin of
`ENTRA_REDIRECT_URI`. Staff and customers share one SPA
(`frontend/src/shell/routes.tsx` serves both routes), so one base URL serves
both; `CUSTOMER_PORTAL_BASE_URL` is an override for the day the customer portal
moves hosts, not a second thing to configure.

### Two deliberate refusals

**It raises `MissingBaseUrlError` rather than returning a relative URL.** A link
is the whole point of these messages: built from an empty base it produces a
notification that looks delivered, is recorded as delivered, consumes the
single-use token, and is useless to whoever receives it — with nothing anywhere
failing. Callers catch it, log at ERROR, and send nothing.

**A value that is set but relative is an error naming that variable**, not a
fall-through to the next candidate. Falling through would quietly send links to
whichever host happened to be configured elsewhere — a working link to the wrong
environment, which is worse than an error because nothing reports it.

Covered by `tests/unit/test_app_urls.py`.

## `shared/` additions — audit Phase 2 (2026-11-15)

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
| `shared/list_filters.py` | `billing_filter(tenant_id, filters)` and `container_filter(tenant_id, filters)`: the WHERE clause and bound parameters of the invoice and container lists, shared by the list queries and their exports so the two cannot disagree (2026-11-16). |
| `shared/pagination.py` | `build_paginated_query` now qualifies its id tiebreaker with the sort field's table alias (`b.created_at` gives `b.id`), and `extract_page`'s `sort_field` must be the column the query sorted by (2026-11-16: page 2 of every aliased, joined list failed on an ambiguous `id`, and a list sorted by another column built its cursor from `created_at`). See `11_api_billing.md`. |
| `shared/pickup_code.py` | Release-note pickup codes (ADR-008): `is_configured()`, `new_code()` (six digits, `secrets`), `hash_code(note_id, code)` (HMAC-SHA256 under `PICKUP_CODE_PEPPER`), `matches()` (constant time; ASCII digits only), `MAX_FAILED_ATTEMPTS = 5`. The plaintext must never be logged or stored. |

## `shared/` additions — tenant data export (audit BE-10, 2026-11-17)

- **`shared/tenant_data.py`** — the single inventory of tables holding a tenant's data, parent-first: `TENANT_TABLES` (each a `TenantTable(name, via=(fk_column, parent) | None, omit=…, decrypt=…)` with `select_sql()` / `delete_sql()`; names are checked to be plain SQL identifiers), `NOT_TENANT_DATA` (platform tables, with the reason), `redact_config(config_key, value)` (drops the webhook secret and the Paystack key), `table(name)`. The export reads it forwards, the cleanup deletes it backwards. `tests/unit/test_tenant_data.py` reads every migration and fails when a table is unaccounted for or the order breaks a foreign key: **add new tables here.**
- **`shared/tenant_export.py`** — the `tenant_offboarding_export` record: `export_prefix`, `object_key` (UUID-checked), `queue_export`, `latest_export`, `has_completed_export(tenant_id, since)`, `claim_next` (`SKIP LOCKED`), `mark_completed` / `mark_failed` / `mark_cancelled` (only from the right state), `cancel_open_exports`. `MAX_ATTEMPTS = 3`, `STALE_AFTER_MINUTES = 60`. PLATFORM scope throughout.
- **`shared/platform_audit.py`** — `insert_platform_audit(action, actor_id, target_tenant_id, details, ip_address)`, moved out of `services/tenant_management/repository.py` (which re-exports it) so platform jobs can write the platform trail.

## `shared/observability.py` — failure counters (audit OPS-04, 2026-11-17)

`record_failure(operation)` counts one failure that was caught and not re-raised; `record_outcome(operation, failed=)` counts an attempt and whether it failed (for a rate). Both write one log line through the normal JSON formatter in CloudWatch's Embedded Metric Format (namespace `ShipX`, dimensions `Environment` and `Operation`); on Azure the same line is queried in Log Analytics. Never raises. `operation` must be one of the fixed `OPERATIONS` (`invoice_generation`, `notification_enqueue`, `notification_send`, `audit_write`, `scheduled_job_step`, `tenant_deletion_refused`): a name is a billed metric dimension, so it is never built from data. The `shipx.metrics` logger is pinned at INFO so a higher `LOG_LEVEL` cannot switch the counts off. Called from `shared/audit.py`, `shared/platform_audit.py` (counts, then re-raises), `shared/notifications.py`, `services/billing` (invoice generation), `services/notification/service.py` (`log_sent` / `log_failed`), and the per-tenant and per-record catches of every scheduled job.

## `shared/uploads.py` — one set of upload rules (audit BE-12, 2026-11-17)

Every direct-to-storage upload goes through it: claim evidence, manifest evidence, payment-claim evidence, container documents and the packing-list import. `UploadPolicy(name, content_types, expires_in)` with three instances — `EVIDENCE` (JPEG, PNG, PDF; 1 h), `CONTAINER_DOCUMENT` (those plus WebP; 15 min), `SPREADSHEET_IMPORT` (`.xlsx`; 15 min), `TENANT_LOGO` (PNG, JPEG, WebP; 15 min; `max_bytes` 5 MB, the same as other uploads (owner decision 2026-11-24; was 1 MB); no SVG, which can carry script — FD-29). `policy.check_content_type(ct)` raises `BusinessRuleViolationError(rule_id="INVALID_CONTENT_TYPE")` and is called before any database read; `presign_upload(policy, tenant_id, segments, filename, ct)` checks again, builds `upload_key(...)` = `{tenant_id}/{segments...}/{safe_filename(filename)}` (the tenant ID must parse as a UUID; a segment that is empty or holds `/`, `\\` or `..` raises `ValueError`) and returns `PresignedUpload(key, expires_in, ticket)` with `as_response()`. A policy cannot be declared with `application/octet-stream`.

Changed behaviour: container documents no longer accept `application/octet-stream` (it let any file through the type check); the frontend now refuses a file the browser cannot type, in the upload dialog. ~~Known limits, not fixed here: no upload size is enforced anywhere (the per-service `_MAX_FILE_SIZE` constants were never read and are removed; runbook "Upload size is not limited"); the declared type binds the upload only on AWS S3 (SigV4) — an Azure SAS and the local Moto do not enforce it.~~ **Superseded 2026-11-17:** uploads are limited to 5 MB (`MAX_UPLOAD_BYTES`, every policy's `max_bytes`). `policy.check(content_type, size_bytes)` refuses a missing size (`ValidationError`) or one over the limit (`FILE_TOO_LARGE`) before any database work; `presign_upload(..., size_bytes)` passes it to the provider as `content_length`. `S3StorageProvider` uses SigV4 against real AWS (`Config(signature_version="s3v4")`; botocore's presign default can be SigV2, which signs nothing), so the URL signs `content-length;content-type;host` and S3 refuses a different size or type. Azure SAS cannot bind either, and local Moto uses SigV2: there, `check_stored_size(policy, key)` (missing → `UPLOAD_NOT_FOUND`, over → `FILE_TOO_LARGE`) guards where a file is used — payment-claim submit and both spreadsheet imports. ~~Evidence and container documents are not re-checked after upload on Azure.~~ **2026-11-19:** they are, by `confirm_stored_upload(policy, key)` at the new confirm routes (see below).

## `shared/encryption.py` — separator fix (2026-11-17)

`decrypt_field` now splits the token at the last `||` (`raw.rindex`), not the first: the wrapped key is binary and may contain `||`; the Fernet ciphertext cannot. Backward compatible with every stored token. See the runbook, "Encrypted fields that would not decrypt".

## Upload confirmation in `shared/uploads.py` (2026-11-19)

- `upload_key` now ends `{uuid4 hex}-{safe_filename}`: two uploads of one name to one record no longer share a key, so one cannot overwrite, or be deleted with, the other. `PresignedUpload.filename` carries the plain safe name for the row.
- `confirm_stored_upload(policy, key) -> int`: the stored size; nothing there → `UPLOAD_NOT_FOUND`; over `max_bytes` → the object is deleted, then `FILE_TOO_LARGE`. Used by the claim-evidence, manifest-evidence and container-document confirm routes.
- `StorageProvider.delete_object(key)` (S3: `delete_object`, the bucket's noncurrent-version rule purges the old version after 30 days; Azure: `delete_blob` with snapshots, a missing blob is not an error).

## Paging past empty sort values (2026-11-19)

**Ground-truth gap closed (found 2026-11-17):** `build_paginated_query` ignored a cursor whose sort value was NULL, so a list sorted by a column that is empty on some rows (invoices by billed date, with unbilled ones) restarted at page one once it reached them. Now every paginated list orders `NULLS LAST` in both directions, the cursor carries `sort_is_null: true` for an empty value, and the next page continues by id among the empty rows; a cursor on a real value also admits the empty rows after it. Visible change: empty values sort at the end even in descending order (Postgres had put them first). Applies to every list using `shared.pagination` (23 call sites). Tests: `tests/unit/test_pagination_walk.py::TestEmptySortValues` (walks page by page through SQLite; all 6 fail on the old code).

## `shared/` additions — platform admin audit Phase 0 (2026-11-28)

- **`shared/seats.py`**, `staff_seat_condition(alias="tenant_user")`: the one SQL rule for a staff seat (an active user who is not a customer portal account). It is used by the quota check, the tenant's plan page, the platform tenant list, the platform dashboard and metering's Usage tab (PA-03). `alias` must be a plain identifier, or it raises `ValueError`.
- **`shared/exceptions.py`**, `MaintenanceModeError`: a 503 with `error_code="MAINTENANCE_MODE"`, raised by `shared/auth._check_maintenance_mode` so the apps can show a maintenance screen (PA-01). It subclasses `ServiceUnavailableError`, so existing handling is unchanged.
- **`shared/platform_audit.py`**, `PlatformAuditAction` (StrEnum): every `action` value written to `platform_audit_log`. `tests/unit/test_platform_audit_actions.py` keeps it in step with the code and with `frontend/src/api/platformAuditActions.ts` (PA-05).
- **`shared/platform_roles.py`** (Phase 1, 2026-11-28): `PlatformRole` (`owner|admin|support|finance`), `PlatformPermission` (`read|tenant_lifecycle|support|plans|settings|admins|approve`), `ROLE_PERMISSIONS`, `APPROVER_ROLES` (owner, admin) and `permissions_for(role)` (an unknown role grants nothing). The one place that says what a platform role may do.
- **`shared/platform_identity.py`** (Phase 1b): `platform_issuer()`, `platform_pool_id()`, `platform_client_id()`, `is_platform_pool_token(claims)` (by verified `iss`), `mfa_required()` (`PLATFORM_MFA_REQUIRED`) and `token_shows_mfa(claims, auth_provider)` (AWS: the platform pool; Entra: `amr` or `acrs`). `CognitoClaimsMapper` reads a platform-pool token as `PLATFORM` / `platform_admin`; `shared.auth` raises `PlatformMfaRequiredError` (403 `PLATFORM_MFA_REQUIRED`) when MFA is required and missing; `auth_verify.verify_oidc_jwt` falls back to the platform pool's keys; `shared.providers.get_platform_identity_provider()` returns a `CognitoIdentityProvider(user_pool_id=…)` bound to the platform pool (the ordinary provider on Entra).
- **`shared/job_runs.py`** (Phase 1c): `tracked_job(job)` decorator for scheduled handlers, writing one `job_run` row per run (best effort), and `count_result(result) -> (items, failures)`.
- **`shared/platform_directory.py`**: `resolve_platform_caller(subject, email, name) -> (platform_user_id, role)`, called by `shared.auth.get_tenant_context` for every platform request (through `shared.auth._resolve_platform_caller`, which test suites stub). Binds a console invite on first request, binds a seeded invite by email, bootstraps the first owner while there is none (advisory lock), refuses a disabled row (`PlatformAdminDisabledError`, 403) or a stranger (`PlatformAdminNotEnrolledError`, 403), and fails closed (503) when the directory cannot be read. 30-second Redis cache; `evict_platform_caller(subject)` after a change.
- **`shared/tenant_context.py`**: `TenantContext` gains `platform_user_id` and `platform_role`, and `has_platform_permission()` / `assert_platform_permission()` (False for any non-platform context).
- **`shared/auth.py`**: resolves platform callers as above, and `_assert_platform_write_outside_console` refuses a support or finance admin any write outside `/v1/platform` and `/v1/tenants`.
- **`shared/platform_audit.py`**: `insert_platform_audit(..., *, before_state=None, after_state=None)` stores both plus the bound `request_id`; `PlatformAuditAction` gains the directory, step-up and approval actions.
- **`shared/platform_mail.py`**: `send_platform_email(to, subject, text)` for approval and owner notices; honours the non-production allowlist, never raises.
- **`shared/logging_config.py`**: `current_request_id()` returns the bound request id.
- **`shared/exceptions.py`**: `PlatformAdminNotEnrolledError` (403 `PLATFORM_ADMIN_NOT_ENROLLED`) and `StepUpRequiredError` (403 `STEP_UP_REQUIRED`).
