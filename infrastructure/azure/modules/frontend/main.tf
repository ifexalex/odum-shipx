# ---------------------------------------------------------------------------
# Frontend hosting — Blob static website + Front Door Standard.
# Azure analogue of the AWS modules/cloudfront (S3 + CloudFront).
#
#   Browser ──TLS──▶ Front Door Standard (CDN + security headers + SPA routing)
#                      ▼
#                    Storage account $web (static SPA assets)
#
# Front Door Standard (not Premium) keeps cost low (~$35/mo base); it has no
# WAF — layer that at the edge with Cloudflare (recommended) or move to Front
# Door Premium later. Static-website origins are public on Standard (private
# origin/Private Link needs Premium); fine for static SPA assets.
# ---------------------------------------------------------------------------

locals {
  # Storage account names: 3–24 chars, lowercase alphanumeric, globally unique.
  sa_base = substr(lower(replace("${var.name_prefix}fe", "-", "")), 0, 16)
}

resource "random_string" "sa_suffix" {
  length  = 6
  special = false
  upper   = false
}

resource "azurerm_storage_account" "frontend" {
  name                     = "${local.sa_base}${random_string.sa_suffix.result}"
  resource_group_name      = var.resource_group_name
  location                 = var.location
  account_tier             = "Standard"
  account_replication_type = "LRS" # cheapest; raise to GRS/ZRS for more durability
  account_kind             = "StorageV2"
  min_tls_version          = "TLS1_2"

  # Block anonymous access to individual blobs; the $web static-website
  # endpoint is a separate surface that still serves the SPA publicly.
  allow_nested_items_to_be_public = false
  https_traffic_only_enabled      = true

  tags = var.common_tags
}

resource "azurerm_storage_account_static_website" "frontend" {
  storage_account_id = azurerm_storage_account.frontend.id
  index_document     = "index.html"
  # SPA fallback: unknown client-side routes return index.html so the router
  # takes over. (Static Website serves this with a 404 status; Front Door's
  # rule set below can be extended to rewrite it to 200 if needed.)
  error_404_document = "index.html"
}

# ---------------------------------------------------------------------------
# Front Door Standard
# ---------------------------------------------------------------------------

resource "azurerm_cdn_frontdoor_profile" "frontend" {
  name                = "${var.name_prefix}-fd"
  resource_group_name = var.resource_group_name
  sku_name            = "Standard_AzureFrontDoor"
  tags                = var.common_tags
}

resource "azurerm_cdn_frontdoor_endpoint" "frontend" {
  name                     = "${var.name_prefix}-fde"
  cdn_frontdoor_profile_id = azurerm_cdn_frontdoor_profile.frontend.id
  tags                     = var.common_tags
}

resource "azurerm_cdn_frontdoor_origin_group" "frontend" {
  name                     = "frontend-origins"
  cdn_frontdoor_profile_id = azurerm_cdn_frontdoor_profile.frontend.id
  session_affinity_enabled = false

  load_balancing {
    sample_size                 = 4
    successful_samples_required = 3
  }

  health_probe {
    path                = "/index.html"
    protocol            = "Https"
    request_type        = "HEAD"
    interval_in_seconds = 100
  }
}

resource "azurerm_cdn_frontdoor_origin" "frontend" {
  name                          = "storage-static-web"
  cdn_frontdoor_origin_group_id = azurerm_cdn_frontdoor_origin_group.frontend.id
  enabled                       = true

  # primary_web_host is "<account>.z##.web.core.windows.net" (no scheme).
  host_name          = azurerm_storage_account.frontend.primary_web_host
  origin_host_header = azurerm_storage_account.frontend.primary_web_host
  http_port          = 80
  https_port         = 443
  priority           = 1
  weight             = 1

  certificate_name_check_enabled = true
}

# ---------------------------------------------------------------------------
# API origin — serve /v1/* and /health from the API Container App on the SAME
# Front Door host as the SPA, so the browser treats the API as first-party:
# the httpOnly auth cookies (shipx_rt, shipx_auth_tx) are sent normally instead
# of being dropped as third-party (Chrome/Safari block cross-site cookies), and
# there is no cross-origin CORS. Created only when api_origin_host is set.
# ---------------------------------------------------------------------------
resource "azurerm_cdn_frontdoor_origin_group" "api" {
  count                    = var.api_origin_host == "" ? 0 : 1
  name                     = "api-origins"
  cdn_frontdoor_profile_id = azurerm_cdn_frontdoor_profile.frontend.id
  session_affinity_enabled = false

  load_balancing {
    sample_size                 = 4
    successful_samples_required = 3
  }

  health_probe {
    path                = "/health"
    protocol            = "Https"
    request_type        = "GET"
    interval_in_seconds = 100
  }
}

resource "azurerm_cdn_frontdoor_origin" "api" {
  count                         = var.api_origin_host == "" ? 0 : 1
  name                          = "api-container-app"
  cdn_frontdoor_origin_group_id = azurerm_cdn_frontdoor_origin_group.api[0].id
  enabled                       = true

  host_name          = var.api_origin_host
  origin_host_header = var.api_origin_host
  http_port          = 80
  https_port         = 443
  priority           = 1
  weight             = 1

  certificate_name_check_enabled = true
}

# Security response headers — mirrors the AWS response-headers policy.
resource "azurerm_cdn_frontdoor_rule_set" "headers" {
  name                     = "securityheaders"
  cdn_frontdoor_profile_id = azurerm_cdn_frontdoor_profile.frontend.id
}

resource "azurerm_cdn_frontdoor_rule" "security_headers" {
  name                      = "securityheaders"
  cdn_frontdoor_rule_set_id = azurerm_cdn_frontdoor_rule_set.headers.id
  order                     = 1
  behavior_on_match         = "Continue"

  # Apply to every request (match all hosts).
  conditions {
    host_name_condition {
      operator         = "Equal"
      negate_condition = true
      match_values     = ["does-not-exist.invalid"]
    }
  }

  actions {
    response_header_action {
      header_action = "Overwrite"
      header_name   = "X-Content-Type-Options"
      value         = "nosniff"
    }
    response_header_action {
      header_action = "Overwrite"
      header_name   = "X-Frame-Options"
      value         = "DENY"
    }
    response_header_action {
      header_action = "Overwrite"
      header_name   = "Referrer-Policy"
      value         = "strict-origin-when-cross-origin"
    }
    response_header_action {
      header_action = "Overwrite"
      header_name   = "Strict-Transport-Security"
      value         = "max-age=63072000; includeSubDomains; preload"
    }
    response_header_action {
      header_action = "Overwrite"
      header_name   = "Content-Security-Policy"
      value         = var.content_security_policy
    }
  }
}

resource "azurerm_cdn_frontdoor_route" "frontend" {
  name                          = "default-route"
  cdn_frontdoor_endpoint_id     = azurerm_cdn_frontdoor_endpoint.frontend.id
  cdn_frontdoor_origin_group_id = azurerm_cdn_frontdoor_origin_group.frontend.id
  cdn_frontdoor_origin_ids      = [azurerm_cdn_frontdoor_origin.frontend.id]
  cdn_frontdoor_rule_set_ids    = [azurerm_cdn_frontdoor_rule_set.headers.id]

  supported_protocols    = ["Http", "Https"]
  patterns_to_match      = ["/*"]
  forwarding_protocol    = "HttpsOnly"
  https_redirect_enabled = true
  link_to_default_domain = true

  cache {
    compression_enabled           = true
    query_string_caching_behavior = "IgnoreQueryString"
    content_types_to_compress = [
      "text/html",
      "text/css",
      "application/javascript",
      "application/json",
      "image/svg+xml",
    ]
  }
}

# API route — more specific than "/*", so Front Door sends /v1/* and /health to
# the Container App origin while everything else serves the SPA. No cache block
# → API responses are never cached. Same host as the SPA ⇒ first-party cookies.
resource "azurerm_cdn_frontdoor_route" "api" {
  count                         = var.api_origin_host == "" ? 0 : 1
  name                          = "api-route"
  cdn_frontdoor_endpoint_id     = azurerm_cdn_frontdoor_endpoint.frontend.id
  cdn_frontdoor_origin_group_id = azurerm_cdn_frontdoor_origin_group.api[0].id
  cdn_frontdoor_origin_ids      = [azurerm_cdn_frontdoor_origin.api[0].id]

  supported_protocols    = ["Http", "Https"]
  patterns_to_match      = ["/v1/*", "/health"]
  forwarding_protocol    = "HttpsOnly"
  https_redirect_enabled = true
  link_to_default_domain = true
}
