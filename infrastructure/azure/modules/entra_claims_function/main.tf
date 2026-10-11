# ---------------------------------------------------------------------------
# Entra custom authentication extension (OnTokenIssuanceStart) claims provider.
#
# A standalone Azure Function that injects ShipX's tenant_id + role claims into
# Entra-issued tokens at sign-in (code in services/entra_token_claims/). Needed
# because Entra External ID (CIAM) does not emit app-manifest optionalClaims for
# directory extensions (ADR-004 addendum). The Function reads those attributes
# off the user via Graph using its system-assigned managed identity.
#
# NOT Terraformable (manual / Graph, documented in the azure README):
#   - the managed identity's Graph application permission (User.Read.All) — the
#     Contributor deploy identity cannot create app-role assignments; grant it
#     with `az rest` using the principal_id output below;
#   - the Entra `customAuthenticationExtensions` resource + the app's
#     token-issuance event binding (no azurerm/azuread resource exists).
# The Function code itself is zip-deployed by CI (Phase 5).
# ---------------------------------------------------------------------------

resource "random_string" "sa_suffix" {
  length  = 6
  upper   = false
  special = false
}

resource "azurerm_storage_account" "fn" {
  # Storage account names: 3-24 chars, lowercase alphanumeric, globally unique.
  name                            = substr("${replace(var.name_prefix, "-", "")}fn${random_string.sa_suffix.result}", 0, 24)
  resource_group_name             = var.resource_group_name
  location                        = var.location
  account_tier                    = "Standard"
  account_replication_type        = "LRS"
  min_tls_version                 = "TLS1_2"
  allow_nested_items_to_be_public = false
  tags                            = var.common_tags
}

resource "azurerm_service_plan" "fn" {
  name                = "${var.name_prefix}-claims-plan"
  resource_group_name = var.resource_group_name
  location            = var.location
  os_type             = "Linux"
  sku_name            = "Y1" # Consumption
  tags                = var.common_tags
}

resource "azurerm_linux_function_app" "claims" {
  name                       = "${var.name_prefix}-entra-claims"
  resource_group_name        = var.resource_group_name
  location                   = var.location
  service_plan_id            = azurerm_service_plan.fn.id
  storage_account_name       = azurerm_storage_account.fn.name
  storage_account_access_key = azurerm_storage_account.fn.primary_access_key
  https_only                 = true
  tags                       = var.common_tags

  identity {
    type = "SystemAssigned"
  }

  site_config {
    application_stack {
      python_version = var.python_version
    }
    application_insights_connection_string = var.app_insights_connection_string != "" ? var.app_insights_connection_string : null
    ftps_state                             = "Disabled"
    minimum_tls_version                    = "1.2"
  }

  app_settings = {
    FUNCTIONS_WORKER_RUNTIME = "python"
    # Inbound-caller verification (the Entra token Entra sends to the extension).
    CALLER_JWKS_URL = var.caller_jwks_url
    CALLER_AUDIENCE = var.caller_audience
    CALLER_ISSUER   = var.caller_issuer
    # Directory extension attributes to read and the claim names to emit.
    ENTRA_TENANT_ID_ATTR = var.tenant_id_attr
    ENTRA_ROLE_ATTR      = var.role_attr
    OUT_TENANT_CLAIM     = var.out_tenant_claim
    OUT_ROLE_CLAIM       = var.out_role_claim
    GRAPH_BASE_URL       = var.graph_base_url
  }

  # Code is zip-deployed out of band (CI / az functionapp deployment); don't let
  # Terraform fight the deployed package.
  lifecycle {
    ignore_changes = [app_settings["WEBSITE_RUN_FROM_PACKAGE"]]
  }
}
