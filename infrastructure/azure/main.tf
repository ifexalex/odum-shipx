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

module "frontend" {
  source = "./modules/frontend"

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
