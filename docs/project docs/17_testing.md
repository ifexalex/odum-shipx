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
