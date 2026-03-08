# Task 21 — Missing Endpoints, Edge Cases & Gap Closures

## Objective

Implement all remaining endpoints and logic gaps identified during the audit: carryover exemption, miscellaneous charge CRUD, platform settings, tenant reports, health check, unauthenticated tracking, seized/missing item listing, storage fee log viewing, dispute listing, and WhatsApp webhook verification.

## Depends On

- Task 06 (shared layer), relevant service tasks (07–16)

## Part 1: Carryover Exemption Endpoint

**Add to:** `services/billing/handler.py` and `services/billing/service.py`

| Method | Path | Roles |
|---|---|---|
| GET | `/v1/billing/carryovers` | tenant_admin, nigeria_office_staff |
| PATCH | `/v1/billing/carryovers/{id}/exempt` | tenant_admin only |

### GET /billing/carryovers
List all carryover_ledger entries for the tenant, filterable by:
- `?customer_id=uuid`
- `?status=outstanding` (or `applied`, `exempted`)

```json
{
  "data": [
    {
      "id": "uuid",
      "customer_id": "uuid",
      "customer_name": "Customer A",
      "source_billing_id": "uuid",
      "source_container_number": "MSKU7654321",
      "target_billing_id": null,
      "amount_ngn": 12000.00,
      "status": "outstanding",
      "created_at": "2026-02-01T00:00:00Z"
    }
  ]
}
```

### PATCH /billing/carryovers/{id}/exempt (Business Rule BR-BL-005)
1. Validate carryover exists, status = 'outstanding', tenant_admin role
2. Set `carryover_ledger.status = 'exempted'`
3. Set `exempted_by`, `exempted_at`
4. The carryover is NOT added to the current billing
5. Create a **new** carryover_ledger entry with `status = 'outstanding'` (debt rolls forward to subsequent shipment)
6. Audit log the exemption

```json
// Request
{
  "notes": "Customer agreed to defer payment to next shipment"
}

// Response 200
{
  "data": {
    "id": "uuid",
    "status": "exempted",
    "exempted_at": "2026-03-01T10:00:00Z",
    "new_carryover_id": "uuid",
    "notes": "Debt rolled forward to next shipment"
  }
}
```

---

## Part 2: Miscellaneous Charge CRUD

**Add to:** `services/billing/handler.py` and `services/billing/service.py`

| Method | Path | Roles |
|---|---|---|
| POST | `/v1/billing/{billing-id}/charges` | tenant_admin, nigeria_office_staff |
| GET | `/v1/billing/{billing-id}/charges` | tenant_admin, nigeria_office_staff, customer (own) |
| DELETE | `/v1/billing/{billing-id}/charges/{charge-id}` | tenant_admin |

### POST /billing/{billing-id}/charges — Add Misc Charge

```json
// Request
{
  "charge_type": "stopdown_fee",
  "description": "Container was stopped at customs for additional inspection",
  "amount_usd": 25.00,
  "amount_ngn": 39500.00
}

// Response 201
{
  "data": {
    "id": "uuid",
    "billing_id": "uuid",
    "charge_type": "stopdown_fee",
    "amount_usd": 25.00,
    "amount_ngn": 39500.00,
    "created_at": "2026-03-01T10:00:00Z"
  }
}
```

**Side effects on POST:**
1. Insert `misc_charge` record
2. Update `billing.misc_fees_usd += amount_usd`
3. Update `billing.misc_fees_ngn += amount_ngn`
4. Recalculate `billing.total_due_usd`, `billing.total_due_ngn`, `billing.outstanding_ngn`
5. Audit log

**Side effects on DELETE:**
1. Reverse the above calculations
2. Only allowed if billing.payment_status = 'unpaid' (cannot remove charges after partial payment)

---

## Part 3: Unauthenticated Tracking Lookup

**Context:** The backend spec says `GET /shipments/{tracking-code}` uses no JWT — just tracking code + phone verification.

**Add to:** `services/tracking/handler.py`

### Route Configuration

This route needs special handling in API Gateway — it must NOT have the JWT authorizer attached.

**In the Lambda handler:**
```python
def _handle_public_tracking_lookup(event: dict) -> dict:
    """Public tracking lookup — no JWT required."""
    tracking_code = event["pathParameters"]["tracking-code"]
    phone = (event.get("queryStringParameters") or {}).get("phone")

    if not phone:
        return validation_error([{"field": "phone", "code": "REQUIRED", 
                                  "message": "Phone number required for verification"}])

    # Look up tracking by code + verify customer phone matches
    result = tracking_repository.get_by_code_and_phone(tracking_code, phone)
    if not result:
        return error_response(ResourceNotFoundError("shipment", tracking_code))

    # Fetch tenant branding for company_name
    tenant = tenant_repository.get_tenant(result["tenant_id"])

    return success({
        "tracking_code": result["tracking_code"],
        "current_stage": result["current_stage"],
        "company_name": tenant["branding_config"].get("company_display_name", tenant["company_name"]),
        "stage_history": result["stage_history"],
        "estimated_stages": result.get("estimated_stages", []),
    })
```

**Repository query:**
```sql
SELECT st.*, c.phone, c.name as customer_name
FROM shipment_tracking st
JOIN customer c ON c.id = st.customer_id AND c.tenant_id = st.tenant_id
WHERE st.tracking_code = :tracking_code
AND (c.phone = :phone OR c.whatsapp = :phone)
```

**Note:** This query bypasses RLS since there's no authenticated tenant context. The Lambda must use a special DB connection that doesn't set `app.current_tenant_id`, or use a superuser role for this specific query only. Implement as:
```python
def execute_without_rls(query: str, params: dict) -> list[dict]:
    """Execute query without RLS — for public endpoints only. Use sparingly."""
    conn = get_connection()
    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute("SET LOCAL app.current_tenant_id = '00000000-0000-0000-0000-000000000000'")
        # Use RESET before query to bypass RLS, or use a different DB role
        cur.execute("RESET app.current_tenant_id")
        cur.execute(query, params)
        ...
```

**Better approach:** Create a separate DB role `logistics_public` that is exempt from RLS for the tracking table only:
```sql
CREATE ROLE logistics_public LOGIN PASSWORD '...';
GRANT SELECT ON shipment_tracking, customer, tenant TO logistics_public;
-- Do NOT apply RLS to this role for these specific tables
```

---

## Part 4: Platform Settings

**Add to:** `services/tenant_management/handler.py`

| Method | Path | Roles |
|---|---|---|
| GET | `/v1/platform/settings` | platform_admin |
| PUT | `/v1/platform/settings` | platform_admin |

Platform-level settings (stored in a `platform_config` table or as a special tenant_config with `tenant_id = NULL`):

```json
{
  "data": {
    "default_subscription_tier": "starter",
    "whatsapp_business_phone_id": "1234567890",
    "africas_talking_api_key_ref": "arn:aws:secretsmanager:...",
    "platform_email_from": "notifications@logistics.example.com",
    "max_tenants": 50,
    "maintenance_mode": false
  }
}
```

**Implementation:** Store as rows in `tenant_config` with a sentinel `tenant_id` (create a platform tenant record with a well-known UUID), or create a simple `platform_settings` table:

```sql
CREATE TABLE platform_settings (
    key VARCHAR(100) PRIMARY KEY,
    value JSONB NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_by UUID
);
```

Include this in a new migration file.

---

## Part 5: Tenant Reports Endpoint

**Add to:** `services/tenant_management/handler.py`

| Method | Path | Roles |
|---|---|---|
| GET | `/v1/tenant/reports` | tenant_admin |

Returns summary analytics for the tenant:

```json
{
  "data": {
    "period": "2026-02",
    "containers": { "total": 5, "in_transit": 2, "at_warehouse": 1, "fully_released": 2 },
    "customers": { "total": 45, "with_active_shipments": 30 },
    "billing": {
      "total_billed_ngn": 5250000.00,
      "total_collected_ngn": 4800000.00,
      "outstanding_ngn": 450000.00,
      "average_cbm_per_container": 38.5
    },
    "claims": { "open": 3, "resolved_this_month": 7 },
    "disputes": { "open": 2, "resolved_this_month": 4 }
  }
}
```

**Implementation:** Aggregate queries across containers, billing, claims, disputes for the caller's tenant.

---

## Part 6: Health Check Endpoint

**Add to:** API Gateway + a lightweight Lambda or inline in any existing Lambda

| Method | Path | Auth |
|---|---|---|
| GET | `/v1/health` | None (no JWT) |

```json
{
  "status": "healthy",
  "version": "1.0.0",
  "timestamp": "2026-02-22T10:30:00Z"
}
```

Optionally check DB connectivity (but keep it fast — no heavy queries).

---

## Part 7: Seized/Missing Item List Endpoints

**Add to:** `services/claims/handler.py`

| Method | Path | Roles |
|---|---|---|
| GET | `/v1/claims/missing-items` | nigeria_office_staff, tenant_admin |
| GET | `/v1/claims/missing-items/{id}` | nigeria_office_staff, tenant_admin |
| GET | `/v1/claims/seized-items` | nigeria_office_staff, tenant_admin |
| GET | `/v1/claims/seized-items/{id}` | nigeria_office_staff, tenant_admin |

Support filters: `?container_id=`, `?customer_id=`, `?status=`

---

## Part 8: Storage Fee Log Viewing

**Add to:** `services/billing/handler.py`

| Method | Path | Roles |
|---|---|---|
| GET | `/v1/billing/{billing-id}/storage-fees` | tenant_admin, nigeria_office_staff, customer (own) |

Returns daily storage fee log entries for a billing record:

```json
{
  "data": [
    {
      "id": "uuid",
      "day_number": 3,
      "carton_count": 3,
      "daily_rate_ngn": 500.00,
      "fee_amount_ngn": 1500.00,
      "accrual_date": "2026-03-18"
    }
  ]
}
```

---

## Part 9: CBM Dispute Listing + Staff Dispute Creation + Reject

**Add to:** `services/billing/handler.py`

| Method | Path | Roles |
|---|---|---|
| GET | `/v1/billing/disputes` | nigeria_office_staff, tenant_admin, china_office_staff |
| POST | `/v1/billing/disputes` | nigeria_office_staff, tenant_admin (staff-created disputes, `billing_id` in body) |
| PATCH | `/v1/billing/disputes/{id}/reject` | nigeria_office_staff, tenant_admin |

List all CBM disputes for the tenant (not scoped to a single billing record). Filters: `?status=`, `?customer_id=`

`PATCH .../reject` transitions the dispute to `rejected` status (see migration 016 for the CHECK constraint update that added `'rejected'` to the allowed values).

---

## Part 10: WhatsApp Webhook Verification

**Add to:** `services/notification/handler.py`

Meta Cloud API requires a webhook verification endpoint for the WhatsApp Business API:

| Method | Path | Auth |
|---|---|---|
| GET | `/v1/webhooks/whatsapp` | None (Meta sends a verification challenge) |
| POST | `/v1/webhooks/whatsapp` | None (Meta sends delivery status updates) |

**GET (verification):**
```python
def handle_whatsapp_webhook_verify(event):
    params = event.get("queryStringParameters", {})
    mode = params.get("hub.mode")
    token = params.get("hub.verify_token")
    challenge = params.get("hub.challenge")

    if mode == "subscribe" and token == os.environ["WHATSAPP_VERIFY_TOKEN"]:
        return {"statusCode": 200, "body": challenge}
    return {"statusCode": 403, "body": "Forbidden"}
```

**POST (delivery status):**
- Log delivery status (delivered, read, failed)
- Update notification tracking if implemented

---

## Part 11: Notification Preference Checking

**Context:** Before publishing events that trigger notifications, services should respect tenant notification preferences.

**Add to:** `shared/notifications.py` (new helper)

```python
def should_notify(tenant_id: str, event_type: str, channel: str) -> bool:
    """Check if this tenant has this notification channel enabled for this event type."""
    tenant = get_tenant_cached(tenant_id)  # Uses 60s cache from auth.py
    prefs = tenant.get("notification_preferences", {})
    
    # Check global channel enable
    if not prefs.get(f"{channel}_enabled", True):
        return False
    
    # Check event-specific channel
    event_channels = prefs.get("events", {}).get(event_type, [])
    return channel in event_channels


def enqueue_notifications(tenant_id: str, event_type: str, recipient: dict, template_data: dict) -> None:
    """Enqueue notification messages to appropriate SQS queues based on tenant preferences."""
    tenant = get_tenant_cached(tenant_id)
    branding = tenant.get("branding_config", {})

    for channel in ["sms", "whatsapp", "email"]:
        if should_notify(tenant_id, event_type, channel):
            queue_url = QUEUE_URLS[channel]
            sqs_client.send_message(
                QueueUrl=queue_url,
                MessageBody=json.dumps({
                    "tenant_id": tenant_id,
                    "event_type": event_type,
                    "channel": channel,
                    "recipient": recipient,
                    "tenant_branding": branding,
                    "template_data": template_data,
                }),
            )
```

**Integration:** All services that publish notification-triggering events (packing list, tracking, billing, claims, payment/release) should use `enqueue_notifications()` instead of directly publishing to EventBridge for notification routing. EventBridge remains for domain events; SQS enqueueing is for notifications specifically.

---

## Migration Files

### File: `migrations/versions/007_platform_settings_table.py`
```sql
CREATE TABLE platform_settings (
    key VARCHAR(100) PRIMARY KEY,
    value JSONB NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_by UUID
);

INSERT INTO platform_settings (key, value) VALUES
  ('default_subscription_tier', '"starter"'),
  ('max_tenants', '50'),
  ('maintenance_mode', 'false'),
  ('platform_email_from', '"notifications@logistics.example.com"');
```

## Acceptance Criteria

- [x] Carryover exemption creates new outstanding entry (debt rolls forward)
- [x] Misc charge CRUD updates billing totals correctly
- [x] Misc charge deletion blocked after partial payment
- [x] Unauthenticated tracking works with tracking code + phone
- [x] Platform settings CRUD for platform_admin
- [x] Tenant reports return aggregated analytics
- [x] Health check returns 200 with no auth required
- [x] Missing/seized item list endpoints with filters
- [x] Storage fee log viewable per billing record
- [x] Top-level CBM dispute listing with filters, staff creation, and reject transition
- [x] WhatsApp webhook verification responds correctly to Meta
- [x] Notification preference checking before SQS enqueue
- [x] `enqueue_notifications()` helper respects per-tenant, per-event channel config
