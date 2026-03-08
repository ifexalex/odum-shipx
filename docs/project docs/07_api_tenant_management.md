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
├── cognito_client.py # Cognito user provisioning
└── models.py         # Already defined in Task 03
```

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

### Tenant Admin Endpoints
| Method | Path | Handler | Roles |
|---|---|---|---|
| GET | `/v1/tenant/config` | Get tenant config | tenant_admin |
| PUT | `/v1/tenant/config` | Update branding + notifications | tenant_admin |
| POST | `/v1/tenant/users` | Create user (+ Cognito) | tenant_admin |
| GET | `/v1/tenant/users` | List tenant users | tenant_admin |
| GET | `/v1/tenant/users/{id}` | Get user detail | tenant_admin |
| PATCH | `/v1/tenant/users/{id}` | Update user | tenant_admin |
| DELETE | `/v1/tenant/users/{id}` | Deactivate user | tenant_admin |
| GET | `/v1/tenant/dollar-rate` | Get current rate | tenant_admin |
| PUT | `/v1/tenant/dollar-rate` | Update rate | tenant_admin |
| POST | `/v1/tenant/charge-types` | Create charge type | tenant_admin |
| GET | `/v1/tenant/charge-types` | List charge types | tenant_admin |
| PUT | `/v1/tenant/charge-types/{id}` | Update charge type | tenant_admin |
| DELETE | `/v1/tenant/charge-types/{id}` | Deactivate charge type | tenant_admin |

### Customer Endpoints
| Method | Path | Handler | Roles |
|---|---|---|---|
| POST | `/v1/customers` | Create customer | tenant_admin, china_office_staff, nigeria_office_staff |
| GET | `/v1/customers` | List customers (supports `?q=` search) | all staff roles |
| GET | `/v1/customers/{id}` | Get customer | all staff + customer (own only) |
| PATCH | `/v1/customers/{id}` | Update customer | tenant_admin, staff roles |
| DELETE | `/v1/customers/{id}` | GDPR anonymisation (Art. 17 — right to erasure) | tenant_admin |
| GET | `/v1/customers/{id}/export` | GDPR data portability export (Art. 20) | tenant_admin |

## Key Business Logic

### Tenant Creation (POST /platform/tenants)
1. Validate request
2. Insert `tenant` record (status = 'active')
3. Create Cognito user for initial admin with `custom:tenant_id = {new_tenant_id}`
4. Create Cognito group `{tenant_id}:tenant_admin`
5. Add user to group
6. Insert `tenant_user` record
7. Insert default `tenant_config` records (dollar_rate, storage_fee, warehouse_address, cbm_rate, etc.)
8. Publish `TenantOnboarded` event
9. Log to `platform_audit_log`
10. Return tenant + admin user info

### Tenant Suspension (PATCH /platform/tenants/{id}/suspend)
1. Validate tenant exists and is 'active'
2. Update `tenant.status = 'suspended'`
3. Publish `TenantSuspended` event
4. Log to `platform_audit_log`
- **Note:** Suspended tenants have all API requests blocked by auth middleware (403 TENANT_SUSPENDED)

### User Creation (POST /tenant/users)
1. Validate request + check usage limits (starter: 10 users, business: 50)
2. Create Cognito user with `custom:tenant_id`, temporary password
3. Create or get Cognito group `{tenant_id}:{role}`
4. Add user to group
5. Insert `tenant_user` record
6. If role == 'customer' and customer record exists with matching email, link `customer.user_id`

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
```

### PATCH /tenant/users/{id} — Update User
- Supports updating `full_name` and `role` only
- Email (`username`) **cannot** be changed — it is the immutable Cognito username used as login credential
- Both DB record and Cognito user attributes are updated in sync:
  - `full_name` → Cognito `name` attribute
  - `role` → Cognito `custom:role` attribute

### GET /v1/platform/audit-log — Platform Audit Log

Query params:

| Param | Type | Default | Description |
|---|---|---|---|
| `limit` | int | 50 | Page size |
| `tenant_id` | UUID | — | Filter by target tenant (optional) |
| `action` | string | — | Filter by action e.g. `TENANT_UPDATED`, `TENANT_CREATED` (optional) |
| `cursor` | string | — | Opaque pagination cursor from previous response (optional) |

Response uses standard `paginated()` envelope: `{ "data": [...], "next_cursor": "...", "has_more": true }`.

### Dollar Rate
- **PUT** — Updates `tenant_config` with key `'dollar_rate'`; response includes `previous_rate` for audit visibility
- **GET** — Returns current `rate`, `currency_pair`, and `effective_from`. Does **not** include `previous_rate` (only available in the PUT response)
- Audit log the change

### Tier Limits (from Task 03)
- Starter: 10 users, 5 containers/month, 5 GB storage
- Business: 50 users, 25 containers/month, 25 GB storage
- Enterprise: unlimited (or very high limits)

## Acceptance Criteria

- [x] All 25+ routes handled with correct role authorization
- [x] Tenant creation provisions Cognito user + group + default config
- [x] Tenant suspension blocks all API access for that tenant
- [x] User creation checks tier limits before provisioning
- [x] Dollar rate updates recorded in tenant_config with audit trail
- [x] Customer search supports `?q=` parameter with ILIKE
- [x] Platform dashboard aggregates cross-tenant metrics
- [x] All mutations logged to audit_log or platform_audit_log
- [x] Events published: TenantOnboarded, TenantSuspended
- [x] PATCH user supports `full_name` and `role` with Cognito sync (email immutable)
- [x] GDPR: DELETE /customers/{id} anonymises PII in place (Art. 17)
- [x] GDPR: GET /customers/{id}/export returns full data bundle (Art. 20)
- [x] Platform admin JWT uses `PLATFORM` tenant and unprefixed `platform_admin` group
