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
    "GET /v1/platform/onboarding-requests"        = "tenant_management"
    "GET /v1/platform/onboarding-requests/{id}"   = "tenant_management"
    "PATCH /v1/platform/onboarding-requests/{id}" = "tenant_management"

    # --- Tenant Admin (13 routes) -------------------------------------------
    "GET /v1/tenant/config"               = "tenant_management"
    "PUT /v1/tenant/config"               = "tenant_management"
    "POST /v1/tenant/users"               = "tenant_management"
    "GET /v1/tenant/users"                = "tenant_management"
    "GET /v1/tenant/users/{id}"           = "tenant_management"
    "PATCH /v1/tenant/users/{id}"         = "tenant_management"
    "DELETE /v1/tenant/users/{id}"        = "tenant_management"
    "GET /v1/tenant/registration-link"    = "tenant_management"
    "PATCH /v1/tenant/registration-link"  = "tenant_management"
    "GET /v1/tenant/dollar-rate"          = "tenant_management"
    "PUT /v1/tenant/dollar-rate"          = "tenant_management"
    "POST /v1/tenant/charge-types"        = "tenant_management"
    "GET /v1/tenant/charge-types"         = "tenant_management"
    "PUT /v1/tenant/charge-types/{id}"    = "tenant_management"
    "DELETE /v1/tenant/charge-types/{id}" = "tenant_management"

    "GET /v1/tenant/container-capacities"         = "tenant_management"
    "POST /v1/tenant/container-capacities"        = "tenant_management"
    "PATCH /v1/tenant/container-capacities/{id}"  = "tenant_management"
    "DELETE /v1/tenant/container-capacities/{id}" = "tenant_management"

    # --- Packing lists (8 routes) -------------------------------------------
    "POST /v1/packing-lists"               = "packing_list"
    "GET /v1/packing-lists"                = "packing_list"
    "GET /v1/packing-lists/{id}"           = "packing_list"
    "PUT /v1/packing-lists/{id}"           = "packing_list"
    "PATCH /v1/packing-lists/{id}/submit"  = "packing_list"
    "PATCH /v1/packing-lists/{id}/approve" = "packing_list"
    "PATCH /v1/packing-lists/{id}/reject"  = "packing_list"
    # Sub-resource alias, handled by packing_list/handler.py's _container_packing_lists()
    "GET /v1/containers/{id}/packing-lists" = "packing_list"

    # --- Manifests (4 routes) -----------------------------------------------
    "POST /v1/manifests"                                     = "manifest"
    "GET /v1/manifests"                                      = "manifest"
    "GET /v1/manifests/stats"                                = "manifest"
    "GET /v1/manifests/{id}"                                 = "manifest"
    "PATCH /v1/manifests/{id}/verify"                        = "manifest"
    "PATCH /v1/manifests/{id}/revoke-verification"           = "manifest"
    "PATCH /v1/manifests/{id}/resolve-discrepancy"           = "manifest"
    "POST /v1/manifests/{id}/evidence"                       = "manifest"
    "POST /v1/manifests/{id}/evidence/{evidence-id}/confirm" = "manifest"

    # --- Shipments (1 route; GET /{tracking-code} is public — see public_routes) ---
    "GET /v1/shipments" = "tracking"

    # --- Billing (3 routes) -------------------------------------------------
    # {customer-id} really is a *customer* id, so the by-billing-id read needs
    # the /detail suffix beside it — both ids are UUIDs, so the bare
    # /v1/billing/{id} shape cannot serve both.
    "GET /v1/billing/{customer-id}"       = "billing"
    "GET /v1/billing/{billing-id}/detail" = "billing"
    "POST /v1/billing/{id}/dispute"       = "billing"

    # --- Billing extension (7 routes) ---------------------------------------
    "GET /v1/billing/stats"                        = "billing"
    "GET /v1/billing/unbilled"                     = "billing"
    "GET /v1/billing/report"                       = "billing"
    "GET /v1/billing/payments"                     = "billing"
    "GET /v1/billing/carryovers"                   = "billing"
    "PATCH /v1/billing/carryovers/{id}/exempt"     = "billing"
    "POST /v1/billing/{billing-id}/charges"        = "billing"
    "GET /v1/billing/{billing-id}/charges"         = "billing"
    "DELETE /v1/billing/{billing-id}/charges/{id}" = "billing"
    "GET /v1/billing/{billing-id}/storage-fees"    = "billing"
    "GET /v1/billing/disputes"                     = "billing"
    "GET /v1/search"                               = "search"
    "GET /v1/billing/disputes/{id}"                = "billing"

    # --- CBM dispute lifecycle (5 routes) -----------------------------------
    "GET /v1/billing/{id}/disputes"               = "billing"
    "POST /v1/billing/disputes"                   = "billing"
    "PATCH /v1/billing/disputes/{id}/acknowledge" = "billing"
    "PATCH /v1/billing/disputes/{id}/resolve"     = "billing"
    "PATCH /v1/billing/disputes/{id}/reject"      = "billing"

    # --- Claims (5 routes) --------------------------------------------------
    "POST /v1/claims"                                     = "claims"
    "GET /v1/claims"                                      = "claims"
    "GET /v1/claims/{id}"                                 = "claims"
    "PATCH /v1/claims/{id}/inspect"                       = "claims"
    "PATCH /v1/claims/{id}/resolve"                       = "claims"
    "POST /v1/claims/{id}/evidence/{evidence-id}/confirm" = "claims"

    # --- Claims extension (4 routes) ----------------------------------------
    "GET /v1/claims/stats"              = "claims"
    "GET /v1/claims/missing-items"      = "claims"
    "GET /v1/claims/missing-items/{id}" = "claims"
    "GET /v1/claims/seized-items"       = "claims"
    "GET /v1/claims/seized-items/{id}"  = "claims"

    # --- Payments & Release notes (5 routes) --------------------------------
    "POST /v1/payments/{billing-id}/initialize" = "payment_release" # customer Paystack checkout (B12)
    "POST /v1/payments/{billing-id}/confirm"    = "payment_release"
    # Manual bank-transfer payment claims — customer's "I've made this
    # payment" submission with mandatory evidence, reviewed by staff.
    "POST /v1/payments/claims/presigned-url"    = "payment_release"
    "POST /v1/payments/{billing-id}/claims"     = "payment_release"
    "GET /v1/payments/{billing-id}/claims"      = "payment_release"
    "PATCH /v1/payments/claims/{id}/confirm"    = "payment_release"
    "PATCH /v1/payments/claims/{id}/reject"     = "payment_release"
    "GET /v1/payments/claims/{id}/evidence-url" = "payment_release"
    "POST /v1/release-notes"                    = "payment_release"
    "GET /v1/release-notes"                     = "payment_release"
    "GET /v1/release-notes/stats"               = "payment_release"
    "GET /v1/release-notes/{id}"                = "payment_release"
    "PATCH /v1/release-notes/{id}/release"      = "payment_release"
    "POST /v1/release-notes/{id}/split"         = "payment_release"
    "POST /v1/release-notes/{id}/reissue"       = "payment_release"
    "POST /v1/release-notes/{id}/pickup-code"   = "payment_release"

    # --- Refunds (6 routes) -------------------------------------------------
    "POST /v1/refunds"               = "refunds"
    "GET /v1/refunds"                = "refunds"
    "GET /v1/refunds/{id}"           = "refunds"
    "PATCH /v1/refunds/{id}/review"  = "refunds"
    "PATCH /v1/refunds/{id}/approve" = "refunds"
    "PATCH /v1/refunds/{id}/reject"  = "refunds"

    # --- Uploads (1 route) --------------------------------------------------
    "POST /v1/uploads/presigned-url" = "claims"

    # --- Excel import/export (11 routes) -------------------------------------
    "GET /v1/packing-lists/{id}/export"           = "excel"
    "POST /v1/packing-lists/import"               = "excel"
    "POST /v1/packing-lists/import/presigned-url" = "excel"
    "GET /v1/manifests/{id}/export"               = "excel"
    "GET /v1/billing/{id}/export"                 = "excel"
    "GET /v1/containers/{id}/billing/export"      = "excel"
    "GET /v1/containers/{id}/events/export"       = "excel"
    # Whole-list exports: a literal segment beats the {id} routes on the same path.
    "GET /v1/billing/export"        = "excel"
    "GET /v1/containers/export"     = "excel"
    "GET /v1/billing/report/export" = "excel"

    # --- Customers (6 routes) -----------------------------------------------
    "POST /v1/customers"            = "tenant_management"
    "GET /v1/customers"             = "tenant_management"
    "GET /v1/customers/stats"       = "tenant_management"
    "GET /v1/customers/{id}"        = "tenant_management"
    "PATCH /v1/customers/{id}"      = "tenant_management"
    "DELETE /v1/customers/{id}"     = "tenant_management"
    "GET /v1/customers/{id}/export" = "tenant_management"

    # --- Containers (4 routes) ----------------------------------------------
    "POST /v1/containers"              = "tracking"
    "GET /v1/containers"               = "tracking"
    "GET /v1/containers/stats"         = "tracking"
    "GET /v1/containers/{id}"          = "tracking"
    "PATCH /v1/containers/{id}/status" = "tracking"

    # --- Platform settings (2 routes) ---------------------------------------
    "GET /v1/platform/settings" = "tenant_management"
    "PUT /v1/platform/settings" = "tenant_management"

    # --- Tenant reports (1 route) -------------------------------------------
    "GET /v1/tenant/reports"  = "tenant_management"
    "GET /v1/tenant/activity" = "tenant_management" # tenant-scoped audit feed (B6)

    # =========================================================================
    # Routes added 2026-09-23 after an audit found the application serving
    # ~80 routes this table never declared. scripts/local_server.py routes
    # everything by path prefix, so all of these worked locally while API
    # Gateway would have returned 404 in AWS. Each key's service is the same
    # one local_server.py's _ROUTES / special-case rules resolve it to.
    # =========================================================================

    # --- Billing (list/generate + lifecycle actions) ------------------------
    "GET /v1/billing"                                  = "billing"
    "POST /v1/billing"                                 = "billing"
    "PATCH /v1/billing/{id}/cancel"                    = "billing"
    "PATCH /v1/billing/{id}/apply-carryover"           = "billing"
    "POST /v1/billing/{billing-id}/storage-fees/waive" = "billing"

    # --- Claims: missing / seized item logging ------------------------------
    "POST /v1/claims/missing-items" = "claims"
    "POST /v1/claims/seized-items"  = "claims"

    # --- Packing lists: bulk workflow actions -------------------------------
    "POST /v1/packing-lists/bulk-submit"  = "packing_list"
    "POST /v1/packing-lists/bulk-approve" = "packing_list"
    "POST /v1/packing-lists/bulk-reject"  = "packing_list"

    # --- Excel service: manifest import + PDF documents ---------------------
    # PDFs sit under other resources' prefixes but are generated by the excel
    # Lambda (see scripts/local_server.py's _excel_pdf_prefixes).
    "POST /v1/manifests/import"                       = "excel"
    "GET /v1/packing-lists/{id}/pdf"                  = "excel"
    "GET /v1/packing-lists/{id}/image"                = "excel" # ENG-5 single-page PNG
    "GET /v1/packing-lists/{id}/loading-receipt/pdf"  = "excel" # ENG-4 bilingual loading receipt PDF
    "GET /v1/packing-lists/{id}/loading-receipt/image" = "excel" # ENG-5 single-page loading receipt PNG
    "GET /v1/packing-lists/{id}/documents"            = "excel" # ENG-5 dual-format eligibility metadata
    "POST /v1/packing-lists/{id}/share-whatsapp"      = "excel" # ENG-5 WhatsApp image/PDF share
    "GET /v1/billing/{id}/pdf"                        = "excel" # FD-39 invoice
    "GET /v1/manifests/{id}/pdf"        = "excel" # FD-39 manifest
    "GET /v1/release-notes/{id}/pdf"    = "excel"
    "GET /v1/payments/{id}/receipt/pdf" = "excel"

    # --- Payments (online-payment reconciliation) + warehouses --------------
    "POST /v1/payments/{billing-id}/verify" = "payment_release"
    "GET /v1/warehouses"                    = "payment_release"
    "POST /v1/warehouses"                   = "payment_release"
    "PATCH /v1/warehouses/{id}/set-default" = "payment_release"
    "PATCH /v1/warehouses/{id}/deactivate"  = "payment_release"
    "PATCH /v1/warehouses/{id}"             = "payment_release"
    "DELETE /v1/warehouses/{id}"            = "payment_release"

    # --- Containers: lifecycle, documents, event history --------------------
    "DELETE /v1/containers/{id}"                          = "tracking"
    "POST /v1/containers/{id}/cancel"                     = "tracking"
    "GET /v1/containers/{id}/events"                      = "tracking"
    "GET /v1/containers/{id}/documents"                   = "tracking"
    "POST /v1/containers/{id}/documents/presigned-url"    = "tracking"
    "GET /v1/containers/{id}/documents/{doc-id}/download" = "tracking"
    "POST /v1/containers/{id}/documents/{doc-id}/confirm" = "tracking"

    # --- Tenant admin: rates, payment gateway, webhook, templates, users ----
    "GET /v1/tenant/cbm-rate"                                 = "tenant_management"
    "PUT /v1/tenant/cbm-rate"                                 = "tenant_management"
    "GET /v1/tenant/rate-history"                             = "tenant_management"
    "PATCH /v1/tenant/me"                                     = "tenant_management" # self-service profile/locale
    "GET /v1/tenants/me/quota"                                = "tenant_management"
    "POST /v1/tenant/config/logo/upload-url"                  = "tenant_management" # FD-29 tenant logo
    "PUT /v1/tenant/config/logo"                              = "tenant_management"
    "DELETE /v1/tenant/config/logo"                           = "tenant_management"
    "PUT /v1/tenant/config/paystack"                          = "tenant_management"
    "DELETE /v1/tenant/config/paystack"                       = "tenant_management"
    "POST /v1/tenant/config/paystack/test"                    = "tenant_management"
    "POST /v1/tenant/config/webhook/rotate-secret"            = "tenant_management"
    "POST /v1/tenant/config/webhook/test"                     = "tenant_management"
    "GET /v1/tenant/notification-templates"                   = "tenant_management"
    "GET /v1/tenant/notification-templates/{event}/{channel}" = "tenant_management"
    "PUT /v1/tenant/notification-templates/{event}/{channel}" = "tenant_management"
    "POST /v1/tenant/users/{id}/resend-invite"                = "tenant_management"
    "POST /v1/tenant/users/{id}/resend-activation"            = "tenant_management"
    "POST /v1/tenant/users/{id}/reset-password"               = "tenant_management"
    "POST /v1/customers/{id}/invite"                          = "tenant_management"

    # --- Platform admin: plans, gateways, per-tenant ops, impersonation -----
    "GET /v1/platform/plans"                        = "tenant_management"
    "PUT /v1/platform/plans/{tier}"                 = "tenant_management"
    "GET /v1/platform/settings/gateways"            = "tenant_management"
    "PUT /v1/platform/settings/{gateway}"           = "tenant_management" # sms-gateway | whatsapp-gateway | email-gateway
    "POST /v1/platform/settings/{gateway}/test"     = "tenant_management"
    "GET /v1/platform/tenants/{id}/config"          = "tenant_management"
    "GET /v1/platform/tenants/{id}/users"           = "tenant_management"
    "POST /v1/platform/tenants/{id}/quota-override" = "tenant_management"
    "POST /v1/platform/tenants/{id}/impersonate"    = "tenant_management"
    # Offboarding data export (audit BE-10): status, queue, five-minute download link
    "GET /v1/platform/tenants/{id}/offboarding-export"       = "tenant_management"
    "POST /v1/platform/tenants/{id}/offboarding-export"      = "tenant_management"
    "POST /v1/platform/tenants/{id}/offboarding-export/link" = "tenant_management"
    "DELETE /v1/platform/impersonation/{id}"                 = "tenant_management"

    # --- Notifications: delivery log, in-app bells, announcements -----------
    # Served by the VPC-attached notification_api Lambda (http_handler) — these
    # read/write Aurora, so they cannot live on the non-VPC SQS consumers.
    "GET /v1/notifications/log"             = "notification_api"
    "GET /v1/notifications/log/{id}"        = "notification_api"
    "POST /v1/notifications/log/{id}/retry" = "notification_api"

    "GET /v1/notifications/staff"                 = "notification_api"
    "GET /v1/notifications/staff/unread-count"    = "notification_api"
    "GET /v1/notifications/staff/banner"          = "notification_api"
    "PATCH /v1/notifications/staff/mark-all-read" = "notification_api"
    "DELETE /v1/notifications/staff/clear-all"    = "notification_api"
    "PATCH /v1/notifications/staff/{id}/read"     = "notification_api"
    "DELETE /v1/notifications/staff/{id}"         = "notification_api"

    "GET /v1/notifications/customer"                 = "notification_api"
    "GET /v1/notifications/customer/unread-count"    = "notification_api"
    "GET /v1/notifications/customer/banner"          = "notification_api"
    "PATCH /v1/notifications/customer/mark-all-read" = "notification_api"
    "DELETE /v1/notifications/customer/clear-all"    = "notification_api"
    "PATCH /v1/notifications/customer/{id}/read"     = "notification_api"
    "DELETE /v1/notifications/customer/{id}"         = "notification_api"

    "POST /v1/notifications/announce"                             = "notification_api"
    "GET /v1/notifications/announcements"                         = "notification_api"
    "GET /v1/notifications/announcements/pending"                 = "notification_api"
    "GET /v1/notifications/announcements/mine"                    = "notification_api"
    "PATCH /v1/notifications/announcements/requests/{id}"         = "notification_api"
    "DELETE /v1/notifications/announcements/requests/{id}"        = "notification_api"
    "PATCH /v1/notifications/announcements/requests/{id}/approve" = "notification_api"
    "PATCH /v1/notifications/announcements/requests/{id}/reject"  = "notification_api"
    "PATCH /v1/notifications/announcements/{group-id}"            = "notification_api"
    "DELETE /v1/notifications/announcements/{group-id}"           = "notification_api"
    "PATCH /v1/notifications/announcements/{group-id}/activate"   = "notification_api"
    "PATCH /v1/notifications/announcements/{group-id}/deactivate" = "notification_api"
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
    "GET /v1/health"                    = "tracking"             # lightweight health check
    "GET /v1/shipments/{tracking-code}" = "tracking"             # public shipment lookup
    "GET /v1/webhooks/whatsapp"         = "notification_webhook" # Meta webhook verification
    "POST /v1/webhooks/whatsapp"        = "notification_webhook" # Meta webhook status callback
    "POST /v1/onboarding-requests"      = "tenant_management"    # shipping-company onboarding lead (public; no account created)
    "POST /v1/register"                 = "tenant_management"    # customer self-registration (legacy, body-resolved slug)
    "POST /v1/register/{slug}"          = "tenant_management"    # customer self-registration, tenant-scoped by slug
    "GET /v1/invites/{token}"           = "tenant_management"    # account-creation invite claim-page preview
    "POST /v1/invites/{token}/accept"   = "tenant_management"    # account-creation invite claim
    "GET /v1/activate/{token}"          = "tenant_management"    # staff/admin activation preview (set-password page)
    "POST /v1/activate/{token}"         = "tenant_management"    # staff/admin activation — set chosen password
    "POST /v1/auth/login"               = "auth"                 # Entra ROPC login proxy (CORS-blocked direct from SPA)
    "POST /v1/auth/authorize-url"       = "auth"                 # begin interactive Entra login (BFF auth-code + PKCE)
    "POST /v1/auth/callback"            = "auth"                 # complete interactive login — exchange code for tokens
    "POST /v1/auth/session"             = "auth"                 # persist refresh token as httpOnly cookie
    "POST /v1/auth/refresh"             = "auth"                 # silent session restore on page load
    "POST /v1/auth/logout"              = "auth"                 # revoke + clear cookie
    "POST /v1/webhooks/payment"         = "payment_release"      # Paystack/Flutterwave gateway webhook (HMAC-verified in-handler)
  }

  active_public_routes = {
    for route_key, svc in local.public_routes : route_key => svc
    if contains(keys(var.lambda_arns), svc)
  }

  # Per-route throttles for the unauthenticated routes (requests/second, burst). These are per ROUTE, not per
  # client: API Gateway has no per-client limit. What they buy is a ceiling on how much of the stage-wide budget
  # (default_route_settings: 50/s) a flood of ONE public route can take from everybody else. Per-client and
  # per-tenant limits are enforced in the Lambdas (shared/rate_limit.py), except where a Lambda cannot reach
  # Redis: the auth Lambda is outside the VPC, so /v1/auth/* leans on these alone.
  #
  # The numbers are generous relative to real use (a silent token refresh is about one request per user per
  # hour) and exist to bound abuse, not to shape normal traffic; raise them before they are ever noticed.
  public_route_throttles = {
    "POST /v1/auth/refresh"        = { rate = 30, burst = 60 }
    "POST /v1/auth/session"        = { rate = 10, burst = 20 }
    "POST /v1/auth/callback"       = { rate = 10, burst = 20 }
    "POST /v1/auth/authorize-url"  = { rate = 10, burst = 20 }
    "POST /v1/auth/logout"         = { rate = 10, burst = 20 }
    "POST /v1/auth/login"          = { rate = 5, burst = 10 }
    "POST /v1/register"            = { rate = 3, burst = 6 }
    "POST /v1/register/{slug}"     = { rate = 3, burst = 6 }
    "POST /v1/onboarding-requests" = { rate = 2, burst = 4 }
  }

  active_public_route_throttles = {
    for route_key, limits in local.public_route_throttles : route_key => limits
    if contains(keys(local.active_public_routes), route_key)
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
    # Required for the browser to send/receive the /v1/auth/* httpOnly session
    # cookie (services/auth/handler.py) on cross-subdomain fetches (frontend on
    # shipx.co, API on api.shipx.co). Only safe because allow_origins is never
    # "*" (enforced by convention — a wildcard origin + allow_credentials is
    # rejected by browsers outright, so this is not itself a guardrail).
    allow_credentials = true
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

  # A flood of one public route must not be able to use up the stage-wide budget above; see public_route_throttles.
  dynamic "route_settings" {
    for_each = local.active_public_route_throttles
    content {
      route_key              = route_settings.key
      throttling_rate_limit  = route_settings.value.rate
      throttling_burst_limit = route_settings.value.burst
    }
  }

  access_log_settings {
    destination_arn = aws_cloudwatch_log_group.api_access_logs.arn
    format          = "$context.requestId $context.status $context.error.message"
  }

  # route_settings name routes by key, and API Gateway rejects a key that does not exist yet.
  depends_on = [aws_apigatewayv2_route.public_routes]

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
