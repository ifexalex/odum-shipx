output "frontend_url" {
  description = "Public HTTPS URL of the SPA (Front Door default endpoint)."
  value       = "https://${azurerm_cdn_frontdoor_endpoint.frontend.host_name}"
}

output "storage_account_name" {
  description = "Storage account name — CI uploads built dist/ into its $web container."
  value       = azurerm_storage_account.frontend.name
}

output "storage_primary_access_key" {
  description = "Storage account key — CI uploads the SPA with `--account-key` (no data-plane RBAC role needed on the least-privilege deploy identity, mirroring the ACR admin-creds choice)."
  value       = azurerm_storage_account.frontend.primary_access_key
  sensitive   = true
}

output "storage_web_host" {
  description = "Static-website primary host of the storage account."
  value       = azurerm_storage_account.frontend.primary_web_host
}

output "frontdoor_profile_name" {
  description = "Front Door profile name — used by CI for cache purge."
  value       = azurerm_cdn_frontdoor_profile.frontend.name
}

output "frontdoor_endpoint_name" {
  description = "Front Door endpoint name — used by CI for cache purge."
  value       = azurerm_cdn_frontdoor_endpoint.frontend.name
}
