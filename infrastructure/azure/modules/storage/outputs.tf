output "storage_account_name" {
  description = "App assets storage account name."
  value       = azurerm_storage_account.assets.name
}

output "container_name" {
  description = "Blob container name (set as BLOB_CONTAINER_NAME)."
  value       = azurerm_storage_container.assets.name
}

output "connection_string" {
  description = "Storage account connection string (set as AZURE_STORAGE_CONNECTION_STRING)."
  value       = azurerm_storage_account.assets.primary_connection_string
  sensitive   = true
}
