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
