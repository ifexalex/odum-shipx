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
  description = "The OWNER login. Used by the migrate job only — the application connects as application_login."
  value       = azurerm_postgresql_flexible_server.main.administrator_login
}

output "administrator_password" {
  description = "Admin (owner) password — the migrate job's DATABASE_PASSWORD. Not the application's."
  value       = random_password.admin.result
  sensitive   = true
}

output "application_login" {
  description = "The role the APPLICATION connects as — DML only, no BYPASSRLS, so RLS is enforced. Created by migration 005, given LOGIN by 060."
  value       = "logistics_app"
}

output "application_password" {
  description = "Password for logistics_app — the app containers' DATABASE_PASSWORD, and the migrate job's APP_DB_PASSWORD (migration 060 sets it on the role)."
  value       = random_password.app.result
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
