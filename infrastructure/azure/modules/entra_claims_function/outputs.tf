output "function_app_name" {
  description = "Function App name (for CI zip deploy)."
  value       = azurerm_linux_function_app.claims.name
}

output "endpoint_url" {
  description = "The token-claims endpoint to register as the Entra custom authentication extension target."
  value       = "https://${azurerm_linux_function_app.claims.default_hostname}/api/token-claims"
}

output "principal_id" {
  description = "System-assigned managed identity object id — grant it Graph User.Read.All (manual, see README)."
  value       = azurerm_linux_function_app.claims.identity[0].principal_id
}
