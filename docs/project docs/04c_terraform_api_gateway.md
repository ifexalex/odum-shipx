# Task 04c — Terraform: API Gateway (HTTP API) + Cognito Authorizer

## Objective

Create the Terraform module for Amazon API Gateway HTTP API with JWT authorizer (Cognito) and all route definitions.

## Depends On

- Task 01, Task 04b (Cognito outputs: user_pool_id, client_id)

## Architecture Context

- **HTTP API** (not REST API) — 70% cheaper, sufficient for this use case
- Base URL: `https://api.logistics.example.com/v1`
- JWT Authorizer validates Cognito tokens and extracts claims
- Rate limiting: 1000 req/s platform-wide; per-API-key throttling
- CORS enabled for web client origins

## Deliverables

### File: `infrastructure/aws/modules/api-gateway/main.tf`

**Resources:**
- `aws_apigatewayv2_api` — "logistics-api-{env}", protocol_type = "HTTP"
  - cors_configuration: allow_origins (configurable), allow_methods, allow_headers, max_age
- `aws_apigatewayv2_authorizer` — JWT authorizer pointing to Cognito
  - authorizer_type = "JWT"
  - identity_sources = ["$request.header.Authorization"]
  - jwt_configuration: audience = [cognito_client_id], issuer = cognito_issuer_url
- `aws_apigatewayv2_stage` — "$default" with auto_deploy = true
  - default_route_settings: throttling_burst_limit = 100, throttling_rate_limit = 50
  - access_log_settings → CloudWatch log group
- Route integrations (one per Lambda, using `aws_apigatewayv2_integration` + `aws_apigatewayv2_route`):

**Platform Admin Routes (all require JWT auth):**
```
POST   /v1/platform/tenants                → tenant_management Lambda
GET    /v1/platform/tenants                → tenant_management Lambda
GET    /v1/platform/tenants/{id}           → tenant_management Lambda
PATCH  /v1/platform/tenants/{id}           → tenant_management Lambda
DELETE /v1/platform/tenants/{id}           → tenant_management Lambda
PATCH  /v1/platform/tenants/{id}/suspend   → tenant_management Lambda
PATCH  /v1/platform/tenants/{id}/activate  → tenant_management Lambda
GET    /v1/platform/tenants/{id}/usage     → metering Lambda
GET    /v1/platform/dashboard              → tenant_management Lambda
GET    /v1/platform/audit-log              → tenant_management Lambda
```

**Tenant Admin Routes:**
```
GET    /v1/tenant/config                   → tenant_management Lambda
PUT    /v1/tenant/config                   → tenant_management Lambda
POST   /v1/tenant/users                    → tenant_management Lambda
GET    /v1/tenant/users                    → tenant_management Lambda
GET    /v1/tenant/users/{id}               → tenant_management Lambda
PATCH  /v1/tenant/users/{id}               → tenant_management Lambda
DELETE /v1/tenant/users/{id}               → tenant_management Lambda
GET    /v1/tenant/dollar-rate              → tenant_management Lambda
PUT    /v1/tenant/dollar-rate              → tenant_management Lambda
POST   /v1/tenant/charge-types             → tenant_management Lambda
GET    /v1/tenant/charge-types             → tenant_management Lambda
PUT    /v1/tenant/charge-types/{id}        → tenant_management Lambda
DELETE /v1/tenant/charge-types/{id}        → tenant_management Lambda
```

**Operational Routes:**
```
POST   /v1/packing-lists                   → packing_list Lambda
GET    /v1/packing-lists                   → packing_list Lambda
GET    /v1/packing-lists/{id}              → packing_list Lambda
PUT    /v1/packing-lists/{id}              → packing_list Lambda
PATCH  /v1/packing-lists/{id}/approve      → packing_list Lambda
PATCH  /v1/packing-lists/{id}/reject       → packing_list Lambda
GET    /v1/containers/{id}/packing-lists   → packing_list Lambda  (sub-resource alias)

POST   /v1/manifests                       → manifest Lambda
GET    /v1/manifests                       → manifest Lambda
GET    /v1/manifests/{id}                  → manifest Lambda
PATCH  /v1/manifests/{id}/verify           → manifest Lambda

GET    /v1/shipments                       → tracking Lambda
GET    /v1/shipments/{tracking-code}       → tracking Lambda
PATCH  /v1/shipments/{id}/status           → tracking Lambda

GET    /v1/billing/{customer-id}           → billing Lambda
GET    /v1/billing/{billing-id}/detail     → billing Lambda
POST   /v1/billing/{id}/dispute            → billing Lambda

POST   /v1/claims                          → claims Lambda
GET    /v1/claims                          → claims Lambda
GET    /v1/claims/{id}                     → claims Lambda
PATCH  /v1/claims/{id}/inspect             → claims Lambda
PATCH  /v1/claims/{id}/resolve             → claims Lambda

POST   /v1/payments/{billing-id}/confirm   → payment_release Lambda
POST   /v1/release-notes                   → payment_release Lambda
GET    /v1/release-notes/{id}              → payment_release Lambda
PATCH  /v1/release-notes/{id}/release      → payment_release Lambda

POST   /v1/refunds                         → refunds Lambda
GET    /v1/refunds                         → refunds Lambda
GET    /v1/refunds/{id}                    → refunds Lambda
PATCH  /v1/refunds/{id}/review             → refunds Lambda
PATCH  /v1/refunds/{id}/approve            → refunds Lambda

POST   /v1/uploads/presigned-url           → claims Lambda

POST   /v1/customers                       → tenant_management Lambda
GET    /v1/customers                       → tenant_management Lambda
GET    /v1/customers/{id}                  → tenant_management Lambda
PATCH  /v1/customers/{id}                  → tenant_management Lambda

POST   /v1/containers                      → tracking Lambda
GET    /v1/containers                      → tracking Lambda
GET    /v1/containers/{id}                 → tracking Lambda
```

**Note:** Each route's integration points to a Lambda ARN (provided as variable). The actual Lambda resources are created in Task 04e.

Use `for_each` or dynamic blocks to reduce repetition.

**Outputs:** api_endpoint, api_id, execution_arn (for Lambda permissions)

### File: `infrastructure/aws/modules/api-gateway/variables.tf`

```hcl
variable "project_name" { type = string }
variable "environment" { type = string }
variable "cognito_user_pool_id" { type = string }
variable "cognito_client_id" { type = string }
variable "cognito_issuer_url" { type = string }
variable "lambda_arns" { type = map(string) }  # service_name → Lambda ARN
variable "cors_allow_origins" { type = list(string) }
```

## Per-Tenant Rate Limiting

API Gateway usage plans enforce per-tenant throttling via API keys. Each tenant receives an API key mapped to a usage plan:

| Tier | Burst limit (RPS) | Steady-state limit (RPS) | Monthly quota |
|---|---|---|---|
| starter | 10 | 5 | 100,000 |
| business | 50 | 25 | 500,000 |
| enterprise | 200 | 100 | unlimited |

When a tenant exceeds their quota, API Gateway returns `429 Too Many Requests` before the Lambda is invoked. The app-level `UsageLimitExceededError` (429) supplements this for soft limits enforced in code (container limit, user count).

Terraform resources:
- `aws_api_gateway_usage_plan` per tier
- `aws_api_gateway_api_key` per tenant (provisioned at tenant creation)
- `aws_api_gateway_usage_plan_key` to link key → plan

## Public Routes — Customer Account-Creation Invites (2026-09-01)

Added to `local.public_routes` (`main.tf`) alongside `POST /v1/register`: `POST /v1/register/{slug}`
(the primary tenant-scoped self-signup path — `POST /v1/register` is kept for backward compatibility,
slug resolved from the body), `GET /v1/invites/{token}` (claim-page preview), `POST
/v1/invites/{token}/accept` (claim). All `authorization_type = "NONE"` like the rest of `public_routes`
— see `07_api_tenant_management.md` §"Customer Account-Creation Invites". Same ground-truth-gap class as
the original `POST /v1/register` omission (2026-07-11): a handler route with no API Gateway route 404s
in every real deployment while working in unit tests, since those mock the handler directly.

## Route-table catch-up (2026-09-23)

An audit comparing what the application serves against `local.all_routes` found **~80 served routes that
API Gateway never declared**. `scripts/local_server.py` routes by path prefix, so all of them worked in
local dev and would have returned 404 in AWS — the third occurrence of this ground-truth-gap class
(`POST /v1/register` 2026-07-11, invites 2026-09-01). Now declared, grouped in `main.tf`:

| Area | Routes added |
|---|---|
| Billing | `GET/POST /v1/billing`, `PATCH /v1/billing/{id}/cancel`, `…/apply-carryover`, `POST …/{billing-id}/storage-fees/waive` |
| Claims | `POST /v1/claims/missing-items`, `POST /v1/claims/seized-items` |
| Packing lists | `POST /v1/packing-lists/bulk-submit|bulk-approve|bulk-reject` |
| Excel service | `POST /v1/manifests/import`; PDFs `GET /v1/packing-lists/{id}/pdf`, `/v1/release-notes/{id}/pdf`, `/v1/payments/{id}/receipt/pdf` |
| Payments / warehouses | `POST /v1/payments/{billing-id}/verify`, `GET/POST /v1/warehouses`, `PATCH /v1/warehouses/{id}`, `PATCH /v1/warehouses/{id}/set-default`, `PATCH /v1/warehouses/{id}/deactivate`, `DELETE /v1/warehouses/{id}` |
| Containers | `DELETE /v1/containers/{id}`, `…/cancel`, `…/events`, `…/documents` (+ `presigned-url`, `{doc-id}/download`) |
| Tenant admin | `GET/PUT /v1/tenant/cbm-rate`, `GET /v1/tenant/rate-history`, `PATCH /v1/tenant/me`, `GET /v1/tenants/me/quota`, Paystack config (`PUT`/`DELETE`/`POST …/test`), webhook `rotate-secret`/`test`, notification-templates, `POST /v1/tenant/users/{id}/resend-invite|reset-password`, `POST /v1/customers/{id}/invite` |
| Platform admin | `GET/PUT /v1/platform/plans`, `GET /v1/platform/settings/gateways`, `PUT`/`POST …/test` on `/v1/platform/settings/{gateway}`, `GET /v1/platform/tenants/{id}/config|users`, `POST …/quota-override|impersonate`, `DELETE /v1/platform/impersonation/{id}` |
| Notifications | all 29 `/v1/notifications/*` routes (delivery log, staff + customer bells, banners, announcements) → new `notification_api` service key |

**New service keys.** `notification_api` (`notification.handler.http_handler`) and `notification_webhook`
(`notification.handler.webhook_handler`, now serving the public `GET/POST /v1/webhooks/whatsapp`) are
VPC-attached API Lambdas — see `04e_terraform_lambda_monitoring.md`. Previously *no* Lambda served the
notification HTTP surface, and the WhatsApp webhook was routed to an SQS consumer.

**Silent-drop gotcha.** `active_routes` filters out any route whose service key isn't in `var.lambda_arns`
with no error. `GET /v1/platform/tenants/{id}/usage` mapped to `metering`, which the lambda module never
exposed (and had no invoke permission for), so that route had been silently inert. `metering` is now in
`api_lambda_arns` with an `aws_lambda_permission`.

**Guard.** `tests/unit/test_infrastructure_contracts.py` fails if a frontend API call has no route, a route
targets a service key with no deployed Lambda, or a route key is duplicated.

## Acceptance Criteria

- [x] Route table stays in sync with the application (enforced by `tests/unit/test_infrastructure_contracts.py`)
- [x] HTTP API (not REST API) created
- [x] JWT authorizer configured with Cognito User Pool
- [x] All routes defined matching the API specification
- [x] CORS configured for web client
- [x] Access logging enabled
- [x] Stage with auto-deploy and throttling
- [x] Per-tenant usage plans with tier-based rate limits configured
- [ ] `terraform plan` succeeds — `terraform validate` passes (2026-09-23); a real plan/apply against AWS is still outstanding
