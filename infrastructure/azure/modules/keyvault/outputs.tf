output "vault_uri" {
  description = "Key Vault URI (set as AZURE_KEY_VAULT_URL)."
  value       = azurerm_key_vault.main.vault_uri
}

output "vault_name" {
  description = "Key Vault name."
  value       = azurerm_key_vault.main.name
}

output "encryption_key_id" {
  description = "Versioned RSA key id for envelope wrap/unwrap (set as ENCRYPTION_KEY_VAULT_KEY_ID). Pinned to a version so existing ciphertext stays unwrappable across key rotation."
  value       = azurerm_key_vault_key.data_key.id
}

output "smoke_secret_name" {
  description = "Name of the smoke-test secret (value 'ok') for verifying the SecretsProvider."
  value       = azurerm_key_vault_secret.smoke.name
}
