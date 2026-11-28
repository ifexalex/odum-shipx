# Task 20 — Metering & Usage Service Implementation

## Objective

Implement the Metering Lambda service that consumes `UsageRecorded` events from the SQS metering queue, writes usage data to the `usage_record` table, and enforces per-tenant tier limits. Also implement the usage data retrieval for the Platform Admin dashboard.

## Depends On

- Task 06 (shared layer), Task 04d (SQS metering queue), Task 04e (metering Lambda)

## Architecture

```
Any service action
  → publishes UsageRecorded event to EventBridge
    → EventBridge routes to SQS metering queue
      → Metering Lambda consumes, writes to usage_record table

Tier limit checks:
  → Called inline by other services BEFORE performing limited actions
  → Read from usage_record + real-time counter
```

## Files to Create

```
services/metering/
├── __init__.py
├── handler.py          # SQS event consumer + API handler for usage queries
├── service.py          # Usage recording, aggregation, limit checking
├── repository.py       # usage_record table queries
└── models.py           # Already partially defined in Task 03
```

## Two Trigger Modes

### 1. SQS Consumer (async — records usage events)

Triggered by SQS `logistics-metering-{env}` queue. Processes batches of `UsageRecorded` events.

**SQS message body:**
```json
{
  "tenant_id": "uuid",
  "metric_type": "containers_processed",
  "value": 1,
  "occurred_at": "2026-02-22T10:30:00Z"
}
```

**Processing:**
1. Parse SQS batch (up to 10 messages per invocation)
2. For each message:
   - Validate metric_type is one of: `api_calls`, `containers_processed`, `storage_bytes`, `users_active`, `sms_sent`, `whatsapp_sent`, `emails_sent`
   - Determine period_start and period_end (current day or month depending on metric)
   - UPSERT into `usage_record`: increment existing record or insert new one
3. Acknowledge successful messages, fail individual messages on error (partial batch failure)

**UPSERT query:**
```sql
INSERT INTO usage_record (tenant_id, metric_type, value, period_start, period_end, recorded_at)
VALUES (:tenant_id, :metric_type, :value, :period_start, :period_end, NOW())
ON CONFLICT (tenant_id, metric_type, period_start)
DO UPDATE SET value = usage_record.value + EXCLUDED.value, recorded_at = NOW();
```

**Note:** This requires adding a unique constraint to `usage_record`:
```sql
ALTER TABLE usage_record ADD CONSTRAINT uq_usage_tenant_metric_period 
  UNIQUE (tenant_id, metric_type, period_start);
```
Include this in a migration file as part of this task.

### 2. API Handler (sync — serves usage queries)

Triggered by API Gateway for Platform Admin usage endpoints.

| Method | Path | Roles |
|---|---|---|
| GET | `/v1/platform/tenants/{id}/usage` | platform_admin |

**GET /platform/tenants/{id}/usage response:**
```json
{
  "data": {
    "tenant_id": "uuid",
    "period": "2026-02",
    "subscription_tier": "starter",
    "limits": {
      "users": { "used": 8, "max": 10 },
      "containers_per_month": { "used": 4, "max": 5 },
      "storage_gb": { "used": 2.3, "max": 5.0 }
    },
    "api_calls": 12450,
    "notifications": {
      "sms_sent": 340,
      "whatsapp_sent": 280,
      "emails_sent": 95
    }
  }
}
```

## Tier Limits & Enforcement

### Limit Definitions (from backend spec §3.5)

| Metric | Starter | Business | Enterprise |
|---|---|---|---|
| Users (active) | 10 | 50 | Unlimited |
| Containers/month (new) | 5 | 25 | Unlimited |
| Storage (GB) | 5 | 25 | Unlimited |

### Enforcement Functions (called by other services)

```python
# services/metering/service.py

TIER_LIMITS = {
    "starter": {"users": 10, "containers_per_month": 5, "storage_gb": 5},
    "business": {"users": 50, "containers_per_month": 25, "storage_gb": 25},
    "enterprise": {"users": 999999, "containers_per_month": 999999, "storage_gb": 999999},
}

def check_user_limit(tenant_id: str) -> None:
    """Check if tenant can create another user. Raises UsageLimitExceededError if not."""
    tenant = get_tenant(tenant_id)
    limits = TIER_LIMITS[tenant["subscription_tier"]]
    current_users = count_active_tenant_users(tenant_id)
    if current_users >= limits["users"]:
        raise UsageLimitExceededError("users", current_users, limits["users"])

def check_container_limit(tenant_id: str) -> None:
    """Check if tenant can create another container this month. Raises UsageLimitExceededError if not."""
    tenant = get_tenant(tenant_id)
    limits = TIER_LIMITS[tenant["subscription_tier"]]
    current_month_containers = count_containers_created_this_month(tenant_id)
    if current_month_containers >= limits["containers_per_month"]:
        raise UsageLimitExceededError(
            "containers_per_month", current_month_containers, limits["containers_per_month"]
        )

def check_storage_limit(tenant_id: str, additional_bytes: int) -> None:
    """Check if tenant can upload more files. Raises UsageLimitExceededError if not."""
    tenant = get_tenant(tenant_id)
    limits = TIER_LIMITS[tenant["subscription_tier"]]
    current_storage_gb = get_tenant_storage_usage_gb(tenant_id)
    new_total = current_storage_gb + (additional_bytes / (1024 ** 3))
    if new_total > limits["storage_gb"]:
        raise UsageLimitExceededError(
            "storage_gb", round(current_storage_gb, 2), limits["storage_gb"]
        )
```

### Where Limits Are Checked

| Action | Service | Limit Check |
|---|---|---|
| Create tenant user | Task 07 (tenant_management) | `check_user_limit()` |
| Create container | Task 10 (tracking) | `check_container_limit()` |
| Upload file (presigned URL) | Task 12 (claims) | `check_storage_limit()` |

These services import and call the metering check functions directly (synchronous, not via events).

### Container Counting Rule

From the backend spec: "In-progress containers (status ≠ 'fully_released') are NOT counted against the limit; only **newly created** containers in the current calendar month count."

```sql
SELECT COUNT(*) FROM container
WHERE tenant_id = :tenant_id
AND date_trunc('month', created_at) = date_trunc('month', NOW());
```

### Storage Usage Calculation

Query S3 prefix size for tenant (or maintain a running total in usage_record):

```python
def get_tenant_storage_usage_gb(tenant_id: str) -> float:
    """Get total S3 storage for tenant prefix."""
    # Option A: Query usage_record for latest 'storage_bytes' metric
    # Option B: Use S3 ListObjects to sum sizes (expensive, cache result)
    result = execute_with_tenant(tenant_id,
        "SELECT value FROM usage_record WHERE tenant_id = %(tid)s "
        "AND metric_type = 'storage_bytes' ORDER BY recorded_at DESC LIMIT 1",
        {"tid": tenant_id}
    )
    if result:
        return float(result[0]["value"]) / (1024 ** 3)
    return 0.0
```

## Publishing Usage Events (for other services to use)

Each service should publish usage events for metering. Create a helper:

```python
# shared/metering.py

from shared.events import publish_event

def record_usage(tenant_id: str, metric_type: str, value: float = 1) -> None:
    """Publish a UsageRecorded event for metering."""
    publish_event(
        source="logistics.metering",
        detail_type="UsageRecorded",
        tenant_id=tenant_id,
        payload={
            "metric_type": metric_type,
            "value": value,
        },
    )
```

**Integration points (add to existing services):**
- Task 10 (tracking): `record_usage(tenant_id, "containers_processed")` on container creation
- Task 12 (claims): `record_usage(tenant_id, "storage_bytes", file_size)` on file upload
- Task 15 (notifications): `record_usage(tenant_id, "sms_sent")`, `"whatsapp_sent"`, `"emails_sent"`
- Task 06 (shared/auth.py): `record_usage(tenant_id, "api_calls")` in auth middleware

## Migration File

### File: `migrations/versions/006_usage_record_upsert_constraint.py`

```sql
ALTER TABLE usage_record ADD CONSTRAINT uq_usage_tenant_metric_period 
  UNIQUE (tenant_id, metric_type, period_start);
```

## Implementation notes / ground-truth gaps found

**`record_usage()` was a plain INSERT, not the upsert this doc specifies
(2026-09-06).** The spec above and migration 010's own docstring both
document `ON CONFLICT (tenant_id, metric_type, period_start) DO UPDATE SET
value = usage_record.value + EXCLUDED.value` — but `shared/metering.py`'s
actual `record_usage()` never used it. Effect: the *first* write for a given
`(tenant_id, metric_type, period_start)` succeeded; every subsequent one hit
`uq_usage_tenant_metric_period` and was silently dropped (the function fails
open by design). This isn't a rare race — for `api_calls`, every tenant's
usage counter was capped at 1 per day, every day, since the first successful
call each day permanently blocked every later one via the constraint.
Tier-limit enforcement reading these totals (`shared/tier_limits.py`) has
therefore never seen real usage past the first request of the day for any
metric.

**A second, separate cause of the same symptom found in the same investigation:**
`record_usage("PLATFORM", ...)` — every platform-admin request — failed with
`InvalidTextRepresentation`, since `usage_record.tenant_id` is a UUID column
and the platform-admin sentinel is the literal string `"PLATFORM"`. Fixed by
skipping metering entirely for that sentinel: platform_admin has no tier
limits to meter against in the first place, so there was nothing to record.

**The actual root cause, found last:** neither bug above should have been
able to corrupt anything outside its own request — both are correctly rolled
back by `execute_write_with_tenant`. They kept doing so anyway because
`scripts/local_server.py`'s dev server runs multi-threaded by Flask's own
default, and `shared/db.py`'s single module-level connection has no lock —
two concurrent requests really were racing on one psycopg2 connection. Fixed
by making the dev server single-threaded (`LOCAL_TESTING.md`), which also
happens to match real Lambda's one-invocation-per-container execution model.

Found via e2e testing, not a metering-focused investigation: the resulting
`IntegrityError`, though itself correctly rolled back, was observed leaving
the shared DB connection in a failed-transaction state afterward — breaking
*every subsequent unrelated request* on the same process with
`psycopg2.errors.InFailedSqlTransaction`. Since this constraint is hit on
essentially every request after the first each day, that was the normal
steady state, not an edge case, and it's what a new e2e smoke sweep
(`frontend/e2e/flows/smoke-navigation.spec.ts`) caught as a scattered
"Internal server error" across unrelated pages. `shared/db.py`'s
`get_connection()` now self-heals a poisoned connection regardless of cause,
but this fix removes the actual trigger. Covered by `tests/unit/test_metering.py`.

## Acceptance Criteria

- [x] SQS consumer processes batches of UsageRecorded events
- [x] UPSERT correctly increments existing usage records
- [x] Partial batch failure supported (individual message failure doesn't fail batch)
- [x] `check_user_limit()` blocks user creation when tier limit reached
- [x] `check_container_limit()` counts only current month's newly created containers
- [x] `check_storage_limit()` checks cumulative S3 usage
- [x] Limit exceeded returns HTTP 429 with `USAGE_LIMIT_EXCEEDED` error code
- [x] Enterprise tier has effectively unlimited limits
- [x] Platform Admin can query per-tenant usage via API
- [x] `record_usage()` helper available for all services
- [x] Usage aggregation unique constraint migration created

**Staff seats, and the dead dashboard placeholder (2026-11-28, platform audit PA-03 and PA-10).** `count_active_tenant_users` counted every active `tenant_user`, customer portal accounts included, so the platform Usage tab's "Staff users" bar disagreed with the quota check and the tenant's own plan page, which exclude customers. It now uses `shared.seats.staff_seat_condition()`, like every other seat count. The handler's `GET /v1/platform/dashboard` branch returned a placeholder message and could never run: API Gateway and `shared/http_routing.py` send that path to tenant_management. It was deleted, and metering now answers that path with 404.
