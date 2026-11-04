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
│   ├── test_tenant_management.py  # Service layer unit tests (incl. self-register FK fix, customer invites)
│   ├── test_onboarding.py         # Shipping-company onboarding leads (public lead + platform queue + provision-links-lead)
│   ├── test_cognito_client.py     # Moto-backed: Cognito group sync, create_user_with_password (invite claim)
│   ├── test_phone.py              # shared/phone.py — E.164 normalisation, dial-code lookup, masking
│   ├── test_invites.py            # shared/invites.py — token mint/hash, expiry/consumed validity checks
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

### Structured Logging Tests (`tests/unit/test_logging_config.py`)

Covers `shared/logging_config.py` (see 00_CROSS_CUTTING_STANDARDS §3):

```python
class TestStructuredFormatter:
    # core JSON schema, extra-field passthrough (duration_ms no longer dropped),
    # non-JSON value serialisation (Decimal), exception capture

class TestContextPropagation:
    # bound request_id/tenant_id/user_id appear on every record;
    # partial bind refines without clearing; explicit extra= wins over bound
    # context; clear_log_context() prevents cross-invocation leakage;
    # unbound fields serialise as null (not missing)
```

### Impersonation Read-Only Tests (`tests/unit/test_auth.py` — `TestReadOnlyImpersonation`)

Enforces the central read-only guard added to `get_tenant_context` (Task 1 — P0 security fix):

- `test_post_blocked_for_impersonation` — POST raises `BusinessRuleViolationError(rule_id="IMPERSONATION_READ_ONLY")`
- `test_patch_blocked_for_impersonation`, `test_delete_blocked_for_impersonation`, `test_put_blocked_for_impersonation` — same for all write verbs
- `test_get_allowed_for_impersonation`, `test_head_allowed_for_impersonation`, `test_options_allowed_for_impersonation` — read verbs pass through
- `test_normal_post_not_blocked` — non-impersonated POST is unaffected
- `test_regression_guard_lives_in_get_tenant_context` — `inspect.getsource` verifies `assert_not_read_only` is called inside `get_tenant_context` (fails if guard is moved to individual handlers)

### Scheduled Job Locale Tests (`tests/unit/test_scheduled_jobs.py` — `TestScheduledLocaleForwarding`)

Verifies locale is forwarded from the recipient DB row to `enqueue_notification` (Task 4):

- `storage_reminders` — `zh` customer → `locale='zh'` on both SMS and email calls; `en` customer → `'en'`; missing `locale` key defaults to `'en'`
- `release_expiry` — `zh` customer → `locale='zh'` propagated through `_notify_customer`
- `dispute_escalation` — `zh` admin → `locale='zh'` on `enqueue_notification`
- `sla_check` — `en` staff member → `locale='en'` forwarded
- Regression: `inspect.getsource` checks that `_get_customer_contact` and staff queries include `locale` column
- `test_enqueue_notification_includes_locale_in_sqs_payload` — verifies `locale` appears in the serialised SQS message body

### Container List SQL Construction Tests (`tests/unit/test_tracking.py` — `TestListContainersRepository`)

Regression coverage for `services/tracking/repository.py::list_containers`'s WHERE-clause construction — added while fixing a ground-truth bug where the container list's `q` free-text filter produced invalid SQL (`c.(c.container_number ILIKE ...)`, a 500 on every table/header search on `ContainerList`). Patches `repository.execute_with_tenant` and asserts on the query string/params actually built, rather than mocking at the service layer:

- `test_q_filter_produces_valid_where_clause` — asserts the double-`c.`-prefix bug pattern (`"c.(c."`) is absent and the free-text OR-clause is well-formed
- `test_status_filter_scoped_to_alias` — `status` filter now renders as `c.status = ANY(%(statuses)s)` (updated row 7.37 — see below)
- `test_created_after_and_before_filters_added` — new `created_after`/`created_before` date-range params (see `10_api_tracking.md`) render as `c.created_at >= / <=` with the right bind params

Frontend: `frontend/src/pages/china/ContainerList.test.tsx` gained 4 cases covering the same fix from the UI side — search debounce (no request per keystroke), header-search/table-search state sync via the new `TopBarContext` `onSearch` slot, the `DateRangeFilter` preset control, and the "Filters" panel's "Clear all filters" action. See `frontend/07_domain_modules.md` §5.1 for the full bug list.

### Table Sort + Multi-Status/ETA Filter Tests (row 7.37)

Added while wiring up the previously-dead `Table` sort UI (`sortable: true` columns with no `onSort` handler anywhere in the app) and reworking `ContainerList`'s Filters panel.

**Backend — `tests/unit/test_tracking.py`:**
- `TestListContainersRepository` — `test_status_filter_accepts_a_list_for_the_filters_panel_multi_select` (comma-separated statuses produce one parameterized `ANY(...)` clause), `test_eta_after_and_before_filters_added`, `test_sort_field_defaults_to_created_at`, `test_sort_field_container_number_ascending`, `test_sort_field_estimated_arrival_date`, `test_invalid_sort_field_rejected`
- `TestContainersHandlerQueryParams` (new) — handler-level: comma-separated `?status=` becomes a list filter, `?sort=&direction=` reach the repo call, `?eta_after=&eta_before=` reach the repo filters

**Backend — `tests/unit/test_billing.py`:**
- `TestListBilling` — `test_sort_field_and_direction_passed_through_to_repo`, `test_sort_field_defaults_to_created_at`
- `TestListBillingAllRepositorySort` (new) — `sort_field` is prefixed with the `b.` alias; verifies `ORDER BY b.billed_at ASC` / `ORDER BY b.invoice_number DESC` / default `ORDER BY b.created_at DESC`

**Backend — `tests/unit/test_claims.py`:**
- `TestListClaimsSort` (new, handler-level) — `?sort=&direction=` reach `repo.list_damage_claims`; defaults to `created_at`/`desc` when omitted
- `TestListDamageClaimsRepositorySort` (new) — `sort_field` prefixed with the `dc.` alias; `ORDER BY dc.reference ASC`, default `ORDER BY dc.created_at DESC`

**Backend — `tests/unit/test_pagination.py`:** unaffected (no hardcoded references to the removed `arrival_date`/`departure_date`/`total_amount_ngn` allowlist entries) — confirms those were genuinely dead.

### Multi-Role Staff Support Tests (migration 039, 2026-07-20)

Backend — `tests/unit/test_auth.py`:
- `TestParseRoles` (renamed from `TestParseRole`) — `_parse_roles` now returns a
  `frozenset[UserRole]`: multiple groups for the same tenant are all kept
  (`test_multiple_groups_for_same_tenant_all_kept`), other-tenant groups excluded,
  JSON-array-string format with 2 roles, `platform_admin` group wins over any tenant
  groups, duplicate groups deduplicated.
- `TestParsePrimaryRole` (new) — `_parse_primary_role` reads `custom:role` when valid
  and assigned; falls back to a deterministic (alphabetically-first) member of `roles`
  when the claim is absent, invalid, or names a role the user no longer holds.
- `TestAssertRole` extended — `roles` defaults to `{role}` when a `TenantContext` is
  constructed without it (regression guard: existing fixtures/call sites must not
  silently lose all permissions); union-check passes when *any* of the user's roles
  matches, even a non-primary one; a regression guard asserting `assert_role`'s
  signature is still `*allowed_roles` (proves none of the 113 existing
  `assert_role`/`require_roles` call sites needed to change).
- `TestGetTenantContext` extended — a multi-role claim set produces `ctx.roles` with
  every assigned role and `ctx.role` from `custom:role`.

Backend — `tests/unit/test_cognito_client.py` (new, moto-backed — a real mocked Cognito
user pool, not `MagicMock`, so these exercise the actual boto3 call shapes):
- `TestRemoveUserFromGroup`, `TestListGroupsForUser` — the two new wrapper methods.
- `TestSyncUserGroups` — the direct regression tests for the group-sync bug:
  add-only from no groups, add-only extending existing membership, **remove-only
  (the exact bug scenario — a role taken away must actually drop the group)**,
  add+remove diff in one call, no-op when already matching, never touches another
  tenant's or `platform_admin`'s groups, empty desired-roles removes everything for
  that tenant.

Backend — `tests/unit/test_tenant_management.py`:
- `TestCreateUser` extended — `create_user` now takes real `CreateTenantUserRequest`
  instances (not `MagicMock`) with `roles`/`primary_role`; asserts
  `cognito.sync_user_groups(...)` replaces the old `create_group_if_not_exists` +
  `add_user_to_group` pair; a multi-role invite seeds `tenant_user_role` for every
  role via `repository.set_user_roles`, not just the primary; `'customer'` as a
  *secondary* role still links the customer record.
- `TestUpdateUserRoles` (new) — `roles` update calls `set_user_roles` +
  `sync_user_groups` + `global_sign_out`; `primary_role` defaults to `roles[0]` when
  omitted and is honored when explicit; `full_name` + `roles` together reach Cognito
  in one `update_user_attributes` call; a plain `full_name`/`locale`-only update never
  touches Cognito groups (`sync_user_groups`/`global_sign_out` not called).
- `TestSetUserRoles` (new, repository-level) — `set_user_roles` issues exactly one
  `execute_transaction` call: 1 `DELETE` + N `INSERT` (one per role, primary flagged)
  + 1 `UPDATE ... tenant_user SET role` mirroring the primary, asserting the actual
  SQL/params; returns `None` when the target user doesn't exist;
  `get_user_roles` orders primary role first.

Live/migration verification (not unit-testable, run manually against the local stack —
see `LOCAL_TESTING.md` and `05a_database_schema_core.md`'s migration 039 note): backfill
produces exactly one `is_primary=TRUE` row per pre-existing `tenant_user`; the partial
unique index rejects a second primary; `GET /v1/tenant/users/{id}` returns both roles
for a real seeded multi-role user; a request gated to either role succeeds regardless
of which is active; `PATCH .../roles` removing a role actually removes the
corresponding Cognito group (`admin-list-groups-for-user` before/after) and a
subsequent request gated to the removed role 403s.

Frontend — see `frontend/07_domain_modules.md`'s 2026-07-20 notes for the full test
list (`StaffUserDetail.test.tsx`, `StaffUserList.test.tsx`, `RoleGuard.test.tsx`,
`jwt.test.ts`, `SessionProvider.test.tsx`, `LocalAuthProvider.test.tsx`,
`tokenStore.test.ts`).

**Frontend:**
- `ContainerList.test.tsx` (+6 cases) — Container/ETA header click toggles `sort`/`direction` asc↔desc; Filters panel has the granular status multi-select and "Arriving" ETA presets with no duplicate date-created control; selecting a status in the panel re-fetches and composes with a second selection; "Clear all filters" resets status/ETA but leaves the standalone date-created button untouched.
- `BillingList.test.tsx` (+2 cases), `ClaimList.test.tsx` (+2 cases) — header click sends the expected `sort`/`direction` pair; second click toggles direction.
- `ContainerDetail.test.tsx` (+1 case) — 'Ref #' header click reorders the packing-lists sub-table purely client-side (`packingListApi.listByContainer` called exactly once, never re-fetched for a sort).
- `frontend/src/hooks/useTableSort.ts` (new, no dedicated test file — exercised indirectly through the three page test suites above; the toggle/default-direction logic is simple enough that page-level coverage was judged sufficient over a redundant unit test).

### Manifest Import Tests (migration 040, `tests/unit/test_import_manifest.py`, 2026-08-23)

New parser (`services/excel/import_manifest.py`) and orchestration
(`services/excel/service.py::process_manifest_import`) for `POST /v1/manifests/import` — see
`19_excel_import_export.md` §"Manifest Import". One synthetic in-memory workbook
(`_build_combined_workbook`) covers both real column layouts observed in the same source file (bale-type
goods and carton/bag goods), header metadata scan, and an on-hold red-font row, exactly as required by the
plan rather than two separate single-layout fixtures.

- `TestHeaderMetadataScan` — PARTIAL NO / LOADING DATE / PORT / ARRIVAL DATE / DEPARTURE DATE label:value
  pairs above the tabular data are correctly scanned into container metadata.
- `TestBothColumnLayouts` — bale-type row (`BALE NO.`/`BALE TYPE`/`KG` columns, no `QTY`) defaults to
  `quantity=1` with `package_unit` from `BALE TYPE`; carton/bag row (`Qty Ctns/Pkg`/`Meas.`/`Port` columns)
  parses `"17CTNS"` → `quantity=17, package_unit='carton'` and `"3BAGS"` → `quantity=3, package_unit='bag'`.
  Both layouts appear in the *same* sheet, separated by a second header row — this caught a real bug during
  development: the parser originally resolved one static header row for the whole sheet, so the second
  layout's header row was mis-parsed as a data row (see `_match_header_row`/re-detection fix in
  `import_manifest.py`).
- `TestOnHoldDetection` — a row with red-colored font (`openpyxl` `Font(color="FFFF0000")`) is marked
  `on_hold=True`; an unmarked row in the same sheet is not.
- `TestQuantityUnitParsing` — direct unit tests of `_parse_quantity_unit` for `"17CTNS"`, `"3BAGS"`,
  `"1CTN"`, blank, and `None`.
- `TestProcessManifestImport` (repository mocked via `patch.object(service.repo, ...)`, same pattern as
  `test_manifest.py`):
  - `test_auto_creates_new_container_and_customers` — a manifest whose container and all four customers
    are new results in `containers_created=1`, `customers_created=4`, one packing list + one item per row.
  - `test_matches_existing_container_without_overwriting_fields` — when `find_container_by_number` returns
    an existing row, `create_container` and `create_packing_list` (for an already-existing packing list)
    are asserted **never called** — the auto-creation-only-at-creation-time guarantee.
  - `test_dedupe_skips_existing_delivery_note` — when `find_existing_item_by_delivery_note` always returns
    a match, every row is skipped: `items_created=0`, `items_skipped_duplicate=4`,
    `insert_manifest_items` never called.
  - `test_rejects_file_key_outside_tenant_prefix` — cross-tenant S3 key guard, same pattern as the existing
    importer.

Live verification (not unit-testable, run manually against the local stack post-migration — see
`19_excel_import_export.md` §"Manifest Import" and the ground-truth-gap note there): hand-built a real
`.xlsx` (`build_manifest_xlsx.py`, openpyxl) transcribing sample rows in both layouts under one
`PARTIAL NO: STL377` container, uploaded and imported via the real presigned-url → S3 → `POST
/v1/manifests/import` flow. Confirmed via `psql`: container created with correct `ship_date` /
`departure_date` / `estimated_arrival_date` / `destination`; 4 customers created and matched by phone;
packing lists in `draft` status with valid `reference` values; items with correct `quantity`,
`package_unit`, `delivery_note_number`, `bale_no`, `original_receipt_number`, `delivery_zone`, `on_hold`. Then:
hand-edited the container's `destination`/`notes` directly in the DB, re-uploaded and re-imported the exact
same file — confirmed the hand-edit survived (`create_container` not re-invoked) and item count stayed at
4 with `items_skipped_duplicate=4`, `items_created=0` in the response. Also re-ran the *existing*
`POST /v1/packing-lists/import` live end-to-end after the `packing_list.reference` fix (below) to confirm
zero regression.

**Ground-truth gap found and fixed during this task:** `services/excel/repository.py::create_packing_list`
(shared by both importers) never supplied `packing_list.reference`, which migration 031 made `NOT NULL`.
Every real (non-mocked) run of `POST /v1/packing-lists/import` would have raised a `NotNullViolation` —
masked because the unit suite mocks the repository layer entirely. Found live during this task's first
end-to-end manifest-import run. Fixed with a new `get_next_pl_reference()` helper (mirrors
`services/packing_list/repository.py`'s existing implementation) wired into both importers' `create_packing_list`
calls; see `19_excel_import_export.md`'s "Implementation notes / ground-truth gaps found" section.

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


### Manifest import — real-export regression suite (`tests/unit/test_import_manifest.py`)

`TestRealExportShape` and `TestContainerMetadataDates` are pinned to the structural quirks of a
genuine `STL409` export supplied by the user. Every one of them corresponds to a defect the
synthetic fixtures missed: the first run of the real file parsed **0 of 87 rows**.

| Test | Defect it pins |
|---|---|
| `test_reads_every_sheet_not_just_the_active_one` | Parser read `wb.active` only; real exports split layouts across `Master-BALES` + `Master-CTN GOOD`, so one whole class of goods was dropped |
| `test_metadata_value_columns_right_of_label_and_misspelled_arrival` | Values sit several columns right of their label, and the source misspells `ARRIVEL DATE` |
| `test_two_row_header_does_not_clobber_the_column_map` | The unit sub-header row was accepted as a fresh header and replaced the real column map, failing every data row |
| `test_double_spaced_alias_and_bale_type_normalisation` | `DLVY  NO.` (double space) missed the alias table; `BIG BALE` needed to normalise to `bale` without losing the type |
| `test_compound_and_annotated_quantities` | `1PALLET(61items)` and `3bags2ctns1pallet` both failed a single-pair regex |
| `test_total_and_footer_rows_are_skipped_not_reported_as_errors` | `TOTAL:` / `CLOSE CONTAINER ITEM:` rows surfaced as bogus "customer name required" errors |
| `test_native_excel_date_cells_survive_to_a_parsed_date` | Excel date cells stringified to `2026-07-04 00:00:00`, matching no format — every container date imported NULL |

**Live cross-check against the source document's own totals.** The real export declares its own
`TOTAL:` figures, which gives an independent checksum no unit test can fake: after importing,
`SUM(cbm) = 72.55` and the carton/package quantity sum `= 419` match the sheet's declared
`CBM: 17.65 + 54.9` and `CTNS/PKGS: 419` exactly. Re-importing the identical file is idempotent
(`items_created: 0`, `items_skipped_duplicate: 81`).

### Customer account-creation invites + self-register FK fix (migration 042, 2026-09-01)

New: `tests/unit/test_phone.py`, `tests/unit/test_invites.py`; extended:
`tests/unit/test_tenant_management.py`, `tests/unit/test_cognito_client.py`,
`tests/unit/test_import_manifest.py`.

- `test_phone.py::TestNormalizePhone` — `08012345678` and `+2348012345678` normalise to the same
  E.164 value; punctuation/whitespace tolerant; blank/unparseable input returns `None`; default dial
  code is Nigeria's `234`. `TestDialCodeForCountry` / `TestMaskPhone` cover the lookup table fallback
  and the `+23480****678`-style masking used in `customer_invite.sent_to_masked`.
- `test_invites.py::TestMintAndHashToken` — `mint_token()` is non-deterministic and URL-safe;
  `hash_token()` is a plain SHA-256 hex digest that never contains the plaintext token.
  `TestIsInviteValid` — `None`, consumed, and expired invites are all invalid; a fresh unconsumed
  invite is valid; string vs. naive-vs-aware `expires_at` values (as Postgres/psycopg2 may hand back)
  don't crash the comparison.
- `test_tenant_management.py::TestSelfRegisterCustomer` — **the FK regression test the plan called
  for**: `test_creates_tenant_user_and_links_customer_user_id` asserts `repo.create_tenant_user` is
  called with the Cognito sub and `role='customer'`, and that `repo.create_customer`'s `user_id` is
  the *tenant_user row's id*, not the bare sub — pinning `customer.user_id` to a real `tenant_user`
  the way its `FOREIGN KEY REFERENCES tenant_user(id)` requires. Plus explicit-slug tenant resolution,
  unknown-slug 404, duplicate-email 409.
- `test_tenant_management.py::TestIssueCustomerInvite` / `TestAcceptCustomerInvite` — issuing deletes
  prior unconsumed invites first (resend invalidates the old link); refuses a customer who already has
  `user_id` set; `accept_customer_invite` has the same FK-regression assertion as self-register (its
  own `create_tenant_user`/`update_customer` call), then marks the invite consumed; expired, consumed,
  and unknown tokens all 404 before any Cognito call is attempted.
- `test_cognito_client.py::TestCreateUserWithPassword` (moto-backed) — the invite-claim path's Cognito
  call sets a **permanent** password directly (`UserStatus == 'CONFIRMED'`, no temp-password email,
  no `NEW_PASSWORD_REQUIRED` challenge on first login) and raises `DuplicateResourceError` on a
  repeat email, exercising the real boto3 call shape rather than a `MagicMock`.
- `test_import_manifest.py::TestProcessManifestImport` extended — asserts `issue_customer_invite` is
  called once per **newly created** customer and never for a phone/name match against an existing one
  (`mock_issue_invite.assert_not_called()` on the match-only case); `get_tenant_destination_country`
  mocked across all three `process_manifest_import` cases now that phone normalisation resolves a
  dial code up front.

Live verification (not unit-testable — see `LOCAL_TESTING.md` and the plan's Verification section, run
against the running local stack): migration 042 pre-flight duplicate report and unique-index creation;
RLS blocks a cross-tenant invite read; re-imported STL409 and confirmed invites issued + visible in
`notification_log`; claimed a real invite end-to-end and logged in as that customer to see their
shipment's transit status; reuse/expiry/resend of the same token; self-signup via `/register/{slug}`
end to end confirming the FK bug is gone. Full log in `00_MASTER_PLAN.md` row 7.52.

## Backend debugging pass — tenant-isolation drift, SSRF, infrastructure contracts, lint/type gates (2026-09-23)

**Tenant-isolation tests had drifted from the code.** Four tests failed on a clean checkout:
`test_list_passes_jwt_tenant` (mock returned a 3-tuple; `service.list_packing_lists` has returned a 4-tuple
`(page, next_cursor, has_more, total)` since the count feature), and three `test_db_isolation.py` cases that
called through to a real DB (`KeyError: 'DATABASE_HOST'`) because later features added unmocked calls:
`get_cbm_rate_config` / `get_effective_dollar_rate` / `repo.get_cbm_by_package_type` in `handle_payment_due`
(module-level imports, so `patch.object(service.repo, …)` cannot intercept them — they must be patched at
`services.billing.service.<name>`), `resolve_container_id` / `get_container_status` / `get_next_claim_reference`
in `file_claim`, and `get_tenant_short` / `get_next_receipt_number` / `log_audit` in `confirm_payment`. Fixed by
mocking them; the tests still assert what they exist to assert — that `tenant_id` is the first argument to
every repo call.

**New: `tests/unit/test_url_safety.py`** (44 cases) — `validate_public_https_url` (accepts public hosts; rejects
http/file/ftp, embedded credentials, localhost/.internal/.local, RFC1918, link-local/metadata `169.254.169.254`,
CGNAT, `0.0.0.0`, `::1`, `fe80::`, `fd00::`, IPv4-mapped private, and the numeric forms `2130706433`, `0x7f.1`,
`127.1`), `resolve_public_ips` (a multi-record answer with one private record is refused; unresolvable is
refused), `open_public_https` (no connection is attempted for a private target; redirects aren't followed; the
connection goes to the validated IP with SNI on the hostname; falls back across validated IPs), webhook delivery
(`fire_tenant_webhook` never raises or connects for an unsafe or malformed URL), and the
`WebhookConfigRequest` save-time validator. Also verified once against real TLS (not in the suite — needs
network): pinned-IP delivery succeeds, a redirect to the metadata IP surfaces as 302 and is not followed, and a
hostname-mismatched certificate still fails verification.

**New: `tests/unit/test_infrastructure_contracts.py`** (26 cases, file parsing only) — every frontend API call has
an API Gateway route; every route targets a service key the lambda module actually exposes (catches the silent
`active_routes` drop); route keys are unique; every Lambda `handler` in Terraform resolves to a function that
exists in `services/`. Confirmed non-vacuous by running it against the pre-fix Terraform from git: it reported 22
unroutable frontend calls, the orphaned metering route, and all three `notification.handler.lambda_handler`
references.

**New: `tests/unit/test_sort_injection.py`** (51 cases) — a **CRITICAL SQL injection** in `?sort=` on
`GET /v1/billing|claims|containers`, found while auditing bandit's B608 findings: `build_paginated_query` validated
only `sort_field.split(".")[-1]` against the allowlist but interpolated the whole string into `ORDER BY`, so
`id,(select pg_sleep(5))::text,b.created_at` passed as `created_at` and ran (reproduced against Postgres: 2.2s vs
0.1s; the existing regression test used `"injected; DROP TABLE"`, which has no trailing `.created_at` and so never
exercised the bypass). Fixed at the choke point (`fullmatch` of `identifier[.identifier]` plus allowlisted column).
Tests: 17 hostile payloads (each ending in a real allowlisted column so the *old* validator accepted them — stacked
statement, subquery, `desc,id`, double dot, trailing newline/space/NUL, quoted identifier…) × with and without a
cursor; legitimate aliased/negated fields still work; a non-allowlisted column is still refused; a hostile
`sort_direction` cannot carry a payload; and, for billing (staff **and** customer), claims (staff **and** customer)
and containers, the real handler → service → repository → builder chain returns `422` with `execute_with_tenant`
wired to raise if any query is sent at all. Confirmed non-vacuous against the pre-fix `pagination.py` from git.

**New: `tests/unit/test_safe_filename.py`** (33 cases) — `safe_filename` (traversal, backslash paths, quote/`filename*=`
breakout, CRLF, bidi override, hidden/dot-only names, non-strings, length cap keeping the extension, and that Chinese
and `IMG (1).jpg` names are preserved), each of the four upload flows (the S3 key **and** the stored name are the
sanitised value, and an unusable name is a `422` before any S3 call), and both `Content-Disposition` builders for
legacy unsafe rows.

**Lint/type gates are now clean** (`make check`): `ruff` 89 → 0 (48 import-sort and 9 unused-import autofixes; SLA
constants hoisted out of `_fmt_dispute`; dead local removed; four over-long lines wrapped; test-only
`S105/S106/S107/N803/N814` added to `tests/**` per-file ignores in `pyproject.toml` — fixture strings and boto3-style
kwargs, not credentials), `mypy` 31 → 0. The mypy pass also removed real hazards: an unguarded `None`
dereference in the payment-verify race path (`current["status"]` when the billing row vanished), `Decimal | float`
from `sum()` in the Bybit averaging, and count-based release maths that mypy showed could see `None`.

## Notification delivery tests (added 2026-09-06)

`tests/unit/test_whatsapp_first.py` covers WhatsApp-first routing and the SMS
fallback. Four production defects survived the original suite because the fallback
tests stub `get_log_for_fallback` to *return* `customer_id` and `locale` — they
asserted the stub, not the code that was supposed to supply those values.

Added classes assert the **inputs** instead:

- `TestFallbackInputsArePersisted` — the enqueued SQS message carries `customer_id`,
  and `log_queued` persists `locale`.
- `TestSendResultsAreHonoured` — a `False` return from `send_sms` records `failed`
  and meters no usage (it previously logged `sent` and billed for a message that
  never left), and a WhatsApp failure's `error_detail` names Meta's own code rather
  than a generic "raised an exception".

Each was verified to fail when its fix is reverted. **A stub that supplies the value
under test cannot detect its absence** — when a test mocks the layer that produces
the data, add a companion test asserting the producer.

## Frontend e2e coverage sweep (2026-09-06)

`frontend/e2e/flows/smoke-navigation.spec.ts` drives directly off the real
`navConfig` export (not a hand-maintained route list, so it can't drift): for
every role, click every item its own nav renders and assert no error banner
and a `<main>` region is present. Cheap, broad net for "this route 500s or
renders blank" across the ~30 destinations no dedicated flow spec visits.

**Found live, not hypothetically:** running it surfaced a real connection-
poisoning bug in `shared/db.py` (see `02_shared_utilities.md`'s "connection
self-heal" entry) that was intermittently crashing arbitrary pages with
"Internal server error" — fixed there, verified by re-running this exact
sweep clean.

## Frontend e2e — real login/logout lifecycle (2026-09-13)

`frontend/e2e/flows/auth-logout.spec.ts` (new) drives a real Cognito-via-Moto
login/logout/reload cycle against the running local stack — claim a real
invite, log in with the resulting credentials, log out, and assert `/login`
(not a still-authenticated dev-shim page); reload and confirm it stays there;
navigate straight to a protected route and confirm the bounce-back; log back
in and confirm it still works. Added alongside the `LocalAuthProvider` fix in
`frontend/04_auth_and_session.md`'s "Explicit logout must not resurrect the
dev-shim session" entry — the existing `flows/auth.spec.ts` only exercises the
dev role-switcher, never a real Cognito login, so it could not have caught
this bug at all.

**Known flakiness, not a regression:** this file's 4 cases each mint a fresh
invite via `mint_test_invite.py` (shelled out per test, same helper
`customer-invite.spec.ts` already uses) — at the suite's default parallelism
that setup step intermittently times out under concurrent DB/Moto load. All 4
pass reliably run serially (`--workers=1`); this is a pre-existing property of
the shared invite-minting helper under concurrency, not something this spec
introduced.

Also added: `manifest-import.spec.ts` (real `.xlsx` upload through Moto's S3
endpoint), `customer-invite.spec.ts` (a real invite minted via
`scripts/mint_test_invite.py` — the API never returns a raw token — then
claimed end to end), `container-list.spec.ts` (search/filters/sort),
`bulk-packing-list-actions.spec.ts` (found the "Submit for approval"
unreachable-checkbox bug documented in `08_api_packing_list.md`).

`tests/unit/test_db_connection_healing.py` covers the self-heal directly:
a connection left `TRANSACTION_STATUS_INERROR` gets rolled back before use;
a healthy one is returned untouched (no unnecessary rollback); `None`
still creates a fresh connection. Uses `setup_method`/`teardown_method`
(not `setup_function`/`teardown_function`) to reset `shared.db._connection`
between tests — the module-level hooks silently don't apply inside a test
class, which the first version of this file discovered the hard way: a mock
connection leaked from one test into the next, and from there into an
unrelated file (`test_scheduled_jobs.py`) in the same pytest session.

## Deep interaction e2e specs (2026-09-06)

Beyond the smoke sweep, real multi-step interaction flows against the live
local stack — each one chained through a genuine business process rather
than testing one screen in isolation:

- `manifest-verify-and-advance.spec.ts` — verify a pending manifest, then
  advance its container `loading` → `sealed`. The exact chain from an
  earlier session bug report ("container must have a manifest"). Confirmed
  by reading the database afterward, not just the UI: the container is
  genuinely `sealed`, the manifest genuinely `verified`.
- `billing-payment-and-release.spec.ts` — record a payment, generate a
  release note (including the "release with outstanding balance" manager-
  override path), record its pickup. Found two real, previously-undetected
  bugs (see `13_api_payment_release.md` and `frontend/07_domain_modules.md`):
  a page-crashing null-safety bug in the tenant dashboard, and a completely
  broken non-delegate pickup path. Confirmed each fix by reading the
  database afterward — `release_note.status = 'picked_up'`, not just a
  green checkmark in the test runner.

Both specs mutate real seeded data (not isolated fixtures) and are written
to be idempotent on re-run — each step checks the record's current state
and skips cleanly if a previous run already advanced it, rather than
assuming a fixed starting point.

**Testing-gap pattern repeated here, worth naming explicitly:** every bug
these two specs found was invisible to the existing unit suite, because
unit tests mock the layer where the bug actually lived (a component's own
`.replace()` call, a cross-service SQL upsert, nine copies of the same
error-formatting function) rather than exercising it. Matches the exact
caveat already recorded in `13_api_payment_release.md`'s two earlier
ground-truth fixes for the pickup endpoint.

## cbm-rate-config.spec.ts (2026-09-20)

New e2e coverage for the CBM rate config page (currency + flat/per-package-
type modes — full account in `frontend/07_domain_modules.md`'s "CBM rate"
entry). Directly caught a real, otherwise-invisible bug: `get_cbm_rate`'s
`Decimal` values serialized as JSON *strings* (`shared/responses.py`'s
`success()` uses `json.dumps(..., default=str)`) while `update_cbm_rate`'s
response (already `float`-cast) returned JSON *numbers* for the same
field — the page crashed on load (`config.carton_rate.toFixed is not a
function`) since the frontend types these as `number`. Every Vitest test
for this page mocks `configApi.getCbmRate()` to return a plain JS number
literal directly, so it never exercises real JSON serialization at all —
this class of bug is structurally invisible to a mocked unit test and was
only caught by loading the real page against the real backend. Two cases:
loading in both modes without crashing, and a full `PUT` → reload → confirm
persisted round-trip (restores the tenant's rate to its original value
afterward so it doesn't drift shared config for other tests/manual use).

## Release-note migration-041 fields + split e2e coverage (2026-09-20)

`billing-payment-and-release.spec.ts` (above) predates all of the migration-041
release-note field completeness work (2026-09-13) and only exercises the
original carton-tag generate → pickup path — none of warehouse selection,
document/invoice numbers, count-based release, the officer pickers, print
view, PDF export, or split had any frontend e2e coverage until this pass.
Full account of what was found and fixed (a count-based-release UI gap, a
backend duplicate/over-release guard, a stale release-note-list query cache)
in `frontend/07_domain_modules.md`'s "Release flow audit" entry and
`13_api_payment_release.md`'s "Duplicate / over-release guard" section.

New specs, both following the same real-seeded-data + `test.skip()`
idempotency convention as `billing-payment-and-release.spec.ts` (a genuine
run only succeeds once per fixture; re-runs correctly skip rather than
fail):

- `release-note-migration-fields.spec.ts` — count-based generation with
  warehouse/document-number/invoice-numbers, detail-page field rendering,
  pickup with the warehouse/CSO/accounting-officer pickers, print view
  content, PDF export (a `download` event, not a `popup` — Chromium has no
  PDF viewer plugin in this project's browser config, so `window.open` to a
  PDF URL is treated as a file download; confirmed via trace inspection
  before writing the assertion).
- `release-note-split.spec.ts` — generate a two-tag release note, split one
  tag into a child note, confirm the child shows up as a second row on the
  list.

**A real, repeatable race found writing these:** navigating to
`/release-notes` and immediately checking `page.locator(...).count()` for a
row can return 0 even though the row exists, because the list's data fetch
starts on mount (a tick after the nav click resolves) while a one-shot
`.count()` doesn't wait — it can catch the `Table` component's loading
skeleton (5 blank `<tr>`s) instead. `page.waitForLoadState('networkidle')`
does not reliably fix this (it can resolve in the brief window before the
fetch even starts). Fixed everywhere this list is checked right after a nav,
across all three release-note spec files, with an auto-retrying
`expect(locator).toHaveCount(1, { timeout: 10_000 })` instead.

## App-wide responsive pass — Table.tsx card view + responsive_smoke.spec.ts (2026-09-20)

Full account of the pass this coverage belongs to (why it was needed, what
was found, what changed) is in `frontend/07_domain_modules.md`'s "App-wide
responsive pass" entry and `frontend/03_component_library.md`'s matching
addendum.

**`Table.test.tsx`** (7 → 15 cases): new `describe('mobile card view (width
<= 860px)')` block covers card rendering when the wrapper's measured width is
≤860px (stubbed via `HTMLElement.prototype.getBoundingClientRect`, since
jsdom always reports an all-zero rect and never evaluates `@container`
queries at all) — column 0 as card header, a trailing empty-title column as
the action row, every other column as a label:value pair, the
`hideInCard` escape hatch, `selected`/`suspended` row-state styling
carrying through to the card, and the loading-skeleton/empty-state card
variants. Plus one top-level case confirming the table markup still renders
unchanged at a wide measured width (regression guard for the other 29 pages'
existing `getByText()` row assertions, which would become ambiguous if both
markups ever rendered at once). `frontend/src/test/setup.ts` gained a
`ResizeObserver` polyfill (absent before this pass) since `Table.tsx`'s
`useIsNarrow` hook needs one to measure its wrapper at all.

**`CustomerTopNav.test.tsx`** (+4 cases, new `describe('mobile drawer
(inside a CustShell)')` block): hamburger opens the drawer and shows the nav
links a second time (once in the always-rendered horizontal bar, once in the
drawer), clicking a drawer link closes the drawer and still navigates and
marks the link active, clicking the overlay closes it, Escape closes it.
Plus one new case confirming no hamburger renders when there's no
`ShellDrawer` context (i.e. `CustomerTopNav` rendered standalone, outside a
`CustShell`).

**`e2e/flows/responsive_smoke.spec.ts`** (new, permanent — this started as a
throwaway debugging script during the pass and was kept, since it's the only
signal that actually caught the two overflow bugs below): all 5 cases run at
a fixed 375×800 viewport against the real local stack, with a shared
`assertNoHorizontalOverflow()` helper that scans every DOM element for
`scrollWidth` exceeding `document.documentElement.clientWidth` and logs the
worst 10 offenders before asserting none exist.

- `BillingList` renders the `Table` card view (zero `<table>` elements) with
  no overflow.
- `BillingDetail`'s hero action-button row (up to 4 buttons) has no overflow.
- `PackingListList`'s bulk-selection toolbar, triggered via a real row
  checkbox click (not just loaded — the toolbar only renders once something
  is selected), has no overflow.
- Customer `Account` page has no overflow across all three tabs (Profile /
  Notifications / Privacy).
- The customer-portal hamburger opens the drawer, a drawer link navigates to
  a different page, and the hamburger is present again there (confirms the
  drawer isn't just visually present but actually wired to `ShellDrawer`
  end-to-end).

**Two real overflow bugs live-verified and fixed this way**, neither
catchable by jsdom-based unit tests (jsdom has no layout engine and never
evaluates `@container`/`@media` at all): `BillingList`'s stats row was a
fixed `repeat(4, 1fr)` grid that stayed wider than the phone viewport even
after the `Table` card view landed; `TopBar`'s injected page-action buttons
(e.g. BillingList's Export/Generate-billing) didn't fit at 860px even with
search/role-switcher/user-text already hidden, because `.topbar` had a fixed
`height: 64px` with no way for a second action to wrap onto its own row.

**Test-writing gotchas found using existing e2e support helpers at a mobile
viewport** (worth flagging since `roleSwitch.ts`'s helpers predate any
mobile-viewport test): `goToViaNav()` clicks the staff `Sidebar`'s nav
buttons directly, which are hidden behind the mobile hamburger drawer at
≤860px — it only works at the default desktop viewport. Mobile-viewport
specs navigate via `page.goto(path)` instead. The customer-drawer's nav
items (`CustNavLink`) and the `Check` selection primitive both render as
`role="checkbox"`/plain `<button>`, not native `<input type="checkbox">` /
`<a>` — `getByRole('checkbox')` / `getByRole('button', { name: ... })` are
the correct queries, not a CSS-attribute selector or `getByRole('link')`.

## claims-and-refunds.spec.ts (2026-09-06)

Chains the full real business process — customer files a damage claim,
staff inspects and resolves it as a refund, the resulting refund request
goes through accounts review, and is either approved (tenant_admin, for the
over-threshold case) or rejected. No claims or refunds existed in seed data
at all before this spec created the first ones.

**Found three real bugs, none from code review — from actually running the
chain:**
1. Filing a claim by container *number* (what a customer actually sees, per
   the form's own placeholder) crashed every time — the backend only ever
   accepted a raw UUID.
2. The staff-approval refund threshold was completely dead code —
   `nigeria_office_staff` could resolve a refund of any size with no
   escalation, confirmed by resolving a ₦500,000 refund with zero rejection.
3. Every claim-triggered refund's page title rendered blank —
   `refund_type` was never set at the point of creation.

Full account of all three in `12_api_claims.md`'s "Ground-truth gaps found"
and `14_api_refunds.md`'s matching entry.

**Same pattern as the billing/release-note chain before it:** every one of
these was invisible to the existing unit suite, which mocks the exact layer
where each bug lived (a repository function's own SQL, a request field the
tests always populated by hand even though the real frontend never sends
it, a switch statement's missing default). The fix in each case was
confirmed by reading the real database afterward — a genuinely resolved
`damage_claim`, a `refund_request` with the right `refund_type` and status
— not by the test runner going green alone.

## Follow-up sweep after the claims/refunds chain (2026-09-06)

Prompted by finding three real bugs in one chained flow, swept the codebase
for the same *shapes* of bug elsewhere rather than only moving on to the
next untested page:

- **Other label-rendering switch statements with no default** (the exact
  shape of the `refundTypeLabel` bug): found 10 more across `nigeria/`,
  `customer/` pages and `releaseNotesRules.ts`. All are backed by `status`
  columns that are `NOT NULL DEFAULT '...'` at the DB level — confirmed via
  `information_schema.columns` — so none carry the same live risk
  `refund_type` did (nullable, no default, no code-level fallback).
  Left as-is; noted here so a future column-nullability change to one of
  these doesn't quietly reopen the same failure mode.
- **Other customer-facing free-text fields with number-or-UUID ambiguity**
  (the shape of the claims `container_id` bug): none found — that was the
  only one.
- **Other places checking a request field the real frontend never
  sends**: led directly to `customer-refund-request.spec.ts`'s finding
  below — a second, worse instance of the same *class* of bug (a frontend
  comment asserting server behavior that was never implemented).

`customer-refund-request.spec.ts` — RefundRequest.tsx's self-service
"Request a Refund" flow, reachable from every customer's billing page, had
**never worked for any customer**: the endpoint's role check excluded
`CUSTOMER` outright (a 403 on every attempt), and behind that,
`customer_id` was read directly from a request field the frontend
deliberately sends empty (per its own code comment, on the assumption the
server would derive it from the session — it never did). Full account in
`14_api_refunds.md`. Confirmed fixed by reading the resulting
`refund_request` row in the database — correctly attributed to the
submitting customer, not empty or mismatched.

## MyShipments.test.tsx (2026-09-06)

Found live while testing the customer-invite login flow end to end (not by
this spec — by hand, logged in as a real customer with 3 simultaneously
active shipments): `MyShipments` only ever rendered `activeShipments[0]`
as a single "Active shipment" feature card, silently dropping every other
shipment still in transit from the page entirely — they weren't even
listed in a table, since "Past shipments" only covers
`fully_released`/`cancelled`. Fixed by rendering the same card once per
active shipment in a stack instead of indexing into the array; see
`frontend/07_domain_modules.md`'s matching entry. `MyShipments.test.tsx`
(new) regression-guards both the plural case (3 active shipments → all 3
cards render, `Active shipments (3)` heading) and the singular case (1
active shipment → singular `Active shipment` heading, not the pluralized
form with a count of one).

## Claims could be filed before a shipment arrived (2026-09-06)

Reported directly by the user, not found by a test. Neither
`services/claims/service.py::file_claim` nor `MyClaimsNew.tsx`'s free-text
container field checked whether the container had actually arrived — a
customer could file (and staff would then investigate) a damage claim
against cargo still `loading` or at sea. Full account in
`12_api_claims.md` and `frontend/07_domain_modules.md`.

Backend: `tests/unit/test_claims.py::TestClaimStateMachine` gained
`test_cannot_file_claim_before_container_arrives` (parametrized over
`loading`/`sealed`/`in_transit` — all raise `BusinessRuleViolationError`,
`create_damage_claim` never called) and
`test_can_file_claim_once_container_has_arrived` (parametrized over
`arrived`/`customs_clearance`/`cleared`/`at_warehouse`/`fully_released` —
all still succeed, proving the fix doesn't over-block). The two
pre-existing tests that call `file_claim()` were updated to mock the new
`repository.get_container_status()` call (an unmocked real DB call would
otherwise `KeyError` on `DATABASE_HOST` under pytest — caught immediately
by running the suite, not discovered later).

Frontend: `MyClaimsNew.test.tsx` (new) covers the redesigned step 1 —
zero eligible shipments shows the explanatory banner with no combobox and
no submit button; a mix of statuses lists only the arrived ones in the
dropdown; submitting sends the selected shipment's real container number,
not a free-text value.

Verified live end-to-end against the local stack, not just the test
runner: `curl POST /v1/claims` for a `loading` container returned `422
CONTAINER_NOT_ARRIVED`; the same call against an `at_warehouse` container
returned `201`. Both test claims were deleted from the database afterward.

## Billing money-clarity + manual-payment-claim flow (2026-09-06)

Two related pieces of user feedback in the same session: "misc fees" doesn't
say what it's for (plus a broader ask to check the same surface for other
unclear-money issues), and a request to add a customer confirmation step
with mandatory evidence for manual bank transfers. Full account in
`frontend/07_domain_modules.md`, `07_api_tenant_management.md`,
`13_api_payment_release.md`, and `19_excel_import_export.md`.

**Backend, `tests/unit/test_payment_release.py`** — new `TestSubmitPaymentClaim`,
`TestListPaymentClaims`, `TestConfirmPaymentClaim`, `TestRejectPaymentClaim`
classes: ownership guard (a customer can't submit/list against another
customer's billing, mirroring the exact shape of `12_api_claims.md`'s
container-ownership fix), the fully-paid/waived billing guard, the
one-pending-claim-per-billing conflict returning a clean 422 (not a raw
`IntegrityError` 500 — found live during manual testing, see below), and
`confirm_payment_claim()` proven to go through the *real* `confirm_payment()`
function rather than mutating billing directly.

**Backend, `tests/unit/test_excel.py`** — `test_invoice_names_each_fee_instead_of_a_bare_total`
asserts the exported invoice's itemized fee string names each charge by
description, and that the full breakdown columns (`total_cbm`,
`cbm_rate_usd`, `subtotal_ngn`, `amount_paid_ngn`, …) are present — not the
old 7-column bare-total export.

**Backend, `tests/unit/test_tenant_management.py`** — `test_customer_can_read_config`
(renamed from `test_customer_cannot_read_config` — a deliberate policy
change, not a regression: `GET /v1/tenant/config` now allows `CUSTOMER`)
and `test_update_tenant_config_saves_bank_transfer_config`.

**Found live, not just in unit tests:** the first version of
`create_payment_claim()`'s INSERT had no `ON CONFLICT` clause at all,
relying on the partial unique index (`idx_payment_claim_one_pending_per_billing`)
to reject a second pending claim — which it did, but as a raw
`IntegrityError` surfacing to the caller as a bare `500`, not the intended
`422 PAYMENT_CLAIM_ALREADY_PENDING`. Caught by manually exercising the
duplicate-submission path against the real local stack (not by a unit test,
since the mocked repository layer never touches a real constraint) — fixed
with `ON CONFLICT (billing_id) WHERE status = 'pending' DO NOTHING RETURNING *`,
then verified the corrected 422 live.

**Frontend, `src/pages/customer/MyBillingDetail.test.tsx` and manual
verification** — the existing test file continues to pass with the new
`configApi.getConfig()`/`paymentClaimApi.listForBilling()` calls (both
`.catch()`-guarded, so an unmocked call in tests degrades to an empty/null
state rather than hanging or throwing). The full flow — real bank details
from tenant config, mandatory evidence upload gating the submit button, and
the resulting "pending review" status banner — was verified through an
actual browser session against the local stack rather than only asserted in
jsdom: logged in as a seeded customer, opened bank transfer details,
uploaded a file, submitted, and confirmed the pending-claim banner rendered
with the correct amount, date, and filename.

## Payment-claim staff review + double-payment prevention (2026-09-07)

Same-day follow-up after the user started using the payment-claim feature
and asked how staff actually confirm one, then separately caught a real
double-payment risk while reviewing the answer. Full account in
`13_api_payment_release.md` and `frontend/07_domain_modules.md`.

**Backend, `tests/unit/test_payment_release.py`** — new
`TestGetPaymentClaimEvidenceUrl`: staff can view any claim's evidence,
a customer can view their own, a customer cannot view another
customer's (mirrors the exact ownership-guard shape used throughout this
feature), unknown claim 404s.

**Frontend, `src/pages/nigeria/BillingDetailPaymentClaims.test.tsx`** (new)
— the staff-side review UI: a pending claim renders with Confirm/Reject;
confirming calls `paymentClaimApi.confirm` and the billing view reflects
the new paid status; rejecting is disabled until a reason is typed, then
calls `paymentClaimApi.reject` with it; clicking the evidence filename
opens the presigned URL via `window.open`; a billing with no claims at all
renders no "Payment claims" section (positive-and-negative coverage, not
just the happy path).

**Frontend, `src/pages/customer/MyBillingDetailPaymentClaim.test.tsx`**
(new) — regression-guards the double-payment fix directly: a pending claim
hides both "Pay online" and "Show bank details" and shows the awaiting-
confirmation banner; a rejected claim (nothing pending) shows the rejection
reason *and* restores normal payment options; no claims at all renders
normally. **This test caught a real bug before it shipped**: the first
version rendered the rejection-reason banner twice (once new at the top
level, once from the pre-existing `PaymentClaimPanel`, which auto-expands
whenever the customer has any claim history) — `findByText` failed with
"found multiple elements," not a false pass. Fixed by removing the
now-redundant inner banner and its dead `pending`/`mostRecent` computation
from `PaymentClaimPanel`, which only ever renders once the parent has
already confirmed there's nothing pending.

Verified live against the real API (not just mocks): `GET
/v1/payments/{billing_id}/claims` as staff correctly returned the user's
own real pending claims (submitted through the UI while testing this
feature themselves), confirming the whole chain — real evidence in S3,
real claim rows, real staff-role visibility — works end to end outside the
test suite too.

## Tenant-admin Activity Log + audit-log coverage gaps (2026-09-07)

User feedback: "we need to ensure that we have log trail for everything,
since it has to do with people's goods and money, so that the tenant admin
can see every activity going on." Full account in
`07_api_tenant_management.md`, `02_shared_utilities.md`, and
`frontend/07_domain_modules.md`.

**Backend, `test_tenant_management.py`** — `TestTenantActivityFeed` gained
`test_entity_type_filter_passed_through` and
`test_activity_rows_include_before_after_state`; new
`test_deactivate_writes_audit_entry` on `TestChargeTypes`.

**Backend, `test_claims.py`** — new `TestMissingSeizedItemAuditLogging` (5
cases): `log_missing_item`/`update_missing_item`/`log_seized_item` each
write the right `entity_type`/`action`, and the `refund_request` a
compensation/recovery triggers gets its own separate audit entry with the
right `entity_id`.

**Backend, `test_billing.py`** — new `TestRejectDisputeAuditLogging`,
confirming `reject_dispute` now logs like every other dispute transition.

**Backend, `test_import_manifest.py`** — updated to pass the new required
`ctx` parameter `process_manifest_import` needs for its audit-log call
(a real signature change caught immediately by running the suite, not
discovered later).

**Frontend, `ActivityLog.test.tsx`** (new) — renders real activity rows;
expanding "Details" shows the actual before/after JSON, not just that
something changed; changing the record-type filter re-fetches with
`entityType`; a row with no before/after state renders no Details button.

**Found live while building this, not by code review:** `shared.audit.
log_audit()` never raises on failure — by design, so audit logging can
never break a primary operation — but that also means a broken call
site fails completely silently, logged only as a WARNING nobody was
watching. Two call sites (`payment_release/service.py::
process_webhook_payment`, and a newly-written one in `billing/service.py::
handle_payment_due`) passed a non-UUID placeholder string
(`"gateway"`, `"system"`) into `actor_id`, a `UUID` column — every
webhook-confirmed payment had **silently never been audit-logged** since
that code existed. Reproduced directly against the real local DB
(`invalid input syntax for type uuid: "gateway"`), then confirmed the fix
(`actor_id=None`) writes a real row — this bug could not have been caught
by a unit test alone, since the mocked repository layer never touches a
real UUID column constraint.

Verified live against the real local stack, not just unit tests: `GET
/v1/tenant/activity?entity_type=payment_claim` returned the full real
history built up over this session's testing (real customer submissions,
a real staff confirmation) with correct `before_state`/`after_state`; the
new page rendered it correctly through an actual browser session, filter
dropdown and expandable diff both working.

## Activity Log — real filtering, search, sort, categorization (2026-09-07)

Same-day follow-up: the first Activity Log version's single "Record type"
dropdown "lacks fully functional filtering, sorting and search... we need
it to be properly categorized for easy filtering." Full account in
`07_api_tenant_management.md` and `frontend/07_domain_modules.md`.

**Backend, `test_tenant_management.py`** — `TestTenantActivityFeed` gained
handler-level passthrough tests for the category/multi-entity_type filter,
action filter, search query, date range, and sort direction (default and
override). New `TestListTenantActivityFiltersRepository` asserts the actual
SQL each filter produces against the real query string (`= ANY(...)` for
multiple entity types, the exact ILIKE clause for search, both date-range
bounds, `ORDER BY created_at ASC/DESC` for sort) and — the one that matters
most for an audit trail — that combining filters produces `AND`, never a
silent `OR` that would widen the result set past what the admin selected.

**Frontend, `ActivityLog.test.tsx`** — rewritten around the real filter set:
choosing a category sends every entity_type in it; picking a specific
record type within a category narrows further; switching category clears
a record-type selection that no longer belongs to it (and re-fetches with
the new category's types); the action filter, the debounced search box,
and the sort toggle each independently trigger a correctly-parameterized
re-fetch; "Clear filters" resets category/record-type/action/search/date
range together, verified by the resulting `configApi.activity()` call
having no leftover filter values, not just by the visible option resetting.

Verified live against the real local stack, not just mocks: Category →
"Money" returned exactly the 7 money-related entity types and narrowed the
Record-type dropdown to match; searching an actor's name isolated their
entries; switching to "Oldest first" changed the first visible row from
the newest real record to the oldest one.

## Activity Log UX + information-boundary fixes (2026-09-07)

Third same-day round of direct feedback: filter-bar alignment, "Details"
opening in the wrong place, impersonation records leaking into a tenant's
own view, and a systemic audit-log write failure found while fixing the
Action filter. Full account in `07_api_tenant_management.md`,
`02_shared_utilities.md`, and `frontend/07_domain_modules.md`.

**Backend, `test_impersonation_audit.py`** (new) — `start_impersonation`/
`end_impersonation` call `repository.insert_platform_audit`, never
`shared.audit.log_audit`; a regression guard asserts the module doesn't
even import `log_audit` anymore.

**Backend, `test_tenant_management.py`** — new
`TestTenantActivityExcludesPlatformOnlyRecords`: `impersonation_session`
is excluded from `list_tenant_activity()`'s results with no filters
applied, and — the case that actually matters — still excluded even when
a caller explicitly asks for it via `?entity_type=impersonation_session`.

**Frontend, `ActivityLog.test.tsx`** — new cases: a custom From/To range
sends `createdAfter`/`createdBefore`; setting a custom date clears and
overrides the day-preset selector; "Impersonation" appears in neither the
Category nor Record-type dropdown options.

**Found live while wiring up the Action filter, not by code review — the
largest single finding of the day:** a grep across every `log_audit()`
call site for action values outside `{CREATE, UPDATE, DELETE,
STATUS_CHANGE}` (`audit_log.action`'s CHECK constraint) turned up **20**
call sites across seven services silently failing on every call since
they were written — `EXPORT`, `CANCEL`, `RETRY`, `BULK_APPROVE`, and
sixteen others. Reproduced live (`invalid input syntax` was the wrong
mental model here — this is `new row ... violates check constraint`, a
different failure shape from the earlier `actor_id` bug but the identical
silent-failure *pattern*), then fixed with migration 045 (drop the
constraint, widen to VARCHAR(100), matching `platform_audit_log`'s
already-unconstrained design) and confirmed the exact same repro call now
writes a real row. No mocked unit test could have caught this — the bug
lived entirely in a real Postgres constraint the mocked repository layer
never touches, which is exactly why it had been invisible for as long as
the code existed.

Verified live end-to-end: the filter bar renders with every control's
bottom edge level (screenshot-confirmed); clicking "Details" opens a
centered modal regardless of which row was clicked; a custom "From"/"To"
range correctly narrowed the visible rows to the selected window; the
Category and Record-type dropdowns no longer list impersonation as an
option.

## Server-side stat endpoints — billing/claims/container/customer aggregates (2026-10-01)

Production-readiness pass (task 7.82) moved stat cards off capped client samples onto SQL aggregate endpoints. Backend unit coverage added alongside each endpoint:

- `tests/unit/test_billing.py` — `TestTenantReport` and `get_billing_stats` cases (outstanding/paid-this-month/overdue + per-status counts; the report's overview/claims/pipeline/top-customers/container-billing shape).
- `tests/unit/test_claims.py` — `TestClaimStats` (open/under-inspection/resolved-30d + per-status counts, service delegation scoped by `tenant_id`).
- `tests/unit/test_tracking.py` — `TestContainerStats` (per-status counts + `cleared_30d`, service delegation).
- `tests/unit/test_tenant_management.py` — `TestCustomerStats`: service delegation passes `tenant_id`; repository maps its **two** `execute_with_tenant` calls (customer aggregate row + `packing_list` count) into one dict and scopes both queries to the tenant; empty-tenant returns all-zero.

All four delegation tests follow `test_tracking.py::TestContainerStats`'s `patch.object(service.repo, …)` pattern. `GET /v1/customers/stats` was also verified live against direct SQL (70 total / 372 shipments on the Acme dev tenant). 1145 backend + 799 frontend unit tests pass.

## Dashboard consistency follow-up — formatNgnCompact + Table cardBreakpoint (2026-10-01)

- `frontend/src/lib/format.test.ts` (new): `formatNgnCompact` — millions/thousands collapse, full small amounts, zero/null/undefined/non-finite → `₦0`, sign preserved for negatives.
- `frontend/src/design/components/Table.test.tsx` (+2): a custom `cardBreakpoint` keeps the table tabular above the threshold (776px vs a 600px override) and collapses it to cards below (375px). Drives a stubbed `getBoundingClientRect` width, same harness as the existing card-view cases.

806 frontend unit tests pass.

## Filter-bar consistency — Customers / Users / Activity Log (2026-10-01)

- `ActivityLog.test.tsx`: Category is now a chip set (not a `<select>`), so the four category-interaction cases click `getByRole('button', { name: /^Money/ })` etc. instead of `selectOptions(getByLabelText('Category'), …)`; the Clear-filters case now asserts the reset via the Record-type select showing "All types" + the `entityTypes: undefined` query call; the impersonation-not-offered case checks no category chip names impersonation. Record type / Action / Sort keep their `<label htmlFor>` associations; search + date inputs keep their accessible names via `aria-label`.
- `StaffUserList.test.tsx` / `AdminCustomerList.test.tsx`: unaffected — the search box is still found by placeholder, role/status chips by text.

## Light / dark theme (2026-10-01)

- `frontend/src/design/colorScheme.test.tsx` (5 cases): default = system resolving to the OS preference; cycle System → Light → Dark → System writing `data-theme`; explicit preference persists to localStorage; a stored preference is read on mount; works standalone without a provider.
- `frontend/src/design/components/ThemeToggle.test.tsx` (1 case): clicking cycles the theme and updates the button's accessible label + `data-theme`.
- `frontend/src/test/setup.ts`: added a default `window.matchMedia` mock (jsdom lacks it) so the color-scheme provider can resolve 'system'; a test overrides it to simulate a dark OS.

812 frontend unit tests pass.

## Container capacity presets + Combobox (2026-10-01)

- `frontend/src/design/components/Combobox.test.tsx` (5): opens, filters by label and by meta text, empty state, disabled no-op, keyboard select. The option handler is on the `<li role="option">` (not an inner button) so a click on the row selects — a regression caught in review.
- `frontend/src/pages/tenant-admin/ContainerCapacities.test.tsx` (4): default+custom listing with source badges, Remove only on custom, create delegates with coerced numbers, submit blocked when recommended > capacity.
- `tests/unit/test_tenant_management.py::TestContainerCapacities` (8): defaults+custom merge sorted desc, create coercion/validation (missing name, non-positive capacity, recommended > capacity), delete-default rejected (422), delete-custom delegates, delete-missing 404.
- `tests/unit/test_tracking.py::TestCreateContainer` (+2): capacity snapshot persisted; blank/zero capacity coerced to NULL (guards the NUMERIC(>0) CHECK).
- Updated `CreateContainer.test.tsx` (QueryClientProvider + capacity mock) and `CreatePackingList.test.tsx` (Combobox selection helper) for the picker changes.

1093 backend + 822 frontend unit tests pass.

## Edit container capacity recommended CBM (2026-10-01)

- `tests/unit/test_tenant_management.py::TestUpdateContainerCapacity` (8): default override persisted to `tenant_config`, over-capacity 422, unknown default 404, clearing reverts, list applies the override, custom full-field edit, custom over-capacity 422, missing custom 404.
- `frontend/src/pages/tenant-admin/ContainerCapacities.test.tsx` (+2): editing a default locks name/capacity and PATCHes recommended only; editing a custom PATCHes all fields.

## ContainerDetail overview — top-shippers list (2026-10-01)

- `frontend/src/pages/china/ContainerDetail.test.tsx`: with 20 customers the overview renders the **Top shippers by CBM** list (top 5 only — Customer 5+ absent), subtitle "20 customers on this container", and "View all →" switches to the packing-lists tab. Updated the cargo-summary and contact tests (contact now lives only on the packing-lists tab, not the overview).

## Packing-list item entry + min-CBM + draft edit (2026-10-02)

- `tests/unit/test_packing_list.py::TestMinCbmAndBaleSizing` (3): `apply_min_cbm` floors sub-minimum/None CBM and passes larger values through; `_bale_type_for` returns BIG/SMALL only for bales (threshold 0.3); `get_min_cbm_per_item` default 0.1 + config read + non-positive fallback. Plus a live end-to-end create (floored 0.1, SMALL/BIG BALE, dates, negatives → 422).
- `frontend/src/pages/china/CreatePackingList.test.tsx` (+3): a 0.06-CBM bale floors to 0.100 with `min` + `SM BALE`; a 0.4-CBM bale shows `BIG BALE`; a draft opens prefilled with customer/container disabled and items loaded (uses `packingListApi.get`, never `create`). Updated the existing CBM tests' mock min to 0.001 and the step-2 readiness marker to "Line items".
- `TestGetCbmRate`/`TestUpdateCbmRate`: patched `get_min_cbm_per_item` and asserted `min_cbm_per_item` in the responses; `CbmRateConfig.test.tsx` updated for the extra `min_cbm_per_item` field.

### Nigeria-ops dashboard pipeline (2026-10-03)

- `frontend/src/pages/tenant-admin/DashboardPipeline.test.tsx` (6): every stage + "All active" tile renders with its count (no 6-card cap / h-scroll kanban); the default view fetches the full active list (`status=loading,…,fully_released`); selecting a stage refetches the complete list filtered to that stage (`status=at_warehouse`); the search box passes `?q=` (debounced); the "Arriving" ETA chips apply `eta_after`/`eta_before` (incl. the overdue upper-bound-only case); the container row carries route + packing-list count + a View action.
- `Dashboard.test.tsx` updated: asserts the new **Outstanding invoices** + **Awaiting pickup** cards (replacing the old recent-payments / incoming-containers cards).

### Manifest package-type breakdown (2026-10-03)

- `tests/unit/test_manifest.py::TestManifestPackageMixQuery` (2): the list + detail repo queries carry the `package_mix` aggregation (`jsonb_object_agg` over `pli.package_unit`, approved packing lists only) — a SQL-string guard, since the suite mocks the DB.
- `frontend/src/pages/nigeria/ManifestList.test.tsx` (+2): the row renders the package breakdown (`ctn`/`bale`/`bag` + counts) and total weight (`412 kg`); falls back to the carton count when `package_mix` is null. (Both manifest test files' `vi.mock('../../api/manifest')` now spread `importOriginal` so the new `orderedPackageMix` export resolves.)

### Container utilization column (2026-10-03)

- `frontend/src/pages/china/ContainerList.test.tsx` (+3): renders packed CBM + "% of capacity" when an exact `capacity_cbm` is set (68.4 / 76 → 90%); falls back to the container-type capacity estimate ("40' High Cube (HC)" → ~76 → 50% at 38 CBM); shows just the packed CBM with no % when capacity is unknown. Shared helpers (`containerCapacityCbm`, `utilizationLevel`) live in `api/containerRules.ts`.

### Cloud-portability ports — crypto + object storage (2026-10-05)

- **`tests/unit/test_encryption.py`** (6): field encrypt/decrypt round-trip via a fake `KeyProvider`, `None` passthrough, dev plaintext-fallback when unconfigured, envelope format (`base64(enc_key || "||" || ciphertext)`), and the factory default (`CLOUD_PROVIDER=aws` → `KmsKeyProvider`, satisfies the `KeyProvider` protocol).
- **`tests/unit/test_storage_provider.py`** (9): `S3StorageProvider` exercised against **moto** (real S3 behaviour) — put/get round-trip, `object_size` (HEAD + None-when-absent), `presigned_upload` is a PUT `UploadTicket` with the Content-Type header + correct `.as_response()` wire shape, `presigned_get_url` signs the key and passes through `response_content_disposition`, `delete_prefix` removes only the matching tenant prefix and counts them; plus factory wiring (default cloud → `S3StorageProvider`, per-bucket caching).
- **Migrated patch sites** (the services no longer hold a module-level `_s3_client`/`_S3`): `test_safe_filename.py`, `test_manifest.py`, `test_payment_release.py`, `test_import_manifest.py` now patch `service.get_storage_provider` and assert on the `StorageProvider` interface (`presigned_upload(key, …)`, `presigned_get_url(key, …, response_content_disposition=…)`, `get_object → bytes`) instead of boto3 call kwargs.
- **Frontend** `uploads.test.ts` / `excel.test.ts` / `manifest.test.ts`: assert the new cloud-neutral **PUT** upload contract (`fetch(upload_url, { method:'PUT', headers: upload_headers, body: file })`) rather than a multipart `FormData` POST.

### Cloud-portability ports — secrets + event publishing (2026-10-05)

- **`tests/unit/test_secrets_event_providers.py`** (5): `SecretsManagerProvider.get_secret` returns the raw secret string (moto round-trip); `EventBridgeProvider.publish` succeeds against a real moto bus and raises `ExternalServiceError` when `put_events` reports `FailedEntryCount` (stubbed client); factory wiring (default cloud → AWS adapters) + singleton caching for both.
- No existing test needed rewriting: `publish_event` is patched at each service's import site (`conftest.py::mock_publish_event` + per-service `patch("…service.publish_event")`), the DB tests force local-mode (`DB_SECRET_ARN=""`) so they never hit the secrets provider, and `test_impersonation_audit.py` patches the unchanged `_get_signing_secret`.

### Cloud-portability ports — queue (SQS) + email (SES) (2026-10-05)

- **`tests/unit/test_queue_email_providers.py`** (4): `SqsQueueProvider.send` round-trips a body through a moto queue; `SesEmailProvider.send` maps to the SES `send_email` Source/Destination/Message structure (stubbed client); factory wiring (default → AWS adapters) + singleton caching.
- **Migrated mocks** — the notification tests moved from patching the removed `_get_sqs()` + asserting boto3 `send_message(QueueUrl=…, MessageBody=…)` to patching `get_queue_provider` and asserting `send(destination=…, body=…)`: `test_whatsapp_first.py` (whole suite — note the SMS-fallback cases patch `services.notification.service.get_queue_provider`, since the fallback/retry call the provider imported into the *service* module, while `enqueue_notifications` cases patch `shared.notifications.get_queue_provider`), `test_notification_guard.py`, and `test_scheduled_jobs.py` (locale-passthrough capture rewritten to `send(*, destination, body)`).

### Cloud-portability — X-Ray tracing shim (2026-10-05)

- No test changes needed. All 19 Lambda entry points replaced `from aws_xray_sdk.core import patch_all; patch_all()` with `shared/observability.py::init_tracing()` (no-op when `CLOUD_PROVIDER != "aws"`). `conftest.py` already stubs the `aws_xray_sdk` modules, so the lazy import inside `init_tracing` resolves to the stub under test exactly as the direct import did — handler-import and `init_tracing()` smoke-verified; full suite green (1150).

### Cloud-portability — IdentityProvider port (ADR-004 Phase 1, 2026-10-06)

- **`tests/unit/test_cognito_client.py`** (now 15, +2): re-pointed from `services.tenant_management.cognito_client.CognitoClient` to `shared.providers.aws.cognito.CognitoIdentityProvider` (same moto-backed group-management regression tests, byte-identical adapter); added `TestIdentityProviderPort` — the adapter satisfies the `IdentityProvider` protocol, and the factory returns a cached `CognitoIdentityProvider` on the default cloud.
- **`tests/unit/test_tenant_management.py`**: the 18 Cognito mock sites moved from patching `service.get_cognito_client` to `service.get_identity_provider` — a target rename only; the mocked method names (`create_user`, `sync_user_groups`, …) are unchanged since the port mirrors the old class surface. Full suite green (1152).

### Cloud-portability — ClaimsMapper (ADR-004 Phase 2, 2026-10-06)

- **`tests/unit/test_auth.py::TestCognitoClaimsMapper`** (+4): `CognitoClaimsMapper` extracts `user_id`/`tenant_id`/`groups`/`primary_role` from Cognito claims, handles the HTTP-API-v2 `[a,b]` bracket form and missing claims, and the factory returns a cached `CognitoClaimsMapper` satisfying the `ClaimsMapper` protocol on the default cloud.
- The existing `_parse_roles` / `_parse_primary_role` / `get_tenant_context` tests were **not** changed: they pass Cognito-shaped claims and the default mapper reads exactly the same keys, so the interpretation layer's behaviour is byte-identical. Full suite green (1156).

### Azure Blob provider — fully mocked (2026-10-06, revised 2026-10-08)

- **`tests/unit/test_azure_blob_provider.py`** (8): **hermetic — no Azurite, no network, no real Azure.** A small in-memory fake stands in for the Blob container client (put/get/size/delete round-trip in a dict) and `generate_blob_sas` is patched to a fixed token, so the adapter's logic + SDK call shapes (incl. the `x-ms-blob-type: BlockBlob` upload header and the `content_disposition` passed into the SAS) are verified without any external service. Factory returns `BlobStorageProvider` when `CLOUD_PROVIDER=azure`.
- **Policy:** the pytest suite is fully mocked and never touches a real cloud or a running emulator. The real end-to-end proof (live SAS PUT→201 / GET→200 against Azurite or a real account) lives in **`scripts/azure_smoke.py`**, run manually — it is not collected by pytest. (This replaces the earlier Azurite-backed/skip-when-down version of these tests.)

### Azure Service Bus provider — mocked SDK (2026-10-06)

- **`tests/unit/test_azure_servicebus_provider.py`** (3): `ServiceBusQueueProvider.send` targets the right queue and constructs a real `ServiceBusMessage(body)` (asserted via `str(msg)`), protocol conformance, and the factory returning it when `CLOUD_PROVIDER=azure`. Uses a stubbed Service Bus client rather than the emulator — the SB emulator needs a SQL Edge sidecar and is arm64-finicky, and the adapter is send-only, so the mocked SDK gives the same rigor as the SES stub. Full e2e against the emulator is a documented follow-up.

### Azure Key Vault providers — mocked SDK (2026-10-06)

- **`tests/unit/test_azure_keyvault_provider.py`** (8): `KeyVaultKeyProvider` (envelope via RSA-OAEP wrap/unwrap) — generate returns a 32-byte key + wrapped blob, generate→decrypt round-trips, non-32-byte unwrap raises, and — the real-coverage case — a full `shared/encryption.py` `encrypt_field`/`decrypt_field` round-trip with only the Key-Vault wrap stubbed (the Fernet envelope is real). `KeyVaultSecretsProvider.get_secret` returns the raw secret value. Both factory selections (`CLOUD_PROVIDER=azure`). Stubbed Key Vault clients — no official emulator exists.

### Azure Event Grid + ACS email providers — mocked SDK (2026-10-06)

- **`tests/unit/test_azure_eventgrid_acs_providers.py`** (7): `EventGridProvider.publish` maps `source`→`subject` / `detail_type`→`event_type` / `detail`→`data` on a real `EventGridEvent`, and normalizes any SDK error to `ExternalServiceError`; `AcsEmailProvider.send` builds the ACS message shape (`senderAddress` / `recipients.to` / `content.{subject,html,plainText}`); both factory selections. Stubbed SDK clients — neither service has a local emulator.

### Compute portability — container edge (ADR-005, 2026-10-09)

Fully mocked — no gunicorn, Service Bus, JWKS, DB, or Azure SDK is touched.

- **`tests/unit/test_auth_verify.py`** (9): `shared/auth_verify.build_authorizer_claims` — the OIDC branch projects the Cognito-shaped context and flattens a list-valued `cognito:groups` to CSV; falls through to the impersonation branch; returns `None` when both strategies fail or the token is empty. `verify_oidc_jwt` returns `None` without a JWKS URL and on a bogus token; `OIDC_*` env takes precedence over `COGNITO_*` with fallback.
- **`tests/unit/test_http_routing.py`** (19): `resolve_service` for every special case (excel export/pdf/import, container `/packing-lists` sub-resource, platform `/usage`→metering, GDPR `/customers/{id}/export` stays tenant_management, query-string stripping, unrouted→None) and `is_public_route` (health, public tracking with path param vs authenticated list, both webhook methods, invite/register/auth-session routes, method + segment-count discrimination).
- **`tests/unit/test_http_app.py`** (8): the container HTTP app via Flask test client with `build_authorizer_claims`/`invoke_handler` patched — `/health` 200 unauthenticated; authenticated route 401 without a token and invokes the handler with the verified claims in the event when present; unrouted→404; handler exception→500; public route skips verification and carries no authorizer context; OPTIONS preflight→204.
- **`tests/unit/test_queue_worker.py`** (7): `process_message` wraps a Service Bus body into a single-record SQS-shaped event and propagates handler errors (for abandon/retry); `_QUEUE_CONFIG` covers sms/whatsapp/email/metering; `run_worker` guards unknown queue key + missing queue-name/connection-string env; argparse rejects an unknown queue.
- **`tests/unit/test_scheduled_run.py`** (5): `run_job` returns 0 on success (invoking the job's `lambda_handler` with a traceable event) / 1 on handler failure / raises on an unknown job; every advertised job name imports and exposes `lambda_handler`; argparse rejects an unknown job.
- **`tests/unit/test_db_connection_healing.py::TestSslMode`** (3, added Phase 3): `shared/db.py` sslmode selection — explicit `DATABASE_SSLMODE` wins (Azure sets `require`), AWS `DB_SECRET_ARN` defaults to `require`, local defaults to `prefer`; `psycopg2.connect` + `_get_db_password` mocked.
- **`tests/unit/test_distributed_cache.py`** (3, added Phase 3): the redis client is built with `password`/`ssl` off by default (AWS/local) and on from `REDIS_PASSWORD`/`REDIS_SSL=true` (Azure); case-insensitive flag; the `redis` package is faked.

### Compute portability — Entra identity (ADR-004 Phase 4, 2026-10-09)

Fully mocked — no Microsoft Graph, credential, or network.

- **`tests/unit/test_entra_claims.py`** (23): `EntraClaimsMapper` — `user_id` prefers `oid` then `sub`; tenant id from the configurable claim; `groups` from a list / JSON-array string / CSV normalized to `{tenant_id}:{role}`; `primary_role` from the role claim. Plus the ADR-004 addendum (2026-10-11) three-shape handling: bare object-id groups are dropped when unmapped; `platform_admin` / `{tenant_id}:{role}` are synthesized from the `role`+`tenant_id` optional claims; `ENTRA_PLATFORM_ADMIN_GROUP_ID` + `ENTRA_GROUP_ID_MAP` translate GUIDs (malformed JSON ignored); `ENTRA_TENANT_ID_CLAIM`/`ENTRA_ROLE_CLAIM` redirect to directory-extension claim names; and the CIAM case — `tenant_id` derived as `PLATFORM` from `platform_admin` group membership when no tenant claim is present (not derived for tenant-scoped users). `TestDualCloudRoleResolution` asserts the same `shared.auth` logic resolves platform/tenant admin from both a Cognito-shaped token and a native Entra/CIAM token (incl. the real group-GUID-only id_token), proving config-only cloud switching.
- **`tests/unit/test_entra_token_claims.py`** (19): the Entra custom authentication extension (OnTokenIssuanceStart claims provider, `services/entra_token_claims/`, a Container App workload on the shared image) — `extract_object_id` from the event (and empty on missing pieces); `build_claims_response` maps an injected lookup into the Microsoft response envelope, passes the oid to the lookup, drops empty values, and fails open (empty claim set, valid envelope) for an unknown user or a `None` lookup; `is_authorized` accepts matching `aud`+`iss`, rejects either mismatch, and fails closed on unconfigured expected values; the `DatabaseClaimsReader` resolves tenant_id/role by oid with a PLATFORM-scoped parameterized read (short-circuits empty oid, empty on unknown user, fails open on DB error, honours custom output claim names); and the Flask `app.py` wiring (`/health` 200, 401 without a valid caller, full claims envelope when caller + lookup are stubbed). Pure logic / Flask test client — `execute_with_tenant` and the JWKS verify are stubbed, no DB or network.
- **`tests/unit/test_entra_identity_provider.py`** (8): `EntraIdentityProvider` with `_graph` stubbed — `create_user`/`create_user_with_password` POST `/users` with the right `forceChangePasswordNextSignIn` and sync groups; disable/enable PATCH `accountEnabled`; `sync_user_groups` adds missing + removes stale groups scoped to the tenant prefix (leaving other tenants' groups); and with `urlopen`+token stubbed, `_graph` maps HTTP 409 → `DuplicateResourceError` and other codes → `ExternalServiceError`; factory selects Entra under `CLOUD_PROVIDER=azure`.

### Warehouse management — reported defects pinned (2026-11-02)

Three live-reported defects, each with a regression test that fails against the
pre-fix code. Full root-cause account in `13_api_payment_release.md`.

**Backend — `tests/unit/test_payment_release.py::TestWarehouses` (+11, 41 total):**
- `test_china_office_staff_can_read_the_warehouse_list` — the role gate that
  emptied the arrival-warehouse picker. A route-level test, since the defect was
  in `_WAREHOUSE_READ_ROLES`, not in any service function.
- `test_create_rejects_a_name_an_active_warehouse_already_holds` /
  `test_a_retired_warehouses_name_can_be_reused` — the pair that encodes
  migration 056's rule. The second asserts `active_only=True` is actually passed,
  because the whole bug was a uniqueness check with the wrong scope.
- `test_create_with_is_default_promotes_the_new_warehouse` /
  `test_create_does_not_promote_on_a_non_boolean_is_default` — the latter exists
  because the service reads `is_default` off a request object with `getattr`; a
  truthiness test would make a `MagicMock` (or any stray value) silently
  reassign the tenant's default, so promotion requires `is True`.
- `test_delete_hard_deletes_an_unreferenced_warehouse` — asserts a real `DELETE`
  and that the audit entry carries a `before_state` rich enough to recreate the
  row, since a hard delete is unrecoverable and the trail is all that remains.
- `test_delete_refuses_a_warehouse_a_release_note_references` — asserts
  `rule_id == "WAREHOUSE_IN_USE"` **and** that the message names the counts
  ("2 release notes", "1 pickup record"), not a generic "in use".
- `test_delete_refuses_the_default_warehouse`,
  `test_patch_cannot_deactivate_a_warehouse` (a bare PATCH must not bypass the
  default/last-active guards), `test_rename_onto_another_active_warehouses_name_is_rejected`,
  `test_renaming_a_warehouse_to_its_own_name_is_allowed` (the clash check compares
  ids, so a no-op rename is not a conflict).

**Frontend:**
- `Warehouses.test.tsx` (+6) — real delete vs. deactivate (`expect(deactivate).not.toHaveBeenCalled()`
  is the assertion that distinguishes the fix from the old behaviour), declined
  confirmation, retire-on-`WAREHOUSE_IN_USE`, explicit success confirmation,
  a surfaced set-default failure, and create-as-default.
- `CreatePackingList.test.tsx` (+2) — the important one asserts both that
  "could not be loaded" appears **and** that "No warehouses configured" does
  *not*: the original defect was those two states being indistinguishable.

**Totals:** 1380 backend, 877 frontend passing. 7 frontend failures
(`colorScheme.test.tsx`, `storage.test.ts`) were verified identical on `main` by
stashing the branch and re-running — pre-existing and unrelated.

**Harness note:** `vite.config.ts` sets `test.exclude: ['node_modules', 'e2e']`
as plain strings rather than globs. Running `vitest` from the repo root (instead
of `frontend/`) therefore collects the Playwright specs under `frontend/e2e/`
and reports hundreds of spurious failures. Always run it from `frontend/`.

### Country/state pickers + phone field (2026-11-02)

**The seam test is the important one.** `tests/unit/test_phone.py::TestFrontendDialCodesAgree`
parses `frontend/src/data/countries.ts` **from the backend suite** and asserts it
agrees with `shared/phone.py::_DIAL_CODES` for every country the backend knows,
and that the frontend default is still Nigeria. Without it, each side could stay
internally consistent while disagreeing on a dial code — and because the backend
*prepends* a dial code to local-format numbers, that would store a number under
the wrong country's prefix with nothing to catch it. It lives in pytest rather
than vitest because the frontend tsconfig carries no Node types, and loosening
that config for one test is the wrong trade.

**Frontend:**
- `src/data/phone.test.ts` (18) — parse/format round-trips, longest-dial-code
  matching (+1268 beating +1), the shared-dial-code tie-break, and two tests that
  exist because of a real bug: `toE164` tested emptiness *before* stripping the
  trunk `0`, so a lone `"0"` emitted a bare `+234` that `parsePhone` read back as
  national digits — the next keystroke produced `+234234…`. One test asserts the
  lone-zero case directly; the other **simulates typing character by character**
  through the controlled loop, which is the shape that actually failed.
- `src/data/countries.test.ts` (12) — unique codes, plausible dial codes, picker
  ordering, and that each subdivision list is sorted and duplicate-free.
- `src/design/components/PhoneField.test.tsx` (8) — defaults to +234, splits a
  stored E.164 back into its parts, parses a legacy local-format value, rewrites
  the number when the country changes, and emits `''` (not `+234`) when cleared.
- `src/design/components/StateSelect.test.tsx` (11) — includes `CountrySelect`.
  Asserts the **free-text fallback** for a country with no list (Kenya), that an
  unrecognised stored value is preserved rather than blanked, and that the label
  follows local usage (Province for China, Region for Ghana).

**Backend:** `TestGetShipmentByCodeAndPhone` (+3) — a local-format number must
normalise to E.164 before matching, the raw input stays a candidate (for rows
predating normalisation and for foreign numbers), and an E.164 input passes
through unchanged.

**Updated, not deleted:** `AdminCustomerList.test.tsx` and `Warehouses.test.tsx`
typed a full `+234…` string into what is now the *national* box. Corrected to type
the national part only — which is what a user does, and what surfaced the
doubling bug above.

**Totals:** 1385 backend, 927 frontend passing. The 7 frontend failures
(`colorScheme.test.tsx`, `storage.test.ts`, `ThemeToggle.test.tsx`) remain the
pre-existing, unrelated set verified against `main` earlier.

### Cache invalidation (2026-11-03)

Two test files, deliberately split, because the bug had two halves — a missing
rule and missing wiring — and either alone would have let it through.

**`api/cacheInvalidation.test.ts` (10) — the registry.** The load-bearing one
scrapes every mutating path out of `api/*.ts` and asserts each matches a rule, so
adding an endpoint without a mapping fails CI rather than silently going stale.
It reads the sources via `import.meta.glob` rather than `node:fs`, because the app
tsconfig carries no Node types and loosening it for one test is the wrong trade.
A companion test asserts the scraper itself finds >50 paths — otherwise a change in
how `api/*.ts` is written would make every other assertion here vacuously pass.
Also covers: specific-before-generic ordering (`/v1/claims/seized-items/...` must
not be swallowed by `/v1/claims/...`), query-string stripping, the named
cross-domain effects, pre-auth paths mapping to an empty root set, and that no
rule's roots are `undefined` (a typo'd key import would invalidate nothing while
looking fine).

**`api/client.test.ts` (+6) — the wiring.** That the client actually *applies* the
rule: a container DELETE invalidates containers and packing lists; a GET
invalidates nothing (invalidating on reads is how you build a refetch loop); a
**failed** write invalidates nothing (it changed nothing, and refetching would
mask the failure); and a write still resolves normally when invalidation itself
throws — a cache problem must never turn a successful write into a UI error.

**Totals:** 943 frontend passing, same 7 pre-existing failures. No existing test
needed changing, which is the useful signal: the behaviour was added without
altering any page's contract.
### Packing-list goods dates (2026-11-03)

**Backend — `TestShipmentDateOrdering` (8):** loading-before-delivery rejected;
same-day allowed (goods received in the morning are loaded that afternoon);
future `delivery_date` rejected; future `loading_date` **allowed** (unbounded on
purpose); each date still optional on its own; and the same rules asserted on
`UpdatePackingListRequest`, because the edit path has its own model and could
otherwise write exactly the ordering the create path refuses.

One test exists purely for a timezone trap:
`test_todays_date_is_accepted_even_from_a_timezone_ahead_of_utc`. The China office
is UTC+8, so a naive comparison against UTC "today" would reject the date on their
own wall calendar for several hours each evening. The validator allows one day
past UTC; the test pins that allowance so a later "tightening" cannot silently
reintroduce the bug.

**Frontend — `CreatePackingList.test.tsx` (+8):** DOM order (delivery before
loading), both helper texts present, `max`/`min` attributes on the pickers, and
the four rule cases.

**A weak assertion caught while writing them:** the "Next is disabled" tests
initially passed for the wrong reason — `canProceedFrom1` also requires a customer
and container, so the button was disabled regardless of the dates. They now call
`pickCustomerAndContainer()` first, so the step is genuinely valid and only the
date rule can disable it. The two "accepts" cases are what exposed this, by
failing where they should have passed.

### Row-level security, tested for real (2026-11-03)

`tests/tenant_isolation/test_rls_enforcement.py` (13 tests) is the first test in
the repo that exercises **layer 3** — the Postgres policies themselves. Everything
else under `tests/tenant_isolation/` tests the application layer: that services
pass `tenant_id` and handlers reject the wrong role.

**The design point is who connects.** Postgres exempts a table's owner from
non-forced RLS, and exempts any `SUPERUSER`/`BYPASSRLS` role from RLS entirely.
CI's Postgres service runs as `POSTGRES_USER=test_user`, which **is** a superuser
— so a test connecting the normal way would pass whether or not RLS worked at
all. Each test here creates a deliberately unprivileged probe role and connects
as it, and the fixture **asserts** `NOT rolsuper AND NOT rolbypassrls` rather
than trusting `CREATE ROLE`'s defaults: the test is worthless if the probe can
bypass what it is measuring.

Covered:
- A tenant sees only its own `warehouse` rows, and cannot read another tenant's
  even by asking for that `tenant_id` directly.
- `PLATFORM` scope still reads across tenants — the access pattern migration
  005's `::uuid` cast cannot support (`'PLATFORM'::uuid` raises).
- A connection that never called `_set_tenant` sees **nothing** (fails closed:
  `current_setting(..., TRUE)` is NULL, and `tenant_id::text = NULL` is NULL).
- `WITH CHECK` blocks writing a row for another tenant — without it a scoped
  session could create rows it then could not see.
- Every repaired table is both `ENABLE`d **and** `FORCE`d (`pg_class`), and no
  policy still references `app.tenant_id` (`pg_policy`) — the latter pins the
  exact bug.

These skip when no database is reachable, so a local run without the stack stays
green; CI always has one, migrated before the suite.

**Would have caught it:** run against pre-058 schema, the `FORCE` and
`app.current_tenant_id` assertions fail outright.

**Unexplained observation, recorded rather than guessed at:** during this work
`tests/unit/test_azure_keyvault_provider.py::...::test_integrates_with_the_real_fernet_envelope`
failed **once** in a combined `tests/unit tests/tenant_isolation` run, then passed
in four subsequent runs including the identical invocation. It is not caused by
the new file (the combined run passes with it present), `shared/encryption.py`
has no cached global that would explain order-dependence, and no randomising
pytest plugin is installed. Flagged as intermittent; cause unknown.

#### Extended for migration 059 (same day)

Six more tests, and the important ones are **catalog-driven** rather than
hardcoded — a hardcoded table list is exactly how four tables drifted onto a
broken predicate for four migrations:

- Every tenant-scoped table (RLS enabled **and** a `tenant_id` column) is
  `FORCE`d. A table that is `ENABLE`-only is bypassed by the owner.
- No policy casts to `::uuid` (raises on `'PLATFORM'`), references
  `app.tenant_id` (the setting nothing sets), or lacks a PLATFORM branch (denies
  platform-scoped reads). All three historical styles are rejected by name.
- A guard asserting the catalog query finds **≥ 20** tables, because every
  assertion above passes vacuously on an empty list.
- Functional isolation on `customer` — one of migration 005's original 21, the
  group whose uuid-cast predicate 059 replaced — proving the rewrite works on
  them and not just the four 058 repaired.
- `logistics_app` cannot log in (005 committed its password), and **has grants on
  tables added after 005**: that `GRANT ... ON ALL TABLES` covered only tables
  existing at the time, so the switchover would have failed with "permission
  denied" on a newer table.

**A future migration that adds a tenant-scoped table with a non-canonical policy
fails CI**, which is the property the schema previously lacked.

**Local verification was not possible and that is worth stating.** Docker is down
and the Homebrew `postgresql@14` install is broken (`postgres` missing from its
Cellar bin), so migrations 058/059 were reviewed by reading the generated SQL,
not executed locally. Their `format('%I', ...)`-inside-`op.execute` pattern is
the same one migration 005 uses and CI runs successfully, so the `%` handling is
proven; the policy logic is verified by these tests in CI against `postgres:15`.
