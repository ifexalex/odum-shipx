# ---------------------------------------------------------------------------
# ShipX — Azure root stack (portability target; alongside the AWS stack in
# ../). Build out incrementally; the frontend (Blob static site + Front Door
# Standard) is the first module, mirroring the AWS CloudFront module.
# ---------------------------------------------------------------------------

resource "azurerm_resource_group" "main" {
  name     = "${local.name_prefix}-rg"
  location = var.location
  tags     = local.common_tags
}

# ─── Auth configuration guard ───────────────────────────────────────────────
# auth_provider defaults to "azure", so an environment whose tfvars omit the
# entra_* values deploys with Entra auth ENABLED and no configuration — the API
# comes up healthy and every sign-in fails. That is the single most expensive
# failure mode in this stack: it looks like a code bug and is a missing tfvar.
#
# Fail the plan instead. Each value below has to come from the Entra tenant
# (the scripts under scripts/ print them); none can be derived from Terraform,
# which is exactly why they are easy to forget.
resource "terraform_data" "auth_config_guard" {
  input = var.auth_provider

  lifecycle {
    precondition {
      condition = var.auth_provider != "azure" || alltrue([
        var.oidc_jwks_url != "",
        var.oidc_audience != "",
        var.entra_client_id != "",
        var.entra_token_endpoint != "",
        var.entra_redirect_uri != "",
      ])
      error_message = <<-EOT
        auth_provider = "azure" but the Entra configuration is incomplete for
        environment "${var.environment}". Required and currently empty-checked:
          oidc_jwks_url, oidc_audience, entra_client_id,
          entra_token_endpoint, entra_redirect_uri

        Populate environments/${var.environment}.tfvars. To obtain the values,
        run against the target Entra tenant (see docs/runbook.md):
          scripts/setup_entra_auth.sh             (provisioning app + consent)
          scripts/setup_entra_claims_provider.sh  (redirect URI + claims; prints
                                                   the issuer/JWKS to use)
          scripts/setup_entra_platform_admin.sh   (platform_admin group)

        To stand the environment up without auth, set auth_provider = "aws".
      EOT
    }

    precondition {
      condition     = var.app_base_url != "" || var.entra_redirect_uri != ""
      error_message = <<-EOT
        Both app_base_url and entra_redirect_uri are empty for environment
        "${var.environment}". Activation and password-reset emails build their
        links from app_base_url, falling back to the origin of
        entra_redirect_uri — with neither set, those emails ship an empty link
        and a newly provisioned user can never set a password.
      EOT
    }
  }
}

# User-assigned managed identity for the Container Apps compute (Phase 3). Kept
# in the root to break the module cycle: Key Vault grants it access, and the
# container_app module uses it for ACR pull + Key Vault/Storage auth.
resource "azurerm_user_assigned_identity" "app" {
  name                = "${local.name_prefix}-app-identity"
  resource_group_name = azurerm_resource_group.main.name
  location            = var.location
  tags                = local.common_tags
}

# The Front Door profile lives here, not inside module.frontend, because two things need it that also need each
# other: module.frontend routes /v1/* to the API container app, and the container app needs this profile's id to
# recognise requests Front Door forwarded (shared/client_ip.py). Inside the module that is a dependency cycle.
resource "azurerm_cdn_frontdoor_profile" "frontend" {
  # Optional: Front Door is forbidden on Free Trial/Student subscriptions.
  count = var.enable_frontend ? 1 : 0

  name                = "${local.name_prefix}-fd"
  resource_group_name = azurerm_resource_group.main.name
  sku_name            = "Standard_AzureFrontDoor"
  tags                = local.common_tags
}

# The profile was created inside the module before 2026-11-17. This keeps an existing deployment's profile (and
# with it the public hostname) instead of destroying and recreating it.
moved {
  from = module.frontend[0].azurerm_cdn_frontdoor_profile.frontend
  to   = azurerm_cdn_frontdoor_profile.frontend[0]
}

module "frontend" {
  source = "./modules/frontend"
  count  = var.enable_frontend ? 1 : 0

  frontdoor_profile_id   = azurerm_cdn_frontdoor_profile.frontend[0].id
  frontdoor_profile_name = azurerm_cdn_frontdoor_profile.frontend[0].name

  name_prefix             = local.name_prefix
  resource_group_name     = azurerm_resource_group.main.name
  location                = var.location
  common_tags             = local.common_tags
  content_security_policy = local.content_security_policy
  # Serve /v1/* and /health from the API Container App on the same Front Door
  # host as the SPA → first-party auth cookies, no CORS. (frontend depends on
  # container_app; container_app no longer references frontend, so no cycle.)
  api_origin_host = module.container_app.api_fqdn
}

# ─── Backend provider-adapter targets (object storage + Key Vault) ──────────
# These back shared/providers/azure/{blob,keyvault,keyvault_secrets}.py. Apply
# just these without the frontend via:
#   terraform apply -target=module.storage -target=module.keyvault

module "storage" {
  source = "./modules/storage"

  name_prefix          = local.name_prefix
  resource_group_name  = azurerm_resource_group.main.name
  location             = var.location
  common_tags          = local.common_tags
  cors_allowed_origins = local.storage_cors_origins
}

module "keyvault" {
  source = "./modules/keyvault"

  name_prefix         = local.name_prefix
  resource_group_name = azurerm_resource_group.main.name
  location            = var.location
  common_tags         = local.common_tags

  # Grant the app identity runtime access (wrap/unwrap keys + read secrets) so
  # KeyVaultKeyProvider/KeyVaultSecretsProvider work via DefaultAzureCredential.
  extra_object_ids = [azurerm_user_assigned_identity.app.principal_id]
}

# ─── Data + messaging layer (Phase 2) ───────────────────────────────────────
# Mirrors the AWS networking/aurora/elasticache/sqs/eventbridge/ses/monitoring
# modules. Postgres is VNet-integrated (private); the rest use keyed public
# endpoints. Outputs feed the adapter env vars consumed by the Phase-3 compute.

module "networking" {
  source = "./modules/networking"

  name_prefix         = local.name_prefix
  resource_group_name = azurerm_resource_group.main.name
  location            = var.location
  common_tags         = local.common_tags
}

module "postgres" {
  source = "./modules/postgres"

  name_prefix         = local.name_prefix
  resource_group_name = azurerm_resource_group.main.name
  location            = var.location
  common_tags         = local.common_tags

  vnet_id             = module.networking.vnet_id
  delegated_subnet_id = module.networking.postgres_subnet_id
  key_vault_id        = module.keyvault.vault_id

  sku_name   = var.postgres_sku_name
  storage_mb = var.postgres_storage_mb
}

module "redis" {
  source = "./modules/redis"
  # Optional: classic Azure Cache for Redis is retiring and blocked on some
  # subscriptions. When disabled, the app's distributed cache degrades to DB
  # lookups (miss path), so it stays functional.
  count = var.enable_redis ? 1 : 0

  name_prefix         = local.name_prefix
  resource_group_name = azurerm_resource_group.main.name
  location            = var.location
  common_tags         = local.common_tags

  sku_name = var.redis_sku_name
}

module "servicebus" {
  source = "./modules/servicebus"

  name_prefix         = local.name_prefix
  resource_group_name = azurerm_resource_group.main.name
  location            = var.location
  common_tags         = local.common_tags
}

module "eventgrid" {
  source = "./modules/eventgrid"

  name_prefix         = local.name_prefix
  resource_group_name = azurerm_resource_group.main.name
  location            = var.location
  common_tags         = local.common_tags
}

module "acs" {
  source = "./modules/acs"

  name_prefix         = local.name_prefix
  resource_group_name = azurerm_resource_group.main.name
  common_tags         = local.common_tags
  data_location       = var.acs_data_location
}

module "monitoring" {
  source = "./modules/monitoring"

  name_prefix         = local.name_prefix
  resource_group_name = azurerm_resource_group.main.name
  location            = var.location
  common_tags         = local.common_tags
  alerts_email        = var.alerts_email
}

# ─── Compute (Phase 3) ──────────────────────────────────────────────────────
# Container Apps running the Phase-1 image; consumes every Phase-2 output as the
# adapter env. CLOUD_PROVIDER=azure makes the running app resolve Azure adapters.

module "container_app" {
  source = "./modules/container_app"

  name_prefix         = local.name_prefix
  resource_group_name = azurerm_resource_group.main.name
  location            = var.location
  common_tags         = local.common_tags

  identity_id                = azurerm_user_assigned_identity.app.id
  identity_principal_id      = azurerm_user_assigned_identity.app.principal_id
  subnet_id                  = module.networking.container_apps_subnet_id
  log_analytics_workspace_id = module.monitoring.workspace_id

  container_image = var.container_image

  # ENVIRONMENT (log stamping + the notification guard's production check) and
  # the non-production recipient allowlist. The guard fails closed, so dev sends
  # nothing until notification_allowlist names a contact.
  environment_name       = var.environment
  notification_allowlist = var.notification_allowlist

  # Postgres
  db_host         = module.postgres.host
  db_port         = module.postgres.port
  db_name         = module.postgres.database_name
  db_user         = module.postgres.administrator_login
  db_password     = module.postgres.administrator_password
  db_app_user     = module.postgres.application_login
  db_app_password = module.postgres.application_password

  # Redis
  redis_host     = var.enable_redis ? module.redis[0].hostname : ""
  redis_port     = var.enable_redis ? module.redis[0].ssl_port : 6380
  redis_password = var.enable_redis ? module.redis[0].primary_access_key : ""

  grant_acr_pull = var.grant_acr_pull
  enable_redis   = var.enable_redis

  # Service Bus
  service_bus_connection_string = module.servicebus.connection_string
  queue_names                   = module.servicebus.queue_names

  # Event Grid
  event_grid_endpoint = module.eventgrid.endpoint
  event_grid_key      = module.eventgrid.primary_access_key

  # ACS email
  acs_connection_string = module.acs.connection_string
  acs_sender_address    = module.acs.sender_address

  # Storage + Key Vault
  blob_container_name       = module.storage.container_name
  storage_connection_string = module.storage.connection_string
  key_vault_url             = module.keyvault.vault_uri
  encryption_key_id         = module.keyvault.encryption_key_id

  # Observability
  app_insights_connection_string = module.monitoring.app_insights_connection_string

  # Auth. auth_provider selects the IdP (azure=Entra, aws=Cognito bridge).
  auth_provider                 = var.auth_provider
  oidc_jwks_url                 = var.oidc_jwks_url
  oidc_audience                 = var.oidc_audience
  oidc_issuer                   = var.oidc_issuer
  entra_user_domain             = var.entra_user_domain
  entra_local_accounts          = var.entra_local_accounts
  entra_platform_admin_group_id = var.entra_platform_admin_group_id
  entra_group_id_map            = var.entra_group_id_map
  entra_token_endpoint          = var.entra_token_endpoint
  entra_client_id               = var.entra_client_id
  # Graph client-credentials for provisioning users into the CIAM tenant (the
  # managed identity can't — it's single-tenant). Secret via TF_VAR at apply.
  entra_graph_tenant_id     = var.entra_graph_tenant_id
  entra_graph_client_id     = var.entra_graph_client_id
  entra_graph_client_secret = var.entra_graph_client_secret
  # Interactive login (BFF auth-code + PKCE). Set entra_redirect_uri explicitly
  # (the SPA's /auth/callback on the Front Door host) — NOT derived from
  # module.frontend, because the frontend module now depends on this module's
  # api_fqdn (same-origin API route), and a reverse reference here would create a
  # cycle. Register this exact value on the app registration.
  entra_authorize_endpoint = var.entra_authorize_endpoint
  entra_redirect_uri       = var.entra_redirect_uri
  entra_authorize_prompt   = var.entra_authorize_prompt

  # Base URL for activation/password links in outbound email. Explicit for the
  # same no-cycle reason as entra_redirect_uri above.
  app_base_url = var.app_base_url

  # Client address for rate limits and audit logs. The app trusts Front Door's own record of it on requests that
  # carry this Front Door's id, so no proxy count has to be measured. "" when Front Door is not deployed.
  front_door_id      = try(azurerm_cdn_frontdoor_profile.frontend[0].resource_guid, "")
  require_front_door = var.require_front_door
  # Fallback for requests that did not come through Front Door; 0 = their address is treated as unknown.
  trusted_proxy_hops = var.trusted_proxy_hops

  # Notification channels. SMS and WhatsApp were not wired to this deployment at
  # all — see modules/container_app/variables.tf and the
  # notification_config_guard below.
  customer_portal_base_url    = var.customer_portal_base_url
  africastalking_api_key      = var.africastalking_api_key
  africastalking_username     = var.africastalking_username
  africastalking_sender_id    = var.africastalking_sender_id
  meta_whatsapp_access_token  = var.meta_whatsapp_access_token
  meta_whatsapp_phone_id      = var.meta_whatsapp_phone_id
  meta_whatsapp_template_lang = var.meta_whatsapp_template_lang
  whatsapp_verify_token       = var.whatsapp_verify_token

  # The API is served same-origin with the SPA via a Front Door /v1/* route
  # (see module.frontend.api_origin_host), so the auth cookies are first-party;
  # SameSite=Lax survives the Entra redirect return. (Cross-site SameSite=None
  # cookies were dropped by Chrome/Safari third-party-cookie blocking.)
  auth_cookie_samesite = var.auth_cookie_samesite

  # Same-origin ⇒ browser requests are not cross-origin, so no CORS allowlist is
  # needed. (Kept empty rather than pointing at module.frontend to avoid a cycle.)
  cors_allow_origins = ""

  # Sizing
  api_cpu          = var.api_cpu
  api_memory       = var.api_memory
  api_min_replicas = var.api_min_replicas
  api_max_replicas = var.api_max_replicas

  # Entra custom-claims provider (OnTokenIssuanceStart) — its own Container App
  # on the shared image, injecting tenant_id + role so all roles resolve on CIAM
  # (ADR-004). Config filled after the manual Entra setup; empty → denies callers.
  claims_caller_jwks_url  = var.entra_claims_caller_jwks_url
  claims_caller_audience  = var.entra_claims_caller_audience
  claims_caller_issuer    = var.entra_claims_caller_issuer
  claims_out_tenant_claim = var.entra_out_tenant_claim
  claims_out_role_claim   = var.entra_out_role_claim
}

# ---------------------------------------------------------------------------
# Notification channel guard — the Azure twin of the AWS one.
#
# Production is the only environment where these must be complete, and the only
# one where getting it wrong is invisible: every send path logs "not configured"
# and returns, so the deploy is healthy, the API returns 200, and customers are
# simply never told anything. This fails the PLAN instead.
# ---------------------------------------------------------------------------
resource "terraform_data" "notification_config_guard" {
  input = var.environment

  lifecycle {
    precondition {
      condition = var.environment != "prod" || alltrue([
        var.africastalking_api_key != "",
        var.africastalking_username != "",
      ])
      error_message = <<-EOT
        Africa's Talking SMS is not configured for prod
        (africastalking_api_key / africastalking_username). These were absent
        from the Azure deployment entirely: send_sms logs
        "AFRICASTALKING_API_KEY not configured" and returns False, so no SMS is
        ever delivered and nothing fails. The username must be the LIVE one —
        the application default is "sandbox", which accepts messages and
        delivers nothing.
      EOT
    }

    precondition {
      condition = var.environment != "prod" || alltrue([
        var.meta_whatsapp_access_token != "",
        var.meta_whatsapp_phone_id != "",
        var.meta_whatsapp_template_lang != "",
      ])
      error_message = <<-EOT
        WhatsApp is not configured for prod (meta_whatsapp_access_token /
        meta_whatsapp_phone_id / meta_whatsapp_template_lang). WhatsApp is the
        PRIMARY customer channel here and SMS is only its fallback, so an
        unconfigured token means the main way customers are contacted is dead.
        meta_whatsapp_template_lang must match the language the templates named
        in WA_TEMPLATE_MAP were approved under, or Meta 404s every send.
      EOT
    }
  }
}
