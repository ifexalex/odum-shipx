# Task 07 — API Service: Tenant Management + User Provisioning

## Objective

Implement the Tenant Management Lambda service: tenant CRUD, suspension/activation, tenant config, user management (Cognito provisioning), customer CRUD, charge types, dollar rate, and platform dashboard.

## Depends On

- Task 06 (shared layer), Task 03 (models), Task 04b (Cognito)

## Files to Create

```
services/tenant_management/
├── handler.py        # Lambda entry, route dispatch
├── service.py        # Business logic
├── repository.py     # All SQL queries
└── models.py         # Already defined in Task 03
```
(`cognito_client.py` was removed — see the portability note below.)

**Cloud-portability (2026-10-05, ADR-004 Phase 1 done):** the former `cognito_client.py`
is now the AWS adapter `shared/providers/aws/cognito.py` (`CognitoIdentityProvider`,
byte-identical) behind the `IdentityProvider` port; `service.py` calls
`get_identity_provider()` instead of `get_cognito_client()`. This is the **management**
side of identity only. The **authN** side (the authorizer's JWT/JWKS verification + the
`custom:tenant_id`/`cognito:groups`/`custom:role` claim shape, plus token refresh and the
GDPR user-purge) is still Cognito-specific — that's ADR-004 phases 2–5 (claim mapping +
Entra adapter + user migration), scoped in `docs/adr/004-cognito-to-entra-portability.md`.

## API Routes Handled

### Platform Admin Endpoints
| Method | Path | Handler | Roles |
|---|---|---|---|
| POST | `/v1/platform/tenants` | Create tenant + initial admin | platform_admin |
| GET | `/v1/platform/tenants` | List tenants | platform_admin |
| GET | `/v1/platform/tenants/{id}` | Get tenant detail | platform_admin |
| PATCH | `/v1/platform/tenants/{id}` | Update tenant | platform_admin |
| DELETE | `/v1/platform/tenants/{id}` | Offboard tenant | platform_admin |
| PATCH | `/v1/platform/tenants/{id}/suspend` | Suspend tenant | platform_admin |
| PATCH | `/v1/platform/tenants/{id}/activate` | Lift suspension (suspended→active) | platform_admin |
| PATCH | `/v1/platform/tenants/{id}/reactivate` | Re-onboard offboarded tenant (offboarded→active) | platform_admin |
| GET | `/v1/platform/dashboard` | Cross-tenant metrics | platform_admin |
| GET | `/v1/platform/audit-log` | Platform audit log | platform_admin |
| POST | `/v1/platform/tenants/{id}/impersonate` | Start 30-min read-only impersonation session | platform_admin |
| DELETE | `/v1/platform/impersonation/{session_id}` | End impersonation session | platform_admin |
| GET | `/v1/platform/onboarding-requests` | List shipping-company onboarding leads; `?status=` filters (`new\|contacted\|approved\|rejected\|provisioned`) | platform_admin |
| GET | `/v1/platform/onboarding-requests/{id}` | Get one onboarding lead | platform_admin |
| PATCH | `/v1/platform/onboarding-requests/{id}` | Update lead status (`{status, rejection_reason?}`) — mark contacted / approve / reject | platform_admin |

### Public Endpoints (no JWT)
| Method | Path | Handler | Roles |
|---|---|---|---|
| POST | `/v1/onboarding-requests` | Submit a shipping-company onboarding request (lead). Creates **no** account/tenant; records a lead and emits `OnboardingRequested` to platform ops | public |

### Tenant Admin Endpoints
| Method | Path | Handler | Roles |
|---|---|---|---|
| GET | `/v1/tenant/activity` | Tenant-scoped audit feed; `?actor_id=` narrows to one staff member, `?entity_type=` narrows to one kind of record; cursor-paginated; response includes `before_state`/`after_state` | tenant_admin |
| GET | `/v1/tenant/config` | Get tenant config (webhook_config.secret masked to `****`; paystack_config.secret_key_encrypted stripped entirely) | all staff roles + customer (read widened 2026-07-11 for staff — printable documents render `branding_config` for whoever prints them; widened again 2026-09-06 for customer — `MyBillingDetail.tsx`'s bank-transfer panel needs `bank_transfer_config`) |
| PUT | `/v1/tenant/config` | Update branding, notifications, webhook_config, and/or bank_transfer_config | tenant_admin |
| POST | `/v1/tenant/config/webhook/rotate-secret` | Generate new HMAC signing secret; returns it once in plaintext | tenant_admin |
| POST | `/v1/tenant/config/webhook/test` | Send a signed test event to the configured webhook URL; returns delivery result | tenant_admin |
| PUT | `/v1/tenant/config/paystack` | Connect/replace this tenant's own Paystack secret key (encrypted at rest; always a full replace, never a partial merge) | tenant_admin |
| DELETE | `/v1/tenant/config/paystack` | Disconnect Paystack — online payment reverts to bank-transfer-only until reconfigured | tenant_admin |
| POST | `/v1/tenant/config/paystack/test` | Live connectivity check against the stored key (real Paystack API call, not shape-only) | tenant_admin |
| POST | `/v1/tenant/users` | Create user (+ Cognito). **Breaking change (2026-07-20, migration 039):** body is `{email, full_name, roles, primary_role?}` — `role` (singular) removed | tenant_admin |
| GET | `/v1/tenant/users` | List tenant users. Each row now also carries `roles: TenantUserRole[]` alongside the existing primary `role` | tenant_admin |
| GET | `/v1/tenant/users/{id}` | Get user detail. Response adds `roles: TenantUserRole[]` (primary role always included) | tenant_admin |
| PATCH | `/v1/tenant/users/{id}` | Update user (full_name, locale, and/or roles/primary_role). **Breaking change:** `role` (singular) removed, replaced by `roles`/`primary_role` | tenant_admin |
| PATCH | `/v1/tenant/me` | Self-service locale update — any authenticated role | all authenticated |
| DELETE | `/v1/tenant/users/{id}` | Deactivate user | tenant_admin |
| POST | `/v1/tenant/users/{id}/resend-invite` | Resend Cognito temp-password email | tenant_admin |
| POST | `/v1/tenant/users/{id}/reset-password` | Trigger Cognito password-reset email | tenant_admin |
| GET | `/v1/tenant/dollar-rate` | Get effective rate (Bybit base + this tenant's markup) | tenant_admin, china_office_staff, nigeria_office_staff |
| PUT | `/v1/tenant/dollar-rate` | Update this tenant's markup | tenant_admin |
| GET | `/v1/tenant/cbm-rate` | Get current CBM rate (currency + carton/bag/bale rates) | tenant_admin, china_office_staff, nigeria_office_staff |
| PUT | `/v1/tenant/cbm-rate` | Update CBM rate (currency + flat/per-package-type) | tenant_admin |
| GET | `/v1/tenant/rate-history` | Paginated rate change audit (`?rate_type=dollar_rate\|cbm_rate`) | tenant_admin |
| POST | `/v1/tenant/charge-types` | Create charge type | tenant_admin |
| GET | `/v1/tenant/charge-types` | List charge types | tenant_admin |
| PUT | `/v1/tenant/charge-types/{id}` | Update charge type | tenant_admin |
| DELETE | `/v1/tenant/charge-types/{id}` | Deactivate charge type | tenant_admin |
| GET | `/v1/tenant/container-capacities` | List capacity presets (10 defaults + custom, merged, sorted by capacity desc) | all staff roles (`_STAFF_ROLES`) — the create-container form + packing-list wizard need it |
| POST | `/v1/tenant/container-capacities` | Add a custom capacity preset | tenant_admin |
| PATCH | `/v1/tenant/container-capacities/{id}` | Edit recommended load (defaults: recommended only; custom: name/capacity/recommended) | tenant_admin |
| DELETE | `/v1/tenant/container-capacities/{id}` | Remove a custom preset (`default:*` ids 422) | tenant_admin |

**Charge type wire shape** (all four endpoints):
```json
{
  "id": "uuid",
  "name": "Customs examination",
  "description": "Port examination fee",
  "amount_ngn": "15000.00",
  "is_active": true,
  "usage_count": 7
}
```
- `amount_ngn` is the wire field; it maps to the `charge_type.default_amount_ngn`
  column (the service translates in both directions — send/read `amount_ngn`, never
  `default_amount_ngn`). Create/update accept `{name, amount_ngn, description}`.
- `usage_count` (list only) = count of `misc_charge` rows attributed to this type via
  `misc_charge.charge_type_id` (migration 035). Set when a charge is added from a
  configured type; free-form "other" charges are NULL/uncounted. Accurate from
  migration 035 onward — older rows have NULL `charge_type_id`. Powers the §4.4
  "Times used" column.

### Customer Endpoints
| Method | Path | Handler | Roles |
|---|---|---|---|
| POST | `/v1/customers` | Create customer | tenant_admin, china_office_staff, nigeria_office_staff |
| GET | `/v1/customers` | List customers (supports `?q=` search) | staff roles; **customer role gets exactly `[own record]`** (doubles as the portal's "who am I" lookup) |
| GET | `/v1/customers/stats` | Tenant-wide customer aggregates for stat cards | staff roles (`_STAFF_ROLES`) |
| GET | `/v1/customers/{id}` | Get customer | all staff + customer (own only) |
| PATCH | `/v1/customers/{id}` | Update customer | staff roles (full field set); **customer (own record — restricted to `phone`, `whatsapp`, `delivery_address`, `notification_consent`, `locale`; never name/email/contract/user_id)**. `locale` (`en`\|`zh`, else 422 `UNSUPPORTED_LOCALE`) selects the notification template language (P2-1) |
| DELETE | `/v1/customers/{id}` | GDPR anonymisation (Art. 17 — right to erasure) | tenant_admin, **customer (own record — the data subject's own right)** |
| GET | `/v1/customers/{id}/export` | GDPR data portability export (Art. 20) | tenant_admin, customer (own) |

**Implementation notes (2026-07-11 — audit gap A1):** `branding_config` now has a canonical shape the frontend writes via `PUT /v1/tenant/config {branding}` and every consumer reads: `display_name`, `tagline`, `primary_color`, `warehouse_address`, `pickup_hours`, `pickup_phone`, `support_email`, `support_whatsapp`, `document_footer` (all optional; JSONB is free-form so no backend model change was needed — see `frontend/src/api/tenantManagement.ts` `BrandingConfig`). `GET /v1/tenant/config` (exact path, GET only) was widened to all staff roles so the printable packing list / release note can render the tenant's branding for whoever prints them; writes and the webhook sub-routes stay tenant_admin-only, and the guard is covered by `TestTenantConfigReadAccess` in `tests/unit/test_tenant_management.py`.

**Implementation notes / ground-truth gaps found (2026-07-18 — platform admin impersonation was broken at four layers):** (1) `impersonation.py`'s `_get_tenant_admin()` selected non-existent columns `tu.user_id` / `tu.is_active` (real schema: `id` PK, `status` enum) — every `POST /v1/platform/tenants/{id}/impersonate` 500'd against the real DB; (2) `platform_audit_log.actor_id` had an FK to `tenant_user(id)`, but platform admins have no `tenant_user` row by design, so **every platform audit insert silently failed** (swallowed with a warning) and the platform audit-log page was permanently empty — FK dropped in migration 037 (same class as migration 014); (3) the frontend read `result.id_token` where the wire field is `token`; (4) `buildSession()` required `custom:tenant_id`/`cognito:groups` claims, but the raw impersonation token carries bare `tenant_id`/`role` — now accepted as a fallback shape. Also: `scripts/local_server.py` now maps impersonation-token claims the same way the production REQUEST authorizer does, and `LocalAuthProvider` implements `startImpersonation`/`exitImpersonation` (was a hard throw), so "Impersonate" works in both local auth modes. Full loop verified live: start → tenant-scoped read → write blocked 422 → end session.

**Implementation notes / ground-truth gaps found (2026-07-09):** `GET /v1/customers` previously had **no role scoping** — any logged-in customer could list every customer's PII in the tenant (cross-customer data leak within a tenant). Fixed: customer role now receives only their own record, resolved via `customer.user_id = ctx.user_id` (`get_customer_for_user`). At the same time PATCH/DELETE were widened to support customer self-service (Account page 10.7): ownership is verified via the same `user_id` linkage, and PATCH's body is filtered to a safe self-service allowlist before hitting `update_customer`.

### Platform Plans, Quota Overrides & Provider Gateways (added 2026-07-09)

| Method | Path | Purpose | Roles |
|---|---|---|---|
| GET | `/v1/platform/plans` | All tiers with plan-level overrides applied | platform_admin |
| PUT | `/v1/platform/plans/{tier}` | Override a tier's limits platform-wide (partial: only sent dimensions change) | platform_admin |
| POST | `/v1/platform/tenants/{id}/quota-override` | Per-tenant limit override; empty body clears. Returns `effective_limits` | platform_admin |
| GET | `/v1/platform/tenants/{id}/users` | Staff users of a tenant (TenantDetail Users tab) | platform_admin |
| GET | `/v1/platform/tenants/{id}/config` | Read-only tenant config (webhook secret masked) | platform_admin |
| GET | `/v1/platform/settings/gateways` | All three provider configs, secrets masked | platform_admin |
| PUT | `/v1/platform/settings/{sms\|whatsapp\|email}-gateway` | Update provider config. A masked `****` secret in the body keeps the stored value | platform_admin |
| POST | `/v1/platform/settings/{kind}-gateway/test` | Config-shape validation (required fields present) — **not** a live provider call | platform_admin |

**Limit resolution** (see `shared/tier_limits.py::get_effective_limits`): static `TIER_LIMITS` defaults → platform_settings `plan_limits` overrides → platform_settings `quota_override:{tenant_id}`. Overrides are partial and **fail open** to static defaults on infra errors (quota is a commercial limit, not a security boundary). Both `services/metering` limit checks and `GET /v1/tenants/me/quota` resolve through this chain.

**Gateway config contracts:** sms/Termii `{api_key*, sender_id}` · whatsapp/Meta `{access_token*, phone_number_id}` · email/Postmark `{server_token*, from_email}` (`*` = secret, masked on read; audit logs record field *names* only, never values).

## Key Business Logic

### Tenant Creation (POST /platform/tenants)
1. Validate request
2. Insert `tenant` record (status = 'active')
3. Create Cognito user for initial admin with `custom:tenant_id = {new_tenant_id}`
4. Create Cognito group `{tenant_id}:tenant_admin`
5. Add user to group
6. Insert `tenant_user` record — `id` is set explicitly to the Cognito `sub` returned in step 3, never left to `gen_random_uuid()`. `TenantContext.user_id` (every request's JWT `sub`) is used directly as `created_by`/`approved_by`/`rejected_by` with no resolution step, so this is load-bearing: if `id != cognito_sub`, every write by this user 500s on the FK.
7. Insert default `tenant_config` records (dollar_rate_markup, storage_fee, warehouse_address, cbm_rate, etc.)
8. Publish `TenantOnboarded` event
9. Log to `platform_audit_log`
10. Return tenant + admin user info

### Tenant Suspension (PATCH /platform/tenants/{id}/suspend)
1. Validate tenant exists and is 'active'
2. Update `tenant.status = 'suspended'`
3. Publish `TenantSuspended` event
4. Log to `platform_audit_log`
5. Notify the tenant's primary contact (see below)
- **Note:** Suspended tenants have all API requests blocked by auth middleware (403 TENANT_SUSPENDED)

**Ground-truth gap found live, reported by the user (2026-09-09) while investigating a separate missing notification on payment-claim rejection — asked to check every notification in the app:** `tenant_onboarded`/`tenant_suspended` had full SMS/WhatsApp/email templates defined but no call site ever used either — `create_tenant` and `suspend_tenant` only published EventBridge events that were never wired into any routing rule. Both now call `enqueue_notifications` directly against the tenant's own `primary_contact_email`/`primary_contact_phone`, best-effort and never able to fail tenant creation/suspension itself. Full account in `15_api_notifications.md`. Tests: `TestCreateTenantNotifiesOnboarding`, and new cases in `TestSuspendTenant`, in `tests/unit/test_tenant_management.py`.

### User Creation (POST /tenant/users)
**Breaking change (2026-07-20, migration 039 — multi-role staff support):** request body
is now `{email, full_name, roles: TenantUserRole[], primary_role?: TenantUserRole}` —
the previous singular `role` field is gone, no dual-path back-compat (no production
tenants existed at the time of the change). `primary_role` defaults to `roles[0]` when
omitted; if provided it must be a member of `roles` (422 otherwise).

1. Validate request + check usage limits (starter: 10 users, business: 50)
2. Create Cognito user with `custom:tenant_id`, `custom:role` = primary role, temporary password
3. Insert `tenant_user` record with `role` = primary role — same `id = cognito_sub` rule as tenant creation above
4. `repository.set_user_roles()` — transactionally populate `tenant_user_role` with every role in `roles` (primary flagged `is_primary = TRUE`)
5. `CognitoClient.sync_user_groups(email, tenant_id, roles)` — diffs current vs. desired `{tenant_id}:*` groups and adds/removes to match (N=1 case of the same operation used by role updates below; replaces the old single `create_group_if_not_exists` + `add_user_to_group` pair)
6. If `'customer'` is one of `roles` and a customer record exists with matching email, link `customer.user_id` (set to the new `tenant_user.id`, i.e. also the Cognito sub)

### Updating Roles (PATCH /tenant/users/{id})
**Breaking change:** same `role` → `roles`/`primary_role` shape change as create. When
`roles` is present in the PATCH body:
1. `repository.set_user_roles()` replaces the user's `tenant_user_role` rows and mirrors
   the new primary role into `tenant_user.role`, transactionally.
2. `CognitoClient.sync_user_groups()` reconciles Cognito group membership to match —
   **this is the fix for a real, pre-existing bug:** before this change, editing a
   staff member's role updated the DB row and forced re-login
   (`global_sign_out`), but never touched actual Cognito group membership (no
   `remove_user_from_group` existed at all). A user re-derived their *old* role from
   their *old*, untouched group after re-login — role changes had no real effect on
   permissions. `sync_user_groups` is a genuine add/remove diff against
   `admin_list_groups_for_user`, scoped to this tenant's `{tenant_id}:*` groups only
   (never touches `platform_admin` or another tenant's groups).
3. `custom:role` Cognito attribute is updated to the new primary role.
4. `global_sign_out` is called — now it actually matters, since group membership
   genuinely changed.

Verified live against the local stack (Moto Cognito): seeded multi-role user
`amaka@acmeshipping.com` (Acme tenant, `nigeria_office_staff` + `warehouse_attendant`)
started with both Cognito groups; `PATCH /v1/tenant/users/{id} {"roles": ["warehouse_attendant"]}`
removed the `nigeria_office_staff` group (confirmed via `admin-list-groups-for-user`
before/after) and updated `custom:role`. A follow-up request gated to
`nigeria_office_staff` correctly 403'd afterward; a request gated to
`warehouse_attendant` still succeeded.

### Platform Admin Auth Structure
Platform admin requests use a distinct JWT structure from tenant users:
- `cognito:groups`: `"platform_admin"` (no tenant prefix — unlike tenant users which use `"{tenant_id}:{role}"`)
- `custom:tenant_id`: `"PLATFORM"` (bypasses per-tenant active/suspended check in auth middleware)

Locally, set `X-Role: platform_admin` and `X-Tenant-ID: PLATFORM` to simulate platform admin access.

### Tenant Status Transitions

| From | To | Endpoint | Notes |
|---|---|---|---|
| `active` | `suspended` | `PATCH …/suspend` | Blocks all tenant requests immediately (cache evicted) |
| `suspended` | `active` | `PATCH …/activate` | Lifts suspension |
| `active` | `offboarded` | `DELETE …/{id}` | Terminal — `offboarded_at` + `deletion_scheduled_at` (+90d) set |
| `offboarded` | `active` | `PATCH …/reactivate` | Re-onboarding only; `activate` is blocked for offboarded tenants |

**Update guard**: `PATCH /v1/platform/tenants/{id}` (update fields) is blocked for `offboarded` tenants — returns 410.

### PATCH /v1/platform/tenants/{id}/reactivate — Re-onboarding

Re-onboards an offboarded tenant under a **new agreement**. Distinct from `/activate` (which only lifts suspension).

**What it does:**
- Sets `status = 'active'`, stamps `reactivated_at = NOW()`, clears `deletion_scheduled_at`
- Evicts the tenant's cached status so requests unblock immediately
- Publishes `TenantReactivated` event to `logistics-events`
- Writes `TENANT_REACTIVATED` to `platform_audit_log`

**Response** includes a `notices` array with mandatory GDPR disclosures:
```json
{
  "tenant": { ... },
  "notices": [
    "CONSENT_REVERIFICATION_REQUIRED: Tenant admin must re-verify consent from all users under the new agreement.",
    "ANONYMISED_DATA_IRRECOVERABLE: Customer records anonymised during the offboarding period cannot be restored."
  ]
}
```

**GDPR considerations:**
- `reactivated_at` is the audit boundary — data processed after this timestamp operates under the new contract
- Anonymised customer records remain anonymised (Art. 17 erasure is irreversible)
- `tenant_user.consent_given_at` timestamps predate the new agreement — tenant admin must re-verify
- Financial records (billing, payments) are retained under legal obligation (Art. 6(1)(c)) and are immediately accessible on re-onboarding

### POST /v1/customers — Field Aliases
The create customer endpoint accepts `full_name` as an alias for the `name` field (normalised in the service layer). Both `{"name": "..."}` and `{"full_name": "..."}` are accepted.

### GET /v1/tenant/dollar-rate + /v1/tenant/cbm-rate — staff read access
Writes (`PUT`) to these two rate endpoints remain **tenant_admin only**, but the **`GET`** was widened to also allow `china_office_staff` and `nigeria_office_staff` (handler `_dispatch`, special-cased ahead of the blanket `assert_role(TENANT_ADMIN)` on the `/v1/tenant/*` section). Reason: the China packing-list wizard shows a live shipping-price estimate computed from the CBM rate × FX rate, and Nigeria staff preview the same when billing. Least-privilege read-only widening — a shipping rate is neither PII nor a secret. Every other `/v1/tenant/*` path/method is unchanged.

### GET /v1/customers — derived `shipment_count`
The customer **list** endpoint returns a derived `shipment_count` per row: a correlated `COUNT(*)` over `packing_list` for that customer (one packing list = one customer's cargo on one container = one lifetime shipment). Used by the packing-list wizard's customer picker card ("N shipments lifetime"). Not stored; computed in `list_customers` via a subquery-wrapped query so pagination cursors stay unambiguous. The single-record `GET /v1/customers/{id}` does not include it.

### GET /v1/customers/stats — tenant-wide aggregates
Returns SQL-computed counts so the admin customer list's and dashboard's stat cards stay correct beyond the first loaded page (data scales to tens of thousands of rows). Must be matched **before** the `/v1/customers/{id}` branch in `_customer_routes` (segment `"stats"` is not a UUID). Response body:

```json
{ "total": 70, "active": 68, "anonymised": 2, "with_whatsapp": 10, "shipments": 372 }
```

- `active` = `COUNT(*) FILTER (WHERE anonymised_at IS NULL)`, `anonymised` its complement.
- `with_whatsapp` = `COUNT(*) FILTER (WHERE 'whatsapp' = ANY(notification_consent))`.
- `shipments` = `COUNT(*)` over `packing_list` (lifetime shipments across all customers), a second tenant-scoped query.

Both queries run through `execute_with_tenant` (RLS-scoped). Consumed by the frontend as `customersApi.stats()` (`CustomerStats`, `customerKeys.stats()`).

### Minimum CBM per item (2026-10-02)

`GET /v1/tenant/cbm-rate` now also returns `min_cbm_per_item` (float, default 0.1), and `PUT /v1/tenant/cbm-rate` accepts an optional `min_cbm_per_item` (`> 0`; omit to leave unchanged). It's stored in its own `tenant_config` key (`min_cbm_per_item` = `{"value": …}`), separate from the rate config, and read by the packing-list service (`shared/cbm_rate.get_min_cbm_per_item`) to floor each line item's CBM — see `08_api_packing_list.md`. Surfaced on the CBM-rate admin page.

### Container capacity presets (2026-10-01)

`GET /v1/tenant/container-capacities` returns the ten built-in presets (code constants, `is_custom: false`, synthetic `id: "default:<name>"`) merged with the tenant's custom rows (`is_custom: true`, UUID id), sorted by `capacity_cbm` descending. Each item: `{ id, name, capacity_cbm (float), recommended_cbm (float|null), is_custom }`. CBM values are serialized as floats (not Decimal strings) so the frontend can format them directly.

`POST` (tenant_admin) adds a custom preset — validates `name` (required, ≤100 chars), `capacity_cbm` (>0, ≤1000) and optional `recommended_cbm` (>0 and ≤ capacity). `PATCH /{id}` edits the recommended load: for a **custom** preset it updates the DB row (name/capacity/recommended all editable); for a **default** (`default:<name>` id) it stores a per-tenant override of just the recommended load in `tenant_config` under `container_capacity_overrides` (a `{name: recommended}` map applied in the list merge) — a default's name/capacity are physical constants and can't change, and `recommended_cbm: null` reverts a default to its built-in value. `DELETE /{id}` removes a custom preset; a `default:*` id returns 422 (`CAPACITY_DEFAULT_IMMUTABLE`). All audit-logged (`entity_type=container_capacity`). Consumed as `containerCapacitiesApi` (`list`/`create`/`update`/`remove`). The chosen preset's name + CBM are snapshotted onto the container at create time — see `10_api_tracking.md`.

### GDPR Endpoints

#### DELETE /v1/customers/{id} — Right to Erasure (Art. 17)
Soft-deletes the customer by nulling all PII fields:
- `name`, `email`, `phone`, `whatsapp`, `address`, `contract_details` → `NULL`
- `anonymised_at` → set to current timestamp
- Customer UUID is retained for referential integrity (billing, shipment records remain)
- Returns `204 No Content`

#### GET /v1/customers/{id}/export — Data Portability (Art. 20)
Returns a full JSON export of all data held for a customer:
```json
{
  "customer": { ... },
  "billing": [ { "id": "...", "invoice_number": "...", "container_number": "...", ... } ],
  "shipments": [ { "id": "...", "tracking_code": "...", "status": "...", ... } ],
  "damage_claims": [ { "id": "...", "status": "...", "claimed_amount_ngn": "...", ... } ]
}
```

### `cognito_client.py` Implementation

```python
"""Cognito user provisioning wrapper."""
import boto3
import os

class CognitoClient:
    def __init__(self):
        self.client = boto3.client("cognito-idp", region_name=os.environ["AWS_REGION"])
        self.user_pool_id = os.environ["COGNITO_USER_POOL_ID"]

    def create_user(self, email: str, full_name: str, tenant_id: str, role: str) -> str:
        """Create Cognito user. Returns cognito_sub."""
        response = self.client.admin_create_user(
            UserPoolId=self.user_pool_id,
            Username=email,
            UserAttributes=[
                {"Name": "email", "Value": email},
                {"Name": "email_verified", "Value": "true"},
                {"Name": "name", "Value": full_name},
                {"Name": "custom:tenant_id", "Value": tenant_id},
                {"Name": "custom:role", "Value": role},
            ],
            DesiredDeliveryMediums=["EMAIL"],
        )
        return response["User"]["Attributes"][...sub...]

    def create_group_if_not_exists(self, group_name: str) -> None: ...
    def add_user_to_group(self, username: str, group_name: str) -> None: ...
    def disable_user(self, username: str) -> None: ...
    def enable_user(self, username: str) -> None: ...

    def update_user_attributes(self, username: str, full_name: str | None = None, role: str | None = None) -> None:
        """Update mutable Cognito attributes. Email (username) cannot be changed."""
        attrs = []
        if full_name is not None:
            attrs.append({"Name": "name", "Value": full_name})
        if role is not None:
            attrs.append({"Name": "custom:role", "Value": role})
        if attrs:
            self.client.admin_update_user_attributes(
                UserPoolId=self.user_pool_id, Username=username, UserAttributes=attrs
            )

    # --- Added 2026-07-20 (migration 039 — multi-role staff support) -------
    def remove_user_from_group(self, username: str, group_name: str) -> None:
        """Remove a user from a Cognito group (admin_remove_user_from_group). Did not
        exist before this change — role removal never actually revoked group membership."""
        ...

    def list_groups_for_user(self, username: str) -> set[str]:
        """Every group the user currently belongs to (admin_list_groups_for_user, paginated)."""
        ...

    def sync_user_groups(self, username: str, tenant_id: str, roles: set[str]) -> None:
        """Reconcile Cognito group membership to exactly match `roles`. Diffs against
        list_groups_for_user(), scoped to this tenant's `{tenant_id}:*` groups only —
        adds missing groups, removes unassigned ones. The actual fix for the group-sync
        bug described below. N=1 (a single-role user) is just the common case."""
        ...
```

### PATCH /tenant/users/{id} — Update User
- Supports updating `full_name`, `locale`, and/or `roles`/`primary_role` (validated by
  `UpdateTenantUserRequest`, replacing the old ad-hoc dict filter off the raw body)
- **Breaking change (2026-07-20, migration 039):** the old singular `role` field is
  gone — see "Updating Roles" above
- Email (`username`) **cannot** be changed — it is the immutable Cognito username used as login credential
- Both DB record and Cognito user attributes/groups are updated in sync:
  - `full_name` → Cognito `name` attribute
  - `roles`/`primary_role` → `tenant_user_role` rows + `tenant_user.role` (via `set_user_roles`) + Cognito `custom:role` attribute + Cognito group membership (via `sync_user_groups` — see "Updating Roles" above for the bug this fixes)

### GET /v1/platform/audit-log — Platform Audit Log

Query params:

| Param | Type | Default | Description |
|---|---|---|---|
| `limit` | int | 50 | Page size |
| `tenant_id` | UUID | — | Filter by target tenant (optional) |
| `action` | string | — | Filter by action e.g. `TENANT_UPDATED`, `TENANT_CREATED` (optional) |
| `cursor` | string | — | Opaque pagination cursor from previous response (optional) |

Response uses standard `paginated()` envelope: `{ "data": [...], "next_cursor": "...", "has_more": true }`.

### Dollar Rate — Bybit P2P base + per-tenant markup (2026-09-19)

**The rate is no longer typed in directly.** The base USD/NGN rate tracks the real black-market rate via Bybit's public P2P USDT/NGN order book (`shared/fx_rate.py`); a tenant_admin only controls a markup layered on top of it (percentage, or a flat ₦ amount added to the rate). Every consumer that used to read `tenant_config['dollar_rate']` independently — billing (`handle_payment_due`), claims (NGN↔USD conversions), refunds (staff approval threshold) — now calls `shared.fx_rate.get_effective_dollar_rate(tenant_id)`, the single source of truth.

**Bybit endpoint** (public, unauthenticated — the same call bybit.com's own P2P page makes; not part of Bybit's official signed v5 API, which is scoped to a merchant managing their own ads): `POST https://api2.bybit.com/fiat/otc/item/online`, body `{"tokenId":"USDT","currencyId":"NGN","side":"1",...}`. `side="1"` returns sell-USDT ads sorted ascending by price (cheapest first) — the rate at which Naira converts to dollars, verified live to be the lower of the two sides. The effective base rate is the mean of the cheapest 5 online ads.

**Caching/fallback chain** (`shared/fx_rate.get_base_market_rate`), since every billing/claim/refund calculation would otherwise hit Bybit directly:
1. Redis (`DistributedCache`, `fx_rate:ngn_usdt` key, 10-minute TTL) — the fast path almost every call hits.
2. On a cache miss: a circuit-breaker-guarded (`get_circuit_breaker("bybit_p2p")`) live fetch. Success populates both the Redis cache and a platform-wide fallback row (`platform_settings` key `fx_bybit_ngn_rate` — migration 011's table, no RLS, platform-scoped, not tenant data since the black market doesn't vary by tenant).
3. On fetch failure (Bybit down, circuit open): fall back to that persisted `platform_settings` row, however old, logged at WARNING.
4. If that's also missing (a platform that has never successfully fetched a rate): a hardcoded constant, logged at ERROR. Billing/claims/refunds must never hard-block on a missing rate.

No manual override exists (confirmed with the user) — the fallback chain above is the only safety net for a Bybit outage.

- **GET /v1/tenant/dollar-rate** — Returns:
  ```json
  {
    "rate": 1588.20,          // effective — base_rate with this tenant's markup applied; what customers are billed at
    "base_rate": 1573.20,     // raw Bybit P2P rate, before markup
    "markup_type": "flat",    // "percentage" | "flat"
    "markup_value": 15.0,
    "source": "bybit_p2p",
    "fetched_at": "2026-09-19T12:27:57Z",   // when the underlying Bybit rate was last actually fetched (may be older than "now" — cache/fallback)
    "currency_pair": "USD_NGN",
    "effective_from": "2026-09-19T00:00:00Z" // when this tenant's markup was last changed — "" if never changed
  }
  ```
- **PUT /v1/tenant/dollar-rate** — Body: `{ "markup_type": "percentage" | "flat", "markup_value": number }` (`UpdateDollarRateMarkupRequest`, both fields required, `markup_value >= 0` — a markup discounting below Bybit's own rate isn't a "markup"). Upserts `tenant_config['dollar_rate_markup']`, computes the resulting effective rate, appends a `rate_history` row (best-effort, swallowed on failure — values must be pre-cast to plain `float`/`str` before that call, since `repo.append_rate_history`'s `json.dumps()` has no `default=str` and raises on a raw `Decimal`; a real bug caught live during this feature's rollout, see `00_MASTER_PLAN.md`), audit-logs the change, and returns the same shape as GET plus `previous_rate`. tenant_admin only.
- **`tenant_config['dollar_rate']`** (the old key) is no longer read anywhere — a tenant's existing row is harmless legacy data, left in place rather than migrated/deleted. New tenants get `dollar_rate_markup: {markup_type: "percentage", markup_value: 0}` instead (`DEFAULT_CONFIGS`) — zero markup passes Bybit's rate straight through, so no tenant's pricing silently jumps on rollout.

### CBM Rate

**2026-09-20 — currency choice + per-package-type rates.** A tenant admin can
now choose (1) the currency the CBM freight rate is priced in (USD or NGN,
previously USD-only) and (2) whether it's one flat rate or three separate
rates for carton/bag/bale package types (`packing_list_item.package_unit`,
a free-text column — pallet/item/mixed/unspecified/anything else bills at
the carton rate). "Flat" is not a separate code path anywhere downstream —
it's simply the state where `carton_rate == bag_rate == bale_rate`; the
request validator (`UpdateCbmRateRequest._resolve_per_type_rates`) enforces
this server-side whenever `rate_mode = "flat"`, ignoring whatever
`bag_rate`/`bale_rate` the client sends.

`tenant_config['cbm_rate_per_unit']` shape: `{"currency": "usd"|"ngn",
"rate_mode": "flat"|"per_package_type", "carton_rate": number, "bag_rate":
number, "bale_rate": number, "effective_from": iso8601}`. `shared/cbm_rate.py`
(mirrors `shared/fx_rate.py`'s role) is backward-compatible with the
pre-2026-09-20 shape (`{"rate_usd": number}`) at read time — no data
migration was needed; an existing tenant's stored row is normalized on
every read.

- **GET /v1/tenant/cbm-rate** — Returns `{ "currency", "rate_mode",
  "carton_rate", "bag_rate", "bale_rate", "effective_from" }`. Roles: same
  as dollar-rate (`tenant_admin`, `china_office_staff`, `nigeria_office_staff`
  — the China packing-list wizard's live pricing estimate needs it).
- **PUT /v1/tenant/cbm-rate** — Body (`UpdateCbmRateRequest`):
  `{ "currency": "usd"|"ngn", "rate_mode": "flat"|"per_package_type",
  "carton_rate": number, "bag_rate"?: number, "bale_rate"?: number }`.
  `bag_rate`/`bale_rate` are required when `rate_mode = "per_package_type"`,
  ignored (forced equal to `carton_rate`) when `rate_mode = "flat"`. Upserts
  `tenant_config`, appends a `rate_type="cbm_rate"` row to `rate_history`
  (best-effort, values pre-cast to `float` — same `json.dumps` gotcha as
  `dollar_rate_markup`, see above), audit-logs, and returns the same shape
  as GET. tenant_admin only.
- New tenants are seeded directly with the new shape (`DEFAULT_CONFIGS`):
  `{currency: "usd", rate_mode: "flat", carton_rate: 45.00, bag_rate: 45.00,
  bale_rate: 45.00}` — identical effective behavior to the pre-2026-09-20
  default, just in the new shape.
- **Billing** (`services/billing/service.py::handle_payment_due`) groups a
  customer's approved-packing-list CBM by package type
  (`repo.get_cbm_by_package_type`, `GROUP BY package_unit`) and prices each
  bucket at its own rate (`shared/cbm_rate.py::compute_cbm_charge`) — see
  `11_api_billing.md` for the full calculation and the `billing` table's new
  `cbm_rate_currency`/`cbm_rate_mode`/`cbm_breakdown` columns.
- **Ground-truth bug fixed in the same pass**: `rate_history`'s `rate_type`
  for CBM changes has always been written as `"cbm_rate"` (this doc already
  said so), but the frontend queried `"cbm_rate_per_unit"` (the
  `tenant_config` *key*, not the `rate_history` *rate_type*) — so the CBM
  Rate History table/chart on `CbmRateConfig.tsx` silently never matched any
  row. Fixed frontend-side only (`frontend/src/api/tenantManagement.ts`).
- **Ground-truth bug fixed in the same pass**: `get_cbm_rate`'s response
  returned raw `Decimal` values, which `shared/responses.py`'s `success()`
  serializes via `json.dumps(..., default=str)` — silently turning every
  rate into a JSON *string*, inconsistent with `update_cbm_rate`'s response
  (already `float`-cast) and, found live via a real browser hitting this
  route, a frontend crash (`config.carton_rate.toFixed is not a function`,
  since the frontend types these fields as `number`). `get_cbm_rate` now
  casts to `float` before returning, matching `update_cbm_rate`'s existing
  behavior. Note: `get_dollar_rate` has the identical latent issue
  (`rate`/`base_rate`/`markup_value` are raw `Decimal`) — currently benign
  only because `DollarRateConfig.tsx` happens to use `.toLocaleString()`
  everywhere rather than `.toFixed()` (a string silently no-ops through
  `.toLocaleString()`, so no crash, just unformatted display for a JSON
  string vs. a number) — left unfixed here as out of scope for this task,
  flagged for whoever next touches that endpoint.

### Rate History
**GET /v1/tenant/rate-history** — Paginated audit of rate changes (migration 025, `rate_history` table, RLS-enabled, append-only).

Query params: `rate_type` (`dollar_rate` or `cbm_rate`), `limit`, `cursor`.

Response: standard `paginated()` envelope. Each row: `id, tenant_id, rate_type, rate_value (JSONB), previous_value (JSONB), changed_by, effective_from, created_at`.

### Session Invalidation on Role Change
When `PATCH /v1/tenant/users/{id}` changes a user's `roles`, `update_user` calls `cognito.global_sign_out(email)` immediately after `sync_user_groups`/Cognito attribute updates (best-effort — failure is logged at WARNING and does not block the response). This prevents a demoted user's existing JWT from retaining elevated claims for up to 1 hour — and, since migration 039, actually matters: group membership genuinely changes now (previously the group was never touched, so re-login just re-derived the same old role regardless of sign-out).

### Outbound Webhook
Tenant admins configure an outbound HTTP webhook in `tenant_config` key `webhook_config`:
```json
{
  "enabled": true,
  "url": "https://erp.acme.com/hooks/shipx",
  "secret": "hmac-secret-key",
  "events": ["container.status_updated"]
}
```
On each matching event, `shared/webhook.py` fires a signed POST (HMAC-SHA256, header `X-ShipX-Signature-256: sha256=<hex>`). Fire-and-forget — failures are logged at WARNING and never surface to the caller. Default `webhook_config` is disabled. Currently fires on `container.status_updated` from the tracking service.

**Endpoint URL validation / SSRF hardening (2026-09-23).** `endpoint_url` is tenant-controlled and fetched from inside the VPC, so `^https://` was not enough (it allowed `https://169.254.169.254/…`, `https://10.x.x.x/…`, `https://localhost/…`, hostnames resolving to those, and redirects to them). Now:
- **Save time** — `PUT /v1/tenant/config` rejects (`422`) non-https, embedded credentials, `localhost`/`.local`/`.internal`-style hosts, and any IP literal that isn't globally routable (incl. `2130706433`, `0x7f.1`, IPv4-mapped IPv6).
- **Delivery time** — `shared/url_safety.open_public_https()` re-resolves the host and refuses if *any* address is private/reserved (DNS can change after save), connects to the validated IP with TLS verified against the original hostname, and does not follow redirects. A 3xx from the endpoint is treated as a delivery failure.
- `POST /v1/tenant/config/webhook/test` returns the reason (`"Endpoint URL must not point at a private or reserved address"`) for a blocked target instead of a raw socket error, so it can't be used as an internal port-scan oracle.
- Configs saved before this change are re-checked at delivery, so a previously-saved internal URL is inert.

See `02_shared_utilities.md` (`shared/url_safety.py`) and `00_CROSS_CUTTING_STANDARDS.md` §8.4.

### Multi-Tenant Paystack — Design Note (2026-07-19)

**Problem.** Every tenant is a separate shipping company; their customers' payments must land in *that tenant's own* Paystack account, never a platform-wide one. The original implementation used a single `PAYSTACK_SECRET_KEY` Lambda env var (one Terraform variable, shared by every tenant) — a real commingling risk once any second real tenant went live, since a tenant who hadn't set up their own key would silently have payments processed against whoever's key happened to be configured platform-wide.

**Storage.** A new `tenant_config` key, `paystack_config`:
```json
{
  "enabled": true,
  "secret_key_encrypted": "<KMS+Fernet ciphertext — shared/encryption.py>",
  "last4": "3afb",
  "environment": "test",
  "configured_by": "<tenant_user id>",
  "configured_at": "2026-07-19T02:06:40Z"
}
```
`secret_key_encrypted` is **never** returned by `GET /v1/tenant/config` — not masked like `webhook_config.secret` (`****`), stripped from the response entirely. This is a deliberate departure from the `webhook_config` precedent (which stores its HMAC secret in plaintext): a Paystack secret key can move real money out of the tenant's account, whereas the webhook secret only signs outbound payloads ShipX itself sends — the blast radius is categorically different, so it gets the stronger `shared/encryption.py` (KMS + Fernet) protection already used for `pickup_record.id_number`, not the plaintext-JSONB shortcut.

**No platform-wide fallback.** `initialize_online_payment()` resolves the calling tenant's own key via `repository.get_tenant_paystack_secret()`; if none is configured, it raises `PAYMENT_GATEWAY_NOT_CONFIGURED` (422) — bank transfer remains available, "Pay online" simply doesn't appear as a working option until the tenant connects their own account. There is no Terraform variable or Lambda env var to fall back to anymore — `paystack_secret_key` was removed from `infrastructure/aws/variables.tf` / `modules/lambda`.

**Webhook signature verification — the ordering had to invert.** `POST /v1/webhooks/payment` has no JWT (Paystack can't send one) and no `{tenant_id}` in its URL — one shared endpoint for every tenant. Previously: verify HMAC using the one global secret, *then* resolve which tenant the payment belongs to. With per-tenant keys there's no single secret to verify against up front, so the order flips:
1. Parse the JSON body (no trust yet — just reading fields).
2. Extract `billing_id` from the payment `reference` (a harmless string split).
3. Look up `tenant_id` for that `billing_id` (`get_billing_tenant()`, `PLATFORM_TENANT_ID`-scoped — a read, not a trust decision).
4. Fetch and decrypt *that* tenant's own Paystack key.
5. **Only now** verify the HMAC signature — against that specific tenant's key.
6. Only on success does `process_webhook_payment()` ever touch the database.

This is a *stricter* invariant than the old single-secret world, not a weaker one: a signature is only ever accepted against the exact tenant its reference claims to belong to, so a leaked key from tenant B can never be replayed to forge a payment confirmation against tenant A's billing. The endpoint still returns `200` with an empty body on every rejection path (bad signature, unknown billing_id, tenant has no gateway configured) — same anti-timing-attack posture as before, now covering more rejection reasons. See `services/payment_release/webhook.py` and `handler.py::_webhook_routes` for the implementation; `services/payment_release/paystack.py`'s module docstring has the same design note.

Flutterwave (unused — no frontend integration) was left on its original single env-var secret; out of scope for this migration.

**Verified live** (not just unit tests): two tenants each configured with a different key; a webhook payload referencing tenant A's billing but signed with tenant B's key was correctly rejected (billing stayed unpaid); the same payload signed with tenant A's real key was correctly accepted (billing flipped to paid, correct amount). See `tests/unit/test_payment_webhook.py`, `tests/unit/test_payment_release.py::TestInitializeOnlinePayment`, `tests/unit/test_tenant_management.py::TestPaystackConfig`.

### Manual Bank Transfer Configuration (added 2026-09-06)

**Ground-truth gap found live, reported directly by the user:** `MyBillingDetail.tsx`'s "Manual bank transfer" payment option hardcoded a single tenant's bank account ("First Bank of Nigeria" / "Acme Shipping Ltd") and showed it to **every** tenant's customers — a Global Cargo Co customer transferring money would have been shown Acme's account details. Not just an ambiguity; a real money-misdirection risk.

**Storage.** A new `tenant_config` key, `bank_transfer_config` (plain JSONB — nothing here is a secret, unlike `paystack_config`):
```json
{
  "bank_name": "GTBank",
  "account_name": "Acme Shipping Ltd",
  "account_number": "0123456789",
  "sort_code": null,
  "instructions": "Use your invoice number as the payment description"
}
```
Set via the existing generic `PUT /v1/tenant/config {bank_transfer_config}` (`BankTransferConfigRequest` in `services/tenant_management/models.py`) — no new route needed, following the same pattern `branding`/`notification_preferences` already use. Tenant-admin UI: a new "Manual bank transfer" card on `PaymentGatewayConfig.tsx`, alongside the Paystack connection card.

**`GET /v1/tenant/config` widened to `CUSTOMER`** so `MyBillingDetail.tsx` can read the tenant's own account instead of a hardcoded one — safe, since the response already masks `webhook_config.secret` and strips `paystack_config`'s secret key entirely, and every *write* plus the webhook sub-routes stay behind the `tenant_admin` assert (only the exact-path `GET` branch was widened). Covered by `TestTenantConfigReadAccess::test_customer_can_read_config` in `tests/unit/test_tenant_management.py` (renamed from `test_customer_cannot_read_config` — this is a deliberate policy change, not a regression).

A tenant with no `bank_transfer_config` set shows customers a clear "Your shipping company hasn't set up bank transfer details yet" message instead of silently falling back to anyone else's account.

See `13_api_payment_release.md`'s "Payment Claims" section for the customer's "I've made this payment" + evidence flow that sits alongside this fix.

### Cognito Resend-Invite / Reset-Password
- **POST /v1/tenant/users/{id}/resend-invite** — Calls `admin_create_user` with `MessageAction=RESEND`; re-delivers the temporary-password email without creating a new account.
- **POST /v1/tenant/users/{id}/reset-password** — Calls `admin_reset_user_password`; Cognito sends a verification-code reset email.

Both are tenant_admin only.

### Tier Limits (from Task 03)
- Starter: 10 users, 5 containers/month, 5 GB storage
- Business: 50 users, 25 containers/month, 25 GB storage
- Enterprise: unlimited (or very high limits)

## Customer Self-Registration

**POST /v1/register/{slug}** — Public endpoint (no JWT required). `POST /v1/register` (slug in the body's
`slug` field, or Host-header resolution as a last-resort fallback) still works for backward compatibility.

Customers register against the tenant identified by the `{slug}` path param — the frontend's
`/register/:slug` company-specific signup link. Falls back to Host-header resolution (custom_domain, then
subdomain slug) only when no slug is supplied at all, since the frontend calls a shared
`VITE_API_BASE_URL` and never actually reaches the tenant's own host in practice (see ground-truth fix
below).

Request body:
```json
{
  "name": "Ngozi Okonkwo",
  "email": "ngozi@example.com",
  "phone": "+2348012345678",
  "whatsapp": "+2348012345678",
  "notification_consent": ["sms", "email"]
}
```

Guards: tenant must be `active`; email must not already exist in that tenant's customer table. Cognito
sends a temporary password to the customer's email. `tenant.slug` (migration 023) is auto-derived from
`company_name` at tenant creation. `phone`/`whatsapp` are normalised to E.164 (`shared/phone.py`) using
the tenant's `destination_country` dial code before being stored.

**Ground-truth gap found and fixed (2026-07-11):** this route existed in `tenant_management/handler.py` and was called by the frontend's `RegisterScreen.tsx`, but was missing from both `infrastructure/aws/modules/api-gateway/main.tf`'s `public_routes` map and `scripts/local_server.py`'s `_ROUTES` table — self-registration would 404 in production (never provisioned in API Gateway) and in local dev alike. Added to both.

**Ground-truth bug found and fixed (2026-08-28):** `self_register_customer` wrote the Cognito sub directly into `customer.user_id` — a column with `FOREIGN KEY REFERENCES tenant_user(id)`, verified against the live schema — and never created a `tenant_user` row. That write could never succeed against the real schema; self-registration had never actually worked. Fixed: the function now also creates the `tenant_user` row (`role='customer'`, `id` = the Cognito sub per the existing `id == cognito_sub` convention every other created-by/user chain relies on) and links `customer.user_id` to *that row's id*, not the bare sub. Regression test: `TestSelfRegisterCustomer.test_creates_tenant_user_and_links_customer_user_id` asserts `customer.user_id` resolves to a real `tenant_user`. Tenant resolution was also fixed at the same time: previously Host-header-only (unreachable — see the 2026-07-11 gap above still applying at the transport layer even once the route existed), now resolves from the explicit `{slug}` path param first.

## Customer Account-Creation Invites

Manifest import creates `customer` rows from the forwarder's file with only `name` + `phone` (no email, no
way to log in). This mechanism issues an expiring, single-use link — delivered by SMS/WhatsApp, the only
contact a manifest gives — that lets the customer set an email + password and claim a portal account.

Implementation: `shared/invites.py` (token mint/hash/validity — mirrors `impersonation.py`'s session-row
pattern, minus JWT signing) + `services/tenant_management/service.py` (`issue_customer_invite`,
`get_customer_invite_public`, `accept_customer_invite`). Table: `customer_invite` (migration 042, §05a).

**A random token, never a JWT.** Single-use revocation needs a server-side row regardless (to flip
`consumed_at`), so a JWT buys nothing while adding claims that can't be withdrawn once issued.
`secrets.token_urlsafe(32)`, stored only as a SHA-256 hash — a leaked `customer_invite` table gives no
working links. 48-hour expiry. Issuing (or resending) first deletes any prior unconsumed invite for that
customer — a resend invalidates the old link.

| Method | Path | Auth | Purpose |
|---|---|---|---|
| POST | `/v1/customers/{id}/invite` | staff (any `_STAFF_ROLES`) | Issue or resend an invite. Never returns the raw token to staff — only `id`, `expires_at`, `sent_channel`, `sent_to_masked`. `sent_channel` is delegated to `shared/notifications.py::primary_channel` — it was hardcoded to `sms` and kept reporting SMS after the switch to WhatsApp-first, telling staff the link went out over a channel it never used. |
| GET | `/v1/invites/{token}` | public | Claim-page preview — `company_name`, `customer_name`, `expires_at` only. 404 if unknown/expired/consumed (no distinction given to the caller — a leaked token search must not confirm which case it is). |
| POST | `/v1/invites/{token}/accept` | public | Body `{email, password}`. Creates the Cognito login **and** the `tenant_user` row (the same FK the self-register fix above closes), links `customer.user_id`, stamps `consumed_at`. 404 if unknown/expired/consumed; 409 if the email is already registered for the tenant. |

`issue_customer_invite` raises `BusinessRuleViolationError(rule_id="CUSTOMER_ALREADY_HAS_ACCOUNT")` if the
customer already has a `user_id` — inviting is only for customers who cannot yet log in.
`accept_customer_invite` is wrapped so a failed Cognito call leaves the invite unconsumed (the customer's
link keeps working; they can retry).

**Auto-issue on import**: `services/excel/service.py::process_manifest_import` issues an invite for every
customer the import *created* (never matched ones — they may already have a login), best-effort in the
same style as `record_usage` — a notification-side outage never fails the import itself.

**Portability seam**: login creation goes through `cognito_client.py` only —
`CognitoClient.create_user_with_password` (`MessageAction="SUPPRESS"` + `admin_set_user_password(...,
Permanent=True)`, no temp-password email since the customer chooses their own password at claim time). No
new module in this feature calls `boto3.client("cognito-idp")` directly.

Staff UI: "Send account invite" / "Resend account invite" on `AdminCustomerDetail.tsx`'s hero, and an
account-status indicator — *no login* / *invited, expires …* / *active* — on both `AdminCustomerList.tsx`
and `AdminCustomerDetail.tsx`, backed by a new `pending_invite_expires_at` correlated-subquery column on
`GET /v1/customers` and `GET /v1/customers/{id}`.

## Session Persistence — `services/auth/` (added 2026-07-11)

A separate, minimal Lambda service (not part of `tenant_management`) handling the httpOnly-cookie refresh-token flow that lets a page reload silently restore a session instead of forcing re-login. See [frontend/04_auth_and_session.md](frontend/04_auth_and_session.md) ("Token Refresh") and [frontend/11_security_and_compliance.md](frontend/11_security_and_compliance.md) ("Token Storage") for the full frontend-side flow and threat model.

All of these routes are public (`authorization_type = "NONE"`) — by definition, they run before any JWT exists or while one is being renewed:

| Method | Path | Purpose |
|---|---|---|
| POST | `/v1/auth/authorize-url` | **Entra only** (interactive login, added 2026-10-14). Server-generates the PKCE verifier + state + nonce, stashes them **base64url-encoded** (JSON `{v,s,n}`) in a short-lived httpOnly transaction cookie (`shipx_auth_tx`), and returns the Entra **authorize URL** for the SPA to redirect to. The BFF start of auth-code + PKCE — the flow that triggers the custom-claims provider (`tenant_id`/`role`). Includes `prompt=select_account` (override via `ENTRA_AUTHORIZE_PROMPT`; `""` disables) so the user can choose/switch accounts instead of Entra silently reusing its one SSO session. |
| POST | `/v1/auth/callback` | **Entra only** (interactive login). Body `{code, state}` from Entra's redirect; validates `state` against the transaction cookie, exchanges the code (`authorization_code` grant + stored verifier) server-side, sets the httpOnly refresh cookie, and returns `{id_token, expires_in}`. The PKCE verifier and refresh token never touch JS. |
| POST | `/v1/auth/login` | **Entra only, legacy ROPC login proxy** (added 2026-10-14; superseded by the interactive flow above for multi-tenant/MFA). Takes `{username, password}`, runs the password grant server-side (`entra_refresh.password_grant`), returns the token set. Kept for local-account/testing use; ROPC can't carry a tenant-scoped user's claims and doesn't trigger the claims provider. On Cognito this route **404s**. | Takes `{username, password}`, runs the OAuth2 password grant against Entra server-side (`entra_refresh.password_grant`), returns `{id_token, access_token, refresh_token, expires_in}`. Exists because Entra's token endpoint sends **no CORS header for the password grant**, so the SPA can't call it directly. Normalizes the submitted email to the account's managed-domain UPN via `ENTRA_USER_DOMAIN` so users log in with their real email. On Cognito this route **404s** (that SPA signs in client-side). |
| POST | `/v1/auth/session` | Persists a just-issued refresh token as a `Secure; HttpOnly; SameSite=Strict` cookie (`Path=/v1/auth`). Called once, immediately after a successful login (client-side on Cognito; from the `/v1/auth/login` response on Entra). |
| POST | `/v1/auth/refresh` | Reads the cookie (attached automatically by the browser), exchanges it (Cognito `REFRESH_TOKEN_AUTH` / Entra OAuth2 refresh-token grant, selected by `AUTH_PROVIDER`), returns a fresh `id_token` in the response body. Called on every app boot and on the API client's 401-recovery path. |
| POST | `/v1/auth/logout` | Revokes the refresh token server-side (`RevokeToken` — invalidates it and every access/ID token issued from it) and clears the cookie. |

Deliberately a separate, narrower Lambda from `tenant_management`: its IAM policy grants only `cognito-idp:InitiateAuth` and `cognito-idp:RevokeToken` on the user pool — the non-admin, non-destructive Cognito APIs. It cannot create, disable, delete, or read users (that stays scoped to `tenant_management`'s broader `cognito_admin` policy). It's also the one Lambda in this service tier not attached to the VPC — it never queries Aurora, so skipping the ENI attach avoids that cold-start cost on a path that sits on the critical render path of every page load.

**Implementation notes / ground-truth gaps found (2026-10-15 — interactive Entra login 401'd at the callback):** `/v1/auth/authorize-url` set the `shipx_auth_tx` cookie value to **raw JSON** (`{"v": …, "s": …, "n": …}`). That value contains spaces, commas, quotes and braces, which are not valid cookie-octets (RFC 6265), so browsers dropped/truncated the `Set-Cookie`; `/v1/auth/callback` then found no transaction cookie and returned `401 AuthenticationRequiredError` *before* the code exchange ran. Fixed by base64url-encoding the JSON on write and decoding on read (`services/auth/handler.py`); a malformed/undecodable tx cookie now fails closed (401). Covered by `tests/unit/test_entra_oauth.py::TestHandlerInteractiveRoutes` (authorize-url cookie value asserted free of raw-JSON chars + decodes to `{v,s,n}`; malformed-cookie case). Verified live on dev — the deployed `Set-Cookie` value is now base64url.

**Implementation notes / ground-truth gaps found (2026-10-15 — client-type mismatch on the code exchange):** once the callback reached Entra, the token redemption failed on the app registration's redirect-URI **platform type**. The callback (`https://shipx-dev-fde-…azurefd.net/auth/callback`) was originally registered under the Entra **SPA** platform, which only permits *cross-origin* redemption (a request carrying an `Origin` header) — `AADSTS9002327`. But this BFF redeems the code **server-side** with PKCE and **no client secret**: that is a **public client**, whose matching platform is **Mobile & desktop (publicClient)**, not SPA and not Web (Web would require a client secret / assertion). Resolution: the redirect URI was moved from `spa.redirectUris` to `publicClient.redirectUris` on the `shipx-spa` app (`c6d0fc93-…`, object `ce145844-…`) in the CIAM tenant via a Graph `PATCH` (`spa` emptied, `publicClient` set). publicClient redemption is a plain same-origin POST, so `services/auth/entra_refresh.py` must **not** send an `Origin` header — sending one makes Entra reject it as a cross-origin SPA redemption (`AADSTS9002326`, the inverse error). `_token_request` therefore sends no `Origin` (a brief SPA-era `cross_origin`/Origin experiment was reverted). Covered by `tests/unit/test_entra_oauth.py` (`test_sends_code_verifier_and_grant`, `test_refresh_does_not_send_origin_header` both assert no `Origin`). NB: the same platform move must be applied to each environment's app registration (staging/prod) when they are stood up.

**Implementation notes / ground-truth gaps found (2026-10-15 — claims extension 401'd token issuance):** with the redemption fixed, the exchange still failed with `AADSTS1100001` / underlying `1003002`. Cause: the `OnTokenIssuanceStart` custom authentication extension *does* fire during the `authorization_code` redemption and calls our `shipx-dev-entra-claims` `/token-claims` endpoint, which returned **401**, so Entra aborted token issuance. The 401 came from the caller **issuer** check: the CIAM tenant stamps tokens with the issuer host `https://<tenantGUID>.ciamlogin.com/<tenantGUID>/v2.0` (confirmed via the tenant OIDC discovery doc's `issuer`), but `entra_claims_caller_issuer` in `infrastructure/azure/environments/dev.tfvars` used the **tenant-name** host (`shipxcustomer.ciamlogin.com`). The JWKS host matched, so the RS256 signature + audience passed in `_verify_caller` (no warning) and only the exact-string `iss` compare in `services/entra_token_claims/security.py::is_authorized` failed — silently. Fixed: (1) `entra_claims_caller_issuer` set to the GUID-host issuer (needs a `terraform apply` to update the `CALLER_ISSUER` env on the claims Container App); (2) `services/entra_token_claims/app.py` now logs the audience/issuer mismatch on the 401 path (token identifiers, not secrets; the token is never logged) so the next such misconfig is diagnosable without a redeploy. Same host caveat applies per-environment.

**Implementation notes / ground-truth gaps found (2026-10-15 — frontend rejected the Entra token):** with issuance fixed, the SPA failed with `JWT is missing required claims (sub|oid / tenant id)`. The backend already normalizes Entra's quirks in `shared/providers/azure/entra_claims.py` (`EntraClaimsMapper`): a cloud-only security group is emitted in `groups` as its directory **object id** (a GUID), not the canonical `{tenant}:{role}`/`platform_admin` name, and CIAM does not emit a `tenant_id` claim for a group-based **platform admin** (tenant_id is derived as `PLATFORM` from the `platform_admin` group). The frontend `frontend/src/auth/jwt.ts` did none of this — it read a literal `tenant_id` claim and canonical group names — so a platform-admin token (only `oid` + a group GUID) threw at the tenant-id guard, and tenant users got degraded roles. Fixed by porting the mapper into `jwt.ts` (`normalizeEntraClaims`, applied only when `VITE_AUTH_PROVIDER=entra`, Cognito untouched): GUID→name via `VITE_ENTRA_PLATFORM_ADMIN_GROUP_ID`/`VITE_ENTRA_GROUP_ID_MAP`, `tenant_id=PLATFORM` derivation, and `{tenant}:{role}` synthesis from the `role`+`tenant_id` claims. The two new VITE vars are sourced from Terraform outputs (`entra_platform_admin_group_id`, `entra_group_id_map`) in `frontend-deploy.yml`, like `entra_client_id` — public ids, no secrets. Covered by `frontend/src/auth/jwt.test.ts` (`normalizeEntraClaims` + `buildSession — Entra provider (CIAM GUID token)`). Requires a **frontend redeploy** (`frontend-deploy.yml`, cloud=azure) to take effect.

**Implementation notes / ground-truth gaps found (2026-10-15 — every authenticated API call 401'd post-login):** login succeeded and the SPA built a session, but the dashboard's API calls returned `401 AUTHENTICATION_REQUIRED` (then refresh 401 → logout → back to login). Cause: the container's in-process token verifier `shared/auth_verify.py::_oidc_claims_to_context` projected the verified token into **Cognito-only** keys (`sub`, `custom:tenant_id`, `cognito:groups`), discarding the Entra claims (`oid`, `tenant_id`, `role`, `groups`). On Azure `get_tenant_context` uses `EntraClaimsMapper`, which reads those Entra keys — so it saw an empty identity and denied. (The backend analogue of the frontend `jwt.ts` gap above.) Fixed: `_oidc_claims_to_context` now passes the verified claims through unchanged, only flattening a list-valued `cognito:groups` to CSV (what `CognitoClaimsMapper` needs); every provider's claims survive to the authorizer context. Covered by `tests/unit/test_auth_verify.py::test_oidc_passes_entra_claims_through_unchanged`. Requires a **backend redeploy** (image roll via `deploy-azure.yml`).

**Implementation notes / ground-truth gaps found (2026-10-15 — provisioning a tenant 500'd):** `POST /v1/platform/tenants` (incl. the onboarding→provision flow) returned `500 Could not create tenant`. `service.create_tenant` creates the initial tenant-admin as an **Entra user via Microsoft Graph** (`EntraIdentityProvider.create_user` → `_graph("POST","/users")`), authenticating with `DefaultAzureCredential` — the Container App's **managed identity**. Two problems on this CIAM setup: (1) the managed identity wasn't resolvable for a Graph `.default` token ("Unable to load the proper Managed Identity"); (2) more fundamentally it is **cross-tenant** — the managed identity lives in the subscription's home tenant (`a59c21d1`), but users must be created in the **CIAM tenant** (`062cb98d`), and a managed identity is single-tenant, so it can never mint a Graph token for a foreign tenant. Fix: `_get_credential` now uses a `ClientSecretCredential` when `ENTRA_GRAPH_TENANT_ID`/`ENTRA_GRAPH_CLIENT_ID`/`ENTRA_GRAPH_CLIENT_SECRET` are set (an app registration **in** the CIAM tenant with Graph application permissions), falling back to `DefaultAzureCredential` otherwise. Wired through the `container_app` module (secret as a Container App secret, gated on the non-sensitive client id) with the secret injected at apply via `TF_VAR_entra_graph_client_secret` (a GitHub Environment secret — never committed). **One-time Entra setup required** (see `docs/runbook.md`): register the confidential app in `062cb98d`, grant Graph app permissions `User.ReadWrite.All` + `Group.ReadWrite.All` (admin-consented), set `entra_graph_client_id` in `dev.tfvars` + the `ENTRA_GRAPH_CLIENT_SECRET` GitHub secret. Covered by `tests/unit/test_entra_identity_provider.py::TestCredentialSelection`.

**Implementation notes / ground-truth gaps found (2026-10-15 — provisioning 500'd on a duplicate user, and duplicated tenants):** with Graph auth working, provisioning a tenant whose admin email already existed in the directory failed with `400 Request_BadRequest / ObjectConflict` ("userPrincipalName already exists"). Two bugs: (1) `shared/providers/azure/entra.py::_graph` only mapped **409** to `DuplicateResourceError`; Graph returns a duplicate UPN/identity as a **400 ObjectConflict**, so it surfaced as a 500. Entra is a shared directory (globally-unique UPNs) while ShipX scopes a user to a tenant via the `{tenant_id}:{role}` group, so an existing directory user is **idempotent**, not an error: `_graph` now maps 400-ObjectConflict→`DuplicateResourceError`, and `_create` catches it, resolves the existing `oid`, reconciles the role group, and returns — so provisioning completes and the same person can admin multiple tenants. (2) `create_tenant` committed the tenant row before creating the user and never closed the lead on failure, so a failed attempt left an orphan tenant with the lead still open, and each retry created another tenant. Added an idempotency guard: when `onboarding_request_id` is already `provisioned` (or linked to a tenant), `create_tenant` raises `DuplicateResourceError` instead of creating a second tenant. Covered by `tests/unit/test_entra_identity_provider.py::TestUserLifecycle` (conflict reuse) + `::TestErrorMapping` (400 ObjectConflict) and `tests/unit/test_tenant_management.py::TestCreateTenantLeadIdempotency`. **Cleanup:** orphan/duplicate tenants created by the earlier failed retries must be removed manually (there is no tenant hard-delete endpoint; offboarding only sets status).

**Implementation notes / ground-truth gaps found (2026-10-16 — ObjectIdentity query unsupported):** the idempotent-reuse path then failed resolving the existing local account: `_resolve_user_id`'s `identities/any(...)` `$filter` returned `400 Request_UnsupportedQuery` ("Unsupported query on property 'ObjectIdentity'"). Root cause: on **Entra External ID (CIAM)** that filter is a *regular* query — sending the advanced-query `ConsistencyLevel: eventual` header (+ `$count=true`) makes Graph reject it, the **opposite** of Azure AD B2C. Verified live against the tenant: no header → `200` with the match, header → `400`. Fixed by dropping the header + `$count` from that lookup in `shared/providers/azure/entra.py::_resolve_user_id`. Covered by `tests/unit/test_entra_identity_provider.py::TestResolveUserId`.

**Implementation notes / ground-truth gaps found (2026-10-17 — reusing an admin email 500'd on `tenant_user_pkey`):** provisioning with an admin email that already existed in the directory failed with `psycopg2.errors.UniqueViolation: duplicate key value violates unique constraint "tenant_user_pkey"`. Cause: `create_tenant_user` sets `id = cognito_sub` deliberately (every `created_by`/`approved_by` FK points at `tenant_user(id)`, and `TenantContext.user_id` is the raw IdP subject), so **one IdP identity belongs to exactly one tenant**. The idempotent-reuse added earlier (reuse an existing directory user instead of failing on a duplicate UPN) is correct for an *orphan* directory account, but when that subject already has a `tenant_user` row the insert necessarily violates the PK — and it blew up *after* the tenant row was committed, leaving an orphan tenant. Fixed with two guards using a new PLATFORM-scoped `repo.find_user_across_tenants(email=…|user_id=…)`: (1) `create_tenant` rejects a reused `initial_admin.email` **before creating anything** (`DuplicateResourceError` → 409, no orphan); (2) after the IdP resolves a subject, both `create_tenant` and `create_user` reject if that subject already has a row (catches the same person under a different email spelling, e.g. `…@gmai.com` vs `…@gmail.com`). Operators must use a distinct admin email per tenant. Covered by `tests/unit/test_tenant_management.py::TestCreateTenantIdentityConflict`.

**Implementation notes / ground-truth gaps found (2026-10-17 — provisioning 404'd on Graph replication lag):** `POST /v1/platform/tenants` failed with `404 Request_ResourceNotFound: Resource '<oid>' does not exist or one of its queried reference-property objects are not present`. Cause: Microsoft Graph is **eventually consistent** — provisioning creates the user and then immediately adds them to the `{tenant_id}:{role}` group, and the `POST /groups/{gid}/members/$ref` 404s because the just-created directory object has not replicated yet (that "reference-property objects" wording is the `$ref` target failing to resolve). Fixed in `shared/providers/azure/entra.py`: `_retry_while_missing` retries 404-shaped failures (4 attempts, 0.5s doubling ≈ 3.5s worst case) and `add_user_to_group` now (a) retries while the user/group is unresolvable, (b) treats an already-member re-add as success (Graph reports it as a 400 "already exist"), and (c) degrades to a logged warning rather than raising. `create_group_if_not_exists` tolerates a concurrent-create duplicate, and `_create` wraps the group reconcile best-effort. **Why this is safe:** on Entra the authoritative role is `tenant_user.role` (read by the claims provider), so the Entra group is a secondary signal and must never fail provisioning — unlike Cognito, where group membership *is* authoritative (that path is unchanged). Covered by `tests/unit/test_entra_identity_provider.py::TestReplicationLagTolerance`.

**Implementation notes / feature added (2026-10-16 — account activation so every role can actually log in):** operator-provisioned users (the initial tenant admin via `create_tenant`, and staff/customers via `create_user`) were created in the IdP with a random password and **no email**, so they could never complete a first sign-in — surfacing downstream as `JWT is missing required claims` (they authenticated but never had a usable session). Customers self-registering were fine (`create_user_with_password` sets their own password); only operator-provisioned users were stranded. Added a ShipX-branded **account-activation** flow mirroring `customer_invite`:

- **Data:** `tenant_user_activation` (migration 055) — single-use, 48h, SHA-256-hashed token keyed to `tenant_user`, RLS tenant-isolated (`shared/activation.py`).
- **Issue:** `service.issue_activation` mints a token and emails the user an `account_activation` notification with a `{APP_BASE_URL}/activate/{token}` link (rendered as a CTA button; `APP_BASE_URL`, else derived from `ENTRA_REDIRECT_URI`'s origin). Called best-effort from `create_tenant` (admin) and `create_user` (staff/all roles) — never fails provisioning; resendable.
- **Public endpoints (no JWT):** `GET /v1/activate/{token}` → `{email, full_name}` preview; `POST /v1/activate/{token}` `{password}` → sets the chosen password in the IdP (`IdentityProvider.set_password`, `forceChange=false` — Entra via the Graph provisioning app; Cognito `admin_set_user_password Permanent`) and consumes the token. Added to `shared/http_routing.py` `PUBLIC_ROUTES`/`ROUTES` and `infrastructure/aws/modules/api-gateway` `public_routes`.
- **Resend:** `POST /v1/tenant/users/{id}/resend-activation` (tenant_admin) → `service.resend_activation` re-issues the link (invalidating any prior unconsumed one) — for users provisioned before activation existed, or whose link expired. Surfaced as a "Resend activation link" button on the staff user detail page.
- **Frontend:** `/activate/:token` (`ActivateScreen.tsx`) — fixed email + new-password form; `activationApi` client.
- Covered by `tests/unit/test_activation.py`, `test_entra_identity_provider.py::set_password`. The claims pipeline itself was already correct; this gives provisioned users a first-login path, so **all roles** can sign in.

Cookie attributes (`services/auth/handler.py`): no `Domain` attribute (host-only scope — never sent to the frontend's own origin, only back to the API host that set it); `Max-Age` matches Cognito's `refresh_token_validity` (30 days, `infrastructure/aws/modules/cognito/main.tf`). Requires `allow_credentials = true` on the API Gateway CORS config (`infrastructure/aws/modules/api-gateway/main.tf`) — enforced via a Terraform variable validation block rejecting a wildcard `cors_allow_origins`, since browsers refuse credentialed cross-origin responses against a wildcard origin regardless.

## Notification Template Management

Tenant admins can customise per-event-type message copy:

| Method | Path | Role |
|---|---|---|
| GET | `/v1/tenant/notification-templates` | `tenant_admin` |
| GET | `/v1/tenant/notification-templates/{event_type}/{channel}` | `tenant_admin` |
| PUT | `/v1/tenant/notification-templates/{event_type}/{channel}` | `tenant_admin` |

`channel`: `sms`, `whatsapp`, `email`. Stored in `notification_template` table (migration 024, RLS-enabled). Embedded into SQS messages at enqueue time by `shared.notifications.enqueue_notifications`.

## Tenant Activity Log (2026-09-07)

**Ground-truth gap found live, reported directly by the user:** "we need to ensure that we have log trail for everything, since it has to do with people's goods and money, so that the tenant admin can see every activity going on." Two problems, both real:

1. **The only surface was a small dashboard widget** (`shell/ActivityFeed.tsx`, ~8 rows, no filtering) — a tenant admin had no page to actually browse or search the audit trail, unlike platform admins, who already had a full `PlatformAuditLog.tsx` page for platform-level actions. Added `frontend/src/pages/tenant-admin/ActivityLog.tsx` (route `/admin/activity-log`, nav entry under Admin), modelled directly on that existing page: filters, cursor pagination, and an expandable before/after diff per row.
2. **`GET /v1/tenant/activity`'s "lean projection" excluded `before_state`/`after_state` entirely** — "the feed only shows who/what/when" was fine for an 8-row dashboard widget, but is not an audit trail a tenant admin can actually verify a payment or refund against. `repository.list_tenant_activity()` now selects and returns both (`audit_log` already stores them; only `list_tenant_activity`'s hand-picked column list was excluding them).

**Follow-up the same day — the first filter (a single "Record type" dropdown) wasn't real filtering/sorting/search, reported directly by the user.** `GET /v1/tenant/activity` gained the full set, all combinable (`AND`, never a silent `OR` that would widen what an admin thinks they're looking at):

- `?entity_type=` now accepts **one or more** comma-separated values via `= ANY(%(entity_types)s)` — same contract as `GET /v1/containers`'s multi-status filter. This is what makes **categorization** real: the frontend groups every `entity_type` into six categories (Money, Goods & shipments, Customers, Staff & access, Settings, System) and sends every type in a category as one request when a category (not a specific type) is selected — "show me everything money-related" is a real query, not just a label.
- `?action=` — `CREATE` / `UPDATE` / `DELETE` / `STATUS_CHANGE`.
- `?q=` — matches the actor's name **or** the affected record's id (`u.full_name ILIKE %(q)s OR a.entity_id::text ILIKE %(q)s`). This is the actual "search" a money/goods audit trail needs: paste a `billing_id` or `payment_claim.id` to see every action ever taken on that one specific record, or type a name to see everything one person did.
- `?created_after=` / `?created_before=` — ISO dates, same contract as the container list's date-range filter; the frontend uses the shared `DateRangeFilter` component (7/30/90-day presets).
- `?sort=asc|desc` (default `desc`) — passed straight through to `build_paginated_query`'s existing `sort_direction` parameter, which already flips the cursor comparison operator correctly for either direction, so ascending pagination ("oldest first") works with no separate code path.

**Auditing actual log *coverage* while building this turned up real gaps in the backend, not just the viewer** — several money- or goods-affecting writes had no `log_audit()` call at all, so even the new page would have shown nothing for them:

- `billing.handle_payment_due` (creates the invoice itself — the money leaving no trace at all) — now logs `entity_type="billing"`.
- `billing.reject_dispute` (every other dispute transition already logged; reject was the one exception) — now logs `entity_type="cbm_dispute"`.
- `claims.log_missing_item` / `update_missing_item`, `claims.log_seized_item` / `update_seized_item`, and the `refund_request` each can trigger on compensation/recovery — none were logged at all. Now all four log, plus a separate entry for the triggered refund.
- `excel.import_packing_list` and `excel.process_manifest_import` (bulk-creating containers/customers/packing lists/cartons — goods entering the system with zero trail) — each now writes **one summary entry**, not one per row, since a single import can create dozens of records.
- `tenant_management.deactivate_charge_type` (create/update both logged; deactivate was the exception) — now logs.

**A separate, more serious bug found while adding the `billing.handle_payment_due` entry — see `02_shared_utilities.md`'s matching write-up:** `shared.audit.log_audit()` never raises on failure, and two system-triggered call sites were passing a non-UUID placeholder string (`"gateway"`, `"system"`) into `actor_id`, a `UUID` column — every webhook-confirmed payment had **silently never been audit-logged** since that code existed, with nothing surfacing the failure. Fixed by passing `None` instead (a legitimate "no human actor" value the column already supports) and typing `log_audit`'s `actor_id` as `str | None`.

Verified live against the real local stack: `GET /v1/tenant/activity?entity_type=payment_claim` correctly returns the full history for that entity type with real `before_state`/`after_state` (a real customer's claim submission → a real staff confirmation, both fully attributed); the new page renders it with a working filter dropdown and expandable diff. Confirmed the `log_audit` fix directly: reproduced the `invalid input syntax for type uuid: "gateway"` failure against the real DB, then confirmed passing `None` writes a real row.

Tests: `TestTenantActivityFeed` (entity_type/action/search/date-range/sort param passthrough) and the new `TestListTenantActivityFiltersRepository` (asserting the actual SQL each filter produces, and that they combine with `AND`) in `test_tenant_management.py`; `TestMissingSeizedItemAuditLogging` (`test_claims.py`); `TestRejectDisputeAuditLogging` (`test_billing.py`); `ActivityLog.test.tsx` (frontend — category narrows record-type options and clears on category change, action/search/sort each re-fetch correctly, Clear filters resets everything together). See `17_testing.md` for the full list.

Verified live against the real local stack: Category → "Money" correctly returned only the 7 money-related entity types and narrowed the Record-type dropdown to match; selecting a specific type within it narrowed further; searching "Emeka" correctly isolated that one actor's entries; switching sort to "Oldest first" correctly flipped the first row from the newest to the oldest real record.

**Third same-day follow-up, three separate pieces of direct user feedback:**

1. **Custom date range.** The day-preset `DateRangeFilter` alone isn't "fully functional" date filtering for an audit trail — added explicit "From"/"To" date inputs (`?created_after=`/`?created_before=` already existed on the backend from the filtering pass above; this is a frontend-only addition). A custom date always wins over the preset — picking one clears the other, so the two controls never silently disagree about what's actually being queried.
2. **The "Details" modal opened in the wrong place.** It used to render as a block appended *after the entire table* — clicking it on any row but the last meant scrolling well past the rest of the list, and the diff's position moved depending on which row was clicked. Now a `Modal` (design system component), which opens in the same place regardless of which row was clicked and never disturbs the table's scroll position.
3. **Impersonation records must not be visible to a tenant admin at all — reported directly, alongside a broader instruction that a platform admin must never see a tenant's sensitive financial data or logs.** Investigating turned up that `start_impersonation`/`end_impersonation` were writing `IMPERSONATION_START`/`IMPERSONATION_END` into the **tenant's own** `audit_log` (`entity_type="impersonation_session"`) — a platform-admin action performed *on* a tenant, not a tenant-side business event, and (per the bug found in the same investigation) never actually landing there anyway because `IMPERSONATION_START`/`END` aren't valid CHECK values (see `02_shared_utilities.md`'s widened writeup). Fixed properly, not just papered over in the UI: `services/tenant_management/impersonation.py` now calls `repository.insert_platform_audit()` instead of `shared.audit.log_audit()` — the same mechanism every other platform-level action already uses, visible only via `PlatformAuditLog.tsx`, never via a tenant's own `GET /v1/tenant/activity`. `list_tenant_activity()` also gained a hard `AND a.entity_type NOT IN ('impersonation_session')` clause on every query, unconditionally — belt-and-suspenders: a tenant admin cannot see one even if they explicitly ask for it by name in `?entity_type=`, and the exclusion holds even if a future call site regresses and writes one into the wrong table again. The frontend's Record-type dropdown no longer offers "Impersonation" as an option at all.

   **The broader ask — platform admin should not see a tenant's financial information generally, not just this one log type — is a real, separate policy question about what an impersonation session (or any platform-admin view of a tenant) is allowed to read, not something to guess at unilaterally.** Flagged back to the user rather than assumed; not yet implemented pending their answer on scope (e.g., whether impersonation should be blocked from Billing/Refunds/Claims entirely, or whether specific fields should be masked while the rest of the page stays usable for support purposes).

Tests: `TestImpersonationAudit` (`test_impersonation_audit.py`, new — confirms both functions call `insert_platform_audit`, not `log_audit`), `TestTenantActivityExcludesPlatformOnlyRecords` (`test_tenant_management.py` — the exclusion holds even when explicitly requested), plus new `ActivityLog.test.tsx` cases for the custom date range and the missing impersonation option.

## Platform Admin Impersonation

Platform admins can impersonate a tenant's Tenant Admin for read-only support/debugging. Implementation: `services/tenant_management/impersonation.py`.

### How it works
1. `POST /v1/platform/tenants/{id}/impersonate` — validates tenant is `active`, finds an active `tenant_admin` user, creates an `impersonation_session` row (migration 028), mints a short-lived HS256 JWT carrying `impersonated_by`, `session_id`, `read_only=true`. Returns the token + `expires_at`.
2. The caller uses the impersonation token as a Bearer token in subsequent requests.
3. The Lambda authorizer (`services/authorizer/handler.py`) detects the token type and validates it: verifies HS256 signature, checks the session is still active in DB. Synthesises `cognito:groups` so `get_tenant_context()` works unchanged.
4. `shared/auth.py:get_tenant_context()` populates `TenantContext.impersonated_by`, `.session_id`, `.read_only=True`.
5. `shared/auth.py:get_tenant_context()` calls `assert_not_read_only(ctx, method)` internally after building the context — this is the **single central chokepoint**. The HTTP method is read directly from `event.requestContext.http.method`. No individual write handler needs to call the guard; any future handler that calls `get_tenant_context()` is automatically protected. Non-GET/HEAD/OPTIONS requests with `read_only=True` raise `BusinessRuleViolationError(rule_id="IMPERSONATION_READ_ONLY")` (HTTP 403) before reaching business logic.
6. `DELETE /v1/platform/impersonation/{session_id}` — ends the session; sets `ended_at` + `end_reason`; writes `IMPERSONATION_END` audit record.

### Token format (HS256 JWT)
```json
{
  "sub": "target_user_id",
  "tenant_id": "target_tenant_id",
  "role": "tenant_admin",
  "impersonated_by": "platform_admin_user_id",
  "session_id": "uuid",
  "read_only": true,
  "exp": 1234567890,
  "iat": 1234567890
}
```
Signing secret: `IMPERSONATION_SECRET_ARN` (Secrets Manager) or `IMPERSONATION_SECRET` env var (local dev).

### Terraform changes required
Replace the native Cognito JWT authorizer with a Lambda REQUEST authorizer pointing to `services/authorizer/handler.lambda_handler`. The authorizer Lambda needs:
- VPC placement (DB access for session validation)
- Env vars: `COGNITO_JWKS_URL`, `COGNITO_AUDIENCE`, `IMPERSONATION_SECRET_ARN`
- IAM: `secretsmanager:GetSecretValue` on `IMPERSONATION_SECRET_ARN`

### `impersonation_session` table (migration 028)
Platform-scoped (no tenant RLS). Columns: `id, platform_admin_id, target_tenant_id, target_user_id, target_role, read_only, started_at, expires_at, ended_at, end_reason`.

## Shipping-Company Onboarding Requests (added 2026-10-11)

**Problem:** a shipping company (a *tenant*) had no public way to get onboarded — tenant creation was platform-admin-only, and the public `/register/:slug` page is customer-scoped (it demands a company slug). The two audiences were blurred: a company landing on `/register` was told to "use the link your shipping company gave you."

**Model — admin / sales-led.** A public lead form (`POST /v1/onboarding-requests`) captures a company's interest; a platform admin reviews the queue and provisions the tenant via the existing `POST /v1/platform/tenants`, passing `onboarding_request_id` to link + close the lead in one action. **No public/open tenant creation.** Customer onboarding (invite / `/register/:slug`) is unchanged.

- **`POST /v1/onboarding-requests`** (public, no JWT). Body (`CreateOnboardingRequest`): `company_name`, `contact_name`, `contact_email` (required); `contact_phone`, `monthly_volume`, `notes` optional; `origin_country`/`destination_country` default `China`/`Nigeria`. Inserts a `tenant_onboarding_request` row (status `new`) and best-effort `publish_event("OnboardingRequested", tenant_id=PLATFORM)` so notifications emails **platform ops** (not a customer). Returns only `{id, status}` — no account, no password, no tenant. No PII logged (only the request id). Registered as public in `shared/http_routing.py` `PUBLIC_ROUTES` **and** `infrastructure/aws/modules/api-gateway` `public_routes`, and short-circuited at the top of `lambda_handler` before `get_tenant_context`.
- **`GET /v1/platform/onboarding-requests?status=`** / **`GET …/{id}`** (platform_admin) — review queue, newest first.
- **`PATCH /v1/platform/onboarding-requests/{id}`** (platform_admin) — `OnboardingRequestStatusUpdate` (`status`, optional `rejection_reason`); audited via `insert_platform_audit("ONBOARDING_REQUEST_UPDATED")`.
- **`POST /v1/platform/tenants` extension:** optional `onboarding_request_id` in the body — on a successful create, `create_tenant` best-effort links `tenant_id` onto the lead and flips its status to `provisioned` (sets `reviewed_by`/`reviewed_at`). Failure to link is logged, not fatal (the tenant is already created).

Repository functions (`insert_onboarding_request`, `list_onboarding_requests`, `get_onboarding_request`, `update_onboarding_request`) run at `PLATFORM_TENANT_ID` scope (like `platform_settings`); writes use `RETURNING *` and `execute_write_with_tenant` returns the single row. Table defined in **migration 054** (`05b_database_schema_extended.md`). Tests: `tests/unit/test_onboarding.py`.

## Acceptance Criteria

- [x] All 25+ routes handled with correct role authorization
- [x] Tenant creation provisions Cognito user + group + default config
- [x] Tenant creation auto-generates `slug` from `company_name` (migration 023)
- [x] Tenant suspension blocks all API access for that tenant
- [x] User creation checks tier limits before provisioning
- [x] Dollar rate updates recorded in tenant_config with audit trail
- [x] Dollar rate changes append to `rate_history` (migration 025, best-effort)
- [x] CBM rate has dedicated `GET/PUT /v1/tenant/cbm-rate` endpoints with history tracking
- [x] `GET /v1/tenant/rate-history` returns paginated rate history (supports `?rate_type=dollar_rate|cbm_rate`)
- [x] Role change calls `global_sign_out` to invalidate existing JWT immediately (best-effort)
- [x] Outbound webhook fires on `container.status_updated` with HMAC-SHA256 signature
- [x] `POST /v1/tenant/users/{id}/resend-invite` re-sends Cognito temp-password email
- [x] `POST /v1/tenant/users/{id}/reset-password` triggers Cognito password reset
- [x] `GET /v1/health` on all Lambdas (no JWT, returns `{"status":"healthy"}`)
- [x] Customer search supports `?q=` parameter with ILIKE
- [x] Platform dashboard aggregates cross-tenant metrics
- [x] All mutations logged to audit_log or platform_audit_log
- [x] Events published: TenantOnboarded, TenantSuspended
- [x] PATCH user supports `full_name`, `locale`, and/or `roles`/`primary_role` with Cognito sync (email immutable)
- [x] Multi-role staff support (migration 039, 2026-07-20): `tenant_user` can hold more than one role; `POST`/`PATCH /v1/tenant/users` take `roles`/`primary_role` (breaking change — `role` singular removed, no dual-path back-compat); `TenantContext.assert_role()` does a set-intersection against the user's full `roles`, not just the active/primary role — verified against all 113 existing `assert_role`/`require_roles` call sites (count and call shapes unchanged)
- [x] `CognitoClient.sync_user_groups()` fixes a real pre-existing bug: role changes previously never updated Cognito group membership, so they had no effect on permissions after re-login — verified live (Moto): removing a role via PATCH actually removes the corresponding Cognito group (`admin-list-groups-for-user` before/after), and a subsequent request gated to the removed role 403s
- [x] GDPR: DELETE /customers/{id} anonymises PII in place (Art. 17)
- [x] GDPR: GET /customers/{id}/export returns full data bundle (Art. 20)
- [x] Platform admin JWT uses `PLATFORM` tenant and unprefixed `platform_admin` group
- [x] POST /v1/register/{slug} — public self-registration resolved from the explicit path slug (falls back to Host-header slug/custom_domain only when no slug is supplied); creates the tenant_user row customer.user_id's FK requires (2026-08-28 fix — previously wrote the Cognito sub directly into that FK column and could never succeed)
- [x] POST /v1/customers/{id}/invite, GET /v1/invites/{token}, POST /v1/invites/{token}/accept — customer account-creation invites (customer_invite table, migration 042); accept creates the same tenant_user row + link the self-register fix does; single-use, 48h expiry, resend invalidates the prior token
- [x] GET/PUT /v1/tenant/notification-templates/{event_type}/{channel} — custom template management
- [x] POST /v1/platform/tenants/{id}/impersonate — creates read-only 30-min impersonation session; mints HS256 JWT; audits IMPERSONATION_START; refuses if tenant not active or has no tenant_admin
- [x] DELETE /v1/platform/impersonation/{session_id} — ends session; audits IMPERSONATION_END
- [x] impersonation_session table (migration 028, platform-scoped, no RLS)
- [x] Shipping-company onboarding (admin/sales-led, 2026-10-11): public `POST /v1/onboarding-requests` records a lead (no account/tenant created), emits `OnboardingRequested` to platform ops; platform `GET/GET{id}/PATCH /v1/platform/onboarding-requests` review queue; `POST /v1/platform/tenants` accepts `onboarding_request_id` to link + mark the lead `provisioned`; `tenant_onboarding_request` table (migration 054, platform-scoped, no RLS)
- [x] Lambda authorizer (services/authorizer/handler.py) accepts both Cognito RS256 and ShipX HS256 impersonation tokens; synthesises cognito:groups for get_tenant_context() compatibility
- [x] TenantContext.read_only enforced centrally: `get_tenant_context()` calls `assert_not_read_only()` internally (single chokepoint in `shared/auth.py`) — POST/PATCH/PUT/DELETE with `read_only=True` return 403 IMPERSONATION_READ_ONLY before any business logic; GET/HEAD/OPTIONS pass through; public/webhook routes unaffected (they bypass `get_tenant_context()` entirely)
- [x] Webhook config save: PUT /v1/tenant/config accepts `webhook_config` (endpoint_url validated HTTPS, enabled, events validated against WebhookEventType enum); secret preserved on update, generated on first save, never returned in GET (masked to `****`)
- [x] POST /v1/tenant/config/webhook/rotate-secret — generates cryptographically random 64-char hex secret via `secrets.token_hex(32)`; returns plaintext once; audited
- [x] POST /v1/tenant/config/webhook/test — sends signed test event to configured URL using same HMAC-SHA256 path as real events; returns `{success, status_code, error}`
- [x] Locale (EN/ZH): `tenant_user.locale` writable via PATCH /v1/tenant/users/{id} (tenant_admin) and PATCH /v1/tenant/me (any authenticated role); validated against `{"en","zh"}`; locale NOT synced to Cognito (DB-only); tracking service passes `locale` from `get_customers_for_container` to `enqueue_notifications` so ZH customers receive Chinese-language notifications
