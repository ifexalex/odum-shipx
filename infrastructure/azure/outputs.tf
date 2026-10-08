output "frontend_url" {
  description = "Public HTTPS URL of the SPA (Front Door default endpoint)."
  value       = module.frontend.frontend_url
}

output "frontend_storage_account" {
  description = "Storage account name — CI uploads the built dist/ into its $web container."
  value       = module.frontend.storage_account_name
}

output "frontend_frontdoor_profile" {
  description = "Front Door profile name — used by CI to purge the endpoint after a deploy."
  value       = module.frontend.frontdoor_profile_name
}

output "frontend_frontdoor_endpoint" {
  description = "Front Door endpoint name — used by CI for cache purge."
  value       = module.frontend.frontdoor_endpoint_name
}

output "resource_group" {
  description = "Resource group holding the Azure stack."
  value       = azurerm_resource_group.main.name
}

# ─── Backend adapter env values (feed shared/providers/azure/*) ─────────────

output "blob_container_name" {
  description = "Set as BLOB_CONTAINER_NAME for the BlobStorageProvider."
  value       = module.storage.container_name
}

output "storage_connection_string" {
  description = "Set as AZURE_STORAGE_CONNECTION_STRING for the BlobStorageProvider. Read with: terraform output -raw storage_connection_string"
  value       = module.storage.connection_string
  sensitive   = true
}

output "key_vault_url" {
  description = "Set as AZURE_KEY_VAULT_URL for the KeyVaultSecretsProvider."
  value       = module.keyvault.vault_uri
}

output "encryption_key_vault_key_id" {
  description = "Set as ENCRYPTION_KEY_VAULT_KEY_ID for the KeyVaultKeyProvider."
  value       = module.keyvault.encryption_key_id
}

output "smoke_secret_name" {
  description = "Secret name (value 'ok') for verifying the SecretsProvider."
  value       = module.keyvault.smoke_secret_name
}
