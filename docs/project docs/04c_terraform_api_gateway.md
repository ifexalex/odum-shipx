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

### File: `infrastructure/modules/api-gateway/main.tf`

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

POST   /v1/manifests                       → manifest Lambda
GET    /v1/manifests                       → manifest Lambda
GET    /v1/manifests/{id}                  → manifest Lambda
PATCH  /v1/manifests/{id}/verify           → manifest Lambda

GET    /v1/shipments                       → tracking Lambda
GET    /v1/shipments/{tracking-code}       → tracking Lambda
PATCH  /v1/shipments/{id}/status           → tracking Lambda

GET    /v1/billing/{customer-id}           → billing Lambda
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

### File: `infrastructure/modules/api-gateway/variables.tf`

```hcl
variable "project_name" { type = string }
variable "environment" { type = string }
variable "cognito_user_pool_id" { type = string }
variable "cognito_client_id" { type = string }
variable "cognito_issuer_url" { type = string }
variable "lambda_arns" { type = map(string) }  # service_name → Lambda ARN
variable "cors_allow_origins" { type = list(string) }
```

## Acceptance Criteria

- [ ] HTTP API (not REST API) created
- [ ] JWT authorizer configured with Cognito User Pool
- [ ] All routes defined matching the API specification
- [ ] CORS configured for web client
- [ ] Access logging enabled
- [ ] Stage with auto-deploy and throttling
- [ ] `terraform plan` succeeds
