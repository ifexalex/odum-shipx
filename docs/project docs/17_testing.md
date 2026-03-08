# Task 17 — Testing: Unit, Integration, Tenant Isolation & Load Tests

> **Prerequisite:** Read `00_CROSS_CUTTING_STANDARDS.md` in its entirety — tests verify compliance with all standards.

## Objective

Implement comprehensive test suites: unit tests for all services, integration tests for API flows, specialized tenant isolation tests (FR-TN-006), and load/performance tests.

## Depends On

- All service tasks (07–16)

## Test Structure

```
tests/
├── conftest.py                    # Shared fixtures (mock DB, tenant contexts, etc.)
├── unit/
│   ├── test_auth.py               # JWT parsing, role validation, suspension check
│   ├── test_responses.py          # Response formatting
│   ├── test_pagination.py         # Cursor encoding/decoding
│   ├── test_tenant_management.py  # Service layer unit tests
│   ├── test_packing_list.py       # State machine, CBM calc, carton tag generation
│   ├── test_manifest.py
│   ├── test_tracking.py           # Stage transition validation
│   ├── test_billing.py            # Billing calculation, carryover, CBM dispute
│   ├── test_claims.py             # Claim lifecycle, approval thresholds
│   ├── test_payment_release.py    # Payment status, partial release, proportional billing
│   ├── test_refunds.py            # Refund workflow, debt check
│   ├── test_notifications.py      # Template rendering
│   └── test_scheduled_jobs.py     # Storage fee calculation, escalation logic
├── integration/
│   ├── test_packing_to_release.py # Full flow: packing list → manifest → tracking → billing → payment → release
│   ├── test_dispute_flow.py       # CBM dispute → resolution → billing adjustment
│   ├── test_claim_flow.py         # Damage claim → inspection → resolution → refund
│   └── test_tenant_lifecycle.py   # Create tenant → config → users → suspend → activate
└── tenant_isolation/
    ├── test_db_isolation.py       # RLS blocks cross-tenant queries
    ├── test_api_isolation.py      # API returns empty for wrong tenant
    └── test_s3_isolation.py       # S3 prefix isolation
```

## Key Test Fixtures (`conftest.py`)

```python
import pytest
from shared.tenant_context import TenantContext, UserRole

TENANT_A_ID = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
TENANT_B_ID = "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"

@pytest.fixture
def tenant_a_admin():
    return TenantContext(tenant_id=TENANT_A_ID, user_id="user-a-admin", role=UserRole.TENANT_ADMIN)

@pytest.fixture
def tenant_a_china_staff():
    return TenantContext(tenant_id=TENANT_A_ID, user_id="user-a-china", role=UserRole.CHINA_OFFICE_STAFF)

@pytest.fixture
def tenant_b_admin():
    return TenantContext(tenant_id=TENANT_B_ID, user_id="user-b-admin", role=UserRole.TENANT_ADMIN)

@pytest.fixture
def platform_admin():
    return TenantContext(tenant_id="PLATFORM", user_id="user-platform", role=UserRole.PLATFORM_ADMIN)

@pytest.fixture
def mock_db(monkeypatch):
    """Mock database calls for unit tests."""
    ...

@pytest.fixture
def api_gateway_event():
    """Factory for API Gateway HTTP API events."""
    def _make_event(method, path, body=None, claims=None, query_params=None):
        return {
            "requestContext": {
                "http": {"method": method, "path": path},
                "authorizer": {"claims": claims or {}},
            },
            "body": json.dumps(body) if body else None,
            "queryStringParameters": query_params or {},
            "pathParameters": {},
        }
    return _make_event
```

## Unit Test Coverage Requirements

### State Machine Tests (for each entity)
- Valid transitions succeed
- Invalid transitions raise `IllegalTransitionError` (409)
- Side effects triggered on each valid transition

### Billing Calculation Tests
- CBM summed from packing list items
- Carryover applied correctly
- Credits deducted correctly
- Dollar rate × CBM rate arithmetic
- Partial payment status transitions
- Overpayment detection

### Authorization Tests
- Each endpoint blocks unauthorized roles
- Customer sees only own data
- Self-approval prevention on packing lists

### Approval Threshold Tests
- Claims ≤ $50: nigeria_staff can approve
- Claims > $50: requires tenant_admin
- Correct approval_level recorded

## Tenant Isolation Tests (FR-TN-006)

### `test_db_isolation.py`
1. Create test data for Tenant A and Tenant B (using superuser)
2. Connect as `logistics_app` role
3. Set `app.current_tenant_id = TENANT_A_ID`
4. Query all tenant-scoped tables → verify ONLY Tenant A data returned
5. Attempt to INSERT with `tenant_id = TENANT_B_ID` → verify RLS blocks it
6. Attempt query WITHOUT setting `app.current_tenant_id` → verify RLS blocks it

### `test_api_isolation.py`
1. Create API events with Tenant A JWT claims
2. Call list endpoints → verify no Tenant B data
3. Call get endpoint with Tenant B entity ID → verify 404 (not 403, to prevent enumeration)

### `test_s3_isolation.py`
1. Generate presigned URL for Tenant A claim
2. Verify S3 key starts with `{TENANT_A_ID}/`
3. Attempt to generate URL for Tenant B prefix → verify rejection

## Acceptance Criteria

- [ ] ≥80% code coverage across all services
- [ ] Every state machine transition tested (valid + invalid)
- [ ] Billing arithmetic tests with edge cases (zero CBM, zero rate, negative outstanding)
- [ ] All 6 role types tested for authorization on each endpoint
- [ ] Tenant isolation tests verify RLS blocks cross-tenant access
- [ ] Integration tests cover end-to-end flows
- [ ] All tests pass with `pytest tests/ -v`
- [ ] Tests use mocks for AWS services (moto for Cognito, S3, SQS)
- [ ] Standards compliance tests pass (see below)
- [ ] Load test script exists (locust) for smoke/performance testing

---

## Additional Test Categories

### Standards Compliance Tests (`tests/unit/test_standards_compliance.py`)

Verify that all services comply with `00_CROSS_CUTTING_STANDARDS.md`:

```python
def test_all_responses_include_request_id_header():
    """Every response from every handler must include X-Request-Id."""

def test_all_responses_include_security_headers():
    """Every response must include X-Content-Type-Options, Strict-Transport-Security, Cache-Control."""

def test_post_endpoints_return_201():
    """POST create operations must return 201, not 200."""

def test_post_endpoints_include_location_header():
    """POST create operations must include Location header in response."""

def test_delete_endpoints_return_204():
    """DELETE operations must return 204 with empty body."""

def test_error_responses_are_rfc7807():
    """All error responses must follow RFC 7807 format with type, title, status, detail, instance."""

def test_not_found_returns_404_not_403():
    """Cross-tenant resource access returns 404 (not 403) to prevent enumeration."""

def test_idempotency_key_supported_on_post():
    """POST endpoints with Idempotency-Key header return cached response on replay."""
```

### Security Tests (`tests/unit/test_security.py`)

```python
def test_sql_injection_prevention():
    """Verify parameterized queries — no f-strings in SQL."""

def test_sort_field_allowlist():
    """Verify sort fields are validated against allowlist, not passed raw to SQL."""

def test_s3_keys_scoped_to_tenant():
    """Verify all S3 key generation includes tenant_id prefix."""

def test_no_secrets_in_logs():
    """Verify structured logging never includes passwords, tokens, or secrets."""
```

### Load Tests (`tests/load/locustfile.py`)

```python
from locust import HttpUser, task, between

class LogisticsUser(HttpUser):
    wait_time = between(1, 3)

    def on_start(self):
        """Authenticate and get JWT token."""
        ...

    @task(5)
    def list_packing_lists(self):
        self.client.get("/v1/packing-lists", headers=self.auth_headers)

    @task(3)
    def get_tracking(self):
        self.client.get(f"/v1/shipments/{self.tracking_code}", headers=self.auth_headers)

    @task(1)
    def create_packing_list(self):
        self.client.post("/v1/packing-lists", json=self.sample_packing_list, headers=self.auth_headers)
```

**Performance targets (p95):**
- GET list endpoints: < 500ms
- GET single resource: < 200ms
- POST create: < 1000ms
- State transitions (PATCH): < 500ms
