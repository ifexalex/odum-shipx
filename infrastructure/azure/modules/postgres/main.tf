# ---------------------------------------------------------------------------
# PostgreSQL Flexible Server — the Azure analogue of the AWS `aurora` module.
#
# VNet-integrated (private, no public endpoint), mirroring Aurora-in-private-
# subnets. The app connects via shared/db.py using the standard DATABASE_*
# env vars (host/port/name/user/password); the admin password is generated here
# and stored in Key Vault (the Azure analogue of Aurora's Secrets Manager
# master-password secret). Database name "logistics" + admin user match the AWS
# side so migrations/seed run unchanged.
#
# Sizing is var-driven and defaults to Burstable B1ms (cheapest) for test/dev;
# bump sku_name/storage for prod.
# ---------------------------------------------------------------------------

locals {
  server_name = "${var.name_prefix}-pg"
  # Private DNS zone for the flexible server; must end in postgres.database.azure.com.
  dns_zone_name = "${replace(var.name_prefix, "-", "")}.private.postgres.database.azure.com"
}

resource "random_password" "admin" {
  length           = 28
  special          = true
  override_special = "!#%*_-+="
  min_lower        = 2
  min_upper        = 2
  min_numeric      = 2
  min_special      = 2
}

# Private DNS zone + VNet link so the server's FQDN resolves inside the VNet.
resource "azurerm_private_dns_zone" "pg" {
  name                = local.dns_zone_name
  resource_group_name = var.resource_group_name
  tags                = var.common_tags
}

resource "azurerm_private_dns_zone_virtual_network_link" "pg" {
  name                  = "${var.name_prefix}-pg-dnslink"
  resource_group_name   = var.resource_group_name
  private_dns_zone_name = azurerm_private_dns_zone.pg.name
  virtual_network_id    = var.vnet_id
  registration_enabled  = false
  tags                  = var.common_tags
}

resource "azurerm_postgresql_flexible_server" "main" {
  name                = local.server_name
  resource_group_name = var.resource_group_name
  location            = var.location

  version                = "15"
  administrator_login    = var.administrator_login
  administrator_password = random_password.admin.result

  sku_name   = var.sku_name
  storage_mb = var.storage_mb

  # Private: VNet-integrated, no public endpoint.
  delegated_subnet_id           = var.delegated_subnet_id
  private_dns_zone_id           = azurerm_private_dns_zone.pg.id
  public_network_access_enabled = false

  zone                         = "1"
  backup_retention_days        = var.backup_retention_days
  geo_redundant_backup_enabled = false

  tags = var.common_tags

  # The VNet link must exist before the server (it resolves its own FQDN).
  depends_on = [azurerm_private_dns_zone_virtual_network_link.pg]
}

resource "azurerm_postgresql_flexible_server_database" "logistics" {
  name      = var.database_name
  server_id = azurerm_postgresql_flexible_server.main.id
  charset   = "UTF8"
  collation = "en_US.utf8"
}

# Enforce TLS (Flexible Server requires SSL; the app sets DATABASE_SSLMODE=require).
resource "azurerm_postgresql_flexible_server_configuration" "require_ssl" {
  name      = "require_secure_transport"
  server_id = azurerm_postgresql_flexible_server.main.id
  value     = "ON"
}

# Store the admin password in Key Vault — the Azure analogue of Aurora's
# Secrets Manager master-password secret. Container Apps references it as a
# secret and injects it as DATABASE_PASSWORD.
resource "azurerm_key_vault_secret" "db_password" {
  name         = "postgres-admin-password"
  value        = random_password.admin.result
  key_vault_id = var.key_vault_id
}
