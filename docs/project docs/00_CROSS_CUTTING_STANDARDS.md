# Cross-Cutting Engineering Standards

> **Read this first.** Every task file in this project MUST conform to these standards. This document captures conventions derived from the API Architect and DevOps Engineer instruction sets that apply across all tasks.

---

## 1. Request/Response Conventions

### 1.1 Correlation & Traceability

Every Lambda handler MUST:
- Generate a `request_id` (UUID v4) at the start of every invocation
- Propagate it through all service/repository calls and into EventBridge events
- Return it in the `X-Request-Id` response header
- Include it in every structured log line

```python
import uuid

def lambda_handler(event, context):
    request_id = event.get("requestContext", {}).get("requestId", str(uuid.uuid4()))
    # Pass request_id into service calls and log context
```

### 1.2 Idempotency for Mutating Operations

All `POST` endpoints that create resources MUST support an optional `Idempotency-Key` header:
- Extract from `event["headers"].get("idempotency-key")`
- If present, check a short-lived cache or DB table before processing
- If the key was seen within the last 24 hours, return the original response (HTTP 200, not 201)
- Store: `idempotency_key VARCHAR(100), response_body JSONB, created_at TIMESTAMPTZ` in a lightweight table
- This prevents duplicate tenant creation, duplicate payments, duplicate claims, etc.

Implementation goes in `shared/idempotency.py` (Task 06).

### 1.3 Standard HTTP Status Codes

| Operation | Success Code | Notes |
|---|---|---|
| GET (single) | 200 | |
| GET (list) | 200 | With pagination meta |
| POST (create) | 201 | Include `Location` header with resource URI |
| POST (public, outcome must not be observable) | 202 | e.g. `POST /v1/register/{slug}`: the same answer whether or not the email already had an account (audit SEC-04) |
| PUT (full replace) | 200 | |
| PATCH (partial update) | 200 | |
| PATCH (state transition) | 200 | |
| DELETE | 204 | No body |
| Validation failure | 422 | RFC 7807 with field errors |
| Auth missing | 401 | |
| Auth insufficient | 403 | |
| Not found | 404 | Do NOT return 403 for wrong-tenant — always 404 (prevents enumeration) |
| Illegal state transition | 409 | |
| Rate limit | 429 | Include `Retry-After` header (`shared/rate_limit.py` sets it; see §8.7) |
| Wrong request origin (cookie endpoints) | 403 | `ORIGIN_NOT_ALLOWED` (§8.7) |
| Wrong media type (cookie endpoints that read a body) | 415 | `UNSUPPORTED_MEDIA_TYPE` |
| Tier limit exceeded | 429 | |
| Server error | 500 | |

### 1.4 Standard Response Headers

Every response MUST include:
```
Content-Type: application/json
X-Request-Id: {request_id}
X-Content-Type-Options: nosniff
Strict-Transport-Security: max-age=31536000; includeSubDomains
Cache-Control: no-store
```

CORS headers (set at API Gateway level, but also safe to include):
```
Access-Control-Allow-Origin: {configured_origins}
Access-Control-Allow-Methods: GET, POST, PUT, PATCH, DELETE, OPTIONS
Access-Control-Allow-Headers: Content-Type, Authorization, Idempotency-Key
Access-Control-Expose-Headers: X-Request-Id
Access-Control-Max-Age: 86400
```

### 1.5 Standard Error Catalog

Every error code used across all services:

| Error Code | HTTP | Used By |
|---|---|---|
| `AUTHENTICATION_REQUIRED` | 401 | shared/auth.py |
| `TENANT_SUSPENDED` | 403 | shared/auth.py |
| `TENANT_OFFBOARDED` | 410 | shared/auth.py (tenant closed, data erasure scheduled) |
| `INSUFFICIENT_PERMISSIONS` | 403 | shared/auth.py, all services |
| `RESOURCE_NOT_FOUND` | 404 | all services |
| `ILLEGAL_TRANSITION` | 409 | packing_list, tracking, billing, claims, refunds |
| `DUPLICATE_RESOURCE` | 409 | tenant_management, packing_list |
| `IDEMPOTENCY_CONFLICT` | 409 | shared/idempotency.py |
| `BUSINESS_RULE_VIOLATION` | 422 | all services |
| `VALIDATION_ERROR` | 422 | all services |
| `PAYMENT_REQUIRED` | 422 | payment_release |
| `SELF_APPROVAL_FORBIDDEN` | 422 | packing_list |
| `APPROVAL_THRESHOLD_EXCEEDED` | 403 | claims, refunds |
| `USAGE_LIMIT_EXCEEDED` | 429 | metering |
| `RATE_LIMIT_EXCEEDED` | 429 | `shared/rate_limit.py` (per client address, username, tracking code, tenant), with `Retry-After`; API Gateway for per-route throttles |
| `ORIGIN_NOT_ALLOWED` | 403 | `shared/origin_guard.py` (cookie-authenticated `/v1/auth/*` routes) |
| `UNSUPPORTED_MEDIA_TYPE` | 415 | `shared/origin_guard.py` (`/v1/auth/session`, `/callback`, `/authorize-url`) |
| `INTERNAL_ERROR` | 500 | global handler |
| `EXTERNAL_SERVICE_ERROR` | 502 | notifications (Africa's Talking, Meta, SES) |

---

## 2. Input Validation Standards

### 2.1 Field-Level Constraints

All Pydantic models MUST enforce:

| Field Type | Constraint |
|---|---|
| `company_name` | `min_length=2, max_length=255` |
| `email` | Pydantic `EmailStr`, max_length=255 |
| `phone` | `pattern=r"^\+?[1-9]\d{6,14}$"`, max_length=20 |
| `description` | `min_length=1, max_length=2000` |
| `notes` | `max_length=5000` |
| `container_number` | `pattern=r"^[A-Z]{4}\d{7}$"`, max_length=11 |
| `carton_tag` | `max_length=100` |
| `tracking_code` | `max_length=100` |
| `reference_number` | `max_length=100` |
| All monetary Decimal | `ge=0, decimal_places=2` |
| All weight Decimal | `ge=0, decimal_places=3` |
| All dimension Decimal | `ge=0, decimal_places=2` |
| CBM Decimal | `ge=0, decimal_places=6` |
| UUID string fields | `pattern=r"^[0-9a-f]{8}-[0-9a-f]{4}-..."` or use Pydantic `UUID4` |
| List fields | `max_length=500` (prevent unbounded payloads) |
| JSONB config | `max_length=65536` (64KB max for branding, notification prefs) |

### 2.2 SQL Injection Prevention (Defense in Depth)

Even though RLS and parameterized queries are the primary defense:
- NEVER use f-strings or string concatenation for SQL
- Always use `%s` placeholders with psycopg2
- Validate all sort/filter column names against an allowlist
- Sanitize any user input used in S3 key construction — file names go through `shared.validation.safe_filename()` (fixed 2026-09-23: four upload flows embedded the raw client `filename` in the S3 key, and two download flows put the stored name inside `Content-Disposition: … filename="{name}"`, where a `"` breaks out of the quoted string and a bidi-override character spoofs the extension)

```python
ALLOWED_SORT_FIELDS = {"created_at", "updated_at", "name", "status"}

def validate_sort_field(field: str) -> str:
    clean = field.lstrip("-")
    if clean not in ALLOWED_SORT_FIELDS:
        raise ValidationError(f"Invalid sort field: {clean}")
    return field
```

**Validate the whole expression, not a part of it (CRITICAL SQL injection fixed 2026-09-23).** An identifier is
interpolated into `ORDER BY`, so the check must cover *everything that gets interpolated*.
`build_paginated_query` used to allow a table-aliased field (`b.created_at`) by validating only
`field.split(".")[-1]` against the allowlist while interpolating the full string — so
`?sort=id,(select pg_sleep(5))::text,b.created_at` (or `id;UPDATE …;--.created_at`) passed as
`created_at` and executed (confirmed against Postgres: 2.2s vs 0.1s), reachable by any role that can list
`GET /v1/billing|claims|containers` (customers can list their own billing). `shared/pagination.py` now
requires `fullmatch` of `identifier` or `alias.identifier` (`_SORT_EXPRESSION_RE`) *and* an allowlisted
column, at the single choke point every list endpoint uses; anything else is a `422`. `sort_direction` is
normalised to `ASC`/`DESC`. Regression: `tests/unit/test_sort_injection.py` drives the real
handler → service → repository → builder chain for all three endpoints with the DB layer wired to fail.
Rule of thumb for review: any `f"…{x}…"` reaching SQL needs `x` to be a **literal chosen in code** or to
have passed a `fullmatch` allowlist — never a "contains"/"ends with"/"last segment" check.

---

## 3. Structured Logging Standard

All Lambda functions MUST use JSON structured logging. The canonical
implementation is `shared/logging_config.py` — do not re-implement a formatter
per service. Every handler calls `setup_logging()` once at module load (cold
start) and obtains a logger with `logging.getLogger(__name__)`.

Each line is a single-line JSON object carrying the core schema below, so it is
directly queryable in CloudWatch Logs Insights (e.g.
`filter tenant_id = "..." and level = "ERROR" | sort @timestamp`):

```json
{
  "timestamp": "2026-10-03T12:00:00+00:00",
  "level": "ERROR",
  "service": "billing",
  "environment": "prod",
  "request_id": "abc-123",
  "tenant_id": "t-0001",
  "user_id": "f7c9...",
  "message": "Unhandled error",
  "logger": "services.billing.handler",
  "exception": "Traceback ..."
}
```

### 3.1 Trace-context propagation (`request_id` / `tenant_id` / `user_id`)

Correlation IDs are **not** threaded through function signatures and are **not**
re-specified via `extra={...}` at each call site. Instead they are bound once
per invocation into request-scoped `contextvars` and injected onto every record
by a `logging.Filter`:

- `bind_log_context(request_id=..., tenant_id=..., user_id=...)` — only
  non-None args are applied, so later calls refine the context.
- `clear_log_context()` — resets all three.
- `ContextFilter` — fills any field the caller did not set explicitly. An
  explicit `extra={"tenant_id": ...}` on a single call still wins for that line.

**Wiring contract (enforced across all handlers):**
- API handlers call `clear_log_context()` then `bind_log_context(request_id=...)`
  at entry (immediately after deriving `request_id`). `clear` runs at **entry**,
  not in `finally`, so a reused Lambda execution environment cannot leak the
  previous request's IDs, and the closing `← response` log line keeps full
  context.
- `get_tenant_context()` binds `tenant_id` + `user_id` from the single auth
  chokepoint the moment identity is known — every downstream handler/service/
  repository log line then carries them automatically.
- Scheduled (EventBridge) jobs bind `request_id` from `context.aws_request_id`
  at entry and `bind_log_context(tenant_id=...)` inside their per-tenant loop,
  so a failure in one tenant's processing is attributable.
- SQS consumers (notifications, metering) `clear` + bind `request_id` from the
  SQS `messageId` per record, and bind `tenant_id` once the message body is
  parsed.

### 3.2 Custom fields

Any caller-supplied `extra={...}` field not in the core schema (e.g.
`duration_ms`, `event_type`, `status_code`) is passed through as a top-level
JSON key so it stays queryable — it is **not** dropped.

**Required log events:**
- `INFO` — every request entry (method, path, tenant_id, user_role)
- `INFO` — every request exit (status_code, duration_ms)
- `INFO` — every state transition (entity, from_state, to_state)
- `INFO` — every event published (event_type, detail_type)
- `WARNING` — business rule violations, authorization failures
- `ERROR` — unhandled exceptions, external service failures
- `DEBUG` — SQL queries (only in dev, never in prod)

**Never log PII** (email, phone, name, ID numbers) to CloudWatch — log only
`tenant_id`, `user_id` (UUID), `request_id`, and non-PII metadata. See §11 for
the masking rules applied to audit snapshots.

---

## 4. Caching Strategy

### 4.1 Tenant Status Cache — Distributed (Redis)
- **Tenant status** (`active` / `suspended` / `offboarded`) is cached in **ElastiCache Redis** (`cache.t4g.micro`) with a 60-second TTL.
- Implementation: `shared/distributed_cache.py` — `DistributedCache` class; same interface as `shared/cache.py`.
- Key format: `tenant_status:{tenant_id}` — explicit prefix to avoid collisions.
- **Why distributed, not in-memory:** Lambda scales horizontally. An in-memory dict is per-instance only — a suspended tenant could still transact on all other warm instances until their individual TTL expires. Redis ensures all instances see the same status within the TTL window.
- **Explicit invalidation on status change:** `suspend_tenant`, `offboard_tenant`, `activate_tenant`, and `reactivate_tenant` all call `_tenant_status_cache.delete(tenant_id)` immediately after the DB write, eliminating the TTL lag for the critical path.
- **Fail-soft:** Redis errors are logged as warnings; `get()` returns `None`, which causes a DB fallback. Redis is an optimisation layer, not a hard dependency.
- **No retries, and a circuit breaker (2026-11-15).** redis-py's default retries a failed command with exponential backoff, which made every operation against an unreachable Redis take about four seconds, and a request makes several. `DistributedCache` now disables client retries and, after one failure, leaves Redis alone for 5 seconds (per process), so an outage costs one fast failure instead of one per call. Found by a test against a real Redis (`tests/db/test_rate_limit_redis.py`) while building the rate limiter.
- **User identity (2026-11-15):** the same cache holds `identity:{user_id}` -> `{tenant_id}:{role}` (60 s) or `""` for no active row, read by `get_tenant_context` on every request (§8.7). `evict_identity_cache()` runs after a deactivation or role change.
- **Local dev:** Redis 7 Alpine container on port 6379 (`shipx_redis` in `docker-compose.local.yml`). `REDIS_HOST=localhost` in `.env.local`.
- **Production:** ElastiCache cluster endpoint injected as `REDIS_HOST` Lambda env var via Terraform.

### 4.2 Tenant Configuration Cache
- **Stale-claim correction (2026-09-19):** this section previously claimed `dollar_rate`/`cbm_rate`/`storage_fee` were all cached in-memory via `shared/cache.py` with a 60s TTL. Verified against the actual code while building the Bybit-rate feature below: that was never true — `shared/cache.py`'s `Cache` class has exactly one caller in the whole codebase (`shared/notifications.py`), and every `cbm_rate_per_unit`/`storage_fee` read has always hit Postgres directly, every call, with no cache at all.
- `dollar_rate` now genuinely is cached — but for a different reason and via a different mechanism than what was originally claimed here. The base rate is fetched live from Bybit's P2P order book (`shared/fx_rate.py`; see `07_api_tenant_management.md`'s Dollar Rate section), and that live fetch is what's cached — via `shared/distributed_cache.py`'s Redis-backed `DistributedCache` (10-minute TTL, key `fx_rate:ngn_usdt`, **not** tenant-scoped since the black-market rate itself doesn't vary by tenant), not `shared/cache.py`. This is about avoiding hammering an external API on every billing/claim/refund calculation, not about DB read load.
- `cbm_rate_per_unit` and `storage_fee` remain genuinely uncached, direct-DB-read on every call, as they always have been — read-heavy, write-rare values where the extra DB read is cheap enough not to bother.

### 4.3 No Cache on Transactional Data
- NEVER cache: billing, payments, packing lists, claims, refunds
- These must always read from DB for consistency

---

## 5. Circuit Breaker for External Services

Notification Lambdas calling external APIs (Africa's Talking, Meta WhatsApp) MUST implement a circuit breaker:

```python
# shared/circuit_breaker.py
import time
from enum import Enum

class CircuitState(Enum):
    CLOSED = "closed"       # Normal operation
    OPEN = "open"           # Failing, reject requests
    HALF_OPEN = "half_open" # Testing recovery

class CircuitBreaker:
    def __init__(self, failure_threshold: int = 5, recovery_timeout: int = 60):
        self.failure_threshold = failure_threshold
        self.recovery_timeout = recovery_timeout
        self.failure_count = 0
        self.state = CircuitState.CLOSED
        self.last_failure_time = 0

    def call(self, func, *args, **kwargs):
        if self.state == CircuitState.OPEN:
            if time.time() - self.last_failure_time > self.recovery_timeout:
                self.state = CircuitState.HALF_OPEN
            else:
                raise ExternalServiceError("Circuit breaker open")
        try:
            result = func(*args, **kwargs)
            self._on_success()
            return result
        except Exception as e:
            self._on_failure()
            raise

    def _on_success(self):
        self.failure_count = 0
        self.state = CircuitState.CLOSED

    def _on_failure(self):
        self.failure_count += 1
        self.last_failure_time = time.time()
        if self.failure_count >= self.failure_threshold:
            self.state = CircuitState.OPEN
```

---

## 6. Terraform Standards (All Modules)

### 6.1 Required Provider Block (every module's `versions.tf`)
```hcl
terraform {
  required_version = ">= 1.7.0"
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.40"
    }
  }
}
```

### 6.2 Remote State Backend (`infrastructure/aws/backend.tf`)
```hcl
terraform {
  backend "s3" {
    bucket         = "logistics-terraform-state-{account_id}"
    key            = "logistics/{environment}/terraform.tfstate"
    region         = "eu-west-1"
    dynamodb_table = "logistics-terraform-locks"
    encrypt        = true
  }
}
```

### 6.3 Default Tags (all resources)
```hcl
locals {
  common_tags = {
    Project     = var.project_name
    Environment = var.environment
    ManagedBy   = "terraform"
    CostCenter  = "logistics-platform"
    Owner       = "platform-engineering"
  }
}

provider "aws" {
  region = var.aws_region
  default_tags {
    tags = local.common_tags
  }
}
```

### 6.4 Security Group Lifecycle
```hcl
resource "aws_security_group" "example" {
  # ...
  lifecycle {
    create_before_destroy = true
  }
}
```

### 6.5 Naming Convention
All resources: `{project}-{component}-{environment}`
Examples: `logistics-aurora-prod`, `logistics-lambda-billing-dev`, `logistics-sqs-sms-staging`

---

## 7. Observability Standards

### 7.1 AWS X-Ray Tracing
All Lambda functions MUST have X-Ray tracing enabled:
```hcl
resource "aws_lambda_function" "example" {
  tracing_config {
    mode = "Active"
  }
}
```

Application code should use `aws-xray-sdk`:
```python
from aws_xray_sdk.core import xray_recorder, patch_all
patch_all()  # Patches boto3, psycopg2, requests automatically
```

### 7.2 CloudWatch Custom Metrics
Each service should emit:
- `RequestCount` — per endpoint
- `RequestDuration` — per endpoint (milliseconds)
- `ErrorCount` — per error_code
- `StateTransitionCount` — per entity type and transition

Use CloudWatch Embedded Metrics Format for zero-cost metric emission from logs.

### 7.3 Health Check Contract
`GET /v1/health` returns:
```json
{
  "status": "healthy",
  "version": "1.0.0",
  "environment": "prod",
  "timestamp": "2026-02-22T10:30:00Z",
  "checks": {
    "database": "healthy",
    "event_bus": "healthy"
  }
}
```

---

## 8. Security Standards

### 8.1 Secrets Management
- All secrets stored in AWS Secrets Manager
- Lambda retrieves secrets at cold start, caches in memory
- Secrets rotation: automatic 90-day rotation for DB passwords
- Never log secrets, tokens, or passwords

### 8.2 Encryption
- Data at rest: AES-256 (S3, Aurora, SQS SSE)
- Data in transit: TLS 1.2+ (API Gateway enforces HTTPS)
- Secrets Manager: AWS-managed KMS key

### 8.3 Least Privilege IAM
- Each Lambda has its own IAM role
- Permissions scoped to specific resources (not `*`)
- Example: Claims Lambda gets `s3:PutObject` only on `arn:aws:s3:::logistics-assets-*/*/claims/*`
- Every Lambda role carries the `permissions_boundary` from `infrastructure/aws/modules/iam-oidc` — an
  **allow-list intersection**. An inline grant is ineffective unless the boundary also allows the
  action, so adding an AWS API call to the code means updating **both** the role policy in
  `modules/lambda/main.tf` and the boundary. (Found 2026-09-23: the boundary's KMS statement was
  conditioned on `kms:RequestAlias`, which is only present when a request names an alias — the code
  passes a key ARN to `GenerateDataKey` and no key at all to `Decrypt`, so field encryption would have
  been denied in AWS. Now `kms:ResourceAliases`, which matches however the key is referenced.)

### 8.4 Outbound requests to tenant-supplied URLs (SSRF)
- Never `urlopen()`/`requests.get()` a URL a tenant or customer can influence. Use
  `shared/url_safety.open_public_https()` (see `02_shared_utilities.md`), and validate at the request
  boundary with `validate_public_https_url()`.
- Lambdas run inside the VPC beside Aurora/Redis: a `^https://` check alone is not a defence — block
  private/loopback/link-local/CGNAT/reserved ranges (including numeric-IPv4 tricks and IPv4-mapped
  IPv6), re-resolve DNS at delivery time, pin the connection to the validated IP, and never follow
  redirects.
- Don't echo raw socket errors from a probe endpoint back to the caller — connect-refused vs timeout
  is an internal port-scan oracle.
- Fixed-URL provider calls (Paystack, Bybit, Africa's Talking, Meta, Cognito JWKS) are exempt.

### 8.5 Infrastructure/code contracts
- `scripts/local_server.py` routes by path prefix, so drift between the application and Terraform is
  invisible locally. `tests/unit/test_infrastructure_contracts.py` fails CI if a frontend call has no
  API Gateway route, a route targets a service with no deployed Lambda, or a Lambda handler named in
  Terraform doesn't exist in `services/`.

### 8.6 Edge protection (DDoS / WAF)
- **Frontend (CloudFront):** AWS Shield Standard is automatic (L3/L4). A WAFv2 Web ACL
  (`infrastructure/aws/modules/cloudfront/main.tf`, scope `CLOUDFRONT`/us-east-1) adds L7 defence —
  a per-IP rate limit (`var.waf_rate_limit`, default 2000/5min) plus AWS managed rule groups
  (IP reputation, common rule set, known-bad-inputs). Full deployment + tuning steps and the
  attack-protection posture live in `docs/runbook.md` → "Frontend Deployment & Go-Live".
- **API (API Gateway HTTP v2):** WAFv2 can't attach to HTTP APIs; protected by Shield Standard,
  stage throttling (50 req/s, burst 100), per-route throttles on the public routes
  (`public_route_throttles`), the application-level limits in §8.7, Lambda concurrency caps, and per-tenant
  metering. Full L7 WAF on the API needs a CloudFront front — a documented follow-up, not required for launch.
  ~~Per-tenant throttling through API Gateway usage plans / API keys~~ was claimed here and in
  `04c`/`22` but an HTTP API has neither and the Terraform never created them; the per-tenant limit is
  `shared/rate_limit.py`.

### 8.7 Abuse controls on the public surface (audit Phase 2, 2026-11-15)

Four controls, each at a chokepoint rather than in every handler. ADR-006 and ADR-007 give the reasoning.

- **A token must not outlive its user (SEC-02).** `get_tenant_context` (`shared/auth.py`) confirms on every
  request that the token's `sub` still has an *active* `tenant_user` row, in the tenant the token claims. A
  deactivated user, an erased customer or an unknown subject gets `401` on the very next request, whatever the
  token's expiry. The lookup goes through `identity:{user_id}` in Redis (60 s) and is evicted on
  deactivation. If the lookup fails the request is refused with `503` (fail closed, as the tenant-status
  check). Platform admins have no row and are exempt. Deactivation also calls `global_sign_out`, which revokes
  the refresh token so the session cannot be renewed; erasing a customer (`DELETE /v1/customers/{id}`) now
  does the same to their portal login, and then erases it: the identity-provider account is deleted and the
  `tenant_user` row's `email` / `full_name` are replaced by placeholders (2026-11-16).
- **Cookie endpoints check the request origin (SEC-05).** `/v1/auth/session`, `/refresh`, `/logout`,
  `/authorize-url` and `/callback` return `403 ORIGIN_NOT_ALLOWED`, setting no cookie, unless `Origin` is a
  trusted origin: the origins of `APP_BASE_URL`, `CUSTOMER_PORTAL_BASE_URL` and `ENTRA_REDIRECT_URI`, plus
  `ALLOWED_ORIGINS` (Terraform fills it from `cors_allow_origins`) and `CORS_ALLOW_ORIGINS`. A missing
  `Origin` is refused too. With none configured every request is refused (fail closed). The routes that read a
  body (`/session`, `/callback`, `/authorize-url`) also require `Content-Type: application/json` (`415`).
  `/login` takes credentials and sets no cookie, so it is rate-limited instead.
- **Rate limits (SEC-03).** `shared/rate_limit.py`: Redis fixed windows, `429` + `Retry-After`, **fail open** with
  `rate_limiter_unavailable` logged at ERROR. Policies and defaults: login 10/min per address and 5 failed
  per 15 min per username; register and onboarding-requests 5/hour per address; tracking lookup 30/min per
  address and 10 wrong-phone guesses/hour per code; cookie routes 60/min per address; authenticated 600/min
  per tenant (in `get_tenant_context`, platform admin exempt). Override with `RATE_LIMIT_<POLICY>=limit/window`
  (or `off`); `RATE_LIMIT_ENABLED=false` switches it all off. Terraform disables it on the non-VPC `auth`
  Lambda, which cannot reach Redis; those routes get API Gateway per-route throttles.
- **The client address is trustworthy (SEC-03).** `shared/client_ip.py` reads `requestContext.http.sourceIp`
  (HTTP API) then `identity.sourceIp`, which fixes audit logs that recorded no address in production. On the
  Azure container app (2026-11-17) a request stamped with this deployment's Front Door id (`X-Azure-FDID` equal to
  `AZURE_FRONT_DOOR_ID`) is given the address Front Door itself recorded (`X-Azure-SocketIP`), which a client
  cannot influence; nobody has to count proxies. A request that did not come through Front Door has an
  *unknown* address (audit logs record none and per-address limits are skipped, rather than one bucket for
  everybody) unless `TRUSTED_PROXY_HOPS` says how many known proxies append to `X-Forwarded-For`.
  `REQUIRE_FRONT_DOOR=true` refuses such requests outright.

---

## 9. Disaster Recovery

### 9.1 Aurora Backups
- Automated backups: 7-day retention (prod), 1-day (dev)
- Point-in-time recovery enabled
- Weekly manual snapshots exported to S3 (cross-region: eu-central-1)
- Backup window: 03:00–04:00 UTC (low traffic)
- Maintenance window: Sun 05:00–06:00 UTC

### 9.2 S3 Versioning
- Enabled on all buckets
- Lifecycle: previous versions expire after 30 days
- Cross-region replication for prod (eu-central-1)

### 9.3 Recovery Targets
- RTO (Recovery Time Objective): 1 hour
- RPO (Recovery Point Objective): 5 minutes (Aurora continuous backup)

---

## 10. Cost Optimization

### 10.1 Lambda Right-Sizing
- Start with specified memory, monitor with Lambda Power Tuning
- Use ARM64 (Graviton2) for 20% cost reduction: `architectures = ["arm64"]`

### 10.2 Aurora Auto-Pause
- Dev/staging: auto-pause after 10 minutes idle
- Prod: NO auto-pause (cold start is 25-30 seconds)

### 10.3 Cost Allocation Tags
All resources tagged with `CostCenter = "logistics-platform"` for billing reports.

---

## 11. GDPR & Privacy Standards

### 11.1 GDPR Fields (migration 012)

The following columns were added to support GDPR compliance:

| Table | Column | Purpose |
|---|---|---|
| `customer` | `anonymised_at TIMESTAMPTZ` | Set when customer record is anonymised (Art. 17 erasure) |
| `customer` | `consent_given_at TIMESTAMPTZ` | Timestamp of explicit consent |
| `customer` | `notification_consent TEXT[]` | Channels consented to: `'sms'`, `'whatsapp'`, `'email'` |
| `tenant_user` | `consent_given_at TIMESTAMPTZ` | Timestamp of staff explicit consent |
| `tenant_user` | `marketing_consent BOOLEAN` | Whether staff opted into marketing |

### 11.2 Right to Erasure (Art. 17)

`DELETE /v1/customers/{id}` (tenant_admin only) anonymises the customer record — it does NOT hard-delete, because FK constraints from billing/shipment_tracking/damage_claim would be violated. The following fields are nulled:

```
name → 'Anonymised'
email, phone, whatsapp, address, contract_details, user_id → NULL
anonymised_at → NOW()
```

The UUID shell is retained for FK integrity. All API reads still return the anonymised record with PII stripped.

### 11.3 Data Portability (Art. 20)

`GET /v1/customers/{id}/export` (tenant_admin or the customer themselves) returns a JSON bundle with the customer's full data: billing summary, shipments, claims, and exported_at timestamp.

Every export call writes an `EXPORT` audit log entry (entity_type=customer, action=EXPORT) recording the actor, role, and timestamp. This satisfies the GDPR Art. 5(2) accountability obligation — there is always a traceable record of who accessed personal data and when. The after_state contains only `exported_at` and `record_count` — no PII.

### 11.6 Tenant Offboarding — Auth Revocation (Art. 32)

`offboard_tenant()` performs three operations atomically (best-effort on 2+3):

1. **DB status update** — `tenant.status = 'offboarded'` (and `offboarded_at`, `deletion_scheduled_at` set)
2. **Redis cache eviction** — immediately deletes the cached `'active'` status so `_check_tenant_active()` returns `TenantOffboardedError (410)` on the very next request, without waiting for the 15s TTL
3. **Cognito global sign-out** — calls `AdminUserGlobalSignOut` for every `tenant_user` record, invalidating all existing access tokens and refresh tokens in Cognito

Steps 2 and 3 are wrapped in `try/except` — a cache or Cognito failure does NOT roll back the offboarding. Since the app re-checks tenant status on every request (step 1 + 2), the security invariant is maintained even if step 3 fails partially.

### 11.4 Audit Log PII Masking

`shared/audit.py` masks sensitive fields in `before_state` / `after_state` snapshots. Masked fields:

```python
_AUDIT_SENSITIVE_FIELDS = frozenset({
    "id_number",       # passport / national ID
    "account_number",  # bank account
    "account_name",
    "bank_name",
    "delegate_phone",
    "collected_by_phone",
})
```

### 11.5 Notification PII in Logs

Handlers MUST NOT log PII in CloudWatch. Specifically prohibited in log `extra` dicts:
- `email`, `phone`, `whatsapp` — use only `tenant_id`, `request_id`

---

## 12. Application-Level Field Encryption

Sensitive PII fields are encrypted at the application layer using AWS KMS + Fernet (AES-256). Implemented in `shared/encryption.py` (migration 013 documents which columns are encrypted).

### 12.1 Encrypted Columns

| Table | Column | Reason |
|---|---|---|
| `pickup_record` | `id_number` | Passport / national ID number |
| `refund_request` | `account_number` | Bank account number |
| `refund_request` | `account_name` | Bank account name |

### 12.2 Encryption Scheme

```
plaintext → KMS GenerateDataKey (AES-256) → Fernet encrypt
→ base64(encrypted_key_blob + "||" + ciphertext) → stored in DB column
```

Decryption calls `KMS Decrypt` to recover the data key, then Fernet decrypts the ciphertext. No plaintext key material is ever stored in the database.

### 12.3 Required Environment Variable

`ENCRYPTION_KMS_KEY_ID` — ARN of the KMS key used for field encryption. Must be set in all Lambda environments that read/write the encrypted columns (payment_release and refunds services).

## Display formatting and time zone (audit FE-03, owner decision 2026-11-16)

**Every date and time is shown in Lagos time (Africa/Lagos, WAT) for everyone**, staff in China and Nigeria and customers alike, so one event reads the same wherever it is viewed. Times name the zone ("10 Nov 2026, 11:04 WAT"). A plain calendar date (`YYYY-MM-DD`: an ETA, a ship date) is shown as written and never shifted. Numbers use a fixed locale: commas for grouping, a point for decimals, whatever the browser is set to.

All of it goes through `frontend/src/lib/format.ts`: `formatNgn` (`₦174,375`, or `₦174,375.50` with kobo, never `.5`), `formatUsd` (always cents), `formatAmount` (a column whose header names the currency), `formatCbm`, `formatNumber`, `formatCount`, `formatDate` (`10 Nov 2026`; `short`, `long`), `formatDateTime`, `formatTime`, and `todayIso` / `isoDateOffset` for the Lagos date as `YYYY-MM-DD` (date inputs, query presets; not `toISOString().slice(0, 10)`, which is the UTC date and is still yesterday for the first hour of the Lagos day). Missing or unreadable values render as "—", never "NaN" or "Invalid Date". `lib/format.test.ts` fails if any other source file calls `toLocaleString`, `toLocaleDateString` or `toLocaleTimeString`, or slices an ISO string for a date. The backend's PDFs and exports are separate: timestamps in the new list exports are UTC and say so in the header.

## One-time codes and other delivered secrets (2026-11-16)

A secret that is sent to a person (a pickup code today) is stored only as a keyed hash, compared in constant time, limited in attempts, and never written to logs, audit snapshots, API responses or `notification_log` (add its template key to `_SECRET_TEMPLATE_KEYS` in `services/notification/service.py`). See ADR-008.

## Tenant data export at offboarding (audit BE-10, 2026-11-17)

GDPR portability for the tenant as controller (PRD FR-TN-004). The archive holds decrypted personal data, so: platform admins only; five-minute links, each audited with actor and IP; no link without the audit record; IAM limited to the export folders; secrets and token hashes excluded; failures logged by type and location only. The cleanup will not erase a tenant before its export has completed. Residual: at rest the archive relies on bucket encryption, and it lives until the tenant is deleted. Threat model: `07_api_tenant_management.md`.
