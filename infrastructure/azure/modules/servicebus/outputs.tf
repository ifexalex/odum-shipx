output "connection_string" {
  description = "Namespace connection string — set as AZURE_SERVICE_BUS_CONNECTION_STRING."
  value       = azurerm_servicebus_namespace.main.default_primary_connection_string
  sensitive   = true
}

output "namespace_name" {
  description = "Service Bus namespace name."
  value       = azurerm_servicebus_namespace.main.name
}

output "queue_names" {
  description = "Map of channel key → queue name (set as the SQS_*_QUEUE_URL env vars)."
  value       = { for k, q in azurerm_servicebus_queue.channel : k => q.name }
}
