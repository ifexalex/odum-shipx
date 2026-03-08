# Task 04c PATCH — Additional API Gateway Routes

## Objective

Add the routes that were missing from the original Task 04c API Gateway definition. Apply this patch AFTER completing Task 04c, or incorporate these routes during the initial build.

## Additional Routes to Add

### Unauthenticated Routes (NO JWT authorizer)

These routes must be configured **without** the Cognito JWT authorizer:

```
GET    /v1/health                                → any Lambda (lightweight health check)
GET    /v1/shipments/{tracking-code}             → tracking Lambda (public tracking lookup)
GET    /v1/webhooks/whatsapp                     → notification Lambda (Meta webhook verify)
POST   /v1/webhooks/whatsapp                     → notification Lambda (Meta webhook status)
```

**Implementation in Terraform:**
```hcl
# These routes explicitly set authorization_type = "NONE"
resource "aws_apigatewayv2_route" "public_tracking" {
  api_id    = aws_apigatewayv2_api.main.id
  route_key = "GET /v1/shipments/{tracking-code}"
  target    = "integrations/${aws_apigatewayv2_integration.tracking.id}"
  authorization_type = "NONE"   # No JWT authorizer
}

resource "aws_apigatewayv2_route" "health" {
  api_id    = aws_apigatewayv2_api.main.id
  route_key = "GET /v1/health"
  target    = "integrations/${aws_apigatewayv2_integration.tracking.id}"
  authorization_type = "NONE"
}

resource "aws_apigatewayv2_route" "whatsapp_webhook_get" {
  api_id    = aws_apigatewayv2_api.main.id
  route_key = "GET /v1/webhooks/whatsapp"
  target    = "integrations/${aws_apigatewayv2_integration.notification.id}"
  authorization_type = "NONE"
}

resource "aws_apigatewayv2_route" "whatsapp_webhook_post" {
  api_id    = aws_apigatewayv2_api.main.id
  route_key = "POST /v1/webhooks/whatsapp"
  target    = "integrations/${aws_apigatewayv2_integration.notification.id}"
  authorization_type = "NONE"
}
```

### Excel Import/Export Routes (JWT authenticated — Task 19)

```
GET    /v1/packing-lists/{id}/export           → excel Lambda
POST   /v1/packing-lists/import                → excel Lambda
GET    /v1/manifests/{id}/export               → excel Lambda
GET    /v1/billing/{id}/export                 → excel Lambda
GET    /v1/containers/{id}/billing/export      → excel Lambda
```

### Billing Extension Routes (JWT authenticated — Task 21)

```
GET    /v1/billing/carryovers                  → billing Lambda
PATCH  /v1/billing/carryovers/{id}/exempt      → billing Lambda
POST   /v1/billing/{billing-id}/charges        → billing Lambda
GET    /v1/billing/{billing-id}/charges        → billing Lambda
DELETE /v1/billing/{billing-id}/charges/{id}   → billing Lambda
GET    /v1/billing/{billing-id}/storage-fees   → billing Lambda
GET    /v1/billing/disputes                    → billing Lambda
```

### CBM Dispute Lifecycle Routes (JWT authenticated — Task 11/21)

```
GET    /v1/billing/{id}/disputes               → billing Lambda
PATCH  /v1/billing/disputes/{id}/acknowledge   → billing Lambda
PATCH  /v1/billing/disputes/{id}/resolve       → billing Lambda
```

### Claims Extension Routes (JWT authenticated — Task 21)

```
GET    /v1/claims/missing-items                → claims Lambda
GET    /v1/claims/missing-items/{id}           → claims Lambda
GET    /v1/claims/seized-items                 → claims Lambda
GET    /v1/claims/seized-items/{id}            → claims Lambda
```

### Platform Extension Routes (JWT authenticated — Task 21)

```
GET    /v1/platform/settings                   → tenant_management Lambda
PUT    /v1/platform/settings                   → tenant_management Lambda
GET    /v1/tenant/reports                      → tenant_management Lambda
```

### Lambda Addition (Task 19)

Add a new Lambda function for Excel operations:

```
logistics-excel-{env}  | python3.12 | 512MB | 60s | API Gateway | VPC: Yes
```

This Lambda needs:
- DB access (fetch data for exports, customer lookups for imports)
- S3 access (read uploaded imports, write generated exports)
- openpyxl in the Lambda layer or deployment package

### Updated `lambda_arns` Variable

The `lambda_arns` map variable in Task 04c needs an additional entry:

```hcl
variable "lambda_arns" {
  type = map(string)
  # Now includes:
  # tenant_management, packing_list, manifest, tracking, billing,
  # claims, payment_release, refunds, notification, metering, excel
}
```

## Complete Route Count Summary

| Category | Original (04c) | Added (Patch) | Total |
|---|---|---|---|
| Platform Admin | 10 | 3 | 13 |
| Tenant Admin | 14 | 1 | 15 |
| Packing List | 6 | 2 | 8 |
| Manifest | 3 | 1 | 4 |
| Tracking/Containers | 6 | 0 | 6 |
| Billing | 2 | 7 | 9 |
| Claims | 5 | 4 | 9 |
| Payment/Release | 4 | 0 | 4 |
| Refunds | 6 | 0 | 6 |
| Customers | 4 | 0 | 4 |
| Uploads | 1 | 0 | 1 |
| Public/Webhooks | 0 | 4 | 4 |
| **TOTAL** | **61** | **22** | **83** |

## Acceptance Criteria

- [ ] All 22 additional routes added to API Gateway
- [ ] 4 public routes configured with `authorization_type = "NONE"`
- [ ] Excel Lambda added to Lambda module (Task 04e)
- [ ] `lambda_arns` variable updated with `excel` entry
- [ ] `terraform plan` succeeds with all routes
