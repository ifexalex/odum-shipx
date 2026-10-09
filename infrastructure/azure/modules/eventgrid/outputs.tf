output "endpoint" {
  description = "Topic endpoint URL — set as AZURE_EVENT_GRID_ENDPOINT."
  value       = azurerm_eventgrid_topic.main.endpoint
}

output "primary_access_key" {
  description = "Topic access key — set as AZURE_EVENT_GRID_KEY."
  value       = azurerm_eventgrid_topic.main.primary_access_key
  sensitive   = true
}

output "topic_name" {
  description = "Event Grid topic name."
  value       = azurerm_eventgrid_topic.main.name
}
