output "workspace_id" {
  description = "Log Analytics workspace resource id (Container Apps Environment references this)."
  value       = azurerm_log_analytics_workspace.main.id
}

output "workspace_customer_id" {
  description = "Log Analytics workspace GUID (customer id)."
  value       = azurerm_log_analytics_workspace.main.workspace_id
}

output "workspace_primary_shared_key" {
  description = "Log Analytics primary shared key."
  value       = azurerm_log_analytics_workspace.main.primary_shared_key
  sensitive   = true
}

output "app_insights_connection_string" {
  description = "Application Insights connection string — set as APPLICATIONINSIGHTS_CONNECTION_STRING."
  value       = azurerm_application_insights.main.connection_string
  sensitive   = true
}

output "app_insights_instrumentation_key" {
  description = "Application Insights instrumentation key."
  value       = azurerm_application_insights.main.instrumentation_key
  sensitive   = true
}
