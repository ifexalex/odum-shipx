output "host" {
  description = "Server FQDN — set as DATABASE_HOST."
  value       = azurerm_postgresql_flexible_server.main.fqdn
}

output "port" {
  description = "Set as DATABASE_PORT."
  value       = 5432
}

output "database_name" {
  description = "Set as DATABASE_NAME."
  value       = azurerm_postgresql_flexible_server_database.logistics.name
}

output "administrator_login" {
  description = "Set as DATABASE_USER."
  value       = azurerm_postgresql_flexible_server.main.administrator_login
}

output "administrator_password" {
  description = "Admin password — set as DATABASE_PASSWORD (prefer the Key Vault secret reference in Container Apps)."
  value       = random_password.admin.result
  sensitive   = true
}

output "password_secret_name" {
  description = "Key Vault secret name holding the admin password."
  value       = azurerm_key_vault_secret.db_password.name
}

output "server_id" {
  description = "Flexible Server resource id (for monitoring alerts)."
  value       = azurerm_postgresql_flexible_server.main.id
}
