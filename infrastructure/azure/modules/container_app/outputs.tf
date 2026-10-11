output "acr_login_server" {
  description = "ACR login server — the deploy workflow tags/pushes the image here."
  value       = azurerm_container_registry.acr.login_server
}

output "acr_name" {
  description = "ACR name (for `az acr login` / image updates)."
  value       = azurerm_container_registry.acr.name
}

output "api_fqdn" {
  description = "Public FQDN of the API Container App ingress."
  value       = azurerm_container_app.api.ingress[0].fqdn
}

output "api_url" {
  description = "Public HTTPS base URL of the API."
  value       = "https://${azurerm_container_app.api.ingress[0].fqdn}"
}

output "environment_id" {
  description = "Container Apps Environment id."
  value       = azurerm_container_app_environment.main.id
}

output "api_app_name" {
  description = "API Container App name (for `az containerapp update --image`)."
  value       = azurerm_container_app.api.name
}

output "worker_app_names" {
  description = "Worker Container App names by queue."
  value       = { for k, w in azurerm_container_app.worker : k => w.name }
}

output "migrate_job_name" {
  description = "Migration Container App Job name (`az containerapp job start`)."
  value       = azurerm_container_app_job.migrate.name
}

output "claims_app_name" {
  description = "Entra claims-provider Container App name (`az containerapp update --image`)."
  value       = azurerm_container_app.claims.name
}

output "claims_app_fqdn" {
  description = "Public FQDN of the claims provider — register as the Entra custom-auth-extension target (+ /token-claims)."
  value       = azurerm_container_app.claims.ingress[0].fqdn
}
