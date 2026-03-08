locals {
  name_prefix = "${var.project_name}-${var.environment}"
  common_tags = {
    Project     = var.project_name
    Environment = var.environment
    ManagedBy   = "terraform"
    CostCenter  = "logistics-platform"
    Owner       = "platform-engineering"
  }

  # ---------------------------------------------------------------------------
  # All route definitions: API Gateway route key → Lambda service name
  # Routes are only provisioned when a matching key exists in var.lambda_arns.
  # ---------------------------------------------------------------------------
  all_routes = {
    # --- Platform Admin (11 routes) -----------------------------------------
    "POST /v1/platform/tenants"                   = "tenant_management"
    "GET /v1/platform/tenants"                    = "tenant_management"
    "GET /v1/platform/tenants/{id}"               = "tenant_management"
    "PATCH /v1/platform/tenants/{id}"             = "tenant_management"
    "DELETE /v1/platform/tenants/{id}"            = "tenant_management"
    "PATCH /v1/platform/tenants/{id}/suspend"     = "tenant_management"
    "PATCH /v1/platform/tenants/{id}/activate"    = "tenant_management"
    "PATCH /v1/platform/tenants/{id}/reactivate"  = "tenant_management"
    "GET /v1/platform/tenants/{id}/usage"         = "metering"
    "GET /v1/platform/dashboard"                  = "tenant_management"
    "GET /v1/platform/audit-log"                  = "tenant_management"

    # --- Tenant Admin (13 routes) -------------------------------------------
    "GET /v1/tenant/config"               = "tenant_management"
    "PUT /v1/tenant/config"               = "tenant_management"
    "POST /v1/tenant/users"               = "tenant_management"
    "GET /v1/tenant/users"                = "tenant_management"
    "GET /v1/tenant/users/{id}"           = "tenant_management"
    "PATCH /v1/tenant/users/{id}"         = "tenant_management"
    "DELETE /v1/tenant/users/{id}"        = "tenant_management"
    "GET /v1/tenant/dollar-rate"          = "tenant_management"
    "PUT /v1/tenant/dollar-rate"          = "tenant_management"
    "POST /v1/tenant/charge-types"        = "tenant_management"
    "GET /v1/tenant/charge-types"         = "tenant_management"
    "PUT /v1/tenant/charge-types/{id}"    = "tenant_management"
    "DELETE /v1/tenant/charge-types/{id}" = "tenant_management"

    # --- Packing lists (7 routes) -------------------------------------------
    "POST /v1/packing-lists"               = "packing_list"
    "GET /v1/packing-lists"                = "packing_list"
    "GET /v1/packing-lists/{id}"           = "packing_list"
    "PUT /v1/packing-lists/{id}"           = "packing_list"
    "PATCH /v1/packing-lists/{id}/submit"  = "packing_list"
    "PATCH /v1/packing-lists/{id}/approve" = "packing_list"
    "PATCH /v1/packing-lists/{id}/reject"  = "packing_list"

    # --- Manifests (4 routes) -----------------------------------------------
    "POST /v1/manifests"              = "manifest"
    "GET /v1/manifests"               = "manifest"
    "GET /v1/manifests/{id}"          = "manifest"
    "PATCH /v1/manifests/{id}/verify" = "manifest"

    # --- Shipments (1 route; GET /{tracking-code} is public — see public_routes) ---
    "GET /v1/shipments" = "tracking"

    # --- Billing (2 routes) -------------------------------------------------
    "GET /v1/billing/{customer-id}" = "billing"
    "POST /v1/billing/{id}/dispute" = "billing"

    # --- Billing extension (7 routes) ---------------------------------------
    "GET /v1/billing/carryovers"                   = "billing"
    "PATCH /v1/billing/carryovers/{id}/exempt"     = "billing"
    "POST /v1/billing/{billing-id}/charges"        = "billing"
    "GET /v1/billing/{billing-id}/charges"         = "billing"
    "DELETE /v1/billing/{billing-id}/charges/{id}" = "billing"
    "GET /v1/billing/{billing-id}/storage-fees"    = "billing"
    "GET /v1/billing/disputes"                     = "billing"

    # --- CBM dispute lifecycle (5 routes) -----------------------------------
    "GET /v1/billing/{id}/disputes"               = "billing"
    "POST /v1/billing/disputes"                   = "billing"
    "PATCH /v1/billing/disputes/{id}/acknowledge" = "billing"
    "PATCH /v1/billing/disputes/{id}/resolve"     = "billing"
    "PATCH /v1/billing/disputes/{id}/reject"      = "billing"

    # --- Claims (5 routes) --------------------------------------------------
    "POST /v1/claims"               = "claims"
    "GET /v1/claims"                = "claims"
    "GET /v1/claims/{id}"           = "claims"
    "PATCH /v1/claims/{id}/inspect" = "claims"
    "PATCH /v1/claims/{id}/resolve" = "claims"

    # --- Claims extension (4 routes) ----------------------------------------
    "GET /v1/claims/missing-items"      = "claims"
    "GET /v1/claims/missing-items/{id}" = "claims"
    "GET /v1/claims/seized-items"       = "claims"
    "GET /v1/claims/seized-items/{id}"  = "claims"

    # --- Payments & Release notes (4 routes) --------------------------------
    "POST /v1/payments/{billing-id}/confirm" = "payment_release"
    "POST /v1/release-notes"                 = "payment_release"
    "GET /v1/release-notes/{id}"             = "payment_release"
    "PATCH /v1/release-notes/{id}/release"   = "payment_release"

    # --- Refunds (6 routes) -------------------------------------------------
    "POST /v1/refunds"               = "refunds"
    "GET /v1/refunds"                = "refunds"
    "GET /v1/refunds/{id}"           = "refunds"
    "PATCH /v1/refunds/{id}/review"  = "refunds"
    "PATCH /v1/refunds/{id}/approve" = "refunds"
    "PATCH /v1/refunds/{id}/reject"  = "refunds"

    # --- Uploads (1 route) --------------------------------------------------
    "POST /v1/uploads/presigned-url" = "claims"

    # --- Excel import/export (5 routes) -------------------------------------
    "GET /v1/packing-lists/{id}/export"      = "excel"
    "POST /v1/packing-lists/import"          = "excel"
    "GET /v1/manifests/{id}/export"          = "excel"
    "GET /v1/billing/{id}/export"            = "excel"
    "GET /v1/containers/{id}/billing/export" = "excel"

    # --- Customers (6 routes) -----------------------------------------------
    "POST /v1/customers"              = "tenant_management"
    "GET /v1/customers"               = "tenant_management"
    "GET /v1/customers/{id}"          = "tenant_management"
    "PATCH /v1/customers/{id}"        = "tenant_management"
    "DELETE /v1/customers/{id}"       = "tenant_management"
    "GET /v1/customers/{id}/export"   = "tenant_management"

    # --- Containers (4 routes) ----------------------------------------------
    "POST /v1/containers"              = "tracking"
    "GET /v1/containers"               = "tracking"
    "GET /v1/containers/{id}"          = "tracking"
    "PATCH /v1/containers/{id}/status" = "tracking"

    # --- Platform settings (2 routes) ---------------------------------------
    "GET /v1/platform/settings" = "tenant_management"
    "PUT /v1/platform/settings" = "tenant_management"

    # --- Tenant reports (1 route) -------------------------------------------
    "GET /v1/tenant/reports" = "tenant_management"
  }

  # Subset of routes for which a Lambda ARN has been provided
  active_routes = {
    for route_key, svc in local.all_routes : route_key => svc
    if contains(keys(var.lambda_arns), svc)
  }

  # ---------------------------------------------------------------------------
  # Public routes — no JWT required
  # ---------------------------------------------------------------------------
  public_routes = {
    "GET /v1/health"                    = "tracking"     # lightweight health check
    "GET /v1/shipments/{tracking-code}" = "tracking"     # public shipment lookup
    "GET /v1/webhooks/whatsapp"         = "notification" # Meta webhook verification
    "POST /v1/webhooks/whatsapp"        = "notification" # Meta webhook status callback
  }

  active_public_routes = {
    for route_key, svc in local.public_routes : route_key => svc
    if contains(keys(var.lambda_arns), svc)
  }
}

# ---------------------------------------------------------------------------
# HTTP API
# ---------------------------------------------------------------------------

resource "aws_apigatewayv2_api" "main" {
  name          = "${var.project_name}-api-${var.environment}"
  protocol_type = "HTTP"

  cors_configuration {
    allow_origins  = var.cors_allow_origins
    allow_methods  = ["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"]
    allow_headers  = ["Content-Type", "Authorization", "X-Amz-Date", "X-Api-Key"]
    expose_headers = ["X-Request-Id"]
    max_age        = 3600
  }

  tags = local.common_tags
}

# ---------------------------------------------------------------------------
# Access log group
# ---------------------------------------------------------------------------

resource "aws_cloudwatch_log_group" "api_access_logs" {
  name              = "/aws/apigateway/${local.name_prefix}-api"
  retention_in_days = 14
  tags              = local.common_tags
}

# ---------------------------------------------------------------------------
# Default stage (auto-deploy)
# ---------------------------------------------------------------------------

resource "aws_apigatewayv2_stage" "default" {
  api_id      = aws_apigatewayv2_api.main.id
  name        = "$default"
  auto_deploy = true

  default_route_settings {
    throttling_burst_limit = 100
    throttling_rate_limit  = 50
  }

  access_log_settings {
    destination_arn = aws_cloudwatch_log_group.api_access_logs.arn
    format          = "$context.requestId $context.status $context.error.message"
  }

  tags = local.common_tags
}

# ---------------------------------------------------------------------------
# JWT Authorizer (Cognito)
# ---------------------------------------------------------------------------

resource "aws_apigatewayv2_authorizer" "cognito" {
  api_id           = aws_apigatewayv2_api.main.id
  authorizer_type  = "JWT"
  identity_sources = ["$request.header.Authorization"]
  name             = "${local.name_prefix}-cognito-authorizer"

  jwt_configuration {
    audience = [var.cognito_client_id]
    issuer   = var.cognito_issuer_url
  }
}

# ---------------------------------------------------------------------------
# Lambda integrations — one per unique service ARN
# ---------------------------------------------------------------------------

resource "aws_apigatewayv2_integration" "lambda" {
  for_each = var.lambda_arns

  api_id                 = aws_apigatewayv2_api.main.id
  integration_type       = "AWS_PROXY"
  integration_uri        = each.value
  payload_format_version = "2.0"
}

# ---------------------------------------------------------------------------
# Routes — one per entry in active_routes (filtered by available ARNs)
# ---------------------------------------------------------------------------

resource "aws_apigatewayv2_route" "routes" {
  for_each = local.active_routes

  api_id    = aws_apigatewayv2_api.main.id
  route_key = each.key
  target    = "integrations/${aws_apigatewayv2_integration.lambda[each.value].id}"

  authorization_type = "JWT"
  authorizer_id      = aws_apigatewayv2_authorizer.cognito.id
}

# ---------------------------------------------------------------------------
# Public routes — no JWT authorizer (health, public tracking, webhooks)
# ---------------------------------------------------------------------------

resource "aws_apigatewayv2_route" "public_routes" {
  for_each = local.active_public_routes

  api_id    = aws_apigatewayv2_api.main.id
  route_key = each.key
  target    = "integrations/${aws_apigatewayv2_integration.lambda[each.value].id}"

  authorization_type = "NONE"
}
