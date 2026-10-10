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

# User-assigned managed identity for the Container Apps compute (Phase 3). Kept
# in the root to break the module cycle: Key Vault grants it access, and the
# container_app module uses it for ACR pull + Key Vault/Storage auth.
resource "azurerm_user_assigned_identity" "app" {
  name                = "${local.name_prefix}-app-identity"
  resource_group_name = azurerm_resource_group.main.name
  location            = var.location
  tags                = local.common_tags
}

module "frontend" {
  source = "./modules/frontend"
  # Optional: Front Door is forbidden on Free Trial/Student subscriptions.
  count = var.enable_frontend ? 1 : 0

  name_prefix             = local.name_prefix
  resource_group_name     = azurerm_resource_group.main.name
  location                = var.location
  common_tags             = local.common_tags
  content_security_policy = local.content_security_policy
}

# ─── Backend provider-adapter targets (object storage + Key Vault) ──────────
# These back shared/providers/azure/{blob,keyvault,keyvault_secrets}.py. Apply
# just these without the frontend via:
#   terraform apply -target=module.storage -target=module.keyvault

module "storage" {
  source = "./modules/storage"

  name_prefix         = local.name_prefix
  resource_group_name = azurerm_resource_group.main.name
  location            = var.location
  common_tags         = local.common_tags
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

  # Postgres
  db_host     = module.postgres.host
  db_port     = module.postgres.port
  db_name     = module.postgres.database_name
  db_user     = module.postgres.administrator_login
  db_password = module.postgres.administrator_password

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
  auth_provider        = var.auth_provider
  oidc_jwks_url        = var.oidc_jwks_url
  oidc_audience        = var.oidc_audience
  entra_user_domain    = var.entra_user_domain
  entra_token_endpoint = var.entra_token_endpoint
  entra_client_id      = var.entra_client_id

  # Let the SPA's origin (the Front Door URL) call the API from the browser.
  cors_allow_origins = var.enable_frontend ? module.frontend[0].frontend_url : ""

  # Sizing
  api_cpu          = var.api_cpu
  api_memory       = var.api_memory
  api_min_replicas = var.api_min_replicas
  api_max_replicas = var.api_max_replicas
}
